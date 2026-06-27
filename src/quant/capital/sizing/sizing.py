"""Position sizing — the vol-target / fractional-Kelly gross scalar (Phase 3X.7 Capital Layer).

Scales the book's gross exposure so its realised volatility targets ``target_vol``, under-bet by a
``kelly_fraction`` (quarter-Kelly by default) and hard-capped at ``max_leverage`` (1.0 = no
leverage). A separate, conservative scalar on top of the unit-gross weights from construction.
"""

from quant.capital.errors import CapitalError


def vol_target_scalar(
    realized_vol: float,
    *,
    target_vol: float,
    max_leverage: float = 1.0,
    kelly_fraction: float = 0.25,
) -> float:
    """Return the gross-exposure scalar in ``[0, max_leverage]`` targeting ``target_vol``.

    ``kelly_fraction * target_vol / realized_vol``, capped at ``max_leverage``. A non-positive
    realised vol (a degenerate/flat book) returns ``max_leverage`` (nothing to scale down).

    Raises:
        CapitalError: If ``target_vol``/``max_leverage``/``kelly_fraction`` are not positive.
    """
    if target_vol <= 0 or max_leverage <= 0 or kelly_fraction <= 0:
        raise CapitalError("target_vol, max_leverage, and kelly_fraction must be positive")
    if realized_vol <= 0:
        return max_leverage
    return min(kelly_fraction * target_vol / realized_vol, max_leverage)
