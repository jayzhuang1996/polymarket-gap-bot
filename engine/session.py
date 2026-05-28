"""Trading session loop — 2-minute cadence, entry/exit decisions, DB recording."""

import asyncio
import json
from datetime import datetime

import engine.state as state
from config import (
    TICKERS, SPRT_YES_PARAMS, SPRT_ENTER_LR, SPRT_ABORT_LR,
    MAX_REPRICE_ATTEMPTS, REPRICE_DRIFT_THRESHOLD,
)
from engine.sizer import compute_position_size
from engine.strategy import (
    _et_now_hm, _in_market_hours, _entry_frozen, _is_late_entry, _is_thursday,
    _entry_edge_min, _fetch_vix_change, _vix_zone, _check_entry, _check_exit,
    ENTRY_CONFIRMATIONS_NEEDED, GFR_COOLDOWN_MINUTES, FULLY_EXITED_THRESHOLD,
)
from engine.data_feed import _token_id
from engine.order_manager import ORDER_TTL_SEC
from database.db import get_unresolved_decisions, store_decision, store_outcome, store_scan_log


# ── Startup reconciliation ────────────────────────────────────────────────────

def reconcile_session_state() -> None:
    """Restore in-memory position state from the DB after a server restart.

    Problem: if the server crashes at 11am while holding 2 open positions,
    _remaining_fractions, _session_entered, and _decision_ids all reset to
    empty. On restart the bot would think it has no positions and could
    try to re-enter markets it already holds.

    This function reads today's unresolved decisions (entered but not yet
    resolved) and rehydrates the relevant state dicts so the bot knows
    it is already in those positions.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        open_rows = [r for r in get_unresolved_decisions() if r["date"] == today]
    except Exception:
        return

    if not open_rows:
        return

    for row in open_rows:
        ticker = row["ticker"]
        # Mark as entered — prevents spurious re-entry
        state._session_entered.add(ticker)
        # Assume full position still open (conservative — better than double-entering)
        state._remaining_fractions[ticker] = 1.0
        # Restore decision ID so exit logic can write the outcome correctly
        state._decision_ids[ticker] = row["id"]

    tickers = [r["ticker"] for r in open_rows]
    print(f"  [session] Reconciled {len(open_rows)} open position(s) from DB: {tickers}")


# ── Session state snapshot for dashboard ──────────────────────────────────────

def get_session_state() -> dict:
    """Snapshot of all live session variables for the dashboard."""
    h, m = _et_now_hm()

    sprt_state: dict[str, dict] = {}
    for ticker, params in SPRT_YES_PARAMS.items():
        history = state._signal_history.get(ticker, [])
        p1, p0  = params
        lr      = 1.0
        for sig in history:
            lr *= (p1 / p0) if sig == "GO" else ((1 - p1) / (1 - p0))
        status = "ABORT" if lr <= SPRT_ABORT_LR else ("ENTER" if lr >= SPRT_ENTER_LR else "WATCH")
        sprt_state[ticker] = {"lr": round(lr, 3), "status": status}

    now_dt    = datetime.now()
    cooldowns: dict[str, int] = {}
    for ticker, start in state._gfr_exit_cooldowns.items():
        remaining        = max(0, GFR_COOLDOWN_MINUTES * 60 - (now_dt - start).total_seconds())
        cooldowns[ticker] = round(remaining)

    return {
        "type":                "session_state",
        "vix_change":          state._vix_change,
        "vix_high":            state._vix_high,
        "vix_zone":            _vix_zone(),
        "aborted":             list(state._session_aborted),
        "entered":             list(state._session_entered),
        "cooldowns":           cooldowns,
        "remaining_fractions": {k: round(v, 3) for k, v in state._remaining_fractions.items()},
        "exit_triggers_fired": {k: list(v) for k, v in state._exit_triggers_fired.items()},
        "no_peaks":            {k: round(v, 3) for k, v in state._no_token_peak.items()},
        "sprt":                sprt_state,
        "edge_min":            round(_entry_edge_min(h, m), 3),
        "is_thursday":         _is_thursday(),
        "is_late_entry":       _is_late_entry(h, m),
        "entry_frozen":        _entry_frozen(h, m),
        "et_time":             f"{h:02d}:{m:02d}",
    }


# ── Session loop ───────────────────────────────────────────────────────────────

VIX_REFRESH_INTERVAL_MIN = 30   # re-fetch VIX every 30 minutes during market hours


async def trading_session_loop():
    """2-minute brain — runs from 9:30am to 3pm ET every trading day."""
    last_day      = None
    last_vix_tick = 0   # loop-tick counter; reset each day

    while True:
        await asyncio.sleep(120)
        h_now, m_now = _et_now_hm()
        # Run until 4:30pm ET so time exits and settlement exits fire after 3pm hard exit.
        # Only skip during overnight hours (before 9:30am or after 4:30pm).
        if (h_now, m_now) < (9, 30) or (h_now, m_now) >= (16, 30):
            continue

        h, m  = _et_now_hm()
        today = datetime.now().date()

        # Daily reset
        if today != last_day:
            state._signal_history.clear()
            state._session_entered.clear()
            state._session_aborted.clear()
            state._exit_triggers_fired.clear()
            state._gfr_exit_cooldowns.clear()
            state._remaining_fractions.clear()
            state._prev_gfr.clear()
            state._gfr_snapshot.clear()
            state._pending_orders.clear()
            state._held_contracts.clear()
            state._no_token_peak.clear()
            state._decision_ids.clear()
            state._realized_pnl.clear()
            state._vix_change, state._vix_high = _fetch_vix_change()
            last_day      = today
            last_vix_tick = 0
            vix_label = f"{state._vix_change:+.2f}" if state._vix_change is not None else "unavailable"
            print(f"  [session] New trading day — state reset ({today}) | "
                  f"VIX change={vix_label}, high_regime={state._vix_high}")

        # VIX refresh every 30 minutes (15 × 2-min ticks)
        last_vix_tick += 1
        ticks_per_refresh = VIX_REFRESH_INTERVAL_MIN // 2
        if last_vix_tick % ticks_per_refresh == 0:
            new_vc, new_vh = _fetch_vix_change()
            if new_vc is not None:
                old_vc = state._vix_change
                state._vix_change = new_vc
                state._vix_high   = new_vh
                if old_vc != new_vc:
                    print(f"  [session] VIX refreshed {h:02d}:{m:02d} "
                          f"{old_vc:+.2f}→{new_vc:+.2f}  high={new_vh}")

        # ── Resolve pending orders ─────────────────────────────────────────
        if state.order_manager and state._pending_orders:
            to_remove: list[str] = []
            for pticker, pending in list(state._pending_orders.items()):
                age    = (datetime.now() - pending["placed_at"]).total_seconds()
                fill   = await asyncio.to_thread(state.order_manager.check_fill, pending["order_id"])
                status = fill["status"]

                if status == "MATCHED":
                    if pending["type"] == "entry":
                        avg_p = fill["avg_price"] or pending["price"]
                        state._held_contracts[pticker] = pending["size_contracts"]
                        print(f"  [order] BUY FILLED {pticker}  "
                              f"{pending['size_contracts']:.1f} contracts @ ${avg_p:.3f}")
                    else:
                        sold = pending["size_contracts"]
                        state._held_contracts[pticker] = max(
                            0.0, state._held_contracts.get(pticker, 0) - sold
                        )
                        print(f"  [order] SELL FILLED {pticker}  {sold:.1f} contracts")
                    to_remove.append(pticker)

                elif age > ORDER_TTL_SEC:
                    await asyncio.to_thread(state.order_manager.cancel, pending["order_id"])
                    if pending["type"] != "entry":
                        print(f"  [order] CANCELLED (TTL) sell {pticker}")
                        to_remove.append(pticker)
                        continue

                    reprice_count = pending.get("reprice_count", 0)
                    pticker_q     = state.current_quotes.get(pticker, {})
                    new_price     = (pticker_q.get("yes_ask") if pending["side"] == "YES"
                                     else pticker_q.get("no_ask"))
                    signal_ok     = (
                        not _entry_frozen(h, m) and
                        pticker_q.get("signal") == "GO" and
                        sum(1 for s in state._signal_history.get(pticker, [])[-4:]
                            if s == "GO") >= ENTRY_CONFIRMATIONS_NEEDED
                    )
                    price_ok      = new_price is not None and 0.40 <= new_price <= 0.70
                    attempts_left = reprice_count < MAX_REPRICE_ATTEMPTS

                    if signal_ok and price_ok and attempts_left:
                        drift         = abs(new_price - pending["price"])
                        drift_label   = (f"{pending['price']:.3f}→{new_price:.3f}"
                                         if drift > REPRICE_DRIFT_THRESHOLD else "stable")
                        adj_wr        = pticker_q.get("adj_wr") or 0.60
                        size_usd      = compute_position_size(adj_wr, new_price)
                        size_contracts = round(size_usd / new_price, 1)
                        new_id = await asyncio.to_thread(
                            state.order_manager.place_buy,
                            pending["token_id"], new_price, size_usd,
                        )
                        if new_id:
                            state._pending_orders[pticker] = {
                                "order_id":       new_id,
                                "type":           "entry",
                                "token_id":       pending["token_id"],
                                "side":           pending["side"],
                                "price":          new_price,
                                "size_contracts": size_contracts,
                                "size_usd":       size_usd,
                                "placed_at":      datetime.now(),
                                "reprice_count":  reprice_count + 1,
                            }
                            print(f"  [order] REPRICED ({reprice_count+1}/{MAX_REPRICE_ATTEMPTS})"
                                  f" {pticker} {pending['side']} {drift_label}")
                        else:
                            state._session_entered.discard(pticker)
                            to_remove.append(pticker)
                    else:
                        reason = ("max retries" if not attempts_left
                                  else "frozen" if _entry_frozen(h, m) else "signal gone")
                        print(f"  [order] ABANDONED {pticker} — {reason}")
                        state._session_entered.discard(pticker)
                        to_remove.append(pticker)

            for t in to_remove:
                state._pending_orders.pop(t, None)

        # ── Snapshot GFR for velocity calculation ─────────────────────────
        for display, _yahoo in TICKERS:
            q       = state.current_quotes.get(display, {})
            gfr_now = q.get("gfr")
            if gfr_now is not None:
                state._gfr_snapshot[display] = gfr_now

        # ── Update signal history ─────────────────────────────────────────
        for display, _yahoo in TICKERS:
            q    = state.current_quotes.get(display, {})
            sig  = q.get("signal", "WAIT")
            hist = state._signal_history.setdefault(display, [])
            hist.append(sig)
            if len(hist) > 6:
                hist.pop(0)

        # ── Load open positions ───────────────────────────────────────────
        try:
            open_positions = {row["ticker"]: dict(row) for row in get_unresolved_decisions()}
        except Exception:
            open_positions = {}

        signals_this_cycle: list[dict] = []

        for display, _yahoo in TICKERS:
            q = state.current_quotes.get(display, {})
            if not q:
                continue

            in_position    = display in open_positions
            remaining      = state._remaining_fractions.get(display, 1.0)
            fully_exited   = in_position and remaining < FULLY_EXITED_THRESHOLD
            cooldown_start = state._gfr_exit_cooldowns.get(display)
            cooldown_ok    = (
                cooldown_start is not None and
                (datetime.now() - cooldown_start).total_seconds() / 60 >= GFR_COOLDOWN_MINUTES
            )
            eligible_reentry = fully_exited and cooldown_ok

            # ── Entry ─────────────────────────────────────────────────────
            if (not in_position or eligible_reentry) and not _entry_frozen(h, m):
                is_reentry = eligible_reentry
                if is_reentry:
                    state._session_entered.discard(display)
                entry = _check_entry(display, q, h, m, reentry=is_reentry)
                if entry:
                    state._session_entered.add(display)
                    state._exit_triggers_fired[display] = set()
                    if is_reentry:
                        state._remaining_fractions[display] = 1.0
                        del state._gfr_exit_cooldowns[display]
                    tag_str  = entry["tag"]
                    tag_str += "  REENTRY" if is_reentry else ""
                    tag_str += "  LATE"    if entry["late"] else ""
                    tag_str += "  THU"     if entry["thursday"] else ""
                    print(f"  [session] ENTRY SIGNAL {display} {entry['side']} "
                          f"@ ${entry['entry_price']:.3f}  edge {entry['live_edge']*100:.1f}%"
                          f"  [{tag_str}]")
                    signals_this_cycle.append({"event": "entry_signal", **entry})

                    _psize  = compute_position_size(entry.get("adj_wr") or 0.60, entry["entry_price"])
                    _dec_id = store_decision(
                        datetime.now().strftime("%Y-%m-%d"),
                        display,
                        f"BUY {entry['side']} [{tag_str.strip()}]",
                        gap_bps=entry["gap_bps"],
                        entry_side=entry["side"],
                        entry_price=entry["entry_price"],
                        position_size=_psize,
                        expected_edge=entry["live_edge"],
                        adj_wr=entry.get("adj_wr"),
                        gfr_at_entry=q.get("gfr"),
                        spread_at_entry=q.get("yes_spread"),
                    )
                    state._decision_ids[display] = _dec_id
                    state._realized_pnl[display] = 0.0

                    if state.order_manager and display not in state._pending_orders:
                        token = _token_id(display, entry["side"])
                        if token:
                            adj_wr         = entry.get("adj_wr") or 0.60
                            size_usd       = compute_position_size(adj_wr, entry["entry_price"])
                            if size_usd > 0:
                                size_contracts = round(size_usd / entry["entry_price"], 1)
                                order_id = await asyncio.to_thread(
                                    state.order_manager.place_buy,
                                    token, entry["entry_price"], size_usd,
                                )
                                if order_id:
                                    state._pending_orders[display] = {
                                        "order_id":       order_id,
                                        "type":           "entry",
                                        "token_id":       token,
                                        "side":           entry["side"],
                                        "price":          entry["entry_price"],
                                        "size_contracts": size_contracts,
                                        "size_usd":       size_usd,
                                        "placed_at":      datetime.now(),
                                        "reprice_count":  0,
                                    }
                elif is_reentry:
                    state._session_entered.add(display)

            # ── Exit ──────────────────────────────────────────────────────
            elif in_position and not fully_exited:
                position = open_positions[display]
                if position.get("entry_side") == "NO":
                    no_bid_now = q.get("no_bid")
                    if no_bid_now and no_bid_now > state._no_token_peak.get(display, 0.0):
                        state._no_token_peak[display] = no_bid_now

                exit_sig = _check_exit(
                    display, q, position, h, m,
                    no_peak=state._no_token_peak.get(display, 0.0),
                )
                if exit_sig:
                    fired  = state._exit_triggers_fired.setdefault(display, set())
                    reason = exit_sig["reason"]
                    if reason not in fired:
                        fired.add(reason)
                        frac  = exit_sig["fraction"]
                        price = exit_sig["price"]
                        pct   = exit_sig["profit_pct"]

                        state._remaining_fractions[display] = (
                            state._remaining_fractions.get(display, 1.0) * (1.0 - frac)
                        )

                        if reason in ("gfr<-0.5_fading", "gfr<-0.8_reversed"):
                            if display not in state._gfr_exit_cooldowns:
                                state._gfr_exit_cooldowns[display] = datetime.now()
                                print(f"  [session] GFR cooldown started for {display}"
                                      f" — re-entry eligible after {GFR_COOLDOWN_MINUTES}min")

                        if reason == "no_trail_stop":
                            state._session_aborted.add(display)
                            print(f"  [session] NO trail stop abort {display} — no re-entry today")

                        rem_pct = state._remaining_fractions[display] * 100
                        print(f"  [session] EXIT SIGNAL {display}  {reason}"
                              f"  sell {frac*100:.0f}%  @ ${price:.3f}"
                              f"  P&L {pct*100:+.1f}%  remaining {rem_pct:.0f}%")
                        signals_this_cycle.append({
                            "event":     "exit_signal",
                            "ticker":    display,
                            "reason":    reason,
                            "fraction":  frac,
                            "price":     price,
                            "pnl_pct":   round(pct, 4),
                            "remaining": round(state._remaining_fractions[display], 3),
                        })

                        _ep = position.get("entry_price") or 0
                        _sz = position.get("position_size") or 0
                        if _ep > 0 and _sz > 0:
                            state._realized_pnl[display] = (
                                state._realized_pnl.get(display, 0.0) + _sz * frac * pct * 0.99
                            )
                        if (state._remaining_fractions[display] < FULLY_EXITED_THRESHOLD
                                and display in state._decision_ids):
                            store_outcome(
                                state._decision_ids.pop(display),
                                datetime.now().strftime("%Y-%m-%d"),
                                display,
                                resolved_yes=None,
                                pnl_usd=round(state._realized_pnl.get(display, 0.0), 2),
                                exit_price=price,
                                exit_type=reason,
                            )
                            print(f"  [paper] OUTCOME recorded {display}"
                                  f"  pnl ${state._realized_pnl.get(display, 0):.2f}"
                                  f"  via {reason}")

                        if state.order_manager and display not in state._pending_orders:
                            pos_side       = position.get("entry_side", "YES")
                            token          = _token_id(display, pos_side)
                            held           = state._held_contracts.get(display, 0.0)
                            sell_contracts = round(held * frac, 1)
                            if token and sell_contracts > 0:
                                order_id = await asyncio.to_thread(
                                    state.order_manager.place_sell, token, price, sell_contracts,
                                )
                                if order_id:
                                    state._pending_orders[display] = {
                                        "order_id":       order_id,
                                        "type":           "exit",
                                        "token_id":       token,
                                        "side":           pos_side,
                                        "price":          price,
                                        "size_contracts": sell_contracts,
                                        "placed_at":      datetime.now(),
                                    }

            # ── Scan log — every tick, every ticker, regardless of outcome ──
            try:
                store_scan_log(
                    datetime.now().strftime("%Y-%m-%d"),
                    display,
                    q.get("signal", "UNKNOWN"),
                    et_time=f"{h:02d}:{m:02d}",
                    gap_bps=q.get("gap_bps"),
                    yes_ask=q.get("yes_ask"),
                    yes_bid=q.get("yes_bid"),
                    adj_wr=q.get("adj_wr"),
                    edge=q.get("live_edge"),
                    gfr=q.get("gfr"),
                    gfr_velocity=q.get("gfr_velocity"),
                    settlement_p_win=q.get("settlement_p_win"),
                    vix_change=state._vix_change,
                )
            except Exception:
                pass

        # ── Broadcast ─────────────────────────────────────────────────────
        if signals_this_cycle:
            state.broadcast_queue.put_nowait(json.dumps({
                "type":    "trading_signals",
                "signals": signals_this_cycle,
                "et_time": f"{h:02d}:{m:02d}",
            }))
        state.broadcast_queue.put_nowait(json.dumps(get_session_state()))
