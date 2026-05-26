"""Position sizing and config validation."""

from config import (
    BANKROLL_USD, KELLY_FRACTION,
    MAX_POSITION_SIZE, MIN_POSITION_SIZE,
    GAP_THRESHOLD_YES, GAP_THRESHOLD_NO,
    MIN_YES_PRICE, MAX_YES_PRICE,
    POSITION_SIZE_USD, MAX_POSITIONS_SIMULTANEOUS,
)


def compute_position_size(win_rate: float, entry_price: float, n_obs: int = 0) -> float:
    """Return position size in USD using quarter-Kelly on full bankroll, capped.

    When n_obs >= 10, sizes on the 90% CI lower bound of win_rate rather than
    the point estimate. With n=15 at 70% WR the lower bound is ~54%, so the bot
    bets as if WR=54%. As observations accumulate and the CI tightens, Kelly
    scales up naturally.

    Returns 0.0 to signal "skip this trade" (negative edge or below minimum).
    """
    if win_rate <= 0.50 or entry_price <= 0.01 or entry_price >= 0.99:
        return 0.0

    wr_for_kelly = win_rate
    if n_obs >= 10:
        try:
            from scipy.stats import proportion_confint
            approx_wins = int(round(win_rate * n_obs))
            lo, _ = proportion_confint(approx_wins, n_obs, alpha=0.10, method="wilson")
            wr_for_kelly = lo
        except ImportError:
            pass  # fall back to point estimate if scipy not available

    if wr_for_kelly <= 0.50:
        return 0.0

    b = (1.0 - entry_price) / entry_price  # payout odds
    q = 1.0 - wr_for_kelly
    f_star = (wr_for_kelly * b - q) / b    # full Kelly fraction

    if f_star <= 0:
        return 0.0

    kelly_amount = BANKROLL_USD * KELLY_FRACTION * f_star
    position = min(kelly_amount, MAX_POSITION_SIZE)

    if position < MIN_POSITION_SIZE:
        return 0.0

    return round(position, 2)


def validate_config() -> bool:
    """Validate configuration parameters. Returns True if all checks pass."""
    errors = []

    if GAP_THRESHOLD_YES <= 0:
        errors.append("GAP_THRESHOLD_YES must be positive")
    if GAP_THRESHOLD_NO >= 0:
        errors.append("GAP_THRESHOLD_NO must be negative")
    if GAP_THRESHOLD_YES <= GAP_THRESHOLD_NO:
        errors.append("GAP_THRESHOLD_YES must be > GAP_THRESHOLD_NO")
    if MIN_YES_PRICE >= MAX_YES_PRICE:
        errors.append("MIN_YES_PRICE must be less than MAX_YES_PRICE")
    if POSITION_SIZE_USD * MAX_POSITIONS_SIMULTANEOUS > BANKROLL_USD * 0.5:
        errors.append("Position sizing too aggressive — max exposure > 50% of bankroll")

    if errors:
        print("Configuration issues:")
        for e in errors:
            print(f"  - {e}")
        return False
    return True
