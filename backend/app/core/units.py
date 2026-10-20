"""Standardized engineering unit helpers for WellCostingPro.

All well configuration depths and daily cost actual depths are standardized to
metres (``m``) using the fixed conversion factor ``1 m = 3.281 ft``
(``meters = feet / 3.281``).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.core.precision import DECIMAL_QUANT

FEET_PER_METER = Decimal("3.281")
DEPTH_QUANT = DECIMAL_QUANT
VALID_DEPTH_UNITS = ("m", "ft")


def normalize_depth_unit(unit: str | None) -> str:
    """Normalize any human depth unit string to ``'m'`` or ``'ft'``."""
    cleaned = (unit or "m").strip().lower()
    if cleaned in ("ft", "feet", "foot", "'"):
        return "ft"
    if cleaned in ("m", "meter", "meters", "metre", "metres", ""):
        return "m"
    raise ValueError(f"Unsupported depth unit '{unit}'. Use 'm' or 'ft'.")


def depth_to_meters(
    value: Decimal | int | float | str | None,
    unit: str | None = "m",
    *,
    quant: Decimal = DEPTH_QUANT,
) -> Decimal | None:
    """Convert a depth measurement to standardized metres (``feet / 3.281``)."""
    if value is None:
        return None
    normalized_unit = normalize_depth_unit(unit)
    numeric = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
    if normalized_unit == "ft":
        numeric = numeric / FEET_PER_METER
    return numeric.quantize(quant, rounding=ROUND_HALF_UP)
