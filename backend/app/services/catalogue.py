"""Business rules for Tangibles, Consumables and the Catalogue Lists.

The routers in ``app/api/catalogue_*.py`` stay thin: they authorise, call into
this module, commit once and return. Everything that decides whether a change
is valid lives here so the single-record endpoints, the bulk endpoints and the
spreadsheet import all enforce exactly the same rules.

Rules worth knowing:

* Codes are entered manually, trimmed and upper-cased, and are unique per
  workspace including removed records, so a code is never reused by accident.
* A dropdown value is referenced by id. Removing a value is a soft delete; the
  records that already use it keep it and show it as removed.
* Rate changes are revisions. A revision needs a reason, is never earlier than
  the current rate's effective date, and cannot be dated in the future.
* Import creates missing dropdown values (audited) instead of failing, and
  requires the currency and unit of measure to exist in Master Data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Callable

from fastapi import Request
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Currency, UnitOfMeasurement
from app.models.catalogue import CATALOGUE_LISTS, CatalogueOption
from app.models.catalogue import (
    CementAdditive,
    DrillBit,
    MudChemical,
    Tangible,
)
from app.schemas.catalogue import PricedItemOverview, RateRevisionOut, BreakdownItem
from app.services import audit

Q4 = Decimal("0.0001")
DEFAULT_UPLIFT = Decimal("100")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%Y/%m/%d")


class CatalogueError(Exception):
    """A rule violation that the API returns to the user next to the responsible field."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Spec: how one priced catalogue type is structured
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionField:
    attr: str  # foreign key on the item, e.g. "category_id"
    header: str  # spreadsheet header used for the name, e.g. "category"
    list_key: str  # Catalogue Lists key, e.g. "tangible_category"
    label: str  # UI label, e.g. "Category"
    required: bool = True
    parent_attr: str | None = None  # subcategory -> category foreign key


@dataclass(frozen=True)
class TextField:
    attr: str
    label: str
    max_length: int
    required: bool = False


@dataclass(frozen=True)
class ChoiceField:
    attr: str
    label: str
    choices: tuple[str, ...]


@dataclass(frozen=True)
class PricedSpec:
    key: str  # URL segment and module key, e.g. "tangibles"
    label: str  # e.g. "Tangibles"
    item_type: str  # e.g. "Tangible" (shown on revisions)
    entity: str  # audit entity_type, e.g. "tangible"
    model: type
    revision_model: type
    revision_fk: str  # e.g. "tangible_id"
    revisions_attr: str  # relationship name on the item, e.g. "revisions"
    code_attr: str
    name_attr: str
    code_label: str
    name_label: str
    priced: str  # "uplift" (rate x uplift %) or "unit" (plain unit rate)
    options: tuple[OptionField, ...] = ()
    texts: tuple[TextField, ...] = ()
    choices: tuple[ChoiceField, ...] = ()
    duplicate_rule: str = "unique_name"  # "relaxed" | "unique_name"
    unique_text_attr: str | None = None  # e.g. a serial number that must be unique
    breakdown_attr: str | None = None
    breakdown_label: str | None = None
    lifecycle: bool = True  # False: no create/delete/import (fixed records such as fuel)
    create_model: type[BaseModel] | None = None
    update_model: type[BaseModel] | None = None
    revise_model: type[BaseModel] | None = None
    out_model: type[BaseModel] | None = None
    import_required: tuple[str, ...] = ()
    import_optional: tuple[str, ...] = ()
    import_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    sample_row: dict[str, str] = field(default_factory=dict)
    seed: Callable[[Session, str], None] | None = None

    @property
    def priced_uplift(self) -> bool:
        return self.priced == "uplift"

    def option(self, attr: str) -> OptionField | None:
        return next((f for f in self.options if f.attr == attr), None)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def today() -> date:
    return datetime.now(timezone.utc).date()


def final_cost(unit_rate: Decimal, uplift: Decimal) -> Decimal:
    return (unit_rate * uplift / Decimal("100")).quantize(Q4, rounding=ROUND_HALF_UP)


def q4(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Q4, rounding=ROUND_HALF_UP)


def value_key(value: str) -> str:
    return " ".join(str(value).split()).casefold()


def clean_value(value: Any) -> str:
    return " ".join(str(value or "").split())


def actor_name(user: Any) -> str:
    return (getattr(user, "full_name", "") or getattr(user, "email", "") or "")[:255]


def normalize_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def parse_decimal(raw: Any, label: str, *, allow_blank: bool = True) -> Decimal | None:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        if allow_blank:
            return None
        raise CatalogueError(f"{label} is required")
    text = str(raw).strip().replace(",", "").replace("%", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise CatalogueError(f"{label} must be a number (got '{raw}')") from error


def parse_date(raw: Any, label: str = "Effective date") -> date | None:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise CatalogueError(f"{label} must be a date such as 2026-01-31 or 31/01/2026 (got '{raw}')")


def _validation_message(error: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in item['loc'])}: {item['msg']}" for item in error.errors())


def _latest_revision(db: Session, spec: PricedSpec, item_id: str) -> Any:
    fk = getattr(spec.revision_model, spec.revision_fk)
    return db.scalar(
        select(spec.revision_model)
        .where(fk == item_id)
        .order_by(spec.revision_model.revision_number.desc())
        .limit(1)
    )


def options_by_id(db: Session, organization_id: str) -> dict[str, CatalogueOption]:
    rows = db.scalars(select(CatalogueOption).where(CatalogueOption.organization_id == organization_id)).all()
    return {row.id: row for row in rows}


