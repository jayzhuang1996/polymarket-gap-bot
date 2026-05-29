"""
Build and extend full_session_2min.csv — the single authoritative script.

Replaces both full_session_analysis.py (parquet-based, full rebuild) and the
old extend_2min_data.py (Gamma API, incremental). Handles both automatically:
  - Dates with a row in data/markets.parquet → metadata from parquet (fast, no API)
  - Dates after the parquet cutoff (~May 1 2026) → Gamma API live lookup

Also regenerates data/settlement_probability.csv from the full CSV after any
new rows are added.

Usage:
  python tools/extend_2min_data.py                         # append missing dates from May 2 → today
  python tools/extend_2min_data.py --from 2026-05-20       # specific range
  python tools/extend_2min_data.py --from 2025-10-16 --rebuild  # full rebuild from scratch
"""

import argparse
import json
import sys
import time
from datetime import date, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

sys.path.insert(0, ".")

DATA_DIR = Path("data")
OUT_CSV  = DATA_DIR / "full_session_2min.csv"
OUT_PROB = DATA_DIR / "settlement_probability.csv"
MARKETS_PARQUET = DATA_DIR / "markets.parquet"

TICKERS = [
    ("SPX",   "^GSPC"),
    ("NVDA",  "NVDA"),
    ("TSLA",  "TSLA"),
    ("AAPL",  "AAPL"),
    ("AMZN",  "AMZN"),
    ("GOOGL", "GOOGL"),
    ("META",  "META"),
    ("MSFT",  "MSFT"),
    ("NFLX",  "NFLX"),
]

GAMMA_API   = "https://gamma-api.polymarket.com"
MONTH_NAMES = ["january","february","march","april","may","june",
               "july","august","september","october","november","december"]

INTERVALS_BEFORE_CLOSE = list(range(390, 0, -2))   # 195 intervals, 9:30am → 3:58pm ET

# settlement_probability.csv bucket definitions
TIME_BUCKETS = [
    ("09:30–10:00", 390, 360), ("10:00–10:30", 360, 330), ("10:30–11:00", 330, 300),
    ("11:00–12:00", 300, 240), ("12:00–13:00", 240, 180), ("13:00–14:00", 180, 120),
    ("14:00–14:30", 120,  90), ("14:30–15:00",  90,  60), ("15:00–16:00",  60,   0),
]
PRICE_BUCKETS = [
    ("40–50¢", 0.40, 0.50), ("50–60¢", 0.50, 0.60), ("60–70¢", 0.60, 0.70),
    ("70–80¢", 0.70, 0.80), ("80–90¢", 0.80, 0.90),
]
GFR_BUCKETS = [
    ("< −0.5", -99, -0.5), ("−0.5–0", -0.5, 0.0),
    ("0–0.5",  0.0,  0.5), ("> 0.5",   0.5, 99),
]


# ── Metadata lookup ──────────────────────────────────────────────────────────


def _load_parquet_index() -> dict[tuple[str, date], dict]:
    """Build a (ticker, date) → {condition_id, outcome_yes} index from markets.parquet.

    Returns empty dict if the parquet file doesn't exist.
    Uses vectorized filtering to handle the 1M-row parquet efficiently.
    """
    if not MARKETS_PARQUET.exists():
        return {}

    mdf = pd.read_parquet(MARKETS_PARQUET, engine="pyarrow")

    # Filter to daily stock resolution markets only (most of the 1M rows are unrelated)
    resolved = mdf[
        (mdf["closed"] == 1) &
        mdf["question"].str.contains("Up or Down on", na=False)
    ].copy()

    index: dict[tuple[str, date], dict] = {}

    for ticker, yahoo_sym in TICKERS:
        tag = "SPX" if yahoo_sym == "^GSPC" else ticker
        ticker_rows = resolved[
            resolved["question"].str.contains(f"({tag})", na=False, regex=False)
        ]

        for _, row in ticker_rows.iterrows():
            end_date = row["end_date"]
            try:
                mkt_date = end_date.date() if hasattr(end_date, "date") else pd.to_datetime(end_date).date()
            except Exception:
                continue

            prices = row.get("outcome_prices")
            if isinstance(prices, str):
                try:
                    import ast as _ast
                    prices = _ast.literal_eval(prices)
                except Exception:
                    continue
            if not prices or len(prices) < 2:
                continue
            try:
                yes_p, no_p = float(prices[0]), float(prices[1])
            except (ValueError, TypeError):
                continue
            if max(yes_p, no_p) < 0.9:
                continue

            cid = str(row.get("condition_id") or "")
            if not cid:
                continue

            index[(ticker, mkt_date)] = {
                "condition_id": cid,
                "outcome_yes":  1 if yes_p > 0.5 else 0,
            }

    return index


