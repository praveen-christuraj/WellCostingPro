"""Shared, typed rules for Mud Cost Analysis.

The configured rows are intentionally code-driven and column-wise. The category
and label are not accepted from the browser: the server owns the mapping so a
changed client cannot move a quantity into a different material-balance column.
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class MudCostLineSpec:
    code: str
    category: str
    label: str


MUD_COST_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("opening_stock", "Opening Stock"),
    ("receipt", "Receipt"),
    ("additions", "Additions"),
    ("consumption_losses", "Consumption/Losses"),
    ("others", "Others"),
    ("closing_stock", "Closing Stock"),
)

MUD_COST_LINE_SPECS: tuple[MudCostLineSpec, ...] = (
    MudCostLineSpec("opening_stock", "opening_stock", "Opening Stock"),
    MudCostLineSpec("extra_obm_received", "receipt", "Extra OBM Received"),
    MudCostLineSpec("other_receipts", "receipt", "Other Receipts"),
    MudCostLineSpec("drill_water", "additions", "Drill Water"),
    MudCostLineSpec("base_oil", "additions", "Base Oil"),
    MudCostLineSpec("crude_tdu_oil", "additions", "Crude/TDU Oil"),
    MudCostLineSpec("chemicals", "additions", "Chemicals"),
    MudCostLineSpec("barite", "additions", "Barite"),
    MudCostLineSpec("other_additions", "additions", "Other Additions"),
    MudCostLineSpec("verti_g_mud_on_cuttings", "consumption_losses", "Verti-G/Mud on Cuttings"),
    MudCostLineSpec("mud_cleaner", "consumption_losses", "Mud Cleaner"),
    MudCostLineSpec("centrifuge", "consumption_losses", "Centrifuge"),
    MudCostLineSpec("by_pass", "consumption_losses", "By-Pass"),
    MudCostLineSpec("formation_seepage", "consumption_losses", "Formation/Seepage"),
    MudCostLineSpec("shakers", "consumption_losses", "Shakers"),
    MudCostLineSpec("evaporation", "consumption_losses", "Evaporation"),
    MudCostLineSpec("pit_cleaning_dump", "consumption_losses", "Pit Cleaning/Dump"),
    MudCostLineSpec("trips", "consumption_losses", "Trips"),
    MudCostLineSpec("left_in_hole", "consumption_losses", "Left-In-Hole"),
    MudCostLineSpec("consumption_losses_others", "consumption_losses", "Others"),
    MudCostLineSpec("offline_centrifuge_loss", "others", "Offline Centrifuge Loss"),
    MudCostLineSpec("backloads", "others", "Backloads"),
    MudCostLineSpec("obm_left_in_hole", "others", "OBM Left-In-Hole"),
    MudCostLineSpec("other_losses_others", "others", "Others"),
    MudCostLineSpec("actual_closing_stock", "closing_stock", "Actual Closing Stock"),
)

MUD_COST_LINE_BY_CODE: Mapping[str, MudCostLineSpec] = {
    item.code: item for item in MUD_COST_LINE_SPECS
}
MUD_COST_LINE_CODES: tuple[str, ...] = tuple(item.code for item in MUD_COST_LINE_SPECS)
MUD_COST_CATEGORIES_BY_KEY: Mapping[str, str] = dict(MUD_COST_CATEGORIES)
MUD_COST_DB_CATEGORY_KEYS: tuple[str, ...] = tuple(MUD_COST_CATEGORIES_BY_KEY)
ZERO = Decimal("0")


def line_amounts(rows: Mapping[str, object]) -> dict[str, Decimal]:
    """Return every configured row as a Decimal, treating absent/blank as zero."""
    amounts: dict[str, Decimal] = {}
    for item in MUD_COST_LINE_SPECS:
        value = rows.get(item.code, ZERO)
        if value is None or value == "":
            amounts[item.code] = ZERO
        else:
            amounts[item.code] = value if isinstance(value, Decimal) else Decimal(str(value))
    return amounts


def group_total(amounts: Mapping[str, Decimal], category: str) -> Decimal:
    return sum(
        (amounts[item.code] for item in MUD_COST_LINE_SPECS if item.category == category
         and item.code not in {"opening_stock", "actual_closing_stock"}),
        ZERO,
    )


def book_closing_stock(
    opening_stock: Decimal,
    receipt: Decimal,
    additions: Decimal,
    consumption_losses: Decimal,
    others: Decimal,
) -> Decimal:
    """Opening + receipts + additions − losses − other deductions."""
    return opening_stock + receipt + additions - consumption_losses - others


def variance(actual_closing_stock: Decimal, book_closing: Decimal) -> Decimal:
    """Variance is explicitly Actual Closing Stock minus Book Closing Stock."""
    return actual_closing_stock - book_closing