def _ensure_code_free(db: Session, spec: PricedSpec, organization_id: str, code: str, exclude_id: str | None) -> None:
    statement = select(spec.model.id).where(
        spec.model.organization_id == organization_id,
        getattr(spec.model, spec.code_attr) == code,
    )
    if exclude_id:
        statement = statement.where(spec.model.id != exclude_id)
    if db.scalar(statement) is not None:
        raise CatalogueError(f"{spec.code_label} {code} already exists in this workspace", 409)


# ---------------------------------------------------------------------------
# Catalogue Lists (dropdown values)
# ---------------------------------------------------------------------------


def list_label(list_key: str) -> str:
    return CATALOGUE_LISTS[list_key][0]


def usage_map() -> dict[str, list[tuple[type, str]]]:
    """Which item tables reference each list, for usage counts and safe removal."""
    return {
        "tangible_category": [(Tangible, "category_id")],
        "tangible_subcategory": [(Tangible, "subcategory_id")],
        "manufacturer": [
            (Tangible, "manufacturer_id"),
            (DrillBit, "manufacturer_id"),
            (MudChemical, "manufacturer_id"),
            (CementAdditive, "manufacturer_id"),
        ],
        "drill_bit_type": [(DrillBit, "bit_type_id")],
        "mud_chemical_group": [(MudChemical, "group_id")],
        "cement_additive_type": [(CementAdditive, "additive_type_id")],
    }


def option_usage_counts(db: Session, organization_id: str, list_key: str) -> dict[str, int]:
    """Number of item rows (active or removed) referencing each option of a list."""
    counts: dict[str, int] = {}
    for model, attr in usage_map().get(list_key, []):
        column = getattr(model, attr)
        rows = db.execute(
            select(column, func.count(model.id))
            .where(model.organization_id == organization_id)
            .group_by(column)
        ).all()
        for option_id, count in rows:
            if option_id:
                counts[option_id] = counts.get(option_id, 0) + int(count)
    return counts


def option_in_use(db: Session, organization_id: str, option: CatalogueOption) -> int:
    total = 0
    for model, attr in usage_map().get(option.list_key, []):
        total += db.scalar(
            select(func.count(model.id)).where(
                model.organization_id == organization_id,
                getattr(model, attr) == option.id,
            )
        ) or 0
    return total


def child_option_count(db: Session, organization_id: str, option: CatalogueOption, *, active_only: bool) -> int:
    statement = select(func.count(CatalogueOption.id)).where(
        CatalogueOption.organization_id == organization_id,
        CatalogueOption.parent_id == option.id,
    )
    if active_only:
        statement = statement.where(CatalogueOption.is_deleted.is_(False))
    return db.scalar(statement) or 0


def _find_option(db: Session, organization_id: str, list_key: str, value: str, parent_key: str) -> CatalogueOption | None:
    return db.scalar(
        select(CatalogueOption).where(
            CatalogueOption.organization_id == organization_id,
            CatalogueOption.list_key == list_key,
            CatalogueOption.parent_key == parent_key,
            CatalogueOption.value_key == value_key(value),
        )
    )


def validate_option_parent(db: Session, organization_id: str, list_key: str, parent_id: str | None) -> CatalogueOption | None:
    """Subcategories need an active parent in the list named by the parent key."""
    parent_list = CATALOGUE_LISTS[list_key][1]
    if parent_list is None:
        if parent_id:
            raise CatalogueError(f"{list_label(list_key)} do not have a parent value")
        return None
    if not parent_id:
        raise CatalogueError(f"Select a parent value from {list_label(parent_list)} first")
    parent = db.scalar(
        select(CatalogueOption).where(
            CatalogueOption.id == parent_id,
            CatalogueOption.organization_id == organization_id,
            CatalogueOption.list_key == parent_list,
        )
    )
    if parent is None or parent.is_deleted:
        raise CatalogueError("Select an active parent value from Catalogue Lists")
    return parent


def create_option(db: Session, organization_id: str, list_key: str, value: str, parent_id: str | None, user: Any, request: Request | None) -> CatalogueOption:
    if list_key not in CATALOGUE_LISTS:
        raise CatalogueError("Unknown catalogue list", 404)
    name = clean_value(value)
    if not name:
        raise CatalogueError("Value is required")
    parent = validate_option_parent(db, organization_id, list_key, parent_id)
    parent_key = parent.id if parent else ""
    existing = _find_option(db, organization_id, list_key, name, parent_key)
    if existing is not None:
        where = f" under {parent.value}" if parent else ""
        state = " It was removed; restore it instead." if existing.is_deleted else ""
        raise CatalogueError(f"'{existing.value}' already exists in {list_label(list_key)}{where}.{state}", 409)
    option = CatalogueOption(
        organization_id=organization_id,
        list_key=list_key,
        parent_id=parent.id if parent else None,
        parent_key=parent_key,
        value=name,
        value_key=value_key(name),
    )
    db.add(option)
    db.flush()
    audit.record(
        db, organization_id=organization_id, actor=user, action="create", entity_type="catalogue_option",
        entity_id=option.id, entity_label=f"{list_label(list_key)} · {name}",
        summary=f"Added '{name}' to {list_label(list_key)}" + (f" under {parent.value}" if parent else ""),
        request=request,
    )
    return option


def rename_option(db: Session, organization_id: str, option: CatalogueOption, value: str, user: Any, request: Request | None) -> CatalogueOption:
    name = clean_value(value)
    if not name:
        raise CatalogueError("Value is required")
    if option.value_key == value_key(name) and option.value == name:
        return option
    clash = _find_option(db, organization_id, option.list_key, name, option.parent_key)
    if clash is not None and clash.id != option.id:
        raise CatalogueError(f"'{clash.value}' already exists in this list", 409)
    previous = option.value
    option.value = name
    option.value_key = value_key(name)
    audit.record(
        db, organization_id=organization_id, actor=user, action="update", entity_type="catalogue_option",
        entity_id=option.id, entity_label=f"{list_label(option.list_key)} · {name}",
        summary=f"Renamed '{previous}' to '{name}' in {list_label(option.list_key)}", request=request,
    )
    return option


