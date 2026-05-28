"""
Multi-scan decision engine — accumulates 12 snapshots (every 5 min, 9:30-10:30 ET),
applies Bayesian WR update, runs 3-gate decision.

Usage:
    decider = MultiScanDecider("NVDA", gap_pct, open_price, prev_close, base_wr)
    decider.add_scan(et_time, current_price, yes_bid, yes_ask, no_bid, no_ask, yes_depth, no_depth)
    ...
    result = decider.decide()  # call after 10:30 or when conviction is clear
"""

from dataclasses import dataclass, field
from typing import Optional

from config import (
    MAX_YES_PRICE, MIN_YES_PRICE, MIN_BOOK_DEPTH, MAX_SPREAD_PCT, TRADING_FEE_PCT,
    GAP_EDGE_MIN, NEUTRAL_EDGE_MIN, FADE_EDGE_MIN, MIN_SCANS_FOR_DECISION,
    TICKER_BETA, TICKER_GAP_THRESHOLD, BASE_GAP_THRESHOLD, BAYES_LAMBDA, BAYES_STEEP_LAMBDA,
)

# ── Engine Constants (algorithm tuning, not strategy parameters) ──────────────
CONFIRM_THRESHOLD = 0.3      # gap_fill_ratio > +0.3 = gap confirmed intraday
FADE_THRESHOLD = -0.3        # gap_fill_ratio < -0.3 = gap fading intraday

# ── Scan Snapshot ─────────────────────────────────────────────────────────────


@dataclass
class Snapshot:
    """One 5-min scan for a single ticker."""
    et_time: str
    current_price: float
    gap_fill_ratio: float
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    yes_depth: float
    no_depth: float


# ── Decision Result ───────────────────────────────────────────────────────────


@dataclass
class Decision:
    action: str                # "BUY" | "SKIP"
    side: Optional[str]        # "YES" | "NO" | None
    price: Optional[float]     # entry price
    edge: Optional[float]     # expected edge %
    conviction: str            # "STRONG" | "MODERATE" | "WEAK"
    reason: str = ""           # human-readable
    skip_reason: Optional[str] = None  # machine code for logging
    win_rate: Optional[float] = None  # Bayesian-adjusted WR used for edge calc

    @property
    def is_buy(self) -> bool:
        return self.action == "BUY"


# ── Decider ───────────────────────────────────────────────────────────────────


