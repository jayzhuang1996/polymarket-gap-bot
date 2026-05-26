#!/usr/bin/env python3
"""
Daily Stock Gap Mispricing Bot — Paper Trade Engine

Usage:
  python main.py scan            Multi-scan 9:30-10:30 → decisions at 10:30
  python main.py scan --force    Single immediate scan (for testing/backfill)
  python main.py resolve         Evening resolve (4pm+) — binary settlement + exit checks
  python main.py today           Full daily loop: scan → hold → resolve
  python main.py                 Same as 'scan'
"""

import sys
import json
import time
import argparse
import requests
import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta

from config import (
    TICKERS,
    POSITION_SIZE_USD,
    MAX_YES_PRICE,
    MAX_POSITIONS_SIMULTANEOUS,
    SPX_PRIORITY,
    ENTRY_WINDOWS,
    ENTRY_FREEZE_TIME,
    LATE_ENTRY_CUTOFF,
    LATE_ENTRY_MAX_SPREAD_PCT,
    LATE_ENTRY_MIN_EDGE,
    THURSDAY_EDGE_MIN,
    THURSDAY_CONVICTION,
    FRIDAY_SKIP_GAP_UP,
    FRIDAY_EDGE_MIN,
    is_thursday,
    is_friday,
    BANKROLL_USD,
    CLOB_EXIT_DISCOUNT,
    TIME_EXIT,
)
from engine.sizer import compute_position_size
from database.db import (
    init_db,
    store_decision,
    store_outcome,
    get_unresolved_decisions,
)
from database.wr_store import load_base_wr, daily_update
from engine.scanner import MultiScanDecider, Decision
from engine.exit_model import estimate_token_price as _calibrated_token_price, calibration_available

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
SLUG_OVERRIDES = {"^GSPC": "spx"}

today = datetime.now(timezone.utc)
TODAY_STR = today.strftime("%Y-%m-%d")


# ── Time Helpers ─────────────────────────────────────────────────────────────

# US Eastern offset: EDT = UTC-4 (Mar-Nov), EST = UTC-5 (Nov-Mar)
_ET_OFFSET = timedelta(hours=-4)


def _et_now() -> str:
    return (datetime.now(timezone.utc) + _ET_OFFSET).strftime("%H:%M")


def _et_dt() -> datetime:
    """Current datetime in ET (naive)."""
    return datetime.now(timezone.utc) + _ET_OFFSET


def _now() -> str:
    return (datetime.now(timezone.utc) + _ET_OFFSET).strftime("%H:%M:%S ET")


def _is_in_window(ticker: str) -> bool:
    now_et = _et_now()
    win = ENTRY_WINDOWS.get(ticker)
    if not win:
        return True
    start, end = win
    return start <= now_et <= end