def remove_option(db: Session, organization_id: str, option: CatalogueOption, user: Any, request: Request | None) -> None:
    if option.is_deleted:
        raise CatalogueError("This value is already removed", 409)
    children = child_option_count(db, organization_id, option, active_only=True)
    if children:
        raise CatalogueError(
            f"Remove the {children} active subcategor{'y' if children == 1 else 'ies'} under '{option.value}' first"
        )
    option.is_deleted = True
    option.deleted_at = datetime.now(timezone.utc)
    used = option_in_use(db, organization_id, option)
    note = f" ({used} existing records keep this value and show it as removed)" if used else ""
    audit.record(
        db, organization_id=organization_id, actor=user, action="soft_delete", entity_type="catalogue_option",
        entity_id=option.id, entity_label=f"{list_label(option.list_key)} · {option.value}",
        summary=f"Removed '{option.value}' from {list_label(option.list_key)}{note}", request=request,
    )


def restore_option(db: Session, organization_id: str, option: CatalogueOption, user: Any, request: Request | None) -> None:
    if not option.is_deleted:
        raise CatalogueError("Only a removed value can be restored", 409)
    if option.parent_id:
        parent = db.get(CatalogueOption, option.parent_id)
        if parent is None or parent.is_deleted:
            raise CatalogueError("Restore the parent value first", 409)
    option.is_deleted = False
    option.deleted_at = None
    audit.record(
        db, organization_id=organization_id, actor=user, action="restore", entity_type="catalogue_option",
        entity_id=option.id, entity_label=f"{list_label(option.list_key)} · {option.value}",
        summary=f"Restored '{option.value}' in {list_label(option.list_key)}", request=request,
    )


def purge_option(db: Session, organization_id: str, option: CatalogueOption, user: Any, request: Request | None) -> None:
    if not option.is_deleted:
        raise CatalogueError("Only a removed value can be permanently deleted", 409)
    used = option_in_use(db, organization_id, option)
    if used:
        raise CatalogueError(f"'{option.value}' is still used by {used} records and cannot be permanently deleted")
    if child_option_count(db, organization_id, option, active_only=False):
        raise CatalogueError(f"'{option.value}' still has subcategories and cannot be permanently deleted")
    audit.record(
        db, organization_id=organization_id, actor=user, action="permanent_delete", entity_type="catalogue_option",
        entity_id=option.id, entity_label=f"{list_label(option.list_key)} · {option.value}",
        summary=f"Permanently deleted '{option.value}' from {list_label(option.list_key)}", request=request,
    )
    db.delete(option)


def resolve_option_by_name(
    db: Session,
    organization_id: str,
    list_key: str,
    name: str,
    parent_id: str | None,
    created: list[str],
) -> str:
    """Import helper: find a dropdown value by name, restoring or creating it as needed."""
    clean = clean_value(name)
    parent_key = parent_id or ""
    existing = _find_option(db, organization_id, list_key, clean, parent_key)
    if existing is not None:
        if existing.is_deleted:
            restore_option(db, organization_id, existing, None, None)
        return existing.id
    option = CatalogueOption(
        organization_id=organization_id,
        list_key=list_key,
        parent_id=parent_id,
        parent_key=parent_key,
        value=clean,
        value_key=value_key(clean),
    )
    db.add(option)
    db.flush()
    created.append(f"{list_label(list_key)}: {clean}")
    return option.id


# ---------------------------------------------------------------------------
# Master-data validation for priced items
# ---------------------------------------------------------------------------


def _currency_code(db: Session, organization_id: str, raw: Any) -> str:
    text = clean_value(raw)
    if not text:
        raise CatalogueError("Currency is required")
    currency = db.scalar(
        select(Currency).where(
            Currency.organization_id == organization_id,
            Currency.is_deleted.is_(False),
            func.lower(Currency.currency_code) == text.lower(),
        )
    )
    if currency is None:
        raise CatalogueError(f"Currency '{text}' is not in Currency master data")
    return currency.currency_code


def _uom_code(db: Session, organization_id: str, raw: Any) -> str:
    text = clean_value(raw)
    if not text:
        return ""
    unit = db.scalar(
        select(UnitOfMeasurement).where(
            UnitOfMeasurement.organization_id == organization_id,
            UnitOfMeasurement.is_deleted.is_(False),
            func.lower(UnitOfMeasurement.unit_code) == text.lower(),
        )
    )
    if unit is None:
        raise CatalogueError(f"UOM '{text}' is not in Units of Measurement master data")
    return unit.unit_code


