"""Shared, typed rules for Mud Cost Analysis.

The configured rows are intentionally code-driven and column-wise. The category
and label are not accepted from the browser: the server owns the mapping so a
changed client cannot move a quantity into a different material-balance column.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping


@dataclass(frozen=True)
class MudCostLineSpec:
    code: str
    category: str
    label: str


# Every well section is configured once with one mud system. WBM needs no
# reconciliation arithmetic; the other three follow the same formula and only
# OTHERS additionally requires a remark explaining the mud system.
MUD_COST_MUD_TYPES: tuple[tuple[str, str], ...] = (
    ("WBM", "Water Based Mud"),
    ("OBM", "Oil Based Mud"),
    ("SOBM", "Synthetic Oil Based Mud"),
    ("OTHERS", "Others"),
)
MUD_COST_MUD_TYPE_LABELS: Mapping[str, str] = dict(MUD_COST_MUD_TYPES)
MUD_COST_MUD_TYPE_KEYS: tuple[str, ...] = tuple(MUD_COST_MUD_TYPE_LABELS)
MUD_COST_REMARK_REQUIRED_TYPE = "OTHERS"


MUD_COST_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("opening_stock", "Opening Stock"),
    ("receipt", "Receipt"),
    ("additions", "Additions"),
    ("consumption_losses", "Consumption/Losses"),
    ("others", "Others"),
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
)

MUD_COST_LINE_BY_CODE: Mapping[str, MudCostLineSpec] = {
    item.code: item for item in MUD_COST_LINE_SPECS
}

# Consumption/loss reporting keeps the user-facing matrix stable while
# retaining older captured rows. Legacy Shakers and the consumption/losses
# Others row roll into Other losses. The separate Others category is a distinct
# adjustment section and is intentionally excluded from loss reporting.
MUD_LOSS_SURFACE_LINES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("verti_g_mud_on_cuttings", "Verti-G/Mud on Cuttings", ("verti_g_mud_on_cuttings",)),
    ("centrifuge", "Centrifuge", ("centrifuge",)),
    ("by_pass", "By-Pass", ("by_pass",)),
    ("evaporation", "Evaporation", ("evaporation",)),
    ("trips", "Trips", ("trips",)),
)
MUD_LOSS_OTHER_LINES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("mud_cleaner", "Mud Cleaner", ("mud_cleaner",)),
    ("formation_seepage", "Formation/Seepage", ("formation_seepage",)),
    ("pit_cleaning_dump", "Pit Cleaning/Dump", ("pit_cleaning_dump",)),
    ("left_in_hole", "Left-In-Hole", ("left_in_hole",)),
    ("other_losses", "Other losses", (
        "consumption_losses_others", "shakers",
    )),
)
MUD_LOSS_REPORT_LINES = (*MUD_LOSS_SURFACE_LINES, *MUD_LOSS_OTHER_LINES)
MUD_COST_LINE_CODES: tuple[str, ...] = tuple(item.code for item in MUD_COST_LINE_SPECS)
MUD_COST_CATEGORIES_BY_KEY: Mapping[str, str] = dict(MUD_COST_CATEGORIES)
MUD_COST_DB_CATEGORY_KEYS: tuple[str, ...] = (*MUD_COST_CATEGORIES_BY_KEY, "closing_stock")
# Retain historical measurements in storage only; they are no longer inputs.
MUD_COST_DB_LINE_CODES = (*MUD_COST_LINE_CODES, "actual_closing_stock")
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
         and item.code != "opening_stock"),
        ZERO,
    )


def loss_breakdown(amounts: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Typed loss matrix where the two group totals equal every stock deduction."""
    result = {
        code: sum((amounts.get(source, ZERO) for source in sources), ZERO)
        for code, _label, sources in MUD_LOSS_REPORT_LINES
    }
    result["surface_loss_total"] = sum(
        (result[code] for code, _label, _sources in MUD_LOSS_SURFACE_LINES), ZERO,
    )
    result["other_loss_total"] = sum(
        (result[code] for code, _label, _sources in MUD_LOSS_OTHER_LINES), ZERO,
    )
    result["total_losses"] = result["surface_loss_total"] + result["other_loss_total"]
    return result