def _slug(yahoo_ticker: str) -> str:
    prefix = SLUG_OVERRIDES.get(yahoo_ticker, yahoo_ticker.lower())
    return (
        f"{prefix}-up-or-down-on-"
        f"{MONTH_NAMES[today.month - 1]}-{today.day}-{today.year}"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_price(resp) -> float | None:
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
        return float(data["price"]) if isinstance(data, dict) else None
    except (ValueError, json.JSONDecodeError, KeyError):
        return None


# ── yfinance Retry Wrapper ─────────────────────────────────────────────────────


def _yf_history(ticker: str, period: str = "5d", interval: str = "1d",
                max_retries: int = 3) -> pd.DataFrame:
    """Fetch yfinance history with exponential backoff retry.

    yfinance is a reverse-engineered scraper with no SLA. A single rate-limit
    at 9:30am kills the entire trading day. Three retries with 1/2/4s backoff
    handles transient 429s and connection drops.

    Falls back to empty DataFrame if all retries fail (caller handles the None).
    """
    import time as _time
    for attempt in range(max_retries):
        try:
            stock = yf.Ticker(ticker)
            if interval == "1d":
                result = stock.history(period=period)
            else:
                result = stock.history(period=period, interval=interval)
            if not result.empty:
                return result
        except Exception:
            pass
        if attempt < max_retries - 1:
            _time.sleep(1 + 2 ** attempt)  # 1s, 2s, 4s
    return pd.DataFrame()


# ── Data Functions ────────────────────────────────────────────────────────────


def find_market(display_name: str, yahoo_ticker: str) -> dict | None:
    """Find today's Polymarket event via Gamma slug search.

    Returns both YES and NO token IDs.
    clobTokenIds is a JSON string: ["YES_token", "NO_token"]
    """
    slug = _slug(yahoo_ticker)
    try:
        resp = requests.get(f"{GAMMA_API}/events?slug={slug}", timeout=15)
        if resp.status_code != 200:
            return None
        events = resp.json()
        if not events:
            return None

        markets = events[0].get("markets", [])
        mk = markets[0] if markets else None
        if not mk:
            return None

        raw = mk.get("clobTokenIds") or "[]"
        ids = json.loads(raw) if isinstance(raw, str) else (raw or [])

        return {
            "slug": slug,
            "question": mk.get("question", ""),
            "token_id": str(ids[0]).strip() if len(ids) > 0 else None,
            "no_token_id": str(ids[1]).strip() if len(ids) > 1 else None,
        }
    except (requests.RequestException, json.JSONDecodeError):
        return None


def calc_gap(yahoo_ticker: str) -> tuple[float | None, float | None, float | None]:
    """Return (gap_pct, open_price, prev_close) via yfinance daily OHLC.

    gap = (open - prev_close) / prev_close
    """
    try:
        hist = _yf_history(yahoo_ticker, period="5d")
        if len(hist) < 2:
            return None, None, None
        today_bar = hist.iloc[-1]
        prev_close = float(hist.iloc[-2]["Close"])
        today_open = float(today_bar["Open"])
        if today_open == 0 or prev_close == 0:
            return None, None, None
        gap = (today_open - prev_close) / prev_close
        return gap, today_open, prev_close
    except Exception:
        return None, None, None


def get_current_price(yahoo_ticker: str) -> float | None:
    """Get the most recent stock price via yfinance intraday data."""
    try:
        hist = _yf_history(yahoo_ticker, period="5d")
        if hist.empty:
            return None
        # Try intraday 5m first, fall back to daily close
        try:
            intra = _yf_history(yahoo_ticker, period="1d", interval="5m")
            if not intra.empty:
                return float(intra.iloc[-1]["Close"])
        except Exception:
            pass
        return float(hist.iloc[-1]["Close"])
    except Exception:
        return None


def get_clob_price(token_id: str) -> tuple[float | None, float | None]:
    """Return (best_bid, best_ask) for any token."""
    try:
        bid = _parse_price(requests.get(
            f"{CLOB_API}/price", params={"token_id": token_id, "side": "BUY"}, timeout=10,
        ))
        ask = _parse_price(requests.get(
            f"{CLOB_API}/price", params={"token_id": token_id, "side": "SELL"}, timeout=10,
        ))
        return bid, ask
    except Exception:
        return None, None


def get_depth(token_id: str, side: str) -> float:
    """Contracts at the best level on a given side ('bids' or 'asks')."""
    try:
        resp = requests.get(f"{CLOB_API}/book", params={"token_id": token_id}, timeout=10)
        if resp.status_code != 200:
            return 0
        levels = resp.json().get(side, [])
        return float(levels[0]["size"]) if levels else 0
    except Exception:
        return 0


# ── Scan ──────────────────────────────────────────────────────────────────────


def run_scan(force: bool = False):
    """Multi-scan from 9:30-10:30 ET, then decide.

    Args:
        force: If True, run one immediate scan and decide (for testing/backfill).
    """
    init_db()
    et_start = _et_dt()
    print(f"\n{'='*90}")
    print(f"  MULTI-SCAN — {TODAY_STR} at {_now()}")
    print(f"{'='*90}")

    if not force:
        hour = et_start.hour
        minute = et_start.minute
        if hour < 9 or (hour == 9 and minute < 35):
            print("  Market not open yet. First 5m candle closes at 9:35am ET.")
            print("  Use --force for testing.")
            return
        freeze_h, freeze_m = map(int, ENTRY_FREEZE_TIME.split(":"))
        if hour > freeze_h or (hour == freeze_h and minute >= freeze_m):
            print(f"  Past {ENTRY_FREEZE_TIME} ET entry freeze — no new entries.")
            return

    open_positions = len(get_unresolved_decisions())

    # ── Pre-scan: find markets, gaps, create deciders ──
    markets = {}
    gaps = {}
    deciders = {}
    obs_counts: dict[str, int] = {}   # effective obs per ticker for CI-based Kelly

    print(f"\n  Pre-scanning {len(TICKERS)} tickers...\n")

    for display_name, yahoo_ticker in TICKERS:
        if not force and not _is_in_window(display_name):
            print(f"  {display_name:6s}: outside entry window, skipping")
            store_decision(
                date_str=TODAY_STR, ticker=display_name, slug=None,
                decision=f"SKIP (outside window)",
            )
            continue

        market = find_market(display_name, yahoo_ticker)
        if not market:
            print(f"  {display_name:6s}: no market found")
            continue

        gap_pct, open_price, prev_close = calc_gap(yahoo_ticker)
        if gap_pct is None or open_price is None:
            print(f"  {display_name:6s}: no gap data")
            continue

        # Load base WR — returns (yes_wr, no_wr, effective_obs) for CI-based Kelly
        gap_up = gap_pct > 0
        base_yes, base_no, eff_obs = load_base_wr(display_name, gap_up)
        obs_counts[display_name] = eff_obs
        gap_label = f"{gap_pct*10000:+.0f} bps"
        print(f"  {display_name:6s}: gap={gap_label}, open=${open_price:.2f}, base_WR={base_yes if gap_up else base_no:.0%} (n≈{eff_obs})")

        decider = MultiScanDecider(
            ticker=display_name,
            gap_pct=gap_pct,
            open_price=open_price,
            prev_close=prev_close,
            base_wr_yes=base_yes,
            base_wr_no=base_no,
        )

        markets[display_name] = market
        gaps[display_name] = gap_pct
        deciders[display_name] = decider

    if not deciders:
        print("\n  No tradeable tickers today.")
        return

    # ── Scan loop ──
    # Extended window: 9:35am → 12pm = 145 min / 5 min = 29 scans max
    n_scans = 1 if force else 29
    scan_results = []
    decisions_made: set[str] = set()

    for round_i in range(n_scans):
        round_time = _et_now()

        if round_i > 0 and not force:
            print(f"\n  ── Scan round {round_i + 1}/{n_scans} at {round_time} ──")
            time.sleep(300)  # 5 min between scans
        else:
            print(f"\n  ── Scan round {round_i + 1}/{n_scans} at {round_time} ──")

        for display_name, yahoo_ticker in TICKERS:
            if display_name not in deciders:
                continue
            if display_name in decisions_made:
                continue

            market = markets[display_name]
            decider = deciders[display_name]

            # 1. Current stock price
            current_price = get_current_price(yahoo_ticker)
            if current_price is None:
                current_price = decider.open_price  # fallback to open
            gap_label = f"{gaps[display_name]*10000:+.0f}"

            # 2. CLOB prices
            yes_bid, yes_ask = get_clob_price(market["token_id"])
            no_bid, no_ask = None, None
            if market.get("no_token_id"):
                no_bid, no_ask = get_clob_price(market["no_token_id"])
            yes_depth = get_depth(market["token_id"], "asks")
            no_depth = get_depth(market["no_token_id"], "asks") if market.get("no_token_id") else 0

            if not yes_ask or not no_ask:
                print(f"  {display_name:6s}: no CLOB prices (gap={gap_label})")
                continue

            # 3. Add scan to decider
            decider.add_scan(
                et_time=round_time,
                current_price=current_price,
                yes_bid=yes_bid or 0,
                yes_ask=yes_ask,
                no_bid=no_bid or 0,
                no_ask=no_ask,
                yes_depth=yes_depth,
                no_depth=no_depth,
            )

            # 3b. Early fire: don't wait for window close if conviction is already STRONG.
            # Requirement: ≥4 scans, STRONG conviction, edge ≥ 8%.
            # Why 8%: early entries get more ladder time, so a higher threshold
            # compensates for the reduced confirmation window.
            if not force and len(decider.scans) >= 4:
                early = decider.decide(min_scans=4)
                if (early.is_buy
                        and early.conviction == "STRONG"
                        and early.edge is not None
                        and early.edge >= 0.08):
                    _log_decision(display_name, market, gaps[display_name], early,
                                  yes_bid, yes_ask, open_positions, scan_results,
                                  obs_counts.get(display_name, 0))
                    if early.is_buy:
                        open_positions += 1
                    decisions_made.add(display_name)
                    print(f"  → {display_name:6s}: EARLY FIRE — {early.reason}")
                    continue

            # 4. If entry window closed, decide now
            if not force and not _is_in_window(display_name):
                # Late entries (after 10:30am) require tighter thresholds
                is_late = _et_now() >= LATE_ENTRY_CUTOFF
                decision = decider.decide()

                if decision.is_buy:
                    from engine.scanner import Decision as _D
                    # Friday: require same higher bar as Thursday (data too thin for outright block)
                    if is_friday() and gaps.get(display_name, 0) > 0:
                        if (decision.edge is None or decision.edge < FRIDAY_EDGE_MIN
                                or decision.conviction != THURSDAY_CONVICTION):
                            decision = _D("SKIP", None, None, None, decision.conviction,
                                          f"Friday gate: need STRONG + edge ≥{FRIDAY_EDGE_MIN*100:.0f}%",
                                          "friday_gate")
                    # Thursday: require higher edge + STRONG conviction only
                    if decision.is_buy and is_thursday():
                        if (decision.edge is None or decision.edge < THURSDAY_EDGE_MIN
                                or decision.conviction != THURSDAY_CONVICTION):
                            decision = _D("SKIP", None, None, None, decision.conviction,
                                          f"Thursday gate: need STRONG + edge ≥{THURSDAY_EDGE_MIN*100:.0f}%",
                                          "thursday_gate")
                    # Late entries (after 10:30am): tighter spread + edge
                    if decision.is_buy and is_late:
                        if decision.edge is None or decision.edge < LATE_ENTRY_MIN_EDGE:
                            decision = _D("SKIP", None, None, None, decision.conviction,
                                          f"late entry: edge {(decision.edge or 0)*100:.1f}% < {LATE_ENTRY_MIN_EDGE*100:.0f}%",
                                          "late_insufficient_edge")

                _log_decision(display_name, market, gaps[display_name], decision,
                              yes_bid, yes_ask, open_positions, scan_results,
                              obs_counts.get(display_name, 0))
                if decision.is_buy:
                    open_positions += 1
                decisions_made.add(display_name)
                print(f"  → {display_name:6s}: {'[LATE] ' if is_late else ''}{decision.reason}")

        if force:
            break  # single scan in force mode

    # ── Post-scan: decide everything remaining ──
    print(f"\n  ── Finalising decisions at {_et_now()} ──")
    for display_name in deciders:
        if display_name in decisions_made:
            continue
        decider = deciders[display_name]
        decision = decider.decide(min_scans=1 if force else None)
        _log_decision(display_name, markets[display_name], gaps[display_name], decision,
                      None, None, open_positions, scan_results,
                      obs_counts.get(display_name, 0))
        if decision and decision.is_buy:
            open_positions += 1
        print(f"  {display_name:6s}: {decision.reason if decision else 'no decision'}")

    # ── Summary ──
    actionable = [r[0] for r in scan_results if r[1] == "BUY"]
    print(f"\n{'='*90}")
    print(f"  MULTI-SCAN SUMMARY — {TODAY_STR}")
    print(f"{'='*90}")
    print(f"  {'Ticker':<8} {'Action':<6} {'Side':<5} {'Entry':<8} {'Edge':<7} {'Conviction':<10} {'Reason'}")
    print(f"  {'-'*85}")
    for r in scan_results:
        ticker, action, side, price, edge, conviction, reason = r
        price_s = f"${price:.2f}" if price else "—"
        edge_s = f"{edge*100:+.1f}%" if edge is not None else "—"
        print(f"  {ticker:<8} {action:<6} {side or '—':<5} {price_s:<8} {edge_s:<7} {conviction:<10} {reason}")
    print(f"  {'-'*85}")
    print(f"  RESULTS: {len(actionable)}/{len(TICKERS)} actionable -> {actionable}")
    print(f"{'='*90}\n")


def _log_decision(
    display_name: str, market: dict, gap_pct: float,
    decision: Decision | None, yes_bid, yes_ask,
    open_positions: int, scan_results: list,
    n_obs: int = 0,
):
    """Store a decision to DB and append to scan_results."""
    if decision is None:
        store_decision(
            date_str=TODAY_STR, ticker=display_name, slug=market["slug"],
            decision="SKIP (no decision)",
            gap_bps=gap_pct * 10000 if gap_pct else None,
        )
        scan_results.append((display_name, "SKIP", None, None, None, "—", "no decision"))
        return

    entry_side = decision.side if decision.is_buy else None
    entry_price = decision.price if decision.is_buy else None

    # Kelly position sizing: CI-lower-bound when n_obs available, else point estimate
    if decision.is_buy and decision.win_rate is not None and entry_price:
        position_size = compute_position_size(decision.win_rate, entry_price, n_obs)
        if position_size <= 0:
            # Kelly says skip — insufficient edge to justify capital at risk
            store_decision(
                date_str=TODAY_STR, ticker=display_name, slug=market["slug"],
                decision=f"SKIP (Kelly: insufficient edge)",
                gap_bps=gap_pct * 10000 if gap_pct else None,
            )
            scan_results.append((display_name, "SKIP", None, None, None, decision.conviction,
                                 f"Kelly skip: WR={decision.win_rate:.0%} price=${entry_price:.2f}"))
            return
    else:
        position_size = POSITION_SIZE_USD if decision.is_buy else 0

    expected_edge = decision.edge if decision.is_buy else None
    skip_reason = decision.skip_reason

    gap_bps = gap_pct * 10000 if gap_pct else None

    store_decision(
        date_str=TODAY_STR,
        ticker=display_name,
        slug=market["slug"],
        decision=f"{decision.action} {decision.side or ''} ({decision.reason})".strip(),
        gap_bps=gap_bps,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        entry_side=entry_side,
        entry_price=entry_price,
        position_size=position_size,
        expected_edge=expected_edge,
    )

    if decision.is_buy:
        output = (display_name, "BUY", entry_side, entry_price, expected_edge, decision.conviction, decision.reason)
    else:
        output = (display_name, "SKIP", None, None, None, decision.conviction, decision.reason)

    scan_results.append(output)


# ── Resolve (Evening) ─────────────────────────────────────────────────────────


def run_resolve():
    """Resolve all outstanding decisions via exit ladder + binary settlement.

    For each open position:
      1. Walk through intraday 5m bars, estimate token price from stock path.
      2. Execute gradual offload at WIN thresholds (scale_out) or RISK thresholds (risk_exit).
      3. Settle remaining contracts at binary $1/$0.
      4. Compute blended exit price and aggregated P&L.
    """
    init_db()
    unresolved = get_unresolved_decisions()

    if not unresolved:
        print(f"\n  No unresolved decisions to resolve on {TODAY_STR}.\n")
        return

    print(f"\n{'='*90}")
    print(f"  RESOLVING POSITIONS — {TODAY_STR} at {_now()}")
    cal_status = "calibrated table" if calibration_available() else "linear formula (run tools/calibrate_exit_model.py to upgrade)"
    print(f"  Exit model: {cal_status}")
    print(f"{'='*90}")

    results = []

    for row in unresolved:
        ticker = row["ticker"]
        entry_side = row["entry_side"]
        entry_price = row["entry_price"]
        position_size = row["position_size"]

        yahoo_ticker = next((yt for dn, yt in TICKERS if dn == ticker), None)
        if not yahoo_ticker:
            print(f"  {ticker}: unknown yahoo ticker, skipping")
            continue

        # Get OHLC for open/prev_close (gap calc for exit ladder)
        try:
            hist = _yf_history(yahoo_ticker, period="5d")
            today_bar = hist.iloc[-1]
            open_price = float(today_bar["Open"])
            close_price = float(today_bar["Close"])
            prev_close = float(hist.iloc[-2]["Close"])
        except (IndexError, Exception) as e:
            print(f"  {ticker}: yfinance error: {e}")
            continue

        contracts = position_size / entry_price if entry_price and entry_price > 0 else 0

        # Load base WR for edge-exhaustion trigger inside the ladder
        gap_up = (open_price > prev_close)
        try:
            _yes_wr, _no_wr, _obs = load_base_wr(ticker, gap_up)
            base_wr = _yes_wr if entry_side == "YES" else _no_wr
        except Exception:
            base_wr = 0.60

        abs_gap_pct = abs((open_price - prev_close) / prev_close * 100) if prev_close > 0 else 0.0

        # Intraday exit ladder between entry time (10:30am) and TIME_EXIT (2pm ET)
        hist_5m = _intraday_5m(yahoo_ticker, min_time="10:30", max_time="15:05")
        ladder = _simulate_exit_ladder(hist_5m, open_price, prev_close,
                                       entry_side, entry_price, position_size,
                                       base_wr=base_wr, abs_gap_pct=abs_gap_pct)

        # Aggregate P&L from ladder partial exits
        total_proceeds = 0.0
        total_sold = 0.0
        for _, exit_price, sold, _ in ladder["partial_exits"]:
            total_proceeds += sold * exit_price
            total_sold += sold

        # ── Tiered time exits ──────────────────────────────────────────────────
        # 2:00pm: review — deep in-money (≥85¢, gfr ≥+0.5) can hold; else sell
        # 2:30pm: sell all except tokens ≥85¢ with gfr ≥+0.2
        # 3:00pm: HARD EXIT — sell everything regardless (MOC danger zone)
        remaining = ladder["remaining_contracts"]
        time_exit_pnl = 0.0

        def _est_at_time(cutoff_time: str) -> tuple[float, float]:
            """Get est_price and gfr from the last bar at or before cutoff_time."""
            if hist_5m is None or hist_5m.empty:
                return entry_price, 0.0
            from datetime import datetime as _dt
            cut_h, cut_m = map(int, cutoff_time.split(":"))
            cut_t = _dt.strptime(cutoff_time, "%H:%M").time()
            bars = hist_5m[hist_5m.index.time <= cut_t]
            if bars.empty:
                bars = hist_5m
            bar = bars.iloc[-1]
            sp = float(bar["Close"])
            gd = open_price - prev_close
            gfr_val = (sp - open_price) / gd if abs(gd) > 0.001 else 0.0
            time_str = bars.index[-1].strftime("%H:%M")
            dow_str  = bars.index[-1].strftime("%a")
            ep, _ = _calibrated_token_price(
                time_str, gfr_val, entry_price, dow_str, abs_gap_pct=abs_gap_pct
            )
            return ep, gfr_val

        if remaining > 0.5:
            ep_2pm, gfr_2pm = _est_at_time("14:00")
            # 2pm: hold only if deep in-money with strong gfr
            hold_past_2pm = ep_2pm >= 0.85 and gfr_2pm >= 0.5
            if not hold_past_2pm:
                # Standard 2pm exit
                time_exit_pnl = remaining * (ep_2pm - entry_price)
                total_proceeds += remaining * ep_2pm
                total_sold += remaining
                remaining = 0
            else:
                ep_230, gfr_230 = _est_at_time("14:30")
                hold_past_230 = ep_230 >= 0.85 and gfr_230 >= 0.2
                if not hold_past_230:
                    time_exit_pnl = remaining * (ep_230 - entry_price)
                    total_proceeds += remaining * ep_230
                    total_sold += remaining
                    remaining = 0
                else:
                    # 3pm hard exit — no exceptions, MOC danger zone
                    ep_3pm, _ = _est_at_time("15:00")
                    time_exit_pnl = remaining * (ep_3pm - entry_price)
                    total_proceeds += remaining * ep_3pm
                    total_sold += remaining
                    remaining = 0

        # Blended exit price across all partial exits + time exit
        ladder_pnl = sum(pnl for (_, _, _, pnl) in ladder["partial_exits"])
        blended_price = round(total_proceeds / total_sold, 4) if total_sold > 0 else entry_price
        total_pnl = round(ladder_pnl + time_exit_pnl, 2)

        # Categorise exit
        if ladder["triggers"]:
            risk_hit = any(t.startswith("risk") for t in ladder["triggers"])
            exit_type = "risk_exit" if risk_hit else "scale_out"
        elif total_sold > 0:
            exit_type = "time_exit"
        else:
            exit_type = "time_exit"

        store_outcome(row["id"], TODAY_STR, ticker,
                      None,  # no binary settlement — price exit only
                      total_pnl, exit_price=blended_price, exit_type=exit_type)
        results.append((ticker, entry_side, entry_price,
                        close_price > prev_close, total_pnl, exit_type,
                        ladder["triggers"]))

        close_str = f"UP  ({close_price:.2f})" if close_price > prev_close else f"DOWN ({close_price:.2f})"
        pnl_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"
        exit_str = {"resolve": "settle", "scale_out": "scale", "risk_exit": "risk"}.get(exit_type, exit_type)
        trigger_str = f" [{', '.join(ladder['triggers'])}]" if ladder["triggers"] else ""
        print(f"  {ticker:6s}  {close_str}  {entry_side} ${entry_price:.2f} → {pnl_str} ({exit_str}{trigger_str})")

    # Update WR table from scraped observations only
    stored = daily_update()
    print(f"\n     WR table: updated {stored} entries")

    if results:
        total_pnl = sum(r[4] for r in results)
        wins = sum(1 for r in results if r[4] > 0)
        losses = sum(1 for r in results if r[4] < 0)

        print(f"\n{'='*90}")
        print(f"  RESOLVE SUMMARY — {TODAY_STR}")
        print(f"{'='*90}")
        print(f"  {'Ticker':<8} {'Side':<6} {'Entry':<8} {'Close':<12} {'P&L':<10} {'Exit':<15} {'Triggers':<20}")
        print(f"  {'-'*75}")
        for r in results:
            side = r[1]
            entry = f"${r[2]:.2f}" if r[2] else "N/A"
            close_str = "UP" if r[3] else "DOWN"
            pnl_str = f"${r[4]:.2f}"
            exit_str = {"resolve": "settle", "scale_out": "scale", "risk_exit": "risk"}.get(r[5], r[5])
            trigger_str = ", ".join(r[6]) if r[6] else "—"
            print(f"  {r[0]:<8} {side:<6} {entry:<8} {close_str:<12} {pnl_str:<10} {exit_str:<15} {trigger_str:<20}")
        print(f"  {'-'*75}")
        print(f"  TOTAL: ${total_pnl:.2f}  ({wins}W / {losses}L)")
        print(f"{'='*90}\n")


# ── Intraday Exit Detection ──────────────────────────────────────────────────


def _intraday_5m(yahoo_ticker: str, min_time: str | None = None, max_time: str | None = None) -> pd.DataFrame | None:
    """Load today's 5-minute bars from yfinance.

    Filters to today's date in ET. Optionally clips to bars after min_time
    (e.g. "10:30" to only see post-entry bars) and before max_time
    (e.g. "14:00" for all bars up to 2pm ET).

    Returns None on failure or empty."""
    try:
        hist = _yf_history(yahoo_ticker, period="2d", interval="5m")
        if hist.empty:
            return None

        import pytz
        eastern = pytz.timezone("US/Eastern")
        hist.index = hist.index.tz_convert(eastern) if hist.index.tz else hist.index.tz_localize("UTC").tz_convert(eastern)
        today = hist[hist.index.date == _et_dt().date()]
        if min_time:
            min_t = datetime.strptime(min_time, "%H:%M").time()
            today = today[today.index.time >= min_t]
        if max_time:
            max_t = datetime.strptime(max_time, "%H:%M").time()
            today = today[today.index.time <= max_t]
        return today
    except Exception:
        return None


def _estimate_token_price(
    stock_price: float, open_price: float, prev_close: float,
    entry_price: float,
    time_et: str = "13:00",
    abs_gap_pct: float = 0.0,
) -> float:
    """Estimate binary token price from stock price path.

    Uses the calibrated lookup table (engine/exit_model.py) when available.
    Falls back to the linear formula if the table has not been built yet or
    has insufficient data for the current (time, gfr) cell.

    Build the table by running: python tools/calibrate_exit_model.py
    """
    gap_dollars = open_price - prev_close
    if abs(gap_dollars) < 0.001:
        return entry_price
    gfr = (stock_price - open_price) / gap_dollars
    est, _ = _calibrated_token_price(time_et, gfr, entry_price, abs_gap_pct=abs_gap_pct)
    return est


def _simulate_exit_ladder(
    hist_5m: pd.DataFrame,
    open_price: float,
    prev_close: float,
    entry_side: str,
    entry_price: float,
    position_size: float,
    base_wr: float = 0.60,     # historical WR for this ticker + gap direction
    abs_gap_pct: float = 0.0,  # absolute overnight gap % — passed to exit model tier 1
) -> dict:
    """Walk through 5m bars and execute gradual position offload at thresholds.

    WIN thresholds (position gaining value):
      Capture 20% of max gain → sell 20% of remaining contracts
      Capture 50% of max gain → sell 50% of remaining
      Capture 80% of max gain → sell 80% of remaining

    RISK thresholds (position losing value):
      Lose 40% of entry value → sell 40% of remaining
      Lose 70% of entry value → sell 70% of remaining
      Lose 100% of entry value → sell 100% of remaining

    Token price estimation from stock price path:
      gfr > 0 (gap holding):  est_price = entry + (1-entry) * gfr
      gfr < 0 (gap fading):   est_price = entry + entry * gfr
      Clamped to [0.0, 1.0].

    Returns dict with:
      - partial_exits: list of (exit_type, exit_price, contracts, pnl)
      - remaining_contracts: float (held to settlement)
      - triggers: list[str] of threshold names hit
    """
    gap_dollars = open_price - prev_close
    if abs(gap_dollars) < 0.001 or hist_5m is None or hist_5m.empty:
        return {
            "partial_exits": [],
            "remaining_contracts": position_size / entry_price if entry_price > 0 else 0,
            "triggers": [],
        }

    # Minimum bar sanity: valid trading day = 78 bars (6.5h / 5min).
    # Fewer than 39 (< 3.25h) means intraday data is incomplete or wrong.
    # Hold all to settlement rather than simulating against bad data.
    if len(hist_5m) < 39:
        return {
            "partial_exits": [],
            "remaining_contracts": position_size / entry_price if entry_price > 0 else 0,
            "triggers": [],
        }

    total_contracts = position_size / entry_price if entry_price > 0 else 0
    remaining = total_contracts
    hold_min = 30
    start = hist_5m.index[0]

    # Dynamic thresholds: sell fraction = unrealized P&L fraction
    # At 20% of max gain → sell 20% of remaining. At 50% → sell 50%.
    # Same for risk: at 40% loss → sell 40%. At 70% → sell 70%.
    # This ties exit aggressiveness directly to conviction strength.
    win_thresholds = [(0.20, 0.20), (0.50, 0.50), (0.80, 0.80)]
    risk_thresholds = [(0.40, 0.40), (0.70, 0.70), (1.00, 1.00)]
    max_gain = 1.0 - entry_price
    max_loss = entry_price
    hit_win         = [False] * len(win_thresholds)
    hit_risk        = [False] * len(risk_thresholds)
    hit_gfr_05        = False   # gfr < -0.5: gap solidly reversed → sell 60% (YES only)
    hit_gfr_08        = False   # gfr < -0.8: gap fully reversed → sell 90% (YES only)
    hit_edge_exhaust  = False   # edge gone while profitable → sell 85%
    hit_no_profit_lock = False  # NO: token gained ≥12¢ → sell 50%
    hit_no_trail_stop  = False  # NO: token fell ≥8¢ from session peak → exit remaining
    no_peak            = 0.0    # session-high NO token price for trailing stop
    partial_exits      = []
    triggers           = []
    TRADE_WINDOW_MIN = 210.0  # 10:30am entry to 2pm exit = 210 minutes

    # direction_sign for adj_wr: +1 for gap-up (YES trade), -1 for gap-down (NO trade)
    direction_sign = 1 if (open_price >= prev_close) else -1
    payout = 1.0 - CLOB_EXIT_DISCOUNT  # approximate fee for edge calc

    for idx, row in hist_5m.iterrows():
        elapsed = (idx - start).total_seconds() / 60
        if elapsed < hold_min:
            continue
        if remaining < 0.5:
            break

        price    = float(row["Close"])
        gfr      = (price - open_price) / gap_dollars
        time_str = idx.strftime("%H:%M")
        dow_str  = idx.strftime("%a")

        est_price, _source = _calibrated_token_price(
            time_str, gfr, entry_price, dow_str, abs_gap_pct=abs_gap_pct
        )

        # Track NO token peak for trailing stop — must happen before any exit checks.
        if entry_side == "NO" and est_price > no_peak:
            no_peak = est_price

        # Time multiplier for WIN exits: exits become more aggressive as 2pm approaches.
        # At 10:30am (entry): 1.0×. At 2pm (exit): 2.0×. Linear between.
        minutes_in_trade = max(0.0, elapsed - hold_min)
        time_mult = min(2.0, 1.0 + minutes_in_trade / TRADE_WINDOW_MIN)

        triggered_this_bar = False

        # ── GFR-based risk exits (YES trades only) ────────────────────────────
        # GFR exits are disabled for NO trades: WR at gfr<-0.5 for NO is 43%
        # (noise, not a reversal signal). NO protection is handled below.
        if not triggered_this_bar and entry_side != "NO":
            if not hit_gfr_08 and gfr < -0.8:
                hit_gfr_08 = True
                sell = round(remaining * 0.90, 4)
                if sell >= 0.5:
                    pnl = round(sell * (est_price - entry_price), 2)
                    remaining -= sell
                    partial_exits.append(("risk_exit_gfr", round(est_price, 4), sell, pnl))
                    triggers.append("gfr<-0.8_reversed")
                triggered_this_bar = True
            elif not hit_gfr_05 and gfr < -0.5:
                hit_gfr_05 = True
                sell = round(remaining * 0.60, 4)
                if sell >= 0.5:
                    pnl = round(sell * (est_price - entry_price), 2)
                    remaining -= sell
                    partial_exits.append(("risk_exit_gfr", round(est_price, 4), sell, pnl))
                    triggers.append("gfr<-0.5_fading")
                triggered_this_bar = True

        # ── NO trade intraday protection ──────────────────────────────────────
        # Mirrors the logic in server.py _check_exit() for simulation consistency.
        if not triggered_this_bar and entry_side == "NO":
            # Profit lock: capture gains before a chop bounce erases them.
            if not hit_no_profit_lock and est_price >= entry_price + 0.12:
                hit_no_profit_lock = True
                sell = round(remaining * 0.50, 4)
                if sell >= 0.5:
                    pnl = round(sell * (est_price - entry_price), 2)
                    remaining -= sell
                    partial_exits.append(("no_profit_lock", round(est_price, 4), sell, pnl))
                    triggers.append("no_profit_lock")
                triggered_this_bar = True
            # Trailing stop: exit remaining when token falls ≥8¢ from session peak.
            # Only arms after a meaningful run (peak ≥10¢ above entry).
            elif (not hit_no_trail_stop
                    and no_peak >= entry_price + 0.10
                    and est_price <= no_peak - 0.08):
                hit_no_trail_stop = True
                sell = round(remaining, 4)
                if sell >= 0.5:
                    pnl = round(sell * (est_price - entry_price), 2)
                    remaining -= sell
                    partial_exits.append(("no_trail_stop", round(est_price, 4), sell, pnl))
                    triggers.append("no_trail_stop")
                triggered_this_bar = True

        # ── Edge-exhaustion profit lock ────────────────────────────────────────
        # When: up ≥15% AND adj_wr × 0.99 ≤ est_price (mispricing gone) AND gfr<0
        # The market has repriced to fair value while we're profitable.
        # Sell 85% immediately to lock profit; keep 15% tail for settlement optionality.
        if not triggered_this_bar and not hit_edge_exhaust:
            adj_wr_now = min(0.95, max(0.05,
                base_wr + BAYES_LAMBDA * gfr * direction_sign))
            edge_now = adj_wr_now * payout - est_price
            if (est_price >= entry_price * 1.15    # up ≥15%
                    and edge_now <= 0              # mispricing extracted
                    and gfr < 0):                  # direction weakening
                hit_edge_exhaust = True
                sell = round(remaining * 0.85, 4)
                if sell >= 0.5:
                    pnl = round(sell * (est_price - entry_price), 2)
                    remaining -= sell
                    partial_exits.append(("edge_exhausted", round(est_price, 4), sell, pnl))
                    triggers.append("edge_exhausted_profit_lock")
                triggered_this_bar = True

        # ── WIN thresholds (time-scaled) ──────────────────────────────────────
        # Sell fraction scales up with time so the same gain level triggers
        # a larger exit at 1pm than at 10:30am — locking in more as expiry nears.
        if not triggered_this_bar and est_price > entry_price and max_gain > 0.001:
            pct_of_max = (est_price - entry_price) / max_gain
            for i, (gain_frac, base_sell_frac) in enumerate(win_thresholds):
                if not hit_win[i] and pct_of_max >= gain_frac:
                    hit_win[i] = True
                    sell_frac = min(0.99, base_sell_frac * time_mult)
                    sell = round(remaining * sell_frac, 4)
                    if sell >= 0.5:
                        pnl = round(sell * (est_price - entry_price), 2)
                        remaining -= sell
                        partial_exits.append(("scale_out", round(est_price, 4), sell, pnl))
                        triggers.append(f"win_{gain_frac:.0%}_t{time_mult:.1f}x")
                    triggered_this_bar = True
                    break

        # ── Price-based risk thresholds (fallback when gfr hasn't triggered) ──
        if not triggered_this_bar and est_price < entry_price and max_loss > 0.001:
            pct_lost = (entry_price - est_price) / max_loss
            for i, (loss_frac, sell_frac) in enumerate(risk_thresholds):
                if not hit_risk[i] and pct_lost >= loss_frac:
                    hit_risk[i] = True
                    sell = round(remaining * sell_frac, 4)
                    if sell >= 0.5:
                        pnl = round(sell * (est_price - entry_price), 2)
                        remaining -= sell
                        partial_exits.append(("risk_exit", round(est_price, 4), sell, pnl))
                        triggers.append(f"risk_{loss_frac:.0%}")
                    break

    return {
        "partial_exits": partial_exits,
        "remaining_contracts": remaining,
        "triggers": triggers,
    }


# ── Today (Full Daily Loop) ────────────────────────────────────────────────────


def run_today(force: bool = False):
    """Full daily loop: scan → resolve (exit ladder + time exit at 2pm ET).

    Positions are gradually offloaded via the exit ladder when estimated
    token price reaches predefined thresholds (WIN: 20/50/80% of max gain;
    RISK: 40/70/100% of entry value lost). All remaining contracts are
    sold at estimated market price at TIME_EXIT (2pm ET) — no binary
    settlement, avoiding late-day decay.
    """
    run_scan(force=force)

    if not force:
        exit_h, exit_m = [int(x) for x in TIME_EXIT.split(":")]
        et = _et_dt()
        resolve_time = et.replace(hour=exit_h, minute=exit_m, second=0, microsecond=0)
        now_ts = et.timestamp()
        if now_ts < resolve_time.timestamp():
            wait_sec = (resolve_time - et).total_seconds()
            print(f"\n  Waiting {wait_sec/60:.0f}min until {TIME_EXIT} ET resolve...")
            time.sleep(wait_sec)
            print(f"  [{_now()}] Waking for resolve.\n")

    run_resolve()


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Daily Stock Gap Mispricing Bot — Paper Trade Engine"
    )
    parser.add_argument(
        "mode", nargs="?", default="scan",
        choices=["scan", "resolve", "today"],
        help="Run mode: scan (entry), resolve (4pm), today (scan+resolve)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip window checks / run single scan (testing/backfill)",
    )
    args = parser.parse_args()

    if args.mode == "scan":
        run_scan(force=args.force)
    elif args.mode == "resolve":
        run_resolve()
    elif args.mode == "today":
        run_today(force=args.force)


if __name__ == "__main__":
    main()