def _master_values(
    db: Session,
    spec: PricedSpec,
    organization_id: str,
    merged: dict[str, Any],
    existing: Any | None,
) -> dict[str, Any]:
    """Validate and normalise the master (non-rate) attributes of one record."""
    code = clean_value(merged.get(spec.code_attr)).upper()
    if not code:
        raise CatalogueError(f"{spec.code_label} is required")
    name = clean_value(merged.get(spec.name_attr))
    if not name:
        raise CatalogueError(f"{spec.name_label} is required")
    values: dict[str, Any] = {spec.code_attr: code, spec.name_attr: name}
    values["description"] = clean_value(merged.get("description"))

    for text in spec.texts:
        raw = clean_value(merged.get(text.attr))
        if text.required and not raw:
            raise CatalogueError(f"{text.label} is required")
        if len(raw) > text.max_length:
            raise CatalogueError(f"{text.label} must be {text.max_length} characters or fewer")
        if text.attr == "uom" and raw and (existing is None or existing.uom != raw):
            raw = _uom_code(db, organization_id, raw)
        values[text.attr] = raw

    for choice in spec.choices:
        raw = merged.get(choice.attr)
        if raw not in choice.choices:
            raise CatalogueError(f"{choice.label} must be one of: {', '.join(choice.choices)}")
        values[choice.attr] = raw

    for option in spec.options:
        chosen = merged.get(option.attr) or None
        if not chosen:
            if option.required:
                raise CatalogueError(f"{option.label} is required")
            values[option.attr] = None
            continue
        target = db.get(CatalogueOption, chosen)
        if target is None or target.organization_id != organization_id or target.list_key != option.list_key:
            raise CatalogueError(f"Select a {option.label.lower()} from Catalogue Lists")
        unchanged = existing is not None and getattr(existing, option.attr) == chosen
        if not unchanged and target.is_deleted:
            raise CatalogueError(f"'{target.value}' was removed from {list_label(option.list_key)}; choose another {option.label.lower()}")
        if option.parent_attr:
            parent_option = spec.option(option.parent_attr)
            parent_id = merged.get(option.parent_attr) or None
            if target.parent_id != parent_id:
                parent_label = parent_option.label.lower() if parent_option else "parent"
                raise CatalogueError(f"The {option.label.lower()} must belong to the selected {parent_label}")
        values[option.attr] = chosen
    return values


def _rate_values(db: Session, organization_id: str, spec: PricedSpec, payload: dict[str, Any]) -> dict[str, Any]:
    rate = q4(payload.get("unit_rate") if payload.get("unit_rate") is not None else 0)
    if rate < 0:
        raise CatalogueError("Rate must not be negative")
    uplift: Decimal | None = None
    final: Decimal | None = None
    if spec.priced_uplift:
        uplift = q4(payload.get("cost_uplift") if payload.get("cost_uplift") is not None else DEFAULT_UPLIFT)
        if uplift < 0:
            raise CatalogueError("Uplift % must not be negative")
        final = final_cost(rate, uplift)
    effective = payload.get("effective_date") or today()
    if effective > today():
        raise CatalogueError("Effective date cannot be in the future")
    return {
        "unit_rate": rate,
        "cost_uplift": uplift,
        "final_cost": final,
        "currency": _currency_code(db, organization_id, payload.get("currency")),
        "po_number": clean_value(payload.get("po_number")),
        "effective_date": effective,
    }


def _check_duplicates(
    db: Session,
    spec: PricedSpec,
    organization_id: str,
    values: dict[str, Any],
    rate: dict[str, Any],
    exclude_id: str | None,
) -> None:
    if spec.unique_text_attr:
        text = values.get(spec.unique_text_attr) or ""
        if text:
            column = getattr(spec.model, spec.unique_text_attr)
            clash_statement = select(spec.model).where(
                spec.model.organization_id == organization_id,
                func.lower(column) == text.casefold(),
            )
            if exclude_id:
                clash_statement = clash_statement.where(spec.model.id != exclude_id)
            clash = db.scalar(clash_statement)
            if clash is not None:
                raise CatalogueError(
                    f"This {spec.unique_text_attr.replace('_', ' ')} is already used by {getattr(clash, spec.code_attr)}",
                    409,
                )

    name = values[spec.name_attr]
    name_column = getattr(spec.model, spec.name_attr)
    base = [spec.model.organization_id == organization_id, func.lower(name_column) == name.casefold()]
    if exclude_id:
        base.append(spec.model.id != exclude_id)

    if spec.duplicate_rule == "relaxed":
        # Names may repeat when the row differs on manufacturer, rate, uplift or description.
        candidates = db.scalars(select(spec.model).where(*base, spec.model.is_deleted.is_(False))).all()
        for other in candidates:
            same = (
                getattr(other, "manufacturer_id", None) == values.get("manufacturer_id")
                and other.unit_rate == rate["unit_rate"]
                and (other.cost_uplift or Decimal("0")) == (rate["cost_uplift"] or Decimal("0"))
                and (other.description or "").strip().casefold() == (values.get("description") or "").casefold()
            )
            if same:
                raise CatalogueError(
                    f"{spec.name_label} '{name}' already exists as {getattr(other, spec.code_attr)} with the same "
                    "manufacturer, rate, uplift and description",
                    409,
                )
    elif spec.duplicate_rule == "unique_name":
        other = db.scalar(select(spec.model).where(*base))
        if other is not None:
            state = " It was removed; restore it instead." if other.is_deleted else ""
            raise CatalogueError(
                f"{spec.name_label} '{name}' already exists as {getattr(other, spec.code_attr)}.{state}", 409
            )


# ---------------------------------------------------------------------------
# Output shaping
# ---------------------------------------------------------------------------