def _slug_for(ticker: str, yahoo_sym: str, d: date) -> str:
    prefix = "spx" if yahoo_sym == "^GSPC" else yahoo_sym.lower()
    return f"{prefix}-up-or-down-on-{MONTH_NAMES[d.month-1]}-{d.day}-{d.year}"


def _fetch_from_gamma(slug: str) -> dict | None:
    """Return {condition_id, outcome_yes} from Gamma API or None if not resolved."""
    try:
        r = requests.get(f"{GAMMA_API}/events?slug={slug}", timeout=15)
        if r.status_code != 200:
            return None
        events = r.json()
        if not events:
            return None
        markets = events[0].get("markets", [])
        if not markets:
            return None
        mk = markets[0]

        prices = mk.get("outcomePrices") or mk.get("outcome_prices")
        if isinstance(prices, str):
            prices = json.loads(prices)
        if not prices or len(prices) < 2:
            return None
        yes_p, no_p = float(prices[0]), float(prices[1])
        if max(yes_p, no_p) < 0.9:
            return None

        cid = mk.get("conditionId") or mk.get("condition_id", "")
        return {"condition_id": cid, "outcome_yes": 1 if yes_p > 0.5 else 0}
    except Exception:
        return None


def get_market_meta(
    ticker: str, yahoo_sym: str, d: date,
    parquet_index: dict,
    parquet_cutoff: date,
) -> dict | None:
    """Return {condition_id, outcome_yes} for a (ticker, date) using the right source."""
    # Parquet covers up to its cutoff — prefer it (no API call, no rate limit)
    if d <= parquet_cutoff:
        return parquet_index.get((ticker, d))

    # Post-cutoff: live Gamma API lookup
    slug = _slug_for(ticker, yahoo_sym, d)
    result = _fetch_from_gamma(slug)
    time.sleep(0.3)  # rate limit
    return result


# ── Data helpers ─────────────────────────────────────────────────────────────


def get_vwap(df: pd.DataFrame) -> float | None:
    if len(df) == 0:
        return None
    total = df["usd_amount"].sum()
    return float((df["price"] * df["usd_amount"]).sum() / total) if total > 0 else None


def get_intraday(yahoo_sym: str, mkt_date: date, cache: dict) -> pd.DataFrame | None:
    if mkt_date in cache:
        return cache[mkt_date]
    try:
        import pytz
        eastern = pytz.timezone("US/Eastern")
        raw = yf.download(yahoo_sym, period="60d", interval="5m",
                          progress=False, auto_adjust=False)
        if raw.empty:
            cache[mkt_date] = None
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]
        raw.index = (raw.index.tz_convert(eastern) if raw.index.tz
                     else raw.index.tz_localize("UTC").tz_convert(eastern))
        day = raw[raw.index.date == mkt_date]
        result = day if len(day) >= 20 else None
        cache[mkt_date] = result
        return result
    except Exception:
        cache[mkt_date] = None
        return None


def trading_days(start: date, end: date) -> list[date]:
    from holidays import NYSE
    holidays = NYSE(years=range(start.year, end.year + 1))
    days, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in holidays:
            days.append(d)
        d += timedelta(days=1)
    return days


# ── Settlement probability table ─────────────────────────────────────────────