def closing_stock(
    opening_stock: Decimal,
    receipt: Decimal,
    additions: Decimal,
    consumption_losses: Decimal,
    others: Decimal,
) -> Decimal:
    """Opening + receipts + additions − losses − other deductions."""
    return opening_stock + receipt + additions - consumption_losses - others


# Reconciliation arithmetic is kept in the domain layer so the Mud Cost page
# and the Well Cost Analysis read exactly the same numbers. Values are kept at
# the ten-decimal entry precision; presentation may round to currency cents.
RECONCILIATION_QUANT = Decimal("0.0000000001")


@dataclass(frozen=True)
class MudCostReconciliation:
    """One section's derived mud cost for a point in time.

    ``total_mud`` is Opening Stock + Extra OBM received + Additions (barrels).
    ``alpha`` values initial opening stock + Extra OBM at the section's
    Cost/BBL base rate; ``beta`` adds the actual mud-chemical spend from the
    Daily Cost register, and ``cost_per_bbl`` is beta divided by the total mud.
    ``reconciled_cost`` values the mud that was consumed or lost at that cost
    per barrel for non-WBM systems. WBM derives Cost/BBL directly from its
    actual mud-chemical cost divided by additions and keeps actual cost as its
    reconciled amount. ``None`` means a required denominator is zero or the
    section has no configuration yet.
    """

    total_mud: Decimal
    alpha: Decimal | None
    beta: Decimal | None
    cost_per_bbl: Decimal | None
    reconciled_cost: Decimal | None


def _q(value: Decimal) -> Decimal:
    return value.quantize(RECONCILIATION_QUANT, rounding=ROUND_HALF_UP)


def reconcile_mud(
    *,
    mud_type: str | None,
    base_rate: Decimal | None,
    opening_stock: Decimal,
    additions: Decimal,
    extra_obm_received: Decimal,
    actual_cost: Decimal,
    consumption_losses: Decimal,
) -> MudCostReconciliation:
    """Apply the section-scoped reconciliation formula.

    WBM Cost/BBL is actual mud-chemical cost divided by additions; its actual
    cost remains the reconciled cost. A section without a mud type returns no
    reconciled figure so the caller can surface the configuration gap instead
    of silently treating it as WBM.

    Total mud is the section opening stock plus the extra OBM received and the
    additions entered for that section/mud type; ALPHA values the opening stock
    plus extra OBM at the Cost/BBL base rate entered once per section, BETA adds
    the section-scoped actual mud chemical cost from the Daily Cost register,
    Cost/BBL is BETA divided by total mud, and reconciled cost is
    consumption/losses priced at that Cost/BBL.
    """
    total_mud = _q(opening_stock + extra_obm_received + additions)
    if mud_type is None:
        return MudCostReconciliation(
            total_mud=total_mud, alpha=None, beta=None, cost_per_bbl=None, reconciled_cost=None,
        )
    if mud_type == "WBM":
        return MudCostReconciliation(
            total_mud=total_mud,
            alpha=None,
            beta=None,
            cost_per_bbl=_q(actual_cost / additions) if additions > 0 else None,
            reconciled_cost=_q(actual_cost),
        )
    rate = base_rate if base_rate is not None else Decimal("0")
    alpha = _q((opening_stock + extra_obm_received) * rate)
    beta = _q(alpha + actual_cost)
    cost_per_bbl = _q(beta / total_mud) if total_mud > 0 else None
    reconciled = _q(consumption_losses * cost_per_bbl) if cost_per_bbl is not None else None
    return MudCostReconciliation(
        total_mud=total_mud,
        alpha=alpha,
        beta=beta,
        cost_per_bbl=cost_per_bbl,
        reconciled_cost=reconciled,
    )
