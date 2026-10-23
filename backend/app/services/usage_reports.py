"""Read-only usage and cost matrix reports for the Reports module.

Every report is a projection of the column-wise Daily Cost ledger (service,
consumable, tangible and other-expense lines). No data is persisted here except
export audit rows. The same filter model drives every report:

* block / rig / explicit multi-well selection
* configuration scope (drilling / completion), taken from the sheet's AFE
* well lifecycle (active well / well under final review / completed well)
* a dedicated from/to cost-date range
* one reporting currency (USD uses the stored USD amounts; any other currency
  keeps sheets whose AFE standard currency matches and reports the others as
  excluded, so currencies are never mixed)

Mud chemicals, drill bits, tangibles, services and vendors share one matrix
shape (item rows, well columns, hole-section sub cells); NPT/UPA uses the same
filters with classification days and costs.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from fastapi import HTTPException, Request
from sqlalchemy import select, union_all
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Afe,
    Block,
    CatalogueOption,
    Currency,
    DailyCostConsumableLine,
    DailyCostEntry,
    DailyCostOtherExpenseLine,
    DailyCostServiceLine,
    DailyCostTangibleLine,
    DrillBit,
    MudChemical,
    Rig,
    Service,
    Tangible,
    User,
    Vendor,
    Well,
    WellSection,
)
from app.schemas.usage_reports import (
    NptUpaDetailRow,
    NptUpaReportOut,
    NptUpaWellRow,
    UsageBlockOption,
    UsageCellOut,
    UsageCurrencyOption,
    UsageDetailRowOut,
    UsageItemRowOut,
    UsageMatrixOut,
    UsageReference,
    UsageRigOption,
    UsageSectionOut,
    UsageWellCellOut,
    UsageWellColumnOut,
    UsageWellOption,
)
from app.services import audit

MONEY_QUANT = Decimal("0.01")
QTY_QUANT = Decimal("0.0001")
ZERO = Decimal("0")
WELL_LEVEL_KEY = "__well__"
WELL_LEVEL_LABEL = "Well level (no hole section)"

REPORT_LABELS = {
    "mud-chemicals": "Mud chemicals usage",
    "drill-bits": "Drill bits usage",
    "tangibles": "Tangibles usage",
    "services": "Service-wise cost",
    "vendors": "Vendor/company-wise cost",
    "npt-upa": "NPT/UPA report",
}
COST_ONLY_REPORTS = {"services", "vendors"}
CLASSIFICATIONS = ("Planned", "UPA", "NPT")

_LINE_MODELS: tuple[tuple[type[Any], str], ...] = (
    (DailyCostServiceLine, "Services"),
    (DailyCostConsumableLine, "Consumables"),
    (DailyCostTangibleLine, "Tangibles"),
    (DailyCostOtherExpenseLine, "Other Expenses"),
)


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY_QUANT)


def _qty(value: Any) -> Decimal:
    quantized = Decimal(str(value or 0)).quantize(QTY_QUANT)
    if not quantized:
        return ZERO
    # Plain notation with trailing zeros trimmed (Decimal.normalize can emit 2E+1).
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return Decimal(text)


# ---------------------------------------------------------------------------
# Reference data (filter options)
# ---------------------------------------------------------------------------


def _afe_scope_map(db: Session, organization_id: str) -> dict[str, set[str]]:
    """Configuration scopes each well runs AFEs for."""
    scopes: dict[str, set[str]] = defaultdict(set)
    rows = db.execute(
        select(Well.id, Afe.configuration_scope)
        .join(Afe, Afe.well_id == Well.id)
        .where(
            Well.organization_id == organization_id,
            Well.is_deleted.is_(False),
            Afe.organization_id == organization_id,
            Afe.is_deleted.is_(False),
        )
    ).all()
    for well_id, scope in rows:
        scopes[well_id].add(str(scope))
    # Fall back to configured well sections where no AFE exists yet.
    section_rows = db.execute(
        select(WellSection.well_id, WellSection.scope).where(
            WellSection.organization_id == organization_id
        )
    ).all()
    for well_id, scope in section_rows:
        scopes[well_id].add(str(scope))
    return scopes


def reference_data(db: Session, organization_id: str) -> UsageReference:
    blocks = db.scalars(
        select(Block).where(
            Block.organization_id == organization_id, Block.is_deleted.is_(False)
        ).order_by(Block.block_code)
    ).all()
    rigs = db.scalars(
        select(Rig).where(
            Rig.organization_id == organization_id, Rig.is_deleted.is_(False)
        ).order_by(Rig.rig_code)
    ).all()
    wells = db.scalars(
        select(Well)
        .options(joinedload(Well.rig), joinedload(Well.block_record))
        .where(Well.organization_id == organization_id, Well.is_deleted.is_(False))
        .order_by(Well.well_code)
    ).unique().all()
    currencies = db.scalars(
        select(Currency).where(
            Currency.organization_id == organization_id, Currency.is_deleted.is_(False)
        ).order_by(Currency.currency_code)
    ).all()
    scope_map = _afe_scope_map(db, organization_id)
    wells_with_costs = set(
        db.scalars(
            select(DailyCostEntry.well_id)
            .where(
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.is_deleted.is_(False),
            )
            .distinct()
        ).all()
    )
    default_currency = next((c.currency_code for c in currencies if c.is_default), "USD")

    return UsageReference(
        blocks=[
            UsageBlockOption(id=row.id, block_code=row.block_code, block_name=row.block_name)
            for row in blocks
        ],
        rigs=[
            UsageRigOption(id=row.id, rig_code=row.rig_code, rig_name=row.rig_name)
            for row in rigs
        ],
        wells=[
            UsageWellOption(
                id=row.id,
                rig_id=row.rig_id,
                block_id=row.block_id,
                well_code=row.well_code,
                well_name=row.well_name,
                display_name=f"{row.well_code} — {row.well_name}",
                status=row.status,
                config_status=row.config_status,
                completion_status=row.completion_status,
                completion_config_status=row.completion_config_status,
                scopes=sorted(scope_map.get(row.id, set())),
                has_costs=row.id in wells_with_costs,
            )
            for row in wells
            if row.rig is not None and row.block_record is not None
        ],
        currencies=[
            UsageCurrencyOption(
                code=row.currency_code,
                name=row.currency_name,
                symbol=row.currency_symbol,
                is_default=bool(row.is_default),
            )
            for row in currencies
        ],
        default_currency=default_currency,
    )


# ---------------------------------------------------------------------------
# Filter resolution and the shared line union
# ---------------------------------------------------------------------------


def _resolve_wells(
    db: Session,
    organization_id: str,
    *,
    block_id: str,
    rig_id: str,
    well_ids: list[str],
    scope: str,
    lifecycle: str,
) -> list[Well]:
    statement = (
        select(Well)
        .options(joinedload(Well.rig), joinedload(Well.block_record))
        .where(Well.organization_id == organization_id, Well.is_deleted.is_(False))
        .order_by(Well.well_code)
    )
    if block_id:
        statement = statement.where(Well.block_id == block_id)
    if rig_id:
        statement = statement.where(Well.rig_id == rig_id)
    if well_ids:
        statement = statement.where(Well.id.in_(well_ids))
    wells = list(db.scalars(statement).unique().all())

    if scope:
        scope_map = _afe_scope_map(db, organization_id)
        wells = [well for well in wells if scope in scope_map.get(well.id, set())]

    if lifecycle:
        chosen_scope = scope or "drilling"
        prefix = "completion_" if chosen_scope == "completion" else ""
        status_field = f"{prefix}status"
        config_field = f"{prefix}config_status"
        if lifecycle == "active":
            wells = [well for well in wells if getattr(well, status_field) == "active"]
        elif lifecycle == "completed":
            wells = [well for well in wells if getattr(well, status_field) == "completed"]
        elif lifecycle == "final_review":
            wells = [well for well in wells if getattr(well, config_field) == "final_review"]
        else:
            raise HTTPException(status_code=422, detail=f"Unknown well lifecycle '{lifecycle}'")
    return wells


def _line_union(
    organization_id: str,
    well_ids: list[str],
    *,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
    scope: str,
    currency: str,
) -> Any:
    """One normalized row per daily cost line across the four line tables."""
    from sqlalchemy import literal

    use_usd = currency.upper() == "USD"
    parts = []
    for model, group in _LINE_MODELS:
        if model is DailyCostServiceLine:
            item_id_col = model.service_id
            item_code_col = model.service_code_snapshot
            item_name_col = model.service_name_snapshot
            uom_col = model.quantity_unit
            category_col = literal("")
        elif model is DailyCostConsumableLine:
            item_id_col = model.item_id
            item_code_col = model.item_code_snapshot
            item_name_col = model.item_name_snapshot
            uom_col = model.uom
            category_col = model.category
        elif model is DailyCostTangibleLine:
            item_id_col = model.tangible_id
            item_code_col = model.tangible_code_snapshot
            item_name_col = model.tangible_name_snapshot
            uom_col = model.uom
            category_col = literal("")
        else:
            item_id_col = model.expense_type
            item_code_col = model.expense_type
            item_name_col = model.expense_type_label
            uom_col = literal("")
            category_col = literal("")
        amount_col = model.usd_amount if use_usd else model.standard_amount
        statement = (
            select(
                DailyCostEntry.id.label("entry_id"),
                DailyCostEntry.well_id.label("well_id"),
                DailyCostEntry.afe_id.label("afe_id"),
                DailyCostEntry.cost_date.label("cost_date"),
                DailyCostEntry.standard_currency.label("standard_currency"),
                Afe.configuration_scope.label("scope"),
                model.classification.label("classification"),
                model.hole_section_id.label("hole_section_id"),
                model.section_code_snapshot.label("section_code"),
                model.section_name_snapshot.label("section_name"),
                model.vendor_id.label("vendor_id"),
                model.vendor_code_snapshot.label("vendor_code"),
                model.vendor_name_snapshot.label("vendor_name"),
                model.party_name.label("party_name"),
                literal(group).label("cost_group"),
                category_col.label("category"),
                item_id_col.label("item_id"),
                item_code_col.label("item_code"),
                item_name_col.label("item_name"),
                uom_col.label("uom"),
                model.quantity.label("quantity"),
                amount_col.label("amount"),
            )
            .select_from(model)
            .join(DailyCostEntry, model.entry_id == DailyCostEntry.id)
            .join(Afe, DailyCostEntry.afe_id == Afe.id)
            .where(
                model.organization_id == organization_id,
                DailyCostEntry.organization_id == organization_id,
                DailyCostEntry.is_deleted.is_(False),
                DailyCostEntry.well_id.in_(well_ids or [""]),
            )
        )
        if not include_draft:
            statement = statement.where(DailyCostEntry.status == "submitted")
        if date_from is not None:
            statement = statement.where(DailyCostEntry.cost_date >= date_from)
        if date_to is not None:
            statement = statement.where(DailyCostEntry.cost_date <= date_to)
        if scope:
            statement = statement.where(Afe.configuration_scope == scope)
        if not use_usd:
            statement = statement.where(DailyCostEntry.standard_currency == currency.upper())
        parts.append(statement)
    return union_all(*parts).subquery("usage_report_lines")


def _entry_counts(
    db: Session,
    organization_id: str,
    well_ids: list[str],
    *,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
    scope: str,
    currency: str,
) -> tuple[int, int]:
    """Return (included entries, currency-excluded entries) for the filters."""
    conditions = [
        DailyCostEntry.organization_id == organization_id,
        DailyCostEntry.is_deleted.is_(False),
        DailyCostEntry.well_id.in_(well_ids or [""]),
    ]
    if not include_draft:
        conditions.append(DailyCostEntry.status == "submitted")
    if date_from is not None:
        conditions.append(DailyCostEntry.cost_date >= date_from)
    if date_to is not None:
        conditions.append(DailyCostEntry.cost_date <= date_to)
    if scope:
        conditions.append(Afe.configuration_scope == scope)
    base = select(DailyCostEntry.id, DailyCostEntry.standard_currency).join(
        Afe, DailyCostEntry.afe_id == Afe.id
    ).where(*conditions)
    rows = db.execute(base).all()
    if currency.upper() == "USD":
        return len(rows), 0
    included = sum(1 for row in rows if row[1] == currency.upper())
    return included, len(rows) - included


# ---------------------------------------------------------------------------
# Master-data enrichment (soft-deleted rows are kept: reports are historical)
# ---------------------------------------------------------------------------


def _option_map(db: Session, organization_id: str, option_ids: Iterable[str]) -> dict[str, str]:
    ids = {option_id for option_id in option_ids if option_id}
    if not ids:
        return {}
    rows = db.scalars(
        select(CatalogueOption).where(
            CatalogueOption.organization_id == organization_id,
            CatalogueOption.id.in_(tuple(ids)),
        )
    ).all()
    return {row.id: row.value for row in rows}


def _chemical_map(db: Session, organization_id: str) -> dict[str, MudChemical]:
    return {
        row.id: row
        for row in db.scalars(
            select(MudChemical).where(MudChemical.organization_id == organization_id)
        ).all()
    }


def _bit_map(db: Session, organization_id: str) -> dict[str, DrillBit]:
    return {
        row.id: row
        for row in db.scalars(
            select(DrillBit).where(DrillBit.organization_id == organization_id)
        ).all()
    }


def _tangible_map(db: Session, organization_id: str) -> dict[str, Tangible]:
    return {
        row.id: row
        for row in db.scalars(
            select(Tangible).where(Tangible.organization_id == organization_id)
        ).all()
    }


def _service_map(db: Session, organization_id: str) -> dict[str, Service]:
    return {
        row.id: row
        for row in db.scalars(
            select(Service).where(Service.organization_id == organization_id)
        ).all()
    }


def _vendor_map(db: Session, organization_id: str) -> dict[str, Vendor]:
    return {
        row.id: row
        for row in db.scalars(
            select(Vendor).where(Vendor.organization_id == organization_id)
        ).all()
    }


# ---------------------------------------------------------------------------
# Section registry (current well plan order, historical sections appended)
# ---------------------------------------------------------------------------


def _section_registries(
    db: Session, organization_id: str, well_ids: list[str]
) -> dict[str, dict[str, dict[str, str]]]:
    """Per-well ordered section metadata keyed by hole section id."""
    registries: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    rows = db.scalars(
        select(WellSection)
        .options(joinedload(WellSection.hole_section))
        .where(
            WellSection.organization_id == organization_id,
            WellSection.well_id.in_(well_ids or [""]),
        )
        .order_by(WellSection.well_id, WellSection.scope, WellSection.sort_order)
    ).unique().all()
    for row in rows:
        master = row.hole_section
        registries[row.well_id][row.hole_section_id] = {
            "section_key": row.hole_section_id,
            "hole_section_id": row.hole_section_id,
            "section_code": master.section_code if master else "",
            "section_name": master.section_name if master else "",
            "scope": row.scope,
            "sort": str(row.sort_order),
        }
    return registries


# ---------------------------------------------------------------------------
# Shared aggregation
# ---------------------------------------------------------------------------


def _facts(
    db: Session,
    organization_id: str,
    well_ids: list[str],
    *,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
    scope: str,
    currency: str,
) -> list[Any]:
    subquery = _line_union(
        organization_id,
        well_ids,
        date_from=date_from,
        date_to=date_to,
        include_draft=include_draft,
        scope=scope,
        currency=currency,
    )
    return list(db.execute(select(subquery)).all())


def _section_for_fact(
    registries: dict[str, dict[str, dict[str, str]]],
    well_id: str,
    fact: Any,
) -> dict[str, str]:
    hole_section_id = fact.hole_section_id or ""
    if not hole_section_id:
        return {
            "section_key": WELL_LEVEL_KEY,
            "hole_section_id": "",
            "section_code": "",
            "section_name": WELL_LEVEL_LABEL,
            "scope": fact.scope or "",
            "sort": "9999",
        }
    known = registries.get(well_id, {}).get(hole_section_id)
    if known:
        return known
    # Historical section removed from the current plan: keep the snapshot.
    return {
        "section_key": hole_section_id,
        "hole_section_id": hole_section_id,
        "section_code": fact.section_code or "",
        "section_name": fact.section_name or "Historical section",
        "scope": fact.scope or "",
        "sort": "9998",
    }


def _ordered_sections(
    section_order: dict[str, list[dict[str, str]]],
    well_id: str,
) -> list[dict[str, str]]:
    sections = section_order.get(well_id, [])
    return sorted(sections, key=lambda row: (row["scope"], int(row["sort"]) if row["sort"].isdigit() else 9999, row["section_name"].casefold()))


def _base_matrix(
    report: str,
    *,
    currency: str,
    date_from: date | None,
    date_to: date | None,
    include_draft: bool,
    entry_count: int,
    excluded_entry_count: int,
) -> UsageMatrixOut:
    return UsageMatrixOut(
        report=report,  # type: ignore[arg-type]
        mode="cost" if report in COST_ONLY_REPORTS else "usage",
        currency=currency.upper(),
        date_from=date_from,
        date_to=date_to,
        include_draft=include_draft,
        entry_count=entry_count,
        excluded_entry_count=excluded_entry_count,
    )


def _well_columns(
    wells: list[Well],
    columns_well_ids: list[str],
    section_order: dict[str, list[dict[str, str]]],
    scope_map: dict[str, set[str]],
) -> list[UsageWellColumnOut]:
    by_id = {well.id: well for well in wells}
    columns: list[UsageWellColumnOut] = []
    for well_id in columns_well_ids:
        well = by_id[well_id]
        sections = [
            UsageSectionOut(
                section_key=section["section_key"],
                hole_section_id=section["hole_section_id"],
                section_code=section["section_code"],
                section_name=section["section_name"],
                scope=section["scope"],
            )
            for section in _ordered_sections(section_order, well_id)
        ]
        columns.append(UsageWellColumnOut(
            well_id=well.id,
            well_code=well.well_code,
            well_name=well.well_name,
            rig_id=well.rig_id,
            rig_code=well.rig.rig_code if well.rig else "",
            rig_name=well.rig.rig_name if well.rig else "",
            block_id=well.block_id,
            block_code=well.block_record.block_code if well.block_record else "",
            block_name=well.block_record.block_name if well.block_record else "",
            scopes=sorted(scope_map.get(well.id, set())),
            sections=sections,
        ))
    return columns


# ---------------------------------------------------------------------------
# Item identity and enrichment for the usage reports
# ---------------------------------------------------------------------------


def _blank_identity() -> dict[str, str]:
    return {"code": "", "name": "", "uom": "", "category": "", "subcategory": "",
            "manufacturer": "", "detail": ""}


def _chemical_identity(
    db: Session, organization_id: str, facts_by_item: dict[str, list[Any]]
) -> dict[str, dict[str, str]]:
    masters = _chemical_map(db, organization_id)
    option_ids = [opt_id for row in masters.values() for opt_id in (row.group_id, row.manufacturer_id)]
    options = _option_map(db, organization_id, option_ids)
    identities: dict[str, dict[str, str]] = {}
    for item_id, rows in facts_by_item.items():
        sample = rows[0]
        master = masters.get(item_id)
        identity = _blank_identity()
        identity["code"] = master.chemical_code if master else sample.item_code
        identity["name"] = master.chemical_name if master else sample.item_name
        identity["uom"] = master.uom if master else sample.uom
        if master:
            identity["category"] = options.get(master.group_id, "")
            identity["manufacturer"] = options.get(master.manufacturer_id, "")
            if master.part_number:
                identity["detail"] = f"Part no. {master.part_number}"
        identities[item_id] = identity
    return identities


def _bit_identity(
    db: Session, organization_id: str, facts_by_item: dict[str, list[Any]]
) -> dict[str, dict[str, str]]:
    masters = _bit_map(db, organization_id)
    option_ids = [opt_id for row in masters.values() for opt_id in (row.bit_type_id, row.manufacturer_id)]
    options = _option_map(db, organization_id, option_ids)
    identities: dict[str, dict[str, str]] = {}
    for item_id, rows in facts_by_item.items():
        sample = rows[0]
        master = masters.get(item_id)
        identity = _blank_identity()
        identity["code"] = master.bit_code if master else sample.item_code
        identity["name"] = master.bit_name if master else sample.item_name
        identity["uom"] = sample.uom or "unit"
        if master:
            identity["category"] = options.get(master.bit_type_id, "")
            identity["manufacturer"] = options.get(master.manufacturer_id, "")
            details = [
                f"Model {master.model_no}" if master.model_no else "",
                f"Size {master.size}" if master.size else "",
                f"IADC {master.iadc_code}" if master.iadc_code else "",
            ]
            identity["detail"] = " · ".join(part for part in details if part)
        identities[item_id] = identity
    return identities


def _tangible_identity(
    db: Session, organization_id: str, facts_by_item: dict[str, list[Any]]
) -> dict[str, dict[str, str]]:
    masters = _tangible_map(db, organization_id)
    option_ids = [
        opt_id
        for row in masters.values()
        for opt_id in (row.category_id, row.subcategory_id, row.manufacturer_id)
    ]
    options = _option_map(db, organization_id, option_ids)
    identities: dict[str, dict[str, str]] = {}
    for item_id, rows in facts_by_item.items():
        sample = rows[0]
        master = masters.get(item_id)
        identity = _blank_identity()
        identity["code"] = master.tangible_code if master else sample.item_code
        identity["name"] = master.tangible_name if master else sample.item_name
        identity["uom"] = master.uom if master else sample.uom
        if master:
            identity["category"] = options.get(master.category_id, "")
            identity["subcategory"] = options.get(master.subcategory_id, "")
            identity["manufacturer"] = options.get(master.manufacturer_id, "")
            identity["detail"] = master.scope
        identities[item_id] = identity
    return identities


def _service_identity(
    db: Session, organization_id: str, facts_by_item: dict[str, list[Any]]
) -> dict[str, dict[str, str]]:
    masters = _service_map(db, organization_id)
    vendors = _vendor_map(db, organization_id)
    identities: dict[str, dict[str, str]] = {}
    for item_id, rows in facts_by_item.items():
        sample = rows[0]
        master = masters.get(item_id)
        identity = _blank_identity()
        identity["code"] = master.service_code if master else sample.item_code
        identity["name"] = master.service_name if master else sample.item_name
        identity["uom"] = sample.uom
        if master:
            identity["category"] = master.service_category
            identity["subcategory"] = master.provider_type
            vendor = vendors.get(master.vendor_id) if master.vendor_id else None
            identity["manufacturer"] = vendor.vendor_name if vendor else ""
            identity["detail"] = master.service_group or ""
        identities[item_id] = identity
    return identities


def _vendor_identity(
    db: Session, organization_id: str, facts_by_item: dict[str, list[Any]]
) -> dict[str, dict[str, str]]:
    masters = _vendor_map(db, organization_id)
    identities: dict[str, dict[str, str]] = {}
    for item_id, rows in facts_by_item.items():
        sample = rows[0]
        identity = _blank_identity()
        if item_id.startswith("party:"):
            identity["name"] = item_id[len("party:"):]
            identity["code"] = sample.vendor_code or ""
            identity["detail"] = "Recorded party (no vendor register entry)"
            identities[item_id] = identity
            continue
        master = masters.get(item_id)
        identity["code"] = master.vendor_code if master else sample.vendor_code
        identity["name"] = master.vendor_name if master else (sample.vendor_name or "Unassigned vendor")
        if master:
            identity["category"] = master.vendor_type
            identity["subcategory"] = master.category
            identity["detail"] = master.status
        identities[item_id] = identity
    return identities


_IDENTITY_BUILDERS = {
    "mud-chemicals": _chemical_identity,
    "drill-bits": _bit_identity,
    "tangibles": _tangible_identity,
    "services": _service_identity,
    "vendors": _vendor_identity,
}


def _item_key(fact: Any) -> str:
    if fact.cost_group == "Services":
        return fact.item_id
    if fact.cost_group == "Tangibles":
        return fact.item_id
    if fact.cost_group == "Consumables":
        return fact.item_id
    # Other expenses only appear in the vendor report.
    return f"party:{fact.party_name or fact.vendor_name or 'Unassigned'}" if not fact.vendor_id else fact.vendor_id


def _vendor_key(fact: Any) -> str:
    if fact.vendor_id:
        return fact.vendor_id
    return f"party:{fact.party_name or fact.vendor_name or 'Unassigned'}"


def matrix_report(
    db: Session,
    organization_id: str,
    report: str,
    *,
    block_id: str = "",
    rig_id: str = "",
    well_ids: list[str] | None = None,
    scope: str = "",
    lifecycle: str = "",
    currency: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    include_draft: bool = True,
) -> UsageMatrixOut:
    if report not in _IDENTITY_BUILDERS:
        raise HTTPException(status_code=422, detail=f"Unknown usage report '{report}'")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    selected_currency = (currency or "USD").upper()
    wells = _resolve_wells(
        db, organization_id,
        block_id=block_id, rig_id=rig_id, well_ids=well_ids or [],
        scope=scope, lifecycle=lifecycle,
    )
    selected_well_ids = [well.id for well in wells]
    scope_map = _afe_scope_map(db, organization_id)
    entry_count, excluded = _entry_counts(
        db, organization_id, selected_well_ids,
        date_from=date_from, date_to=date_to, include_draft=include_draft,
        scope=scope, currency=selected_currency,
    )
    result = _base_matrix(
        report, currency=selected_currency, date_from=date_from, date_to=date_to,
        include_draft=include_draft, entry_count=entry_count, excluded_entry_count=excluded,
    )
    if not selected_well_ids:
        return result

    all_facts = _facts(
        db, organization_id, selected_well_ids,
        date_from=date_from, date_to=date_to, include_draft=include_draft,
        scope=scope, currency=selected_currency,
    )
    # Report-specific fact filter and item keying.
    if report == "mud-chemicals":
        facts = [row for row in all_facts if row.cost_group == "Consumables" and row.category == "Mud Chemicals"]
    elif report == "drill-bits":
        facts = [row for row in all_facts if row.cost_group == "Consumables" and row.category == "Drill Bits"]
    elif report == "tangibles":
        facts = [row for row in all_facts if row.cost_group == "Tangibles"]
    elif report == "services":
        facts = [row for row in all_facts if row.cost_group == "Services"]
    else:
        facts = list(all_facts)

    registries = _section_registries(db, organization_id, selected_well_ids)
    section_order: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_sections: set[tuple[str, str]] = set()

    # accumulator[item_id][well_id][section_key] = [qty, amount]
    accum: dict[str, dict[str, dict[str, list[Decimal]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: [ZERO, ZERO]))
    )
    # One flat detail row per (item, well, section[, cost group]).
    detail_accum: dict[tuple[str, str, str, str], list[Any]] = {}
    facts_by_item: dict[str, list[Any]] = defaultdict(list)
    wells_with_facts: set[str] = set()

    for fact in facts:
        if report == "vendors":
            item_id = _vendor_key(fact)
        else:
            item_id = _item_key(fact)
        facts_by_item[item_id].append(fact)
        section = _section_for_fact(registries, fact.well_id, fact)
        section_key = section["section_key"]
        marker = (fact.well_id, section_key)
        if marker not in seen_sections:
            seen_sections.add(marker)
            section_order[fact.well_id].append(section)
        bucket = accum[item_id][fact.well_id][section_key]
        bucket[0] += Decimal(str(fact.quantity or 0))
        bucket[1] += Decimal(str(fact.amount or 0))
        wells_with_facts.add(fact.well_id)
        detail_key = (item_id, fact.well_id, section_key, fact.cost_group if report == "vendors" else "")
        if detail_key not in detail_accum:
            detail_accum[detail_key] = [fact, section, ZERO, ZERO]
        detail_accum[detail_key][2] += Decimal(str(fact.quantity or 0))
        detail_accum[detail_key][3] += Decimal(str(fact.amount or 0))

    identities = (
        _IDENTITY_BUILDERS[report](db, organization_id, facts_by_item)
        if facts_by_item else {}
    )
    cost_only = report in COST_ONLY_REPORTS
    explicit_selection = bool(well_ids)
    column_well_ids = [
        well_id for well_id in selected_well_ids
        if explicit_selection or well_id in wells_with_facts
    ]
    result.wells = _well_columns(wells, column_well_ids, section_order, scope_map)
    result.well_totals = [
        UsageWellCellOut(well_id=well_id) for well_id in column_well_ids
    ]
    if not facts_by_item:
        return result

    grand_qty = ZERO
    grand_amount = ZERO
    well_totals: dict[str, list[Decimal]] = {well_id: [ZERO, ZERO] for well_id in column_well_ids}
    detail_rows: list[UsageDetailRowOut] = []
    item_rows: list[UsageItemRowOut] = []

    ordered_item_ids = sorted(
        facts_by_item,
        key=lambda key: (
            identities[key]["category"].casefold(),
            identities[key]["subcategory"].casefold(),
            identities[key]["name"].casefold(),
            identities[key]["code"].casefold(),
        ),
    )
    well_by_id = {well.id: well for well in wells}

    for item_id in ordered_item_ids:
        identity = identities[item_id]
        per_well = accum[item_id]
        cells: list[UsageWellCellOut] = []
        item_qty = ZERO
        item_amount = ZERO
        for well_id in column_well_ids:
            section_buckets = per_well.get(well_id, {})
            ordered_keys = [
                section["section_key"] for section in _ordered_sections(section_order, well_id)
            ]
            section_cells = [
                UsageCellOut(
                    section_key=section_key,
                    quantity=ZERO if cost_only else _qty(section_buckets[section_key][0]),
                    amount=_money(section_buckets[section_key][1]),
                )
                for section_key in ordered_keys if section_key in section_buckets
            ]
            well_qty = sum((bucket[0] for bucket in section_buckets.values()), ZERO)
            well_amount = sum((bucket[1] for bucket in section_buckets.values()), ZERO)
            cells.append(UsageWellCellOut(
                well_id=well_id,
                sections=section_cells,
                quantity=ZERO if cost_only else _qty(well_qty),
                amount=_money(well_amount),
            ))
            item_qty += well_qty
            item_amount += well_amount
            well_totals[well_id][0] += well_qty
            well_totals[well_id][1] += well_amount
        item_rows.append(UsageItemRowOut(
            item_id=item_id,
            item_code=identity["code"],
            item_name=identity["name"],
            uom="" if cost_only else identity["uom"],
            category=identity["category"],
            subcategory=identity["subcategory"],
            manufacturer=identity["manufacturer"],
            detail=identity["detail"],
            cells=cells,
            quantity_total=ZERO if cost_only else _qty(item_qty),
            amount_total=_money(item_amount),
        ))
        grand_qty += item_qty
        grand_amount += item_amount

    # Flat, filterable detail rows (item × well × section[, cost group]).
    for (item_id, well_id, section_key, _cost_group), seed in sorted(
        detail_accum.items(), key=lambda entry: (entry[0][1], entry[0][0], entry[0][2])
    ):
        fact, section, total_qty, total_amount = seed
        if well_id not in column_well_ids:
            continue
        identity = identities[item_id]
        well = well_by_id[well_id]
        detail_rows.append(UsageDetailRowOut(
            row_id=f"{report}:{item_id}:{well_id}:{section_key}:{_cost_group}",
            report=report,
            cost_group=fact.cost_group,
            item_id=item_id,
            item_code=identity["code"],
            item_name=identity["name"],
            uom="" if cost_only else identity["uom"],
            category=identity["category"],
            subcategory=identity["subcategory"],
            manufacturer=identity["manufacturer"],
            detail=identity["detail"],
            well_id=well_id,
            well_code=well.well_code,
            well_name=well.well_name,
            rig_code=well.rig.rig_code if well.rig else "",
            block_code=well.block_record.block_code if well.block_record else "",
            scope=section["scope"] or fact.scope or "",
            section_key=section_key,
            section_code=section["section_code"],
            section_name=section["section_name"],
            quantity=ZERO if cost_only else _qty(total_qty),
            amount=_money(total_amount),
            currency=selected_currency,
        ))

    result.rows = item_rows
    result.detail = detail_rows
    result.well_totals = [
        UsageWellCellOut(
            well_id=well_id,
            sections=[],
            quantity=ZERO if cost_only else _qty(well_totals[well_id][0]),
            amount=_money(well_totals[well_id][1]),
        )
        for well_id in column_well_ids
    ]
    result.grand_quantity = ZERO if cost_only else _qty(grand_qty)
    result.grand_amount = _money(grand_amount)
    return result


# ---------------------------------------------------------------------------
# NPT / UPA report
# ---------------------------------------------------------------------------


def npt_upa_report(
    db: Session,
    organization_id: str,
    *,
    block_id: str = "",
    rig_id: str = "",
    well_ids: list[str] | None = None,
    scope: str = "",
    lifecycle: str = "",
    currency: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    include_draft: bool = True,
) -> NptUpaReportOut:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date must not be after the end date")
    selected_currency = (currency or "USD").upper()
    wells = _resolve_wells(
        db, organization_id,
        block_id=block_id, rig_id=rig_id, well_ids=well_ids or [],
        scope=scope, lifecycle=lifecycle,
    )
    selected_well_ids = [well.id for well in wells]
    entry_count, excluded = _entry_counts(
        db, organization_id, selected_well_ids,
        date_from=date_from, date_to=date_to, include_draft=include_draft,
        scope=scope, currency=selected_currency,
    )
    result = NptUpaReportOut(
        currency=selected_currency,
        date_from=date_from,
        date_to=date_to,
        include_draft=include_draft,
        totals=NptUpaWellRow(
            well_id="", well_code="", well_name=f"All wells ({selected_currency})",
        ),
        entry_count=entry_count,
        excluded_entry_count=excluded,
    )
    if not selected_well_ids:
        return result

    facts = _facts(
        db, organization_id, selected_well_ids,
        date_from=date_from, date_to=date_to, include_draft=include_draft,
        scope=scope, currency=selected_currency,
    )
    well_by_id = {well.id: well for well in wells}
    dates: dict[str, dict[str, set[date]]] = defaultdict(lambda: defaultdict(set))
    amounts: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    scopes_seen: dict[str, set[str]] = defaultdict(set)
    wells_with_facts: set[str] = set()
    for fact in facts:
        classification = fact.classification or "Planned"
        if classification not in CLASSIFICATIONS:
            classification = "Planned"
        dates[fact.well_id][classification].add(fact.cost_date)
        amounts[fact.well_id][classification] += Decimal(str(fact.amount or 0))
        if fact.scope:
            scopes_seen[fact.well_id].add(fact.scope)
        wells_with_facts.add(fact.well_id)

    explicit_selection = bool(well_ids)
    column_well_ids = [
        well.id for well in wells
        if explicit_selection or well.id in wells_with_facts
    ]

    totals = {classification: [0, ZERO] for classification in CLASSIFICATIONS}
    well_rows: list[NptUpaWellRow] = []
    detail_rows: list[NptUpaDetailRow] = []
    for well_id in column_well_ids:
        well = well_by_id[well_id]
        row = NptUpaWellRow(
            well_id=well.id,
            well_code=well.well_code,
            well_name=well.well_name,
            rig_code=well.rig.rig_code if well.rig else "",
            block_code=well.block_record.block_code if well.block_record else "",
        )
        for classification in CLASSIFICATIONS:
            day_field = "planned_days" if classification == "Planned" else f"{classification.lower()}_days"
            amount_field = "planned_amount" if classification == "Planned" else f"{classification.lower()}_amount"
            day_count = len(dates[well_id].get(classification, set()))
            amount = _money(amounts[well_id].get(classification, ZERO))
            setattr(row, day_field, day_count)
            setattr(row, amount_field, amount)
            totals[classification][0] += day_count
            totals[classification][1] += amount
            detail_rows.append(NptUpaDetailRow(
                row_id=f"npt-upa:{well_id}:{classification}",
                well_id=well.id,
                well_code=well.well_code,
                well_name=well.well_name,
                rig_code=row.rig_code,
                block_code=row.block_code,
                scope=",".join(sorted(scopes_seen[well_id])),
                classification=classification,
                days=day_count,
                amount=amount,
                currency=selected_currency,
            ))
        row.total_amount = _money(
            amounts[well_id].get("Planned", ZERO)
            + amounts[well_id].get("UPA", ZERO)
            + amounts[well_id].get("NPT", ZERO)
        )
        well_rows.append(row)

    for classification in CLASSIFICATIONS:
        day_field = "planned_days" if classification == "Planned" else f"{classification.lower()}_days"
        amount_field = "planned_amount" if classification == "Planned" else f"{classification.lower()}_amount"
        setattr(result.totals, day_field, totals[classification][0])
        setattr(result.totals, amount_field, _money(totals[classification][1]))
    result.totals.total_amount = _money(sum(
        (totals[classification][1] for classification in CLASSIFICATIONS), ZERO
    ))
    result.wells = well_rows
    result.detail = detail_rows
    return result


# ---------------------------------------------------------------------------
# Export audit
# ---------------------------------------------------------------------------


def record_export(
    db: Session,
    user: User,
    data: Any,
    request: Request | None,
) -> None:
    label = REPORT_LABELS.get(data.report, data.report)
    well_scope = f"{len(data.well_ids)} selected well(s)" if data.well_ids else "all wells"
    scope_label = data.scope or "all scopes"
    lifecycle_label = data.lifecycle or "all well statuses"
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action="export",
        entity_type="usage_report_export",
        entity_id=None,
        entity_label=label,
        summary=(
            f"Exported {data.record_count} {label} row(s) as {data.format.upper()}; "
            f"currency={data.currency or 'workspace default'}; {well_scope}; scope={scope_label}; "
            f"lifecycle={lifecycle_label}; dates={data.date_from or 'start'} to {data.date_to or 'today'}; "
            f"include_draft={data.include_draft}"
        ),
        request=request,
    )
    db.commit()