def item_out(spec: PricedSpec, item: Any, options: dict[str, CatalogueOption]) -> Any:
    data: dict[str, Any] = {
        "id": item.id,
        spec.code_attr: getattr(item, spec.code_attr),
        spec.name_attr: getattr(item, spec.name_attr),
        "description": item.description or "",
        "is_deleted": item.is_deleted,
        "deleted_at": item.deleted_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "unit_rate": item.unit_rate,
        "cost_uplift": item.cost_uplift,
        "final_cost": item.final_cost,
        "currency": item.currency,
        "po_number": item.po_number,
        "effective_date": item.effective_date,
        "current_revision_number": item.current_revision_number,
        "uom": getattr(item, "uom", ""),
        "remarks": getattr(item, "remarks", ""),
        "part_number": getattr(item, "part_number", ""),
        "model_no": getattr(item, "model_no", ""),
        "size": getattr(item, "size", ""),
        "iadc_code": getattr(item, "iadc_code", ""),
        "serial_number": getattr(item, "serial_number", ""),
    }
    for choice in spec.choices:
        data[choice.attr] = getattr(item, choice.attr)
    for option in spec.options:
        option_id = getattr(item, option.attr)
        match = options.get(option_id) if option_id else None
        data[option.attr] = option_id
        data[option.attr.removesuffix("_id") + "_name"] = (match.value if match else None)
    return spec.out_model.model_validate(data)