def build_probability_table(df: pd.DataFrame) -> pd.DataFrame:
    """P(settle YES | time_bucket × price_bucket × gfr_bucket)."""
    results = []
    for t_label, t_hi, t_lo in TIME_BUCKETS:
        t_sub = df[(df["tbf_min"] <= t_hi) & (df["tbf_min"] > t_lo)]
        if len(t_sub) == 0:
            continue
        for p_label, p_lo, p_hi in PRICE_BUCKETS:
            p_sub = t_sub[(t_sub["yes_vwap"] >= p_lo) & (t_sub["yes_vwap"] < p_hi)]
            if len(p_sub) < 3:
                continue
            n, wins = len(p_sub), p_sub["outcome_yes"].sum()
            results.append({
                "time_bucket": t_label, "price_bucket": p_label, "gfr_bucket": "ALL",
                "n_obs": n, "p_settle_yes": round(wins / n * 100, 1),
                "implied_prob": round((p_lo + p_hi) / 2 * 100, 1),
                "edge_vs_market": round((wins / n - (p_lo + p_hi) / 2) * 100, 1),
            })
            g_avail = p_sub.dropna(subset=["gfr"])
            for g_label, g_lo, g_hi in GFR_BUCKETS:
                g_sub = g_avail[(g_avail["gfr"] >= g_lo) & (g_avail["gfr"] < g_hi)]
                if len(g_sub) < 3:
                    continue
                ng, wg = len(g_sub), g_sub["outcome_yes"].sum()
                results.append({
                    "time_bucket": t_label, "price_bucket": p_label, "gfr_bucket": g_label,
                    "n_obs": ng, "p_settle_yes": round(wg / ng * 100, 1),
                    "implied_prob": round((p_lo + p_hi) / 2 * 100, 1),
                    "edge_vs_market": round((wg / ng - (p_lo + p_hi) / 2) * 100, 1),
                })
    return pd.DataFrame(results)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", default="2026-05-02",
                        help="Start date YYYY-MM-DD (default: 2026-05-02)")
    parser.add_argument("--to",   dest="end",   default=date.today().isoformat(),
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--rebuild", action="store_true",
                        help="Full rebuild from scratch (ignores existing CSV rows). "
                             "Combine with --from 2025-10-16 to rebuild everything.")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)

    # ── Load markets.parquet index (fast lookup for pre-cutoff dates) ─────────
    print("Loading markets.parquet index...")
    parquet_index = _load_parquet_index()
    parquet_cutoff = max((d for _, d in parquet_index.keys()), default=date(2026, 5, 1))
    print(f"  Parquet index: {len(parquet_index):,} markets | cutoff: {parquet_cutoff}")
    print(f"  Dates ≤ {parquet_cutoff}: parquet lookup | Dates > {parquet_cutoff}: Gamma API")

    # ── Load existing CSV to skip already-processed (ticker, date) pairs ──────
    existing: set[tuple[str, str]] = set()
    if OUT_CSV.exists() and not args.rebuild:
        df_existing = pd.read_csv(OUT_CSV, usecols=["ticker", "date"])
        for _, row in df_existing.iterrows():
            existing.add((row["ticker"], str(row["date"])))
        print(f"  Existing CSV: {len(df_existing):,} rows | {len(existing)} (ticker,date) pairs")
    elif args.rebuild:
        print("  --rebuild: ignoring existing CSV, will rewrite from scratch")

    days = trading_days(start, end)
    print(f"  Trading days to process: {len(days)} ({start} → {end})\n")

    # ── Load all trade parquets once ──────────────────────────────────────────
    trades_by_ticker: dict[str, pd.DataFrame] = {}
    for name, _ in TICKERS:
        path = DATA_DIR / f"{name.lower()}_trades.parquet"
        if path.exists():
            trades_by_ticker[name] = pd.read_parquet(path)
        else:
            print(f"  WARNING: {path} not found — {name} will be skipped")

    new_rows: list[dict] = []
    intraday_cache: dict = {}

    for d in days:
        dow_name = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][d.weekday()]
        print(f"\n{d} ({dow_name})")

        for ticker, yahoo_sym in TICKERS:
            if (ticker, str(d)) in existing:
                print(f"  {ticker:6s}: already in CSV, skip")
                continue

            # ── Metadata: condition_id + outcome ─────────────────────────────
            mkt = get_market_meta(ticker, yahoo_sym, d, parquet_index, parquet_cutoff)
            if mkt is None:
                src = "parquet" if d <= parquet_cutoff else "Gamma API"
                print(f"  {ticker:6s}: no resolved market ({src})")
                continue

            cid         = mkt["condition_id"]
            outcome_yes = mkt["outcome_yes"]

            # ── yfinance daily for gap ────────────────────────────────────────
            try:
                hist = yf.Ticker(yahoo_sym).history(
                    start=d - timedelta(days=10), end=d + timedelta(days=1))
                if hist.empty or len(hist) < 2:
                    print(f"  {ticker:6s}: no yfinance data")
                    continue
                today_bar  = hist.iloc[-1]
                today_date = today_bar.name.date() if hasattr(today_bar.name, "date") else today_bar.name
                if today_date != d:
                    print(f"  {ticker:6s}: yfinance date mismatch ({today_date} ≠ {d})")
                    continue
                prev_close  = float(hist.iloc[-2]["Close"])
                open_price  = float(today_bar["Open"])
                if prev_close == 0 or open_price == 0:
                    continue
                gap_pct     = (open_price - prev_close) / prev_close * 100
                gap_dollars = open_price - prev_close
            except Exception as e:
                print(f"  {ticker:6s}: yfinance error: {e}")
                continue

            # ── Trades ───────────────────────────────────────────────────────
            trades = trades_by_ticker.get(ticker)
            if trades is None or len(trades) == 0:
                print(f"  {ticker:6s}: no trade parquet")
                continue

            import pytz
            eastern = pytz.timezone("US/Eastern")
            end_dt  = eastern.localize(
                __import__("datetime").datetime(d.year, d.month, d.day, 16, 0, 0))
            end_ts  = int(end_dt.timestamp())

            ticker_trades = trades[trades["condition_id"] == cid]
            if len(ticker_trades) == 0:
                print(f"  {ticker:6s}: 0 trades for cid {cid[:12]}...")
                continue

            intraday    = get_intraday(yahoo_sym, d, intraday_cache)
            ticker_rows = 0

            for tbf in INTERVALS_BEFORE_CLOSE:
                target_ts = end_ts - tbf * 60
                window = ticker_trades[
                    (ticker_trades["timestamp"] >= target_ts - 60) &
                    (ticker_trades["timestamp"] <= target_ts + 60)
                ]
                yes_vwap = get_vwap(window)
                if yes_vwap is None:
                    continue

                gfr = None
                if intraday is not None and abs(gap_dollars) > 0.001:
                    tick_h = (16 * 60 - tbf) // 60
                    tick_m = (16 * 60 - tbf) % 60
                    bars = intraday[
                        (intraday.index.hour < tick_h) |
                        ((intraday.index.hour == tick_h) & (intraday.index.minute <= tick_m))
                    ]
                    if len(bars) > 0:
                        gfr = (float(bars.iloc[-1]["Close"]) - open_price) / gap_dollars
                        gfr = max(-5.0, min(5.0, gfr))

                new_rows.append({
                    "ticker":      ticker,
                    "date":        str(d),
                    "dow":         dow_name,
                    "tbf_min":     tbf,
                    "yes_vwap":    round(yes_vwap, 4),
                    "gfr":         round(gfr, 3) if gfr is not None else None,
                    "gap_pct":     round(gap_pct, 3),
                    "outcome_yes": outcome_yes,
                    "n_trades":    len(window),
                })
                ticker_rows += 1

            print(f"  {ticker:6s}: {ticker_rows} intervals | gap={gap_pct:+.1f}% | "
                  f"outcome={'YES' if outcome_yes else 'NO'} | trades={len(ticker_trades)}")

    # ── Write new rows ────────────────────────────────────────────────────────
    if not new_rows:
        print("\nNo new rows — CSV already up to date.")
    else:
        df_new = pd.DataFrame(new_rows)
        print(f"\nNew rows generated: {len(df_new):,}")

        if args.rebuild:
            # Full rebuild: combine with existing file (minus the date range we just rebuilt)
            if OUT_CSV.exists():
                df_old = pd.read_csv(OUT_CSV)
                rebuilt_dates = {str(d) for d in days}
                df_old = df_old[~df_old["date"].isin(rebuilt_dates)]
                df_combined = pd.concat([df_old, df_new], ignore_index=True)
                df_combined.sort_values(["date", "ticker", "tbf_min"], inplace=True)
                df_combined.to_csv(OUT_CSV, index=False)
            else:
                df_new.to_csv(OUT_CSV, index=False)
        else:
            df_new.to_csv(OUT_CSV, mode="a", header=not OUT_CSV.exists(), index=False)

        print(f"Written to {OUT_CSV}")

    # ── Regenerate settlement_probability.csv ─────────────────────────────────
    if OUT_CSV.exists():
        df_all = pd.read_csv(OUT_CSV)
        print(f"\nTotal rows: {len(df_all):,} | Date range: {df_all['date'].min()} → {df_all['date'].max()}")
        prob_df = build_probability_table(df_all)
        prob_df.to_csv(OUT_PROB, index=False)
        print(f"Settlement probability table: {len(prob_df)} cells → {OUT_PROB}")


if __name__ == "__main__":
    main()
