"""
Train settlement probability model from full_session_2min.csv.

Logistic regression: P(trade wins) given live intraday state.
    win = 1  ← YES token wins (gap_up=True) OR NO token wins (gap_up=False)

Features
    gfr           gap fill ratio, clipped [-3, 3]
    gfr_velocity  2-min change in gfr, clipped [-1, 1]
    log_tbf       log1p(tbf_min) — log time-before-expiry
    gap_abs       abs(gap_pct), clipped at 0.15 — original gap magnitude
    market_p_win  current token price re-expressed as P(our trade wins):
                  yes_vwap if gap_up else (1 − yes_vwap)
    dow_thu       1 if Thursday (lower WR day)
    vix_high      1 if VIX > 20 (set to 0 for all training rows; live value used at inference)

Output  data/settlement_model.pkl  — dict with 'scaler', 'model', 'feature_names'

Usage:
    python tools/train_settlement_model.py
    python tools/train_settlement_model.py --plot        # show calibration curve
"""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

DATA_CSV   = Path("data/full_session_2min.csv")
MODEL_PATH = Path("data/settlement_model.pkl")

FEATURE_NAMES = ["gfr", "gfr_velocity", "log_tbf", "gap_abs", "market_p_win", "dow_thu", "vix_high"]


# ── Feature engineering ───────────────────────────────────────────────────────