def revision_out(spec: PricedSpec, revision: Any, item: Any | None) -> RateRevisionOut:
    return RateRevisionOut(
        id=revision.id,
        item_type=spec.item_type,
        item_id=getattr(revision, spec.revision_fk),
        item_code=getattr(item, spec.code_attr, "") if item else "",
        item_name=getattr(item, spec.name_attr, "") if item else "",
        revision_number=revision.revision_number,
        effective_date=revision.effective_date,
        unit_rate=revision.unit_rate,
        previous_unit_rate=revision.previous_unit_rate,
        cost_uplift=revision.cost_uplift,
        final_cost=revision.final_cost,
        previous_final_cost=revision.previous_final_cost,
        currency=revision.currency,
        uom=revision.uom,
        po_number=revision.po_number,
        reason=revision.reason,
        recorded_by=revision.recorded_by,
        created_at=revision.created_at,
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def list_items(db: Session, spec: PricedSpec, organization_id: str, *, deleted: bool) -> list[Any]:
    statement = select(spec.model).where(
        spec.model.organization_id == organization_id,
        spec.model.is_deleted.is_(deleted),
    )
    order_col = getattr(spec.model, spec.code_attr)
    statement = statement.order_by(order_col)
    return list(db.scalars(statement).all())


def item_overview(db: Session, spec: PricedSpec, organization_id: str) -> PricedItemOverview:
    active = db.scalar(select(func.count(spec.model.id)).where(
        spec.model.organization_id == organization_id, spec.model.is_deleted.is_(False))) or 0
    deleted = db.scalar(select(func.count(spec.model.id)).where(
        spec.model.organization_id == organization_id, spec.model.is_deleted.is_(True))) or 0
    window_start = datetime.now(timezone.utc) - timedelta(days=30)
    recent_count = db.scalar(
        select(func.count(spec.revision_model.id)).where(
            spec.revision_model.organization_id == organization_id,
            spec.revision_model.created_at >= window_start,
        )
    ) or 0

    breakdown: list[BreakdownItem] = []
    breakdown_label = None
    if spec.breakdown_attr:
        breakdown_label = spec.breakdown_label
        column = getattr(spec.model, spec.breakdown_attr)
        rows = db.execute(
            select(column, func.count(spec.model.id))
            .where(spec.model.organization_id == organization_id, spec.model.is_deleted.is_(False))
            .group_by(column)
        ).all()
        options = options_by_id(db, organization_id)
        counts = {option_id: int(count) for option_id, count in rows if option_id}
        ordered = sorted(counts.items(), key=lambda pair: (options[pair[0]].value.casefold() if pair[0] in options else ""))
        for option_id, count in ordered:
            option = options.get(option_id)
            label = option.value if option else "(unknown)"
            if option and option.is_deleted:
                label += " (removed)"
            breakdown.append(BreakdownItem(key=option_id, label=label, count=count))

    recent = db.scalars(
        select(spec.revision_model)
        .where(spec.revision_model.organization_id == organization_id)
        .order_by(spec.revision_model.created_at.desc(), spec.revision_model.revision_number.desc())
        .limit(8)
    ).all()
    items = {getattr(rev, spec.revision_fk): db.get(spec.model, getattr(rev, spec.revision_fk)) for rev in recent}
    return PricedItemOverview(
        active_count=active,
        deleted_count=deleted,
        revisions_last_30_days=recent_count,
        breakdown_label=breakdown_label,
        breakdown=breakdown,
        recent_revisions=[revision_out(spec, rev, items.get(getattr(rev, spec.revision_fk))) for rev in recent],
    )


def revision_history(db: Session, spec: PricedSpec, organization_id: str, item_id: str | None = None, *, include_removed: bool = False) -> list[RateRevisionOut]:
    statement = (
        select(spec.revision_model)
        .where(spec.revision_model.organization_id == organization_id)
        .order_by(spec.revision_model.effective_date.desc(), spec.revision_model.revision_number.desc())
    )
    if item_id:
        statement = statement.where(getattr(spec.revision_model, spec.revision_fk) == item_id)
    revisions = db.scalars(statement).all()
    items = {item.id: item for item in db.scalars(select(spec.model).where(spec.model.organization_id == organization_id)).all()}
    result = []
    for revision in revisions:
        item = items.get(getattr(revision, spec.revision_fk))
        if item is None:
            continue
        if item.is_deleted and not include_removed:
            continue
        result.append(revision_out(spec, revision, item))
    return result


# ---------------------------------------------------------------------------
# Writes (no commit here: routers commit once, imports commit once)
# ---------------------------------------------------------------------------


def _audit_item(db: Session, spec: PricedSpec, organization_id: str, user: Any, item: Any, action: str, summary: str, request: Request | None) -> None:
    audit.record(
        db, organization_id=organization_id, actor=user, action=action, entity_type=spec.entity,
        entity_id=item.id, entity_label=f"{spec.label} · {getattr(item, spec.code_attr)}",
        summary=summary, request=request,
    )


def _append_revision(
    db: Session,
    spec: PricedSpec,
    organization_id: str,
    item: Any,
    rate: dict[str, Any],
    *,
    reason: str,
    user: Any,
    previous_rate: Decimal,
    previous_final: Decimal | None,
    revision_number: int,
) -> Any:
    revision = spec.revision_model(
        organization_id=organization_id,
        **{spec.revision_fk: item.id},
        revision_number=revision_number,
        effective_date=rate["effective_date"],
        unit_rate=rate["unit_rate"],
        previous_unit_rate=previous_rate,
        cost_uplift=rate["cost_uplift"],
        final_cost=rate["final_cost"],
        previous_final_cost=previous_final if spec.priced_uplift else None,
        currency=rate["currency"],
        uom=getattr(item, "uom", "") or "",
        po_number=rate["po_number"],
        reason=reason[:500],
        recorded_by=actor_name(user),
        created_at=datetime.now(timezone.utc),
    )
    db.add(revision)
    return revision


def _apply_rate_to_item(item: Any, rate: dict[str, Any], revision_number: int) -> None:
    item.unit_rate = rate["unit_rate"]
    item.cost_uplift = rate["cost_uplift"]
    item.final_cost = rate["final_cost"]
    item.currency = rate["currency"]
    item.po_number = rate["po_number"]
    item.effective_date = rate["effective_date"]
    item.current_revision_number = revision_number


def create_item(db: Session, spec: PricedSpec, organization_id: str, user: Any, payload: dict[str, Any], request: Request | None, *, via: str = "") -> Any:
    code = clean_value(payload.get(spec.code_attr)).upper()
    _ensure_code_free(db, spec, organization_id, code, None)
    payload = {**payload, spec.code_attr: code}
    values = _master_values(db, spec, organization_id, payload, existing=None)
    rate = _rate_values(db, organization_id, spec, payload)
    _check_duplicates(db, spec, organization_id, values, rate, None)
    item = spec.model(organization_id=organization_id, **values)
    _apply_rate_to_item(item, rate, 1)
    db.add(item)
    db.flush()
    _append_revision(
        db, spec, organization_id, item, rate, reason="Initial rate", user=user,
        previous_rate=Decimal("0"), previous_final=None, revision_number=1,
    )
    suffix = f" {via}" if via else ""
    _audit_item(db, spec, organization_id, user, item, "create",
                f"Created {spec.item_type.lower()} {code} — {values[spec.name_attr]}{suffix}", request)
    return item


def update_item(db: Session, spec: PricedSpec, organization_id: str, user: Any, item: Any, payload: dict[str, Any], request: Request | None, *, via: str = "") -> Any:
    merged: dict[str, Any] = {
        spec.code_attr: getattr(item, spec.code_attr),
        spec.name_attr: getattr(item, spec.name_attr),
        "description": item.description,
        "uom": getattr(item, "uom", ""),
        "remarks": getattr(item, "remarks", ""),
        "part_number": getattr(item, "part_number", ""),
        "model_no": getattr(item, "model_no", ""),
        "size": getattr(item, "size", ""),
        "iadc_code": getattr(item, "iadc_code", ""),
        "serial_number": getattr(item, "serial_number", ""),
    }
    for choice in spec.choices:
        merged[choice.attr] = getattr(item, choice.attr)
    for option in spec.options:
        merged[option.attr] = getattr(item, option.attr)
    merged.update(payload)

    values = _master_values(db, spec, organization_id, merged, existing=item)
    _ensure_code_free(db, spec, organization_id, values[spec.code_attr], item.id)
    rate = {
        "unit_rate": item.unit_rate,
        "cost_uplift": item.cost_uplift,
        "final_cost": item.final_cost,
    }
    _check_duplicates(db, spec, organization_id, values, rate, item.id)
    changed = [attr for attr, value in values.items() if getattr(item, attr, None) != value]
    if not changed:
        return item
    for attr in changed:
        setattr(item, attr, values[attr])
    labels = ", ".join(sorted(changed))
    suffix = f" {via}" if via else ""
    _audit_item(db, spec, organization_id, user, item, "update",
                f"Updated {spec.item_type.lower()} {values[spec.code_attr]}: {labels}{suffix}", request)
    return item


def revise_item(db: Session, spec: PricedSpec, organization_id: str, user: Any, item: Any, payload: dict[str, Any], request: Request | None, *, reason: str | None = None, via: str = "") -> Any:
    reason_text = clean_value(reason if reason is not None else payload.get("reason"))
    if len(reason_text) < 3:
        raise CatalogueError("Give a reason for the price change (at least 3 characters)")
    rate = _rate_values(db, organization_id, spec, payload)
    latest = _latest_revision(db, spec, item.id)
    if latest is not None and rate["effective_date"] < latest.effective_date:
        raise CatalogueError(
            f"Effective date cannot be earlier than the current rate's date ({latest.effective_date.strftime('%d/%m/%Y')})"
        )
    unchanged = (
        q4(item.unit_rate) == rate["unit_rate"]
        and (not spec.priced_uplift or q4(item.cost_uplift or 0) == rate["cost_uplift"])
        and item.currency == rate["currency"]
        and item.po_number == rate["po_number"]
    )
    if unchanged:
        raise CatalogueError("Nothing changed: the rate, uplift, currency and PO number match the current revision")

    previous_rate = item.unit_rate
    previous_final = item.final_cost
    number = max(item.current_revision_number, latest.revision_number if latest else 0) + 1
    _apply_rate_to_item(item, rate, number)
    _append_revision(
        db, spec, organization_id, item, rate, reason=reason_text, user=user,
        previous_rate=previous_rate, previous_final=previous_final, revision_number=number,
    )
    code = getattr(item, spec.code_attr)
    if spec.priced_uplift:
        detail = f"rate {previous_rate} → {rate['unit_rate']} {rate['currency']}, uplift {rate['cost_uplift']}%, final {rate['final_cost']}"
    else:
        detail = f"price {previous_rate} → {rate['unit_rate']} {rate['currency']}"
    suffix = f" {via}" if via else ""
    _audit_item(db, spec, organization_id, user, item, "revise_rate",
                f"Revised {code} (revision {number}, effective {rate['effective_date'].isoformat()}): {detail}. Reason: {reason_text}{suffix}",
                request)
    return item


def soft_delete_item(db: Session, spec: PricedSpec, organization_id: str, user: Any, item: Any, request: Request | None, *, bulk: bool = False) -> None:
    if item.is_deleted:
        raise CatalogueError(f"{getattr(item, spec.code_attr)} is already in Deleted Entries", 409)
    item.is_deleted = True
    item.deleted_at = datetime.now(timezone.utc)
    suffix = " (bulk action)" if bulk else ""
    _audit_item(db, spec, organization_id, user, item, "soft_delete",
                f"Moved {spec.item_type.lower()} {getattr(item, spec.code_attr)} to deleted entries{suffix}", request)


def restore_item(db: Session, spec: PricedSpec, organization_id: str, user: Any, item: Any, request: Request | None, *, bulk: bool = False) -> None:
    if not item.is_deleted:
        raise CatalogueError("Only a deleted record can be restored", 409)
    for option in spec.options:
        value = getattr(item, option.attr)
        target = db.get(CatalogueOption, value) if value else None
        if target is not None and target.is_deleted:
            raise CatalogueError(
                f"Restore '{target.value}' in {list_label(option.list_key)} before restoring this record", 409
            )
    values = {
        spec.name_attr: getattr(item, spec.name_attr),
        "description": item.description,
        "manufacturer_id": getattr(item, "manufacturer_id", None),
    }
    if spec.unique_text_attr:
        values[spec.unique_text_attr] = getattr(item, spec.unique_text_attr)
    _check_duplicates(
        db, spec, organization_id, values,
        {"unit_rate": item.unit_rate, "cost_uplift": item.cost_uplift},
        item.id,
    )
    item.is_deleted = False
    item.deleted_at = None
    suffix = " (bulk action)" if bulk else ""
    _audit_item(db, spec, organization_id, user, item, "restore",
                f"Restored {spec.item_type.lower()} {getattr(item, spec.code_attr)}{suffix}", request)


def purge_item(db: Session, spec: PricedSpec, organization_id: str, user: Any, item: Any, request: Request | None, *, bulk: bool = False) -> None:
    if not item.is_deleted:
        raise CatalogueError("Only a deleted record can be permanently deleted", 409)
    code = getattr(item, spec.code_attr)
    suffix = " (bulk action)" if bulk else ""
    _audit_item(db, spec, organization_id, user, item, "permanent_delete",
                f"Permanently deleted {spec.item_type.lower()} {code} and its rate history{suffix}", request)
    db.delete(item)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _canonical_row(spec: PricedSpec, row: dict[str, Any]) -> dict[str, Any]:
    """Map spreadsheet headers (any casing, spaces or symbols) onto canonical field names."""
    normalized = {normalize_header(key): value for key, value in row.items()}
    canonical: dict[str, Any] = {}

    def first(*names: str) -> Any:
        for name in names:
            value = normalized.get(name)
            if value not in (None, ""):
                return value
        return None

    canonical[spec.code_attr] = first(spec.code_attr, *spec.import_aliases.get(spec.code_attr, ()))
    canonical[spec.name_attr] = first(spec.name_attr, *spec.import_aliases.get(spec.name_attr, ()))
    canonical["description"] = first("description", "desc", *spec.import_aliases.get("description", ()))
    canonical["remarks"] = first("remarks", "notes", *spec.import_aliases.get("remarks", ()))
    for text in spec.texts:
        canonical[text.attr] = first(text.attr, *spec.import_aliases.get(text.attr, ()))
    for choice in spec.choices:
        canonical[choice.attr] = first(choice.attr, *spec.import_aliases.get(choice.attr, ()))
    for option in spec.options:
        canonical[option.header] = first(option.header, *spec.import_aliases.get(option.header, ()))
    canonical["unit_rate"] = first("unit_rate", "rate", *spec.import_aliases.get("unit_rate", ()))
    canonical["cost_uplift"] = first("cost_uplift", "uplift", "uplift_pct", *spec.import_aliases.get("cost_uplift", ()))
    canonical["currency"] = first("currency", "currency_code", *spec.import_aliases.get("currency", ()))
    canonical["po_number"] = first("po_number", "po", *spec.import_aliases.get("po_number", ()))
    canonical["effective_date"] = first("effective_date", "date", *spec.import_aliases.get("effective_date", ()))
    canonical["reason"] = first("reason", *spec.import_aliases.get("reason", ()))
    return canonical


def _choice_value(choice: ChoiceField, raw: Any) -> str:
    text = clean_value(raw)
    for allowed in choice.choices:
        if allowed.casefold() == text.casefold():
            return allowed
    raise CatalogueError(f"{choice.label} must be one of: {', '.join(choice.choices)} (got '{raw}')")


def _import_one(db: Session, spec: PricedSpec, organization_id: str, user: Any, row: dict[str, Any], request: Request | None, created: list[str], seen: set[str]) -> str:
    canonical = _canonical_row(spec, row)
    code = clean_value(canonical.get(spec.code_attr)).upper()
    if not code:
        raise CatalogueError(f"{spec.code_label} is required")
    if code in seen:
        raise CatalogueError(f"{code} appears more than once in this file")
    seen.add(code)

    existing = db.scalar(select(spec.model).where(
        spec.model.organization_id == organization_id,
        getattr(spec.model, spec.code_attr) == code,
    ))
    payload: dict[str, Any] = {
        spec.code_attr: code,
        spec.name_attr: canonical.get(spec.name_attr),
        "description": canonical.get("description") or "",
        "remarks": canonical.get("remarks") or "",
    }
    for text in spec.texts:
        payload[text.attr] = canonical.get(text.attr) or ""
    for choice in spec.choices:
        payload[choice.attr] = _choice_value(choice, canonical.get(choice.attr)) if canonical.get(choice.attr) else None
    for option in spec.options:
        name = clean_value(canonical.get(option.header))
        if not name:
            if existing is not None:
                # Blank cell on an existing record keeps its current value.
                payload[option.attr] = None
                continue
            if option.required:
                raise CatalogueError(f"{option.label} is required")
            payload[option.attr] = None
            continue
        parent_id = payload.get(option.parent_attr) if option.parent_attr else None
        payload[option.attr] = resolve_option_by_name(db, organization_id, option.list_key, name, parent_id, created)

    effective = parse_date(canonical.get("effective_date"))
    rate_text = canonical.get("unit_rate")
    rate_value = parse_decimal(rate_text, "Rate", allow_blank=True)
    uplift_value = parse_decimal(canonical.get("cost_uplift"), "Uplift %", allow_blank=True) if spec.priced_uplift else None
    currency_text = canonical.get("currency")
    po = clean_value(canonical.get("po_number"))
    reason = clean_value(canonical.get("reason")) or "Imported from file"

    if existing is None:
        if rate_value is None:
            raise CatalogueError("Rate is required for a new record")
        create_payload = {
            **payload,
            "unit_rate": rate_value,
            "currency": currency_text,
            "po_number": po,
            "effective_date": effective,
        }
        if spec.priced_uplift:
            create_payload["cost_uplift"] = uplift_value if uplift_value is not None else DEFAULT_UPLIFT
        if spec.create_model is None:
            raise CatalogueError("This module does not support import")
        try:
            validated = spec.create_model.model_validate(create_payload)
        except ValidationError as error:
            raise CatalogueError(_validation_message(error)) from error
        create_item(db, spec, organization_id, user, validated.model_dump(), request, via="from import")
        return "created"

    was_deleted = existing.is_deleted
    # On import, a blank cell keeps the current value of an existing record.
    master_payload = {k: v for k, v in payload.items() if k != spec.code_attr and v not in (None, "")}
    update_item(db, spec, organization_id, user, existing, master_payload, request, via="from import")
    if was_deleted:
        restore_item(db, spec, organization_id, user, existing, request)

    if rate_value is None and uplift_value is None and not currency_text and not po and effective is None:
        return "restored" if was_deleted else "updated"
    rate_candidate = {
        "unit_rate": rate_value if rate_value is not None else existing.unit_rate,
        "cost_uplift": (uplift_value if uplift_value is not None else existing.cost_uplift) if spec.priced_uplift else None,
        "currency": currency_text or existing.currency,
        "po_number": po or existing.po_number,
        "effective_date": effective or today(),
    }
    rate = _rate_values(db, organization_id, spec, rate_candidate)
    changed = (
        rate["unit_rate"] != q4(existing.unit_rate)
        or (spec.priced_uplift and rate["cost_uplift"] != q4(existing.cost_uplift or 0))
        or rate["currency"] != existing.currency
        or rate["po_number"] != existing.po_number
    )
    if changed:
        revise_item(db, spec, organization_id, user, existing, rate_candidate, request, reason=reason, via="from import")
    return "restored" if was_deleted else "updated"


def import_rows(db: Session, spec: PricedSpec, organization_id: str, user: Any, rows: list[dict[str, Any]], request: Request | None) -> tuple[int, list[str], list[str]]:
    """Import previewed rows. Returns (imported_count, errors, created_list_values)."""
    imported = 0
    errors: list[str] = []
    created: list[str] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=1):
        try:
            with db.begin_nested():
                _import_one(db, spec, organization_id, user, row, request, created, seen)
            imported += 1
        except CatalogueError as error:
            errors.append(f"Row {row_number}: {error.message}")
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_message(error)}")
        except IntegrityError:
            errors.append(f"Row {row_number}: conflicts with an existing record (check codes and serial numbers)")
    audit.record(
        db, organization_id=organization_id, actor=user, action="import", entity_type=spec.entity,
        entity_label=spec.label,
        summary=f"Imported {imported} {spec.label.lower()} with {len(errors)} validation errors"
        + (f"; added dropdown values: {', '.join(created[:20])}" if created else ""),
        request=request,
    )
    return imported, errors, created


# ---------------------------------------------------------------------------
# Fixed records (fuel)
# ---------------------------------------------------------------------------


def seed_fixed_records(db: Session, organization_id: str, *, model: type, code_attr: str, name_attr: str, seeds: tuple[tuple[str, str], ...], uom: str) -> int:
    """Create missing fixed rows (for example the four fuel types) for a workspace."""
    added = 0
    for code, name in seeds:
        exists = db.scalar(select(model.id).where(model.organization_id == organization_id, getattr(model, code_attr) == code))
        if exists is None:
            db.add(model(organization_id=organization_id, **{code_attr: code, name_attr: name, "uom": uom}))
            added += 1
    if added:
        db.commit()
    return added
