"""Shared precision contract for user-entered decimal values."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field


DECIMAL_PLACES = 10
DECIMAL_QUANT = Decimal("0.0000000001")

# Sixteen integral digits preserves the widest existing application allowance;
# ten fractional digits implements the common data-entry contract.
Decimal10 = Annotated[Decimal, Field(max_digits=26, decimal_places=DECIMAL_PLACES)]
# Planned days previously allowed ten integral digits (Numeric(12, 2)).
Decimal10Days = Annotated[Decimal, Field(max_digits=20, decimal_places=DECIMAL_PLACES)]