def build_features(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Return df with feature columns + 'win' target. Drops unusable rows."""
    df = df_raw.copy()

    # Only keep rows with meaningful gaps
    df = df[df["gap_pct"].abs() >= 0.001].copy()

    # Trade direction
    df["gap_up"] = df["gap_pct"] > 0

    # Target: did our side win?
    df["win"] = ((df["gap_up"]) == (df["outcome_yes"] == 1)).astype(int)

    # ── gfr_velocity ──────────────────────────────────────────────────────────
    # Within each (ticker, date) session, compute 2-min change in gfr.
    # Sort descending on tbf_min so each diff() step moves forward in wall time.
    df = df.sort_values(["ticker", "date", "tbf_min"], ascending=[True, True, False])
    # gfr NaN means intraday stock price wasn't captured for that row.
    # Fill with 0 (neutral: gap intact, no movement observed yet).
    df["gfr"] = df["gfr"].fillna(0.0)
    df["gfr_velocity"] = (
        df.groupby(["ticker", "date"])["gfr"].diff(1).fillna(0)
    )

    # ── Features ─────────────────────────────────────────────────────────────
    df["gfr"]          = df["gfr"].clip(-3.0, 3.0)
    df["gfr_velocity"] = df["gfr_velocity"].clip(-1.0, 1.0)
    df["log_tbf"]      = np.log1p(df["tbf_min"])
    df["gap_abs"]      = df["gap_pct"].abs().clip(0, 5.0)
    df["market_p_win"] = np.where(df["gap_up"], df["yes_vwap"], 1.0 - df["yes_vwap"])
    df["dow_thu"]      = (df["dow"] == "Thu").astype(int)
    df["vix_high"]     = 0  # unknown for historical data; live value injected at inference

    # Drop rows missing any feature or target
    keep_cols = FEATURE_NAMES + ["win", "date", "ticker"]
    df = df[keep_cols].dropna()

    return df


# ── Train / evaluate ──────────────────────────────────────────────────────────

def train_model(df: pd.DataFrame, test_frac: float = 0.20) -> dict:
    """
    Session-level random split: sample 20% of (ticker, date) sessions for test.
    Rows from the same session stay together to prevent look-ahead leakage.
    """
    rng      = np.random.default_rng(42)
    sessions = df[["ticker", "date"]].drop_duplicates().values
    rng.shuffle(sessions)
    cutoff   = int(len(sessions) * (1 - test_frac))
    train_sessions = {(t, d) for t, d in sessions[:cutoff]}
    test_sessions  = {(t, d) for t, d in sessions[cutoff:]}

    session_key      = list(zip(df["ticker"], df["date"]))
    df["_in_train"]  = [s in train_sessions for s in session_key]
    train = df[df["_in_train"]].drop(columns=["_in_train"])
    test  = df[~df["_in_train"]].drop(columns=["_in_train"])

    X_tr = train[FEATURE_NAMES].values
    y_tr = train["win"].values
    X_te = test[FEATURE_NAMES].values
    y_te = test["win"].values

    n_train_sess = len(train_sessions)
    n_test_sess  = len(test_sessions)
    print(f"  Train: {len(train):,} rows ({n_train_sess} sessions), "
          f"win_rate={y_tr.mean():.3f}")
    print(f"  Test:  {len(test):,} rows ({n_test_sess} sessions), "
          f"win_rate={y_te.mean():.3f}")

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_te_s = scaler.transform(X_te)

    # Logistic regression with Platt scaling for probability calibration
    base  = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
    model = CalibratedClassifierCV(base, cv=5, method="sigmoid")
    model.fit(X_tr_s, y_tr)

    proba_te = model.predict_proba(X_te_s)[:, 1]
    auc    = roc_auc_score(y_te, proba_te)
    brier  = brier_score_loss(y_te, proba_te)
    logloss = log_loss(y_te, proba_te)

    print(f"\n  Test metrics:")
    print(f"    AUC-ROC:    {auc:.4f}  (0.5=random, 1.0=perfect)")
    print(f"    Brier score:{brier:.4f} (lower=better, 0.25=random)")
    print(f"    Log loss:   {logloss:.4f}")

    # Coefficients from the base estimator (first fold, for inspection)
    try:
        coefs = base.coef_[0] if hasattr(base, "coef_") else None
    except Exception:
        coefs = None

    # Print feature importances
    try:
        base_trained = model.calibrated_classifiers_[0].estimator
        coefs = base_trained.coef_[0]
        print("\n  Feature coefficients (positive = increases P(win)):")
        for name, c in sorted(zip(FEATURE_NAMES, coefs), key=lambda x: abs(x[1]), reverse=True):
            print(f"    {name:20s}: {c:+.4f}")
    except Exception:
        pass

    train_dates_list = sorted(train["date"].unique())
    test_dates_list  = sorted(test["date"].unique())
    return {
        "scaler":        scaler,
        "model":         model,
        "feature_names": FEATURE_NAMES,
        "auc":           auc,
        "brier":         brier,
        "train_dates":   (train_dates_list[0], train_dates_list[-1]),
        "test_dates":    (test_dates_list[0],  test_dates_list[-1]),
    }


# ── Calibration plot ──────────────────────────────────────────────────────────

def plot_calibration(df: pd.DataFrame, bundle: dict):
    try:
        import matplotlib.pyplot as plt
        from sklearn.calibration import calibration_curve
    except ImportError:
        print("matplotlib not available — skipping plot")
        return

    test_dates = set(df["date"].unique())
    X = df[df["date"].isin(test_dates)][FEATURE_NAMES].values
    y = df[df["date"].isin(test_dates)]["win"].values
    X_s = bundle["scaler"].transform(X)
    prob = bundle["model"].predict_proba(X_s)[:, 1]

    frac_pos, mean_pred = calibration_curve(y, prob, n_bins=10)
    plt.figure(figsize=(6, 5))
    plt.plot(mean_pred, frac_pos, "s-", label="Model")
    plt.plot([0, 1], [0, 1], "k--", label="Perfect")
    plt.xlabel("Predicted P(win)")
    plt.ylabel("Actual win rate")
    plt.title("Settlement model calibration (test set)")
    plt.legend()
    plt.tight_layout()
    plt.show()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plot", action="store_true", help="Show calibration curve")
    args = parser.parse_args()

    print(f"Loading {DATA_CSV} ...")
    df_raw = pd.read_csv(DATA_CSV)
    print(f"  {len(df_raw):,} rows, {df_raw['date'].nunique()} dates, "
          f"{df_raw['ticker'].nunique()} tickers")

    df = build_features(df_raw)
    print(f"  After filtering: {len(df):,} rows, win_rate={df['win'].mean():.3f}")

    print("\nTraining model ...")
    bundle = train_model(df)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(bundle, f, protocol=4)
    print(f"\nSaved → {MODEL_PATH}")
    print(f"  AUC={bundle['auc']:.4f}  Brier={bundle['brier']:.4f}")

    if args.plot:
        plot_calibration(df, bundle)


if __name__ == "__main__":
    main()