class MultiScanDecider:
    """Accumulates scan snapshots and runs the 3-gate decision.

    The decision uses:
      Signal 1 — Gap magnitude (static, from yfinance open)
      Signal 2 — Intraday path via gap_fill_ratio
        gap_fill = (current_price - open) / (open - prev_close)
        Positive = gap is playing out.  Negative = gap is fading (reversing).
      Signal 3 — CLOB prices (YES and NO token bid/ask)
      Signal 4 — Base WR prior (from historical data, updated daily)

    Bayesian update:
      adj_WR = base_WR + λ × avg_gap_fill (smoothed over last 3 scans)

    Three gates:
      Gate 1 — Static: |gap| > 0.5%?  Unconditional edge > 5%?  → else SKIP
      Gate 2 — Conviction from intraday trend (all scans):
        STRONG  → gap confirmed → trade if edge > 3%
        MODERATE → no clear signal → trade if edge > 5%
        WEAK   → gap fading    → only fade side, edge > 15%
      Gate 3 — Execution: CLOB depth > 1000, valid prices
    """

    def __init__(
        self,
        ticker: str,
        gap_pct: float,
        open_price: float,
        prev_close: float,
        base_wr_yes: float,   # unconditional YES WR for this ticker's gap direction
        base_wr_no: float,    # unconditional NO WR for this ticker's gap direction
    ):
        self.ticker = ticker
        self.gap_pct = gap_pct
        self.open_price = open_price
        self.prev_close = prev_close
        self.gap_up = gap_pct > 0
        self.base_wr_yes = base_wr_yes
        self.base_wr_no = base_wr_no
        self.scans: list[Snapshot] = []

    # ── Public ────────────────────────────────────────────────────────────────

    def add_scan(
        self, et_time: str, current_price: float,
        yes_bid: float, yes_ask: float, no_bid: float, no_ask: float,
        yes_depth: float, no_depth: float,
    ):
        gfr = self._gap_fill_ratio(current_price)
        self.scans.append(Snapshot(
            et_time=et_time,
            current_price=current_price,
            gap_fill_ratio=gfr,
            yes_bid=yes_bid, yes_ask=yes_ask,
            no_bid=no_bid, no_ask=no_ask,
            yes_depth=yes_depth, no_depth=no_depth,
        ))

    def decide(self, min_scans: int = MIN_SCANS_FOR_DECISION) -> Decision:
        """Run the 3-gate decision against ALL accumulated scans.

        Args:
            min_scans: Minimum scans required before making a call.
                       Pass 1 for --force / backfill testing.
        """
        # ── Gate 1: is the gap worth scanning at all? ──
        # Threshold is beta-scaled per ticker — high-beta names need a larger gap
        # before the signal escapes their normal intraday noise range.
        _gap_min = TICKER_GAP_THRESHOLD.get(self.ticker, BASE_GAP_THRESHOLD)
        if abs(self.gap_pct) < _gap_min:
            return Decision("SKIP", None, None, None, "MODERATE",
                            f"neutral gap (|{self.gap_pct*100:.2f}%| < {_gap_min*100:.2f}% threshold for {self.ticker})",
                            "neutral_gap")

        # ── Insufficient scans yet ──
        if len(self.scans) < min_scans:
            return Decision("SKIP", None, None, None, "MODERATE",
                            f"only {len(self.scans)} scans, need {min_scans}", "insufficient_scans")

        # ── Prices from the latest scan ──
        s = self.scans[-1]
        if not s.yes_ask or not s.no_ask:
            return Decision("SKIP", None, None, None, "MODERATE",
                            "no CLOB prices on latest scan", "no_clob")

        # ── Gate 2: conviction from the full scan trajectory ──
        conviction = self._conviction()

        # Bayesian-updated WRs
        yes_wr, no_wr = self._adjusted_wrs()

        # Edge for gap-direction side and fade side
        if self.gap_up:
            dir_side, dir_price = "YES", s.yes_ask
            dir_wr = yes_wr
            fade_side, fade_price = "NO", s.no_ask
            fade_wr = no_wr
        else:
            dir_side, dir_price = "NO", s.no_ask
            dir_wr = no_wr
            fade_side, fade_price = "YES", s.yes_ask
            fade_wr = yes_wr

        dir_edge = self._expected_value(dir_wr, dir_price)
        fade_edge = self._expected_value(fade_wr, fade_price)

        # ── Gate 3: apply conviction-appropriate rules ──
        dir_depth = s.yes_depth if dir_side == "YES" else s.no_depth
        fade_depth = s.no_depth if fade_side == "NO" else s.yes_depth

        # Spread check: wide spreads mean the exit ladder will sell into a thin bid
        # (ask - bid) / mid, checked on the relevant side's token
        yes_spread = self._spread_pct(s.yes_bid, s.yes_ask)
        no_spread = self._spread_pct(s.no_bid, s.no_ask)
        side_spread = yes_spread if dir_side == "YES" else no_spread
        if side_spread is not None and side_spread > MAX_SPREAD_PCT:
            spread_str = f"spread {side_spread:.0f}% > {MAX_SPREAD_PCT:.0f}% cap"
            return Decision("SKIP", None, None, None, conviction,
                            f"gap trade blocked ({spread_str})", "wide_spread")

        if conviction == "STRONG":
            # Gap confirmed → gap-direction trade with low threshold
            if (dir_edge >= GAP_EDGE_MIN and MIN_YES_PRICE <= dir_price <= MAX_YES_PRICE
                    and dir_depth >= MIN_BOOK_DEPTH):
                return Decision("BUY", dir_side, dir_price, round(dir_edge, 1),
                                conviction, f"gap confirmed, edge {dir_edge*100:.1f}%",
                                win_rate=dir_wr)
            block_reason = (f"price ${dir_price:.2f} outside [${MIN_YES_PRICE:.2f}, ${MAX_YES_PRICE:.2f}]"
                            if not (MIN_YES_PRICE <= dir_price <= MAX_YES_PRICE) else
                            f"depth {dir_depth} < {MIN_BOOK_DEPTH}" if dir_depth < MIN_BOOK_DEPTH else
                            f"edge {dir_edge*100:.1f}% < {GAP_EDGE_MIN*100:.0f}%")
            return Decision("SKIP", None, None, None, conviction,
                            f"gap confirmed but blocked ({block_reason})", "blocked_entry")

        elif conviction == "WEAK":
            # Gap fading → only fade side with high threshold
            if (fade_edge >= FADE_EDGE_MIN and MIN_YES_PRICE <= fade_price <= MAX_YES_PRICE
                    and fade_depth >= MIN_BOOK_DEPTH):
                return Decision("BUY", fade_side, fade_price, round(fade_edge, 1),
                                conviction, f"gap fading, fade edge {fade_edge*100:.1f}%",
                                win_rate=fade_wr)
            fade_block = (f"fade price ${fade_price:.2f} outside [${MIN_YES_PRICE:.2f}, ${MAX_YES_PRICE:.2f}]"
                          if not (MIN_YES_PRICE <= fade_price <= MAX_YES_PRICE) else
                          f"fade depth {fade_depth} < {MIN_BOOK_DEPTH}" if fade_depth < MIN_BOOK_DEPTH else
                          f"fade edge {fade_edge*100:.1f}% < {FADE_EDGE_MIN*100:.0f}%")
            return Decision("SKIP", None, None, None, conviction,
                            f"gap fading, blocked ({fade_block})", "insufficient_fade_edge")

        else:  # MODERATE
            # No clear trend → gap-direction trade with higher threshold
            if (dir_edge >= NEUTRAL_EDGE_MIN and MIN_YES_PRICE <= dir_price <= MAX_YES_PRICE
                    and dir_depth >= MIN_BOOK_DEPTH):
                return Decision("BUY", dir_side, dir_price, round(dir_edge, 1),
                                conviction, f"neutral trend, edge {dir_edge*100:.1f}%",
                                win_rate=dir_wr)
            neutral_block = (f"price ${dir_price:.2f} outside [${MIN_YES_PRICE:.2f}, ${MAX_YES_PRICE:.2f}]"
                             if not (MIN_YES_PRICE <= dir_price <= MAX_YES_PRICE) else
                             f"depth {dir_depth} < {MIN_BOOK_DEPTH}" if dir_depth < MIN_BOOK_DEPTH else
                             f"edge {dir_edge*100:.1f}% < {NEUTRAL_EDGE_MIN*100:.0f}%")
            return Decision("SKIP", None, None, None, conviction,
                            f"neutral trend, blocked ({neutral_block})", "neutral_insufficient_edge")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _gap_fill_ratio(self, current_price: float) -> float:
        """How much of the overnight gap has been realised intraday.

        A positive value means price moved in the gap direction (gap holding).
        A negative value means price faded (gap reversing).
        """
        gap_dollars = self.open_price - self.prev_close
        if abs(gap_dollars) < 0.001:
            return 0.0
        move_from_open = current_price - self.open_price
        return move_from_open / gap_dollars

    def _base_edge(self) -> float:
        """Unconditional edge from the base WR alone (no intraday update)."""
        if self.gap_up:
            return self._expected_value(self.base_wr_yes, 0.55)  # approx avg YES price
        else:
            return self._expected_value(self.base_wr_no, 0.55)

    @staticmethod
    def _expected_value(win_rate: float, entry_price: float) -> float:
        """EV = WR × (1 - fee) - price.

        Derivation:
          EV = WR × (1 - fee - price) + (1-WR) × (0 - price)
             = WR × (1 - fee) - price

        The fee only applies at settlement — thesis-break exits avoid it.
        """
        payout_factor = 1.0 - TRADING_FEE_PCT
        return win_rate * payout_factor - entry_price

    @staticmethod
    def _spread_pct(bid: float | None, ask: float | None) -> float | None:
        """Bid-ask spread as a percentage of midpoint. Returns None if missing."""
        if bid is None or ask is None or bid <= 0 or ask <= 0:
            return None
        mid = (bid + ask) / 2.0
        if mid <= 0:
            return None
        return (ask - bid) / mid * 100.0

    def _adjusted_wrs(self) -> tuple[float, float]:
        """Bayesian-updated (yes_wr, no_wr) using the average gap_fill of recent scans.

        Uses the same two-slope formula as data_feed._bayesian_adj_wr:
        - Shallow slope (BAYES_LAMBDA) while stock stays above prev_close.
        - Steep slope (BAYES_STEEP_LAMBDA) once signed_gfr < -1.0 (stock crossed prev_close).
        """
        recent = self.scans[-3:]
        avg_gfr = sum(s.gap_fill_ratio for s in recent) / len(recent)

        # direction_sign: +1 for gap-up (positive gfr = thesis holding),
        #                 -1 for gap-down (positive gfr = stock recovering = bad for NO).
        direction_sign = 1 if self.gap_up else -1
        signed_gfr = avg_gfr * direction_sign

        if signed_gfr >= -1.0:
            adj = BAYES_LAMBDA * signed_gfr
        else:
            adj = BAYES_LAMBDA * (-1.0) + BAYES_STEEP_LAMBDA * (signed_gfr + 1.0)

        if self.gap_up:
            adj_yes = max(0.05, min(0.95, self.base_wr_yes + adj))
            return adj_yes, 1.0 - adj_yes
        else:
            adj_no = max(0.05, min(0.95, self.base_wr_no + adj))
            return 1.0 - adj_no, adj_no

    def _conviction(self) -> str:
        """Determine conviction from the full scan trajectory.

        Uses the proportion of scans that confirmed vs faded the gap.
        Threshold is beta-scaled: higher-beta tickers need more confirmations
        to reach STRONG conviction (their intraday noise is higher).
        """
        if len(self.scans) < 4:
            return "MODERATE"

        beta = TICKER_BETA.get(self.ticker, 1.0)
        confirm_pct = 0.15 + 0.15 * beta  # SPX=0.30, TSLA=0.45

        confirms = sum(1 for s in self.scans if s.gap_fill_ratio > CONFIRM_THRESHOLD)
        fades = sum(1 for s in self.scans if s.gap_fill_ratio < FADE_THRESHOLD)

        n = len(self.scans)
        if confirms >= n * confirm_pct and confirms >= 2 * fades:
            return "STRONG"
        elif fades >= n * confirm_pct and fades >= 2 * confirms:
            return "WEAK"
        else:
            return "MODERATE"
