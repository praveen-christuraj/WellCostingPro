"""AFE register and cost estimate: validation, persistence and output mapping.

The pure pricing rules live in ``app.domain.afe_costing``. This module turns a
request (or stored rows) into engine inputs, validates every reference against
the tenant's master data and the well configuration, and maps engine results to
API outputs.

Persistence rules:

* A saved estimate replaces all of its lines in one transaction. The AFE row is
  locked (``SELECT ... FOR UPDATE``) and saves are serialised inside the process,
  so two quick saves cannot interleave and duplicate lines.
* Captured rates and currencies are snapshots taken at save time. Reads use the
  stored snapshots. Preview prices the request against live master data.
* Preview is a pure computation: it never writes.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain import afe_costing as engine
from app.models import AuditLog, DailyCostBaseline, DailyCostEntry, Rig, Well, WellSection
from app.models.afe import (
    AFE_STATUSES,
    Afe,
    AfeConsumableLine,
    AfeServiceCharge,
    AfeServiceLine,
    AfeServiceRate,
    AfeExchangeRate,
    AfeServiceSectionRate,
    AfeTangibleLine,
)
from app.models.catalogue import CatalogueOption, DrillBit, Tangible
from app.models.master_data import HoleSection, Phase
from app.models.service_master import Service
from app.schemas.afe import (
    AfeEstimateOut,
    CurrencySetupOut,
    ExchangeRateOut,
    AfeIDs,
    AfeOut,
    AfeOverview,
    AfeOverviewStatus,
    AfeOverviewWell,
    AfeRecentActivity,
    AfeReference,
    AfeReferenceDrillBit,
    AfeReferenceRig,
    AfeReferenceService,
    AfeReferenceTangible,
    AfeReferenceWell,
    AfeCreate,
    AfeUpdate,
    ComponentOut,
    ConsumableLineOut,
    CurrencyTotalOut,
    EstimateIn,
    EstimateSummaryOut,
    ServiceLineOut,
    ScopePhaseOut,
    ScopeSectionOut,
    SectionSummaryOut,
    TangibleLineOut,
    WellScopeOut,
)
from app.services import audit
from app.models.entities import User
from app.services.catalogue import options_by_id

AFE_STATUS_LABELS = {
    "draft": "Draft",
    "submitted": "Submitted",
    "review": "Review",
    "approval": "Approval",
}
AUDIT_TYPES = ("afe", "afe_estimate", "afe_export")
MAX_ERRORS = 50

# Status moves: (current status, action) -> next status.
TRANSITIONS: dict[tuple[str, str], str] = {
    ("draft", "submit"): "submitted",
    ("submitted", "review"): "review",
    ("review", "approve"): "approval",
    ("submitted", "reopen"): "draft",
    ("review", "reopen"): "draft",
    ("approval", "reopen"): "draft",
}
ACTION_PERMISSION = {
    "submit": "afe:submit",
    "review": "afe:review",
    "approve": "afe:approve",
    "reopen": "afe:reopen",
}
ACTION_LABELS = {"submit": "submitted", "review": "moved to review", "approve": "approved", "reopen": "reopened as draft"}
REMARKS_REQUIRED_FOR = {"approve", "reopen"}

# A process-level lock serialises estimate saves. Combined with the row lock below it
# also protects single-process SQLite deployments where row locks do not exist.
_SAVE_LOCK = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This change conflicts with an existing AFE or a dependent workspace record",
        ) from error


def _record_audit(
    db: Session,
    *,
    user: User,
    action: str,
    entity_type: str,
    record_id: str | None,
    entity_label: str,
    summary: str,
    request: Request | None,
) -> None:
    audit.record(
        db,
        organization_id=user.organization_id,
        actor=user,
        action=action,
        entity_type=entity_type,
        entity_id=record_id,
        entity_label=entity_label,
        summary=summary,
        request=request,
    )


def _label(code: str, name: str) -> str:
    return " — ".join(part for part in (code, name) if part) or code or name


def _money_text(value: Decimal) -> str:
    return f"{engine.money(value):,.2f}"


def _actor_name(user: User) -> str:
    return user.full_name or user.email


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def afe_or_404(db: Session, afe_id: str, organization_id: str, *, lock: bool = False) -> Afe:
    statement = select(Afe).where(Afe.id == afe_id, Afe.organization_id == organization_id)
    if lock:
        statement = statement.with_for_update()
    afe = db.scalar(statement.execution_options(populate_existing=True))
    if afe is None:
        raise HTTPException(status_code=404, detail="AFE not found in this workspace")
    return afe


def _wells_by_id(db: Session, organization_id: str, well_ids: Iterable[str]) -> dict[str, Well]:
    ids = [well_id for well_id in set(well_ids) if well_id]
    if not ids:
        return {}
    rows = db.scalars(
        select(Well)
        .options(joinedload(Well.rig), selectinload(Well.sections).selectinload(WellSection.phases))
        .where(Well.organization_id == organization_id, Well.id.in_(ids))
    ).unique().all()
    return {well.id: well for well in rows}


def _scope_for_well(well: Well | None, configuration_scope: str = "drilling") -> engine.WellScope:
    if well is None:
        return engine.WellScope()
    sections: list[engine.SectionScope] = []
    for section in sorted(well.sections_for_scope(configuration_scope), key=lambda row: row.sort_order):
        phases = tuple(
            engine.PhaseScope(
                phase_id=row.phase_id,
                label=_label(row.phase.phase_code, row.phase.phase_name),
                days=Decimal(row.days),
            )
            for row in sorted(section.phases, key=lambda row: row.sort_order)
        )
        sections.append(
            engine.SectionScope(
                section_id=section.hole_section_id,
                label=_label(section.hole_section.section_code, section.hole_section.section_name),
                phases=phases,
            )
        )
    return engine.WellScope(sections=tuple(sections))


@dataclass
class Lookups:
    services: dict[str, Service] = field(default_factory=dict)
    drill_bits: dict[str, DrillBit] = field(default_factory=dict)
    tangibles: dict[str, Tangible] = field(default_factory=dict)
    options: dict[str, CatalogueOption] = field(default_factory=dict)
    hole_sections: dict[str, HoleSection] = field(default_factory=dict)
    phases: dict[str, Phase] = field(default_factory=dict)

    def option_name(self, option_id: str | None) -> str:
        option = self.options.get(option_id or "")
        return option.value if option is not None else ""


def _load_lookups(
    db: Session,
    organization_id: str,
    *,
    service_ids: Iterable[str] = (),
    drill_bit_ids: Iterable[str] = (),
    tangible_ids: Iterable[str] = (),
    hole_section_ids: Iterable[str] = (),
    phase_ids: Iterable[str] = (),
) -> Lookups:
    """Batch-load master records by id. Inactive records are loaded too, so callers can explain them."""

    def fetch(model: Any, ids: Iterable[str]) -> dict[str, Any]:
        wanted = [value for value in set(ids) if value]
        if not wanted:
            return {}
        return {
            row.id: row
            for row in db.scalars(select(model).where(model.organization_id == organization_id, model.id.in_(wanted)))
        }

    service_rows = [value for value in set(service_ids) if value]
    services: dict[str, Service] = {}
    if service_rows:
        services = {
            row.id: row
            for row in db.scalars(
                select(Service)
                .options(joinedload(Service.vendor))
                .where(Service.organization_id == organization_id, Service.id.in_(service_rows))
            ).unique()
        }
    return Lookups(
        services=services,
        drill_bits=fetch(DrillBit, drill_bit_ids),
        tangibles=fetch(Tangible, tangible_ids),
        options=options_by_id(db, organization_id),
        hole_sections=fetch(HoleSection, hole_section_ids),
        phases=fetch(Phase, phase_ids),
    )


def _lookups_for_afes(db: Session, organization_id: str, afes: Sequence[Afe]) -> Lookups:
    return _load_lookups(
        db,
        organization_id,
        service_ids=[line.service_id for afe in afes for line in afe.service_lines],
        drill_bit_ids=[line.drill_bit_id or "" for afe in afes for line in afe.consumable_lines],
        tangible_ids=[line.tangible_id for afe in afes for line in afe.tangible_lines],
        hole_section_ids=[
            value
            for afe in afes
            for value in (
                *(line.hole_section_id or "" for line in afe.service_lines),
                *(line.hole_section_id for line in afe.consumable_lines),
                *(row.hole_section_id for line in afe.service_lines for row in line.section_rates),
            )
        ],
        phase_ids=[
            value
            for afe in afes
            for value in (
                *(line.phase_id or "" for line in afe.service_lines),
                *(line.phase_id or "" for line in afe.consumable_lines),
                *(row.phase_id or "" for line in afe.service_lines for row in line.section_rates),
            )
        ],
    )


def _section_label(scope: engine.WellScope, lookups: Lookups, section_id: str | None) -> str:
    if not section_id:
        return ""
    section = scope.section(section_id)
    if section is not None:
        return section.label
    record = lookups.hole_sections.get(section_id)
    return f"{_label(record.section_code, record.section_name)} (not in well plan)" if record else "Removed section"


def _phase_label(scope: engine.WellScope, lookups: Lookups, section_id: str | None, phase_id: str | None) -> str:
    if not phase_id:
        return ""
    section = scope.section(section_id)
    phase = section.phase(phase_id) if section else None
    if phase is not None:
        return phase.label
    record = lookups.phases.get(phase_id)
    return f"{_label(record.phase_code, record.phase_name)} (not in well plan)" if record else "Removed phase"


# ---------------------------------------------------------------------------
# Resolved line models (validated request or stored rows, ready to price and persist)
# ---------------------------------------------------------------------------


@dataclass
class RService:
    key: str
    id: str | None
    service: Service | None
    basis: str
    section_id: str | None
    phase_id: str | None
    currency: str
    service_amount: Decimal
    remarks: str
    rates: tuple[tuple[str, Decimal], ...]
    charges: tuple[tuple[str, Decimal, str], ...]
    section_rates: tuple[tuple[str, str | None, Decimal], ...]
    line: engine.ServiceLine


@dataclass
class RConsumable:
    key: str
    id: str | None
    category: str
    section_id: str
    phase_id: str | None
    drill_bit: DrillBit | None
    quantity: Decimal
    captured_rate: Decimal
    override_rate: Decimal | None
    estimated_amount: Decimal | None
    currency: str
    remarks: str
    line: engine.ConsumableLine


@dataclass
class RTangible:
    key: str
    id: str | None
    tangible: Tangible | None
    quantity: Decimal
    captured_rate: Decimal
    override_rate: Decimal | None
    currency: str
    uom: str
    remarks: str
    line: engine.TangibleLine


@dataclass
class Resolved:
    services: list[RService] = field(default_factory=list)
    consumables: list[RConsumable] = field(default_factory=list)
    tangibles: list[RTangible] = field(default_factory=list)


def _captured_rate(record: Tangible | DrillBit) -> Decimal:
    """Uplift-priced items use the final cost when one is set, otherwise the PO unit rate."""

    return Decimal(record.final_cost) if record.final_cost is not None else Decimal(record.unit_rate)


def _service_label(service: Service | None) -> str:
    return _label(service.service_code, service.service_name) if service else "Removed service"


def _stored_resolved(afe: Afe, lookups: Lookups) -> Resolved:
    resolved = Resolved()
    for row in afe.service_lines:
        service = lookups.services.get(row.service_id)
        rates = tuple((rate.charge_category, Decimal(rate.unit_rate)) for rate in row.rates)
        charges = tuple(
            (charge.charge_category, Decimal(charge.quantity), charge.quantity_unit) for charge in row.charges
        )
        section_rates = tuple(
            (entry.hole_section_id, entry.phase_id, Decimal(entry.amount)) for entry in row.section_rates
        )
        resolved.services.append(
            RService(
                key=row.id,
                id=row.id,
                service=service,
                basis=row.charging_basis,
                section_id=row.hole_section_id,
                phase_id=row.phase_id,
                currency=row.currency,
                service_amount=Decimal(row.service_amount),
                remarks=row.remarks,
                rates=rates,
                charges=charges,
                section_rates=section_rates,
                line=engine.ServiceLine(
                    key=row.id,
                    label=_service_label(service),
                    charging_basis=row.charging_basis,
                    currency=row.currency,
                    section_id=row.hole_section_id,
                    phase_id=row.phase_id,
                    service_amount=Decimal(row.service_amount),
                    rates=tuple(engine.RateInput(category, rate) for category, rate in rates),
                    charges=tuple(engine.ChargeInput(category, qty, unit) for category, qty, unit in charges),
                    section_rates=tuple(
                        engine.SectionRateInput(section_id, phase_id, amount)
                        for section_id, phase_id, amount in section_rates
                    ),
                ),
            )
        )
    for row in afe.consumable_lines:
        drill_bit = lookups.drill_bits.get(row.drill_bit_id or "")
        label = _label(drill_bit.bit_code, drill_bit.bit_name) if drill_bit else "Drill bit removed from master data"
        if row.category != engine.CONSUMABLE_DRILL_BITS:
            label = row.category
        resolved.consumables.append(
            RConsumable(
                key=row.id,
                id=row.id,
                category=row.category,
                section_id=row.hole_section_id,
                phase_id=row.phase_id,
                drill_bit=drill_bit,
                quantity=Decimal(row.quantity),
                captured_rate=Decimal(row.captured_rate),
                override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                estimated_amount=Decimal(row.estimated_amount) if row.estimated_amount is not None else None,
                currency=row.currency,
                remarks=row.remarks,
                line=engine.ConsumableLine(
                    key=row.id,
                    label=label,
                    category=row.category,
                    section_id=row.hole_section_id,
                    phase_id=row.phase_id,
                    quantity=Decimal(row.quantity),
                    captured_rate=Decimal(row.captured_rate),
                    override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                    estimated_amount=Decimal(row.estimated_amount) if row.estimated_amount is not None else None,
                    currency=row.currency,
                ),
            )
        )
    for row in afe.tangible_lines:
        tangible = lookups.tangibles.get(row.tangible_id)
        label = _label(tangible.tangible_code, tangible.tangible_name) if tangible else "Tangible removed from master data"
        resolved.tangibles.append(
            RTangible(
                key=row.id,
                id=row.id,
                tangible=tangible,
                quantity=Decimal(row.quantity),
                captured_rate=Decimal(row.captured_rate),
                override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                currency=row.currency,
                uom=row.uom,
                remarks=row.remarks,
                line=engine.TangibleLine(
                    key=row.id,
                    label=label,
                    quantity=Decimal(row.quantity),
                    captured_rate=Decimal(row.captured_rate),
                    override_rate=Decimal(row.override_rate) if row.override_rate is not None else None,
                    currency=row.currency,
                    uom=row.uom,
                ),
            )
        )
    return resolved


def _validate_request(
    db: Session,
    organization_id: str,
    scope: engine.WellScope,
    payload: EstimateIn,
) -> Resolved:
    """Validate every line against master data and the well configuration; collect all errors."""

    lookups = _load_lookups(
        db,
        organization_id,
        service_ids=[line.service_id for line in payload.services],
        drill_bit_ids=[line.drill_bit_id or "" for line in payload.consumables],
        tangible_ids=[line.tangible_id for line in payload.tangibles],
        hole_section_ids=[
            value
            for value in (
                *(line.hole_section_id or "" for line in payload.services),
                *(line.hole_section_id for line in payload.consumables),
                *(entry.hole_section_id for line in payload.services for entry in line.section_rates),
            )
        ],
        phase_ids=[
            value
            for value in (
                *(line.phase_id or "" for line in payload.services),
                *(line.phase_id or "" for line in payload.consumables),
                *(entry.phase_id or "" for line in payload.services for entry in line.section_rates),
            )
        ],
    )
    errors: list[str] = []
    resolved = Resolved()

    def section_ok(section_id: str | None, phase_id: str | None, where: str) -> bool:
        section = scope.section(section_id)
        if section is None:
            errors.append(f"{where}: the section is not in this well's configuration. Pick a section from the well plan.")
            return False
        if phase_id is not None and section.phase(phase_id) is None:
            errors.append(f"{where}: the phase is not planned under {section.label} in the well plan.")
            return False
        return True

    for index, line in enumerate(payload.services, start=1):
        where = f"Service line {index}"
        service = lookups.services.get(line.service_id)
        if service is None or service.organization_id != organization_id:
            errors.append(f"{where}: select a service from Master Data.")
            continue
        if service.is_deleted:
            errors.append(f"{where}: {service.service_code} is inactive in Master Data. Select an active service.")
            continue
        where = f"{where} ({service.service_code})"
        basis = line.charging_basis
        if not line.currency:
            errors.append(f"{where}: enter the currency for this service.")
        if line.phase_id and not line.hole_section_id:
            errors.append(f"{where}: a phase needs a section first.")
        if basis == engine.BASIS_DAY_RATE:
            if line.hole_section_id or line.phase_id:
                section_ok(line.hole_section_id, line.phase_id, where)
            if line.section_rates:
                errors.append(f"{where}: section rates apply to Per Section Rate services only.")
            if line.service_amount:
                errors.append(f"{where}: the per-service price applies to Per Service Rate services only.")
            seen_rates: set[str] = set()
            for rate in line.rates:
                if rate.category in seen_rates:
                    errors.append(f"{where}: {rate.category} has more than one unit rate.")
                seen_rates.add(rate.category)
            for charge in line.charges:
                if charge.category in engine.ONE_TIME_CATEGORIES:
                    errors.append(
                        f"{where}: {charge.category} is a one-time charge. Enter its unit rate, not days."
                    )
                if charge.quantity_unit == engine.UNIT_HOURS and charge.quantity > engine.HOURS_PER_DAY:
                    errors.append(f"{where}: {charge.category} hours cannot exceed 24 in one entry. Enter days instead.")
            rates = tuple((rate.category, Decimal(rate.unit_rate)) for rate in line.rates)
            charges = tuple((charge.category, Decimal(charge.quantity), charge.quantity_unit) for charge in line.charges)
            section_rates: tuple[tuple[str, str | None, Decimal], ...] = ()
            scope_section_id, scope_phase_id = line.hole_section_id, line.phase_id
            service_amount = Decimal("0")
        elif basis == engine.BASIS_PER_SERVICE:
            if not line.hole_section_id:
                errors.append(f"{where}: a Per Service Rate applies to a section and phase. Select a section.")
            else:
                section_ok(line.hole_section_id, line.phase_id, where)
            if line.service_amount <= 0:
                errors.append(f"{where}: enter the per-service price.")
            if line.rates or line.charges or line.section_rates:
                errors.append(f"{where}: rate cards apply to Day Rate services only.")
            rates, charges, section_rates = (), (), ()
            scope_section_id, scope_phase_id = line.hole_section_id, line.phase_id
            service_amount = Decimal(line.service_amount)
        else:  # Per Section Rate
            if not line.section_rates:
                errors.append(f"{where}: add at least one section rate.")
            if line.hole_section_id or line.phase_id:
                errors.append(f"{where}: a Per Section Rate is entered per section below, not on the service line.")
            if line.rates or line.charges or line.service_amount:
                errors.append(f"{where}: rate cards and per-service prices do not apply to Per Section Rate services.")
            seen_scopes: set[tuple[str, str | None]] = set()
            entries: list[tuple[str, str | None, Decimal]] = []
            for entry in line.section_rates:
                key = (entry.hole_section_id, entry.phase_id or None)
                if key in seen_scopes:
                    errors.append(f"{where}: a section and phase can have only one section rate.")
                seen_scopes.add(key)
                if section_ok(entry.hole_section_id, entry.phase_id or None, where):
                    entries.append((entry.hole_section_id, entry.phase_id or None, Decimal(entry.amount)))
            rates, charges = (), ()
            section_rates = tuple(entries)
            scope_section_id, scope_phase_id = None, None
            service_amount = Decimal("0")

        resolved.services.append(
            RService(
                key=line.client_key or str(uuid.uuid4()),
                id=None,
                service=service,
                basis=basis,
                section_id=scope_section_id,
                phase_id=scope_phase_id,
                currency=line.currency,
                service_amount=service_amount,
                remarks=line.remarks,
                rates=rates,
                charges=charges,
                section_rates=section_rates,
                line=engine.ServiceLine(
                    key=line.client_key or "",
                    label=_label(service.service_code, service.service_name),
                    charging_basis=basis,
                    currency=line.currency,
                    section_id=scope_section_id,
                    phase_id=scope_phase_id,
                    service_amount=service_amount,
                    rates=tuple(engine.RateInput(category, rate) for category, rate in rates),
                    charges=tuple(engine.ChargeInput(category, qty, unit) for category, qty, unit in charges),
                    section_rates=tuple(
                        engine.SectionRateInput(section_id, phase_id, amount)
                        for section_id, phase_id, amount in section_rates
                    ),
                ),
            )
        )

    for index, line in enumerate(payload.consumables, start=1):
        where = f"Consumable line {index}"
        section_ok(line.hole_section_id, line.phase_id, where)
        if line.category == engine.CONSUMABLE_DRILL_BITS:
            drill_bit = lookups.drill_bits.get(line.drill_bit_id or "")
            if drill_bit is None or drill_bit.organization_id != organization_id:
                errors.append(f"{where}: select a drill bit from Master Data.")
                continue
            if drill_bit.is_deleted:
                errors.append(f"{where}: {drill_bit.bit_code} is inactive in Master Data. Select an active drill bit.")
                continue
            if line.quantity <= 0:
                errors.append(f"{where}: enter the number of bits.")
            if line.estimated_amount is not None:
                errors.append(f"{where}: drill bits are priced per bit; remove the estimated amount.")
            where = f"{where} ({drill_bit.bit_code})"
            captured = _captured_rate(drill_bit)
            currency = drill_bit.currency
            label = _label(drill_bit.bit_code, drill_bit.bit_name)
            estimated: Decimal | None = None
            override = Decimal(line.override_rate) if line.override_rate is not None else None
            quantity = Decimal(line.quantity)
            record: DrillBit | None = drill_bit
        else:
            if line.drill_bit_id:
                errors.append(f"{where}: only Drill Bits take a drill bit selection.")
            if line.estimated_amount is None:
                errors.append(f"{where}: enter the estimated amount for {line.category}.")
            if not line.currency:
                errors.append(f"{where}: enter the currency for {line.category}.")
            if line.override_rate is not None:
                errors.append(f"{where}: override rates apply to drill bits and tangibles only.")
            captured = Decimal("0")
            currency = line.currency
            label = line.category
            estimated = Decimal(line.estimated_amount) if line.estimated_amount is not None else Decimal("0")
            override = None
            quantity = Decimal("1")
            record = None
        resolved.consumables.append(
            RConsumable(
                key=line.client_key or str(uuid.uuid4()),
                id=None,
                category=line.category,
                section_id=line.hole_section_id,
                phase_id=line.phase_id,
                drill_bit=record,
                quantity=quantity,
                captured_rate=captured,
                override_rate=override,
                estimated_amount=estimated,
                currency=currency,
                remarks=line.remarks,
                line=engine.ConsumableLine(
                    key=line.client_key or "",
                    label=label,
                    category=line.category,
                    section_id=line.hole_section_id,
                    phase_id=line.phase_id,
                    quantity=quantity,
                    captured_rate=captured,
                    override_rate=override,
                    estimated_amount=estimated,
                    currency=currency,
                ),
            )
        )

    for index, line in enumerate(payload.tangibles, start=1):
        where = f"Tangible line {index}"
        tangible = lookups.tangibles.get(line.tangible_id)
        if tangible is None or tangible.organization_id != organization_id:
            errors.append(f"{where}: select a tangible from Master Data.")
            continue
        if tangible.is_deleted:
            errors.append(f"{where}: {tangible.tangible_code} is inactive in Master Data. Select an active tangible.")
            continue
        where = f"{where} ({tangible.tangible_code})"
        captured = _captured_rate(tangible)
        override = Decimal(line.override_rate) if line.override_rate is not None else None
        quantity = Decimal(line.quantity)
        resolved.tangibles.append(
            RTangible(
                key=line.client_key or str(uuid.uuid4()),
                id=None,
                tangible=tangible,
                quantity=quantity,
                captured_rate=captured,
                override_rate=override,
                currency=tangible.currency,
                uom=tangible.uom,
                remarks=line.remarks,
                line=engine.TangibleLine(
                    key=line.client_key or "",
                    label=_label(tangible.tangible_code, tangible.tangible_name),
                    quantity=quantity,
                    captured_rate=captured,
                    override_rate=override,
                    currency=tangible.currency,
                    uom=tangible.uom,
                ),
            )
        )

    if errors:
        raise HTTPException(status_code=422, detail=errors[:MAX_ERRORS])
    return resolved


# ---------------------------------------------------------------------------
# Output mapping
# ---------------------------------------------------------------------------


def _component_out(component: engine.Component, scope: engine.WellScope, lookups: Lookups) -> ComponentOut:
    return ComponentOut(
        group=component.group,
        category=component.category,
        description=component.description,
        amount=component.amount,
        section_id=component.section_id,
        section_label=_section_label(scope, lookups, component.section_id),
        phase_id=component.phase_id,
        phase_label=_phase_label(scope, lookups, component.section_id, component.phase_id),
        quantity=component.quantity,
        rate=component.rate,
        unit=component.unit,
    )


_CATEGORY_ORDER = {category: index for index, category in enumerate(engine.CHARGE_CATEGORIES)}


def _service_out(
    row: RService, result: engine.LineResult, scope: engine.WellScope, lookups: Lookups
) -> ServiceLineOut:
    service = row.service
    return ServiceLineOut(
        id=row.id,
        client_key=row.key,
        service_id=service.id if service else "",
        service_code=service.service_code if service else "",
        service_name=service.service_name if service else "Removed service",
        service_category=service.service_category if service else "",
        provider_type=service.provider_type if service else "",
        vendor_name=(service.vendor.vendor_name if service and service.vendor else ""),
        charging_basis=row.basis,
        hole_section_id=row.section_id,
        section_label=_section_label(scope, lookups, row.section_id),
        phase_id=row.phase_id,
        phase_label=_phase_label(scope, lookups, row.section_id, row.phase_id),
        currency=row.currency,
        service_amount=row.service_amount,
        remarks=row.remarks,
        rates=[
            {"category": category, "unit_rate": rate}
            for category, rate in sorted(row.rates, key=lambda item: _CATEGORY_ORDER.get(item[0], 99))
        ],
        charges=[
            {"category": category, "quantity": quantity, "quantity_unit": unit}
            for category, quantity, unit in sorted(row.charges, key=lambda item: _CATEGORY_ORDER.get(item[0], 99))
        ],
        section_rates=[
            {
                "hole_section_id": section_id,
                "section_label": _section_label(scope, lookups, section_id),
                "phase_id": phase_id,
                "phase_label": _phase_label(scope, lookups, section_id, phase_id),
                "amount": amount,
            }
            for section_id, phase_id, amount in row.section_rates
        ],
        amount=result.amount,
        warnings=list(result.warnings),
        components=[_component_out(component, scope, lookups) for component in result.components],
    )


def _consumable_out(
    row: RConsumable, result: engine.LineResult, scope: engine.WellScope, lookups: Lookups
) -> ConsumableLineOut:
    bit = row.drill_bit
    effective = engine.effective_rate(row.captured_rate, row.override_rate) if bit is not None else None
    return ConsumableLineOut(
        id=row.id,
        client_key=row.key,
        category=row.category,
        hole_section_id=row.section_id,
        section_label=_section_label(scope, lookups, row.section_id),
        phase_id=row.phase_id,
        phase_label=_phase_label(scope, lookups, row.section_id, row.phase_id),
        drill_bit_id=bit.id if bit else None,
        bit_code=bit.bit_code if bit else "",
        bit_name=bit.bit_name if bit else "",
        bit_type=lookups.option_name(bit.bit_type_id) if bit else "",
        manufacturer=lookups.option_name(bit.manufacturer_id) if bit else "",
        model_no=bit.model_no if bit else "",
        size=bit.size if bit else "",
        iadc_code=bit.iadc_code if bit else "",
        serial_number=bit.serial_number if bit else "",
        bit_description=bit.description if bit else "",
        quantity=row.quantity,
        captured_rate=row.captured_rate,
        override_rate=row.override_rate,
        effective_rate=effective,
        estimated_amount=row.estimated_amount,
        currency=row.currency,
        remarks=row.remarks,
        amount=result.amount,
        warnings=list(result.warnings),
        components=[_component_out(component, scope, lookups) for component in result.components],
    )


def _tangible_out(
    row: RTangible, result: engine.LineResult, scope: engine.WellScope, lookups: Lookups
) -> TangibleLineOut:
    tangible = row.tangible
    return TangibleLineOut(
        id=row.id,
        client_key=row.key,
        tangible_id=tangible.id if tangible else "",
        tangible_code=tangible.tangible_code if tangible else "",
        tangible_name=tangible.tangible_name if tangible else "Tangible removed from master data",
        tangible_scope=tangible.scope if tangible else "",
        category_name=lookups.option_name(tangible.category_id) if tangible else "",
        subcategory_name=lookups.option_name(tangible.subcategory_id) if tangible else "",
        manufacturer_name=lookups.option_name(tangible.manufacturer_id) if tangible else "",
        tangible_description=tangible.description if tangible else "",
        uom=row.uom,
        quantity=row.quantity,
        captured_rate=row.captured_rate,
        override_rate=row.override_rate,
        effective_rate=engine.effective_rate(row.captured_rate, row.override_rate),
        currency=row.currency,
        remarks=row.remarks,
        amount=result.amount,
        warnings=list(result.warnings),
        components=[_component_out(component, scope, lookups) for component in result.components],
    )


@dataclass
class Priced:
    result: engine.EstimateResult
    services: list[ServiceLineOut]
    consumables: list[ConsumableLineOut]
    tangibles: list[TangibleLineOut]
    summary: EstimateSummaryOut


def _currency_out(setup: engine.CurrencySetup) -> CurrencySetupOut:
    return CurrencySetupOut(
        standard_currency=setup.standard_currency,
        currencies=list(setup.currencies),
        multi_currency=setup.multi_currency,
        converted=setup.converted,
        standard_missing=setup.standard_missing,
        missing_rates=list(setup.missing_rates),
        exchange_rates=[ExchangeRateOut(currency_code=code, rate=rate) for code, rate in setup.exchange_rates],
    )


def _price(
    scope: engine.WellScope,
    resolved: Resolved,
    lookups: Lookups,
    standard_currency: str = "",
    exchange_rates: dict[str, Decimal] | None = None,
) -> Priced:
    result = engine.compile_estimate(
        scope,
        services=[row.line for row in resolved.services],
        consumables=[row.line for row in resolved.consumables],
        tangibles=[row.line for row in resolved.tangibles],
        standard_currency=standard_currency,
        exchange_rates=exchange_rates,
    )
    services = [
        _service_out(row, line, scope, lookups) for row, line in zip(resolved.services, result.services, strict=True)
    ]
    consumables = [
        _consumable_out(row, line, scope, lookups)
        for row, line in zip(resolved.consumables, result.consumables, strict=True)
    ]
    tangibles = [
        _tangible_out(row, line, scope, lookups) for row, line in zip(resolved.tangibles, result.tangibles, strict=True)
    ]
    summary = EstimateSummaryOut(
        services_total=result.services_total,
        consumables_total=result.consumables_total,
        tangibles_total=result.tangibles_total,
        total=result.total,
        totals_by_currency=[CurrencyTotalOut(currency=currency, amount=amount) for currency, amount in result.totals_by_currency],
        currency=_currency_out(result.currency),
        by_section=[
            SectionSummaryOut(
                hole_section_id=row.section_id,
                label=row.label,
                planned_days=row.planned_days,
                services=row.services,
                consumables=row.consumables,
                tangibles=row.tangibles,
                total=row.total,
            )
            for row in result.by_section
        ],
        warnings=list(result.warnings),
    )
    return Priced(result=result, services=services, consumables=consumables, tangibles=tangibles, summary=summary)


def _well_scope_out(well: Well, configuration_scope: str = "drilling") -> WellScopeOut:
    sections = sorted(well.sections_for_scope(configuration_scope), key=lambda row: row.sort_order)
    return WellScopeOut(
        scope=configuration_scope,
        well_id=well.id,
        well_code=well.well_code,
        well_name=well.well_name,
        well_location=well.well_location,
        block=well.block,
        objective=well.objective,
        rig_code=well.rig.rig_code if well.rig else "",
        rig_name=well.rig.rig_name if well.rig else "",
        depth_unit=well.scope_value(configuration_scope, "depth_unit"),
        status=well.scope_value(configuration_scope, "status"),
        config_status=well.scope_value(configuration_scope, "config_status"),
        total_depth=sections[-1].to_depth if sections else None,
        total_days=sum((phase.days for section in sections for phase in section.phases), Decimal("0")),
        sections=[
            ScopeSectionOut(
                hole_section_id=section.hole_section_id,
                section_code=section.hole_section.section_code,
                section_name=section.hole_section.section_name,
                from_depth=section.from_depth,
                to_depth=section.to_depth,
                total_days=sum((phase.days for phase in section.phases), Decimal("0")),
                phases=[
                    ScopePhaseOut(
                        phase_id=phase.phase_id,
                        phase_code=phase.phase.phase_code,
                        phase_name=phase.phase.phase_name,
                        days=phase.days,
                    )
                    for phase in sorted(section.phases, key=lambda row: row.sort_order)
                ],
            )
            for section in sections
        ],
    )


def _afe_out(afe: Afe, well: Well | None, priced: Priced, *, counts: tuple[int, int, int] | None = None) -> AfeOut:
    service_count, consumable_count, tangible_count = counts or (
        len(afe.service_lines),
        len(afe.consumable_lines),
        len(afe.tangible_lines),
    )
    rig = well.rig if well is not None else None
    return AfeOut(
        id=afe.id,
        rig_id=afe.rig_id,
        rig_code=rig.rig_code if rig else "",
        rig_name=rig.rig_name if rig else "",
        well_id=afe.well_id,
        well_code=well.well_code if well else "",
        well_name=well.well_name if well else "",
        well_status=well.scope_value(afe.configuration_scope, "status") if well else "",
        afe_code=afe.afe_code,
        afe_name=afe.afe_name,
        afe_type=afe.afe_type,
        configuration_scope=afe.configuration_scope,
        remarks=afe.remarks,
        status=afe.status,
        status_remarks=afe.status_remarks,
        status_changed_at=afe.status_changed_at,
        status_changed_by=afe.status_changed_by,
        estimate_saved_at=afe.estimate_saved_at,
        estimate_saved_by=afe.estimate_saved_by,
        service_count=service_count,
        consumable_count=consumable_count,
        tangible_count=tangible_count,
        services_total=priced.result.services_total,
        consumables_total=priced.result.consumables_total,
        tangibles_total=priced.result.tangibles_total,
        total_cost=priced.result.total,
        standard_currency=priced.result.currency.standard_currency,
        conversion_pending=not priced.result.currency.converted,
        totals_by_currency=[CurrencyTotalOut(currency=c, amount=a) for c, a in priced.result.totals_by_currency],
        warning_count=len(priced.result.warnings),
        is_deleted=afe.is_deleted,
        deleted_at=afe.deleted_at,
        created_at=afe.created_at,
        updated_at=afe.updated_at,
    )


def _stored_rates(afe: Afe) -> dict[str, Decimal]:
    return {row.currency_code: Decimal(row.rate) for row in afe.exchange_rates}


def _stored_priced(afe: Afe, well: Well | None, lookups: Lookups) -> Priced:
    scope = _scope_for_well(well, afe.configuration_scope)
    return _price(scope, _stored_resolved(afe, lookups), lookups, afe.standard_currency, _stored_rates(afe))


def _estimate_view(db: Session, organization_id: str, afe: Afe, *, persisted: bool) -> AfeEstimateOut:
    well = _wells_by_id(db, organization_id, [afe.well_id]).get(afe.well_id)
    lookups = _lookups_for_afes(db, organization_id, [afe])
    priced = _stored_priced(afe, well, lookups)
    return AfeEstimateOut(
        afe=_afe_out(afe, well, priced),
        well=_well_scope_out(well, afe.configuration_scope) if well else _missing_well_scope(afe),
        services=priced.services,
        consumables=priced.consumables,
        tangibles=priced.tangibles,
        summary=priced.summary,
        persisted=persisted,
        saved_at=afe.estimate_saved_at,
        saved_by=afe.estimate_saved_by,
    )


def _missing_well_scope(afe: Afe) -> WellScopeOut:
    return WellScopeOut(
        scope=afe.configuration_scope,
        well_id=afe.well_id, well_code="", well_name="", well_location="", block="", objective="",
        rig_code="", rig_name="", depth_unit="m", status="", config_status="", total_depth=None,
        total_days=Decimal("0"), sections=[],
    )


# ---------------------------------------------------------------------------
# Header operations
# ---------------------------------------------------------------------------


def list_afes(db: Session, organization_id: str, *, deleted: bool) -> list[AfeOut]:
    afes = list(
        db.scalars(
            select(Afe)
            .where(Afe.organization_id == organization_id, Afe.is_deleted.is_(deleted))
            .order_by(Afe.afe_code)
        ).all()
    )
    return _outs_for(db, organization_id, afes)


def _outs_for(db: Session, organization_id: str, afes: Sequence[Afe]) -> list[AfeOut]:
    if not afes:
        return []
    wells = _wells_by_id(db, organization_id, [afe.well_id for afe in afes])
    lookups = _lookups_for_afes(db, organization_id, afes)
    return [_afe_out(afe, wells.get(afe.well_id), _stored_priced(afe, wells.get(afe.well_id), lookups)) for afe in afes]


def afe_out_for(db: Session, organization_id: str, afe: Afe) -> AfeOut:
    return _outs_for(db, organization_id, [afe])[0]


def _require_draft(afe: Afe, verb: str) -> None:
    if afe.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"{afe.afe_code} is {AFE_STATUS_LABELS[afe.status].lower()}. Reopen it as Draft to {verb}.",
        )


def _check_well_and_rig(db: Session, organization_id: str, rig_id: str, well_id: str, configuration_scope: str = "drilling") -> Well:
    well = _wells_by_id(db, organization_id, [well_id]).get(well_id)
    if well is None or well.is_deleted:
        raise HTTPException(status_code=422, detail="Select an active well from this workspace.")
    rig = db.scalar(select(Rig).where(Rig.id == rig_id, Rig.organization_id == organization_id))
    if rig is None or rig.is_deleted:
        raise HTTPException(status_code=422, detail="Select an active rig from this workspace.")
    if well.rig_id != rig.id:
        raise HTTPException(status_code=422, detail="The selected well does not belong to the selected rig.")
    if well.rig is None or well.rig.is_deleted:
        raise HTTPException(status_code=409, detail="Restore the well's rig before creating AFEs for this well.")
    if not well.sections_for_scope(configuration_scope):
        raise HTTPException(
            status_code=422,
            detail=f"Configure the well's sections and phases in Rig & Well Management before creating an AFE ({configuration_scope} scope).",
        )
    if well.scope_value(configuration_scope, "config_status") != "configured":
        raise HTTPException(
            status_code=422,
            detail=f"Mark the well's plan as Configured in Rig & Well Management before creating an AFE for this well ({configuration_scope} scope).",
        )
    return well


def _code_conflict(db: Session, organization_id: str, code: str, exclude_id: str | None = None) -> None:
    statement = select(Afe.id, Afe.is_deleted).where(Afe.organization_id == organization_id, Afe.afe_code == code)
    if exclude_id:
        statement = statement.where(Afe.id != exclude_id)
    row = db.execute(statement).first()
    if row is not None:
        state = " It is in Deleted Entries; restore it instead." if row.is_deleted else ""
        raise HTTPException(status_code=409, detail=f"AFE code {code} is already used in this workspace.{state}")


def create_afe(db: Session, organization_id: str, data: AfeCreate, user: User, request: Request | None) -> AfeOut:
    _code_conflict(db, organization_id, data.afe_code)
    _check_well_and_rig(db, organization_id, data.rig_id, data.well_id, data.configuration_scope)
    afe = Afe(
        organization_id=organization_id,
        rig_id=data.rig_id,
        well_id=data.well_id,
        afe_code=data.afe_code,
        afe_name=data.afe_name,
        afe_type=data.afe_type,
        configuration_scope=data.configuration_scope,
        remarks=data.remarks,
        status="draft",
    )
    db.add(afe)
    db.flush()
    _record_audit(
        db, user=user, action="create", entity_type="afe", record_id=afe.id, entity_label=afe.afe_code,
        summary=f"Created {afe.afe_type} AFE {afe.afe_code} ({afe.configuration_scope} configuration) for well {_well_code(db, organization_id, afe.well_id)}",
        request=request,
    )
    _commit(db)
    db.refresh(afe)
    return afe_out_for(db, organization_id, afe)


def _well_code(db: Session, organization_id: str, well_id: str) -> str:
    well = _wells_by_id(db, organization_id, [well_id]).get(well_id)
    return well.well_code if well else well_id


def update_afe(
    db: Session, organization_id: str, afe_id: str, data: AfeUpdate, user: User, request: Request | None
) -> AfeOut:
    afe = afe_or_404(db, afe_id, organization_id, lock=True)
    if afe.is_deleted:
        raise HTTPException(status_code=409, detail="Restore this AFE before editing it.")
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        return afe_out_for(db, organization_id, afe)
    _require_draft(afe, "edit its header")
    if "afe_code" in changes and changes["afe_code"] and changes["afe_code"] != afe.afe_code:
        _code_conflict(db, organization_id, changes["afe_code"], exclude_id=afe.id)
    rig_id = changes.get("rig_id", afe.rig_id) or afe.rig_id
    well_id = changes.get("well_id", afe.well_id) or afe.well_id
    configuration_scope = changes.get("configuration_scope") or afe.configuration_scope
    if rig_id != afe.rig_id or well_id != afe.well_id or configuration_scope != afe.configuration_scope:
        if configuration_scope != afe.configuration_scope and (afe.service_lines or afe.consumable_lines or afe.tangible_lines):
            raise HTTPException(status_code=409, detail="Clear the saved estimate before changing its configuration scope.")
        _check_well_and_rig(db, organization_id, rig_id, well_id, configuration_scope)
    before = afe.afe_code
    for key, value in changes.items():
        if value is not None:
            setattr(afe, key, value)
    _record_audit(
        db, user=user, action="update", entity_type="afe", record_id=afe.id, entity_label=afe.afe_code,
        summary=f"Updated AFE {before}" + (f" (now {afe.afe_code})" if before != afe.afe_code else "") + f": {', '.join(sorted(changes))}",
        request=request,
    )
    _commit(db)
    db.refresh(afe)
    return afe_out_for(db, organization_id, afe)


def _active_afe(db: Session, organization_id: str, afe_id: str) -> Afe:
    afe = afe_or_404(db, afe_id, organization_id)
    if afe.is_deleted:
        raise HTTPException(status_code=404, detail="AFE not found in this workspace")
    return afe


def _daily_cost_dependency_counts(
    db: Session,
    organization_id: str,
    afe_ids: list[str],
    *,
    active_entries_only: bool,
) -> tuple[dict[str, int], dict[str, int]]:
    if not afe_ids:
        return {}, {}
    entry_statement = select(DailyCostEntry.afe_id, func.count(DailyCostEntry.id)).where(
        DailyCostEntry.organization_id == organization_id,
        DailyCostEntry.afe_id.in_(afe_ids),
    )
    if active_entries_only:
        entry_statement = entry_statement.where(DailyCostEntry.is_deleted.is_(False))
    entries = {
        str(afe_id): int(count)
        for afe_id, count in db.execute(entry_statement.group_by(DailyCostEntry.afe_id)).all()
    }
    baseline_statement = select(DailyCostBaseline.afe_id, func.count(DailyCostBaseline.id)).where(
        DailyCostBaseline.organization_id == organization_id,
        DailyCostBaseline.afe_id.in_(afe_ids),
    )
    baselines = {
        str(afe_id): int(count)
        for afe_id, count in db.execute(baseline_statement.group_by(DailyCostBaseline.afe_id)).all()
    }
    return entries, baselines


def _soft_delete(db: Session, organization_id: str, afe: Afe, user: User, request: Request | None) -> None:
    if afe.status != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"{afe.afe_code} is {AFE_STATUS_LABELS[afe.status].lower()}. Reopen it as Draft before moving it to Deleted Entries.",
        )
    active_entries, _ = _daily_cost_dependency_counts(
        db, organization_id, [afe.id], active_entries_only=True
    )
    if active_entries.get(afe.id):
        raise HTTPException(
            status_code=409,
            detail=(
                f"{afe.afe_code} is used by {active_entries[afe.id]} active daily-cost sheet(s). "
                "Move those sheets to Deleted Entries before deleting this AFE."
            ),
        )
    afe.is_deleted = True
    afe.deleted_at = _now()
    _record_audit(
        db, user=user, action="soft_delete", entity_type="afe", record_id=afe.id, entity_label=afe.afe_code,
        summary=f"Moved AFE {afe.afe_code} to Deleted Entries", request=request,
    )


def delete_afe(db: Session, organization_id: str, afe_id: str, user: User, request: Request | None) -> AfeOut:
    afe = _active_afe(db, organization_id, afe_id)
    _soft_delete(db, organization_id, afe, user, request)
    _commit(db)
    db.refresh(afe)
    return afe_out_for(db, organization_id, afe)


def bulk_delete(db: Session, organization_id: str, data: AfeIDs, user: User, request: Request | None) -> int:
    afes = list(
        db.scalars(select(Afe).where(Afe.organization_id == organization_id, Afe.id.in_(data.ids), Afe.is_deleted.is_(False))).all()
    )
    if len(afes) != len(set(data.ids)):
        raise HTTPException(status_code=404, detail="Some selected AFEs were not found or are already deleted")
    blocked = [afe.afe_code for afe in afes if afe.status != "draft"]
    if blocked:
        raise HTTPException(
            status_code=409,
            detail=f"Only draft AFEs can be moved to Deleted Entries. Reopen first: {', '.join(sorted(blocked)[:10])}",
        )
    entries_by_afe, _ = _daily_cost_dependency_counts(
        db, organization_id, [afe.id for afe in afes], active_entries_only=True
    )
    blocked_sheets = [afe.afe_code for afe in afes if entries_by_afe.get(afe.id)]
    if blocked_sheets:
        raise HTTPException(
            status_code=409,
            detail=(
                "These AFEs are used by active daily-cost sheets. Move those sheets to Deleted Entries first: "
                f"{', '.join(sorted(blocked_sheets)[:10])}"
            ),
        )
    for afe in afes:
        _soft_delete(db, organization_id, afe, user, request)
    _commit(db)
    return len(afes)


def restore_afe(db: Session, organization_id: str, afe_id: str, user: User, request: Request | None) -> AfeOut:
    afe = afe_or_404(db, afe_id, organization_id, lock=True)
    if not afe.is_deleted:
        raise HTTPException(status_code=409, detail="This AFE is not in Deleted Entries")
    _ensure_restorable(db, organization_id, afe)
    afe.is_deleted = False
    afe.deleted_at = None
    _record_audit(
        db, user=user, action="restore", entity_type="afe", record_id=afe.id, entity_label=afe.afe_code,
        summary=f"Restored AFE {afe.afe_code}", request=request,
    )
    _commit(db)
    db.refresh(afe)
    return afe_out_for(db, organization_id, afe)


def _ensure_restorable(db: Session, organization_id: str, afe: Afe) -> None:
    rig = db.scalar(select(Rig).where(Rig.id == afe.rig_id, Rig.organization_id == organization_id))
    well = _wells_by_id(db, organization_id, [afe.well_id]).get(afe.well_id)
    if rig is None or rig.is_deleted:
        raise HTTPException(status_code=409, detail="Restore the rig for this AFE first.")
    if well is None or well.is_deleted:
        raise HTTPException(status_code=409, detail="Restore the well for this AFE first.")


def bulk_restore(db: Session, organization_id: str, data: AfeIDs, user: User, request: Request | None) -> int:
    afes = list(
        db.scalars(select(Afe).where(Afe.organization_id == organization_id, Afe.id.in_(data.ids), Afe.is_deleted.is_(True))).all()
    )
    if len(afes) != len(set(data.ids)):
        raise HTTPException(status_code=404, detail="Some selected AFEs were not found in Deleted Entries")
    for afe in afes:
        _ensure_restorable(db, organization_id, afe)
        afe.is_deleted = False
        afe.deleted_at = None
        _record_audit(
            db, user=user, action="restore", entity_type="afe", record_id=afe.id, entity_label=afe.afe_code,
            summary=f"Restored AFE {afe.afe_code}", request=request,
        )
    _commit(db)
    return len(afes)


def permanently_delete(db: Session, organization_id: str, afe_ids: Iterable[str], user: User, request: Request | None) -> int:
    ids = list(set(afe_ids))
    afes = list(
        db.scalars(select(Afe).where(Afe.organization_id == organization_id, Afe.id.in_(ids))).all()
    )
    if len(afes) != len(ids):
        raise HTTPException(status_code=404, detail="Some selected AFEs were not found")
    active = [afe.afe_code for afe in afes if not afe.is_deleted]
    if active:
        raise HTTPException(status_code=409, detail=f"Move these AFEs to Deleted Entries first: {', '.join(sorted(active)[:10])}")
    entries_by_afe, baselines_by_afe = _daily_cost_dependency_counts(
        db, organization_id, [afe.id for afe in afes], active_entries_only=False
    )
    blocked = [
        afe for afe in afes
        if entries_by_afe.get(afe.id) or baselines_by_afe.get(afe.id)
    ]
    if blocked:
        afe = blocked[0]
        dependencies = []
        if entries_by_afe.get(afe.id):
            dependencies.append(f"{entries_by_afe[afe.id]} daily-cost sheet(s)")
        if baselines_by_afe.get(afe.id):
            dependencies.append("an immutable daily-cost baseline")
        raise HTTPException(
            status_code=409,
            detail=(
                f"AFE {afe.afe_code} is retained by {', '.join(dependencies)}. Permanently delete linked daily-cost "
                "sheets first. Immutable AFE baselines are retained for audit, so an AFE with baseline history "
                "must remain in Deleted Entries."
            ),
        )
    for afe in afes:
        _record_audit(
            db, user=user, action="permanent_delete", entity_type="afe", record_id=None, entity_label=afe.afe_code,
            summary=f"Permanently deleted AFE {afe.afe_code} and its estimate", request=request,
        )
        db.delete(afe)
    _commit(db)
    return len(afes)


def change_status(
    db: Session, organization_id: str, afe_id: str, action: str, remarks: str, user: User, request: Request | None
) -> AfeOut:
    afe = afe_or_404(db, afe_id, organization_id, lock=True)
    if afe.is_deleted:
        raise HTTPException(status_code=409, detail="Restore this AFE before changing its status.")
    granted_keys = {permission.key for role in user.roles for permission in role.permissions}
    if not any(role.is_owner for role in user.roles) and ACTION_PERMISSION[action] not in granted_keys:
        raise HTTPException(status_code=403, detail="Permission denied")
    next_status = TRANSITIONS.get((afe.status, action))
    if next_status is None:
        raise HTTPException(
            status_code=409,
            detail=f"{afe.afe_code} is {AFE_STATUS_LABELS[afe.status].lower()}; it cannot be {ACTION_LABELS[action]} from here.",
        )
    if action in REMARKS_REQUIRED_FOR and len(remarks) < 3:
        raise HTTPException(status_code=422, detail="Enter a reason of at least 3 characters for this status change.")
    if action == "submit":
        if not afe.estimate_saved_at:
            raise HTTPException(status_code=409, detail="Save the AFE cost estimate before submitting.")
        well = _wells_by_id(db, organization_id, [afe.well_id]).get(afe.well_id)
        if well is None or well.scope_value(afe.configuration_scope, "config_status") != "configured":
            raise HTTPException(status_code=409, detail="The well's plan is not Configured. Configure the well before submitting this AFE.")
        priced = _stored_priced(afe, well, _lookups_for_afes(db, organization_id, [afe]))
        if priced.result.total is None:
            raise HTTPException(status_code=409, detail="The saved estimate mixes currencies without a complete conversion. Save it with a standard currency and rates first.")
        if priced.result.total <= 0:
            raise HTTPException(status_code=409, detail="The saved estimate has no cost. Price the AFE before submitting.")
    previous = afe.status
    afe.status = next_status
    afe.status_remarks = remarks
    afe.status_changed_at = _now()
    afe.status_changed_by = _actor_name(user)
    _record_audit(
        db, user=user, action=action, entity_type="afe", record_id=afe.id, entity_label=afe.afe_code,
        summary=f"AFE {afe.afe_code} {ACTION_LABELS[action]} ({previous} → {next_status})" + (f": {remarks}" if remarks else ""),
        request=request,
    )
    _commit(db)
    db.refresh(afe)
    return afe_out_for(db, organization_id, afe)


# ---------------------------------------------------------------------------
# Estimate operations
# ---------------------------------------------------------------------------


def get_estimate(db: Session, organization_id: str, afe_id: str) -> AfeEstimateOut:
    afe = afe_or_404(db, afe_id, organization_id)
    if afe.is_deleted:
        raise HTTPException(status_code=404, detail="AFE not found in this workspace")
    return _estimate_view(db, organization_id, afe, persisted=True)


def preview_estimate(db: Session, organization_id: str, afe_id: str, payload: EstimateIn) -> AfeEstimateOut:
    """Price the request against live master data and the well plan. Writes nothing."""

    afe = afe_or_404(db, afe_id, organization_id)
    if afe.is_deleted:
        raise HTTPException(status_code=404, detail="AFE not found in this workspace")
    well = _wells_by_id(db, organization_id, [afe.well_id]).get(afe.well_id)
    scope = _scope_for_well(well, afe.configuration_scope)
    resolved = _validate_request(db, organization_id, scope, payload)
    lookups = _load_lookups(
        db,
        organization_id,
        service_ids=[row.service.id for row in resolved.services if row.service],
        drill_bit_ids=[row.drill_bit.id for row in resolved.consumables if row.drill_bit],
        tangible_ids=[row.tangible.id for row in resolved.tangibles if row.tangible],
        hole_section_ids=[row.section_id for row in resolved.consumables] + [row.section_id for row in resolved.services if row.section_id],
    )
    rates = {row.currency_code: Decimal(row.rate) for row in payload.exchange_rates}
    priced = _price(scope, resolved, lookups, payload.standard_currency, rates)
    counts = (len(resolved.services), len(resolved.consumables), len(resolved.tangibles))
    return AfeEstimateOut(
        afe=_afe_out(afe, well, priced, counts=counts),
        well=_well_scope_out(well, afe.configuration_scope) if well else _missing_well_scope(afe),
        services=priced.services,
        consumables=priced.consumables,
        tangibles=priced.tangibles,
        summary=priced.summary,
        persisted=False,
        saved_at=afe.estimate_saved_at,
        saved_by=afe.estimate_saved_by,
    )


def _service_rows(afe: Afe, resolved: Resolved) -> list[AfeServiceLine]:
    rows: list[AfeServiceLine] = []
    for index, row in enumerate(resolved.services):
        line = AfeServiceLine(
            organization_id=afe.organization_id,
            service_id=row.service.id,
            charging_basis=row.basis,
            hole_section_id=row.section_id,
            phase_id=row.phase_id,
            currency=row.currency,
            service_amount=row.service_amount,
            remarks=row.remarks,
            sort_order=index,
        )
        line.rates = [
            AfeServiceRate(organization_id=afe.organization_id, charge_category=category, unit_rate=rate, sort_order=i)
            for i, (category, rate) in enumerate(row.rates)
        ]
        line.charges = [
            AfeServiceCharge(
                organization_id=afe.organization_id,
                charge_category=category,
                quantity=quantity,
                quantity_unit=unit,
                sort_order=i,
            )
            for i, (category, quantity, unit) in enumerate(row.charges)
        ]
        line.section_rates = [
            AfeServiceSectionRate(
                organization_id=afe.organization_id,
                hole_section_id=section_id,
                phase_id=phase_id,
                amount=amount,
                sort_order=i,
            )
            for i, (section_id, phase_id, amount) in enumerate(row.section_rates)
        ]
        rows.append(line)
    return rows


def _consumable_rows(afe: Afe, resolved: Resolved) -> list[AfeConsumableLine]:
    return [
        AfeConsumableLine(
            organization_id=afe.organization_id,
            category=row.category,
            hole_section_id=row.section_id,
            phase_id=row.phase_id,
            drill_bit_id=row.drill_bit.id if row.drill_bit else None,
            quantity=row.quantity,
            captured_rate=row.captured_rate,
            override_rate=row.override_rate,
            estimated_amount=row.estimated_amount,
            currency=row.currency,
            remarks=row.remarks,
            sort_order=index,
        )
        for index, row in enumerate(resolved.consumables)
    ]


def _tangible_rows(afe: Afe, resolved: Resolved) -> list[AfeTangibleLine]:
    return [
        AfeTangibleLine(
            organization_id=afe.organization_id,
            tangible_id=row.tangible.id,
            quantity=row.quantity,
            captured_rate=row.captured_rate,
            override_rate=row.override_rate,
            currency=row.currency,
            uom=row.uom,
            remarks=row.remarks,
            sort_order=index,
        )
        for index, row in enumerate(resolved.tangibles)
    ]


def _exchange_rate_rows(afe: Afe, setup: engine.CurrencySetup) -> list[AfeExchangeRate]:
    return [
        AfeExchangeRate(organization_id=afe.organization_id, currency_code=code, rate=rate, sort_order=index)
        for index, (code, rate) in enumerate(setup.exchange_rates)
    ]


def _conversion_problem(setup: engine.CurrencySetup) -> str:
    if setup.standard_missing:
        return "This estimate mixes currencies. Select the standard currency before saving."
    missing = ", ".join(code or "no currency" for code in setup.missing_rates)
    return f"Enter the conversion rate to {setup.standard_currency} for {missing} before saving."


def save_estimate(
    db: Session, organization_id: str, afe_id: str, payload: EstimateIn, user: User, request: Request | None
) -> AfeEstimateOut:
    with _SAVE_LOCK:
        afe = afe_or_404(db, afe_id, organization_id, lock=True)
        if afe.is_deleted:
            raise HTTPException(status_code=409, detail="Restore this AFE before editing its estimate.")
        _require_draft(afe, "edit its cost estimate")
        well = _wells_by_id(db, organization_id, [afe.well_id]).get(afe.well_id)
        if well is None or well.scope_value(afe.configuration_scope, "config_status") != "configured":
            raise HTTPException(
                status_code=409,
                detail="The well's plan is in Draft. Mark the well as Configured in Rig & Well Management before saving this estimate.",
            )
        scope = _scope_for_well(well, afe.configuration_scope)
        resolved = _validate_request(db, organization_id, scope, payload)

        # A mixed-currency estimate is saved only when it can be converted to one standard currency.
        rates = {row.currency_code: Decimal(row.rate) for row in payload.exchange_rates}
        setup = engine.compile_estimate(
            scope,
            services=[row.line for row in resolved.services],
            consumables=[row.line for row in resolved.consumables],
            tangibles=[row.line for row in resolved.tangibles],
            standard_currency=payload.standard_currency,
            exchange_rates=rates,
        ).currency
        if not setup.converted:
            raise HTTPException(status_code=422, detail=_conversion_problem(setup))

        afe.standard_currency = setup.standard_currency
        # Clear the old rates first: inserts run before orphan deletes, and the unique currency key would clash.
        afe.exchange_rates = []
        db.flush()
        afe.exchange_rates = _exchange_rate_rows(afe, setup)
        afe.service_lines = _service_rows(afe, resolved)
        afe.consumable_lines = _consumable_rows(afe, resolved)
        afe.tangible_lines = _tangible_rows(afe, resolved)
        afe.estimate_saved_at = _now()
        afe.estimate_saved_by = _actor_name(user)
        db.flush()

        lookups = _lookups_for_afes(db, organization_id, [afe])
        priced = _stored_priced(afe, well, lookups)
        _record_audit(
            db, user=user, action="update", entity_type="afe_estimate", record_id=afe.id, entity_label=afe.afe_code,
            summary=(
                f"Saved estimate for {afe.afe_code}: {len(resolved.services)} service, "
                f"{len(resolved.consumables)} consumable and {len(resolved.tangibles)} tangible line(s); "
                f"total {_money_text(priced.result.total) + ' ' + afe.standard_currency if priced.result.total is not None else 'pending currency conversion'}"
            ),
            request=request,
        )
        _commit(db)
    afe = afe_or_404(db, afe_id, organization_id)
    return _estimate_view(db, organization_id, afe, persisted=True)


# ---------------------------------------------------------------------------
# Reference data, overview, audit, import
# ---------------------------------------------------------------------------


def reference_data(db: Session, organization_id: str) -> AfeReference:
    from app.models import Currency

    rigs = list(
        db.scalars(select(Rig).where(Rig.organization_id == organization_id, Rig.is_deleted.is_(False)).order_by(Rig.rig_code)).all()
    )
    wells = list(
        db.scalars(
            select(Well)
            .options(selectinload(Well.sections))
            .where(Well.organization_id == organization_id, Well.is_deleted.is_(False))
            .order_by(Well.well_code)
        ).all()
    )
    services = list(
        db.scalars(
            select(Service)
            .options(joinedload(Service.vendor))
            .where(Service.organization_id == organization_id, Service.is_deleted.is_(False))
            .order_by(Service.service_code)
        ).unique().all()
    )
    tangibles = list(
        db.scalars(
            select(Tangible).where(Tangible.organization_id == organization_id, Tangible.is_deleted.is_(False)).order_by(Tangible.tangible_code)
        ).all()
    )
    drill_bits = list(
        db.scalars(
            select(DrillBit).where(DrillBit.organization_id == organization_id, DrillBit.is_deleted.is_(False)).order_by(DrillBit.bit_code)
        ).all()
    )
    options = options_by_id(db, organization_id)
    currencies = list(
        db.scalars(
            select(Currency).where(Currency.organization_id == organization_id, Currency.is_deleted.is_(False)).order_by(Currency.currency_code)
        ).all()
    )
    rig_by_id = {rig.id: rig for rig in rigs}
    return AfeReference(
        rigs=[
            AfeReferenceRig(id=rig.id, rig_code=rig.rig_code, rig_name=rig.rig_name, display_name=_label(rig.rig_code, rig.rig_name))
            for rig in rigs
        ],
        wells=[
            AfeReferenceWell(
                id=well.id,
                rig_id=well.rig_id,
                well_code=well.well_code,
                well_name=well.well_name,
                display_name=_label(well.well_code, well.well_name),
                status=well.status,
                config_status=well.config_status,
                completion_config_status=well.completion_config_status,
                completion_status=well.completion_status,
                completion_section_count=len(well.completion_sections),
                total_days=sum((phase.days for section in well.sections for phase in section.phases), Decimal("0")),
                total_depth=sorted(well.sections, key=lambda row: row.sort_order)[-1].to_depth if well.sections else None,
                depth_unit=well.depth_unit,
                section_count=len(well.sections),
            )
            for well in wells
            if well.rig_id in rig_by_id
        ],
        services=[
            AfeReferenceService(
                id=service.id,
                service_code=service.service_code,
                service_name=service.service_name,
                service_category=service.service_category,
                provider_type=service.provider_type,
                vendor_name=service.vendor.vendor_name if service.vendor else "",
                display_name=_label(service.service_code, service.service_name),
                description=service.description,
            )
            for service in services
        ],
        tangibles=[
            AfeReferenceTangible(
                id=row.id,
                tangible_code=row.tangible_code,
                tangible_name=row.tangible_name,
                scope=row.scope,
                category_name=options[row.category_id].value if row.category_id in options else "",
                subcategory_name=options[row.subcategory_id].value if row.subcategory_id in options else "",
                manufacturer_name=options[row.manufacturer_id].value if row.manufacturer_id in options else "",
                description=row.description,
                uom=row.uom,
                unit_rate=Decimal(row.unit_rate),
                final_cost=Decimal(row.final_cost) if row.final_cost is not None else None,
                captured_rate=_captured_rate(row),
                currency=row.currency,
                display_name=_label(row.tangible_code, row.tangible_name),
            )
            for row in tangibles
        ],
        drill_bits=[
            AfeReferenceDrillBit(
                id=row.id,
                bit_code=row.bit_code,
                bit_name=row.bit_name,
                bit_type=options[row.bit_type_id].value if row.bit_type_id in options else "",
                manufacturer_name=options[row.manufacturer_id].value if row.manufacturer_id in options else "",
                model_no=row.model_no,
                size=row.size,
                iadc_code=row.iadc_code,
                serial_number=row.serial_number,
                description=row.description,
                captured_rate=_captured_rate(row),
                currency=row.currency,
                display_name=_label(row.bit_code, row.bit_name),
            )
            for row in drill_bits
        ],
        currencies=[
            {
                "code": row.currency_code,
                "name": row.currency_name,
                "symbol": row.currency_symbol,
                "is_default": bool(row.is_default),
            }
            for row in currencies
        ],
        afe_types=["Drilling", "Completion"],
        charging_bases=list(engine.CHARGING_BASES),
        charge_categories=list(engine.CHARGE_CATEGORIES),
        one_time_categories=list(engine.ONE_TIME_CATEGORIES),
        consumable_categories=list(engine.CONSUMABLE_CATEGORIES),
        statuses=list(AFE_STATUSES),
    )


def overview(db: Session, organization_id: str, user: User) -> AfeOverview:
    active = list(db.scalars(select(Afe).where(Afe.organization_id == organization_id, Afe.is_deleted.is_(False))).all())
    deleted_count = int(
        db.scalar(select(func.count(Afe.id)).where(Afe.organization_id == organization_id, Afe.is_deleted.is_(True))) or 0
    )
    outs = _outs_for(db, organization_id, active)
    totals: dict[str, Decimal] = {}
    approved_totals: dict[str, Decimal] = {}
    well_totals: dict[str, dict[str, Decimal]] = {}
    well_labels: dict[str, str] = {}
    conversion_pending = 0
    # Each AFE contributes its converted total in its own standard currency. AFEs whose
    # conversion is incomplete are counted separately and are not added in.
    for afe, out in zip(active, outs, strict=True):
        if out.total_cost is None:
            conversion_pending += 1
        elif out.standard_currency and out.total_cost:
            code, amount = out.standard_currency, out.total_cost
            totals[code] = totals.get(code, Decimal("0")) + amount
            if afe.status == "approval":
                approved_totals[code] = approved_totals.get(code, Decimal("0")) + amount
            bucket = well_totals.setdefault(afe.well_id, {})
            bucket[code] = bucket.get(code, Decimal("0")) + amount
        well_labels[afe.well_id] = _label(out.well_code, out.well_name)

    top_wells: list[AfeOverviewWell] = []
    for well_id, by_currency in well_totals.items():
        currencies = sorted(by_currency)
        if len(currencies) == 1:
            total, currency = engine.money(by_currency[currencies[0]]), currencies[0]
        else:
            total, currency = engine.money(sum(by_currency.values(), Decimal("0"))), "mixed"
        top_wells.append(AfeOverviewWell(well_id=well_id, label=well_labels.get(well_id, ""), total=total, currency=currency))
    top_wells.sort(key=lambda row: row.total, reverse=True)

    status_counts = {status: 0 for status in AFE_STATUSES}
    for afe in active:
        status_counts[afe.status] += 1

    recent: list[AfeRecentActivity] = []
    if any(role.is_owner for role in user.roles) or "audit:read" in {p.key for role in user.roles for p in role.permissions}:
        rows = db.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id, AuditLog.entity_type.in_(AUDIT_TYPES))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(8)
        ).all()
        recent = [
            AfeRecentActivity(
                id=row.id, action=row.action, entity_type=row.entity_type, entity_label=row.entity_label,
                summary=row.summary, created_at=row.created_at,
            )
            for row in rows
        ]

    return AfeOverview(
        active_afes=len(active),
        deleted_afes=deleted_count,
        drilling_afes=sum(1 for afe in active if afe.afe_type == "Drilling"),
        completion_afes=sum(1 for afe in active if afe.afe_type == "Completion"),
        approved_afes=sum(1 for afe in active if afe.status == "approval"),
        wells_with_afes=len({afe.well_id for afe in active}),
        totals_by_currency=[CurrencyTotalOut(currency=c, amount=engine.money(a)) for c, a in sorted(totals.items())],
        approved_by_currency=[CurrencyTotalOut(currency=c, amount=engine.money(a)) for c, a in sorted(approved_totals.items())],
        conversion_pending_afes=conversion_pending,
        statuses=[
            AfeOverviewStatus(status=status, label=AFE_STATUS_LABELS[status], count=status_counts[status])
            for status in AFE_STATUSES
        ],
        top_wells=top_wells[:8],
        warning_afes=sum(1 for out in outs if out.warning_count),
        recent_activity=recent,
    )


def _import_value(row: dict[str, Any], *aliases: str) -> Any:
    normalized = {str(key).strip().lower().replace(" ", "_").replace("-", "_"): value for key, value in row.items()}
    for alias in aliases:
        key = alias.strip().lower().replace(" ", "_").replace("-", "_")
        if key in normalized and normalized[key] not in (None, ""):
            return normalized[key]
    return None


def _import_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _validation_text(error: Any) -> str:
    return "; ".join(f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}" for issue in error.errors())


def import_afes(db: Session, organization_id: str, rows: list[dict[str, Any]], user: User, request: Request | None) -> tuple[int, list[str]]:
    from pydantic import ValidationError

    imported = 0
    errors: list[str] = []
    seen: set[str] = set()
    for row_number, row in enumerate(rows, start=1):
        rig_ref = _import_text(_import_value(row, "rig_code", "rig"))
        well_ref = _import_text(_import_value(row, "well_code", "well"))
        rig = db.scalar(select(Rig).where(Rig.organization_id == organization_id, Rig.rig_code == rig_ref.upper(), Rig.is_deleted.is_(False))) if rig_ref else None
        well = db.scalar(select(Well).where(Well.organization_id == organization_id, Well.well_code == well_ref.upper(), Well.is_deleted.is_(False))) if well_ref else None
        if rig is None:
            errors.append(f"Row {row_number}: rig_code '{rig_ref or '—'}' is missing or is not an active rig")
            continue
        if well is None:
            errors.append(f"Row {row_number}: well_code '{well_ref or '—'}' is missing or is not an active well")
            continue
        raw = {
            "rig_id": rig.id,
            "well_id": well.id,
            "afe_code": _import_value(row, "afe_code", "afe", "code"),
            "afe_name": _import_value(row, "afe_name", "name"),
            "afe_type": _import_value(row, "afe_type", "type"),
            "configuration_scope": _import_text(_import_value(row, "configuration_scope")).lower() or "drilling",
            "remarks": _import_value(row, "remarks", "remark") or "",
        }
        try:
            payload = AfeCreate.model_validate(raw)
        except ValidationError as error:
            errors.append(f"Row {row_number}: {_validation_text(error)}")
            continue
        if payload.afe_code in seen:
            errors.append(f"Row {row_number} ({payload.afe_code}): duplicate AFE code in this import")
            continue
        seen.add(payload.afe_code)
        try:
            _check_well_and_rig(db, organization_id, payload.rig_id, payload.well_id, payload.configuration_scope)
        except HTTPException as error:
            errors.append(f"Row {row_number} ({payload.afe_code}): {error.detail}")
            continue
        existing = db.scalar(select(Afe).where(Afe.organization_id == organization_id, Afe.afe_code == payload.afe_code))
        if existing is None:
            afe = Afe(
                organization_id=organization_id, rig_id=payload.rig_id, well_id=payload.well_id,
                afe_code=payload.afe_code, afe_name=payload.afe_name, afe_type=payload.afe_type,
                configuration_scope=payload.configuration_scope,
                remarks=payload.remarks, status="draft",
            )
            db.add(afe)
            db.flush()
            action, summary = "create", f"Created AFE {payload.afe_code} from import"
        else:
            if existing.status != "draft" and not existing.is_deleted:
                errors.append(f"Row {row_number} ({payload.afe_code}): AFE is {existing.status}; reopen it as Draft before importing changes")
                continue
            if existing.status != "draft":
                errors.append(f"Row {row_number} ({payload.afe_code}): restore is blocked for a non-draft AFE")
                continue
            if existing.configuration_scope != payload.configuration_scope:
                if existing.service_lines or existing.consumable_lines or existing.tangible_lines:
                    errors.append(f"Row {row_number} ({payload.afe_code}): clear the saved estimate before changing its configuration scope")
                    continue
            action = "restore" if existing.is_deleted else "update"
            existing.rig_id = payload.rig_id
            existing.well_id = payload.well_id
            existing.afe_name = payload.afe_name
            existing.afe_type = payload.afe_type
            existing.configuration_scope = payload.configuration_scope
            existing.remarks = payload.remarks
            existing.is_deleted = False
            existing.deleted_at = None
            afe = existing
            summary = f"{'Restored and updated' if action == 'restore' else 'Updated'} AFE {payload.afe_code} from import"
        _record_audit(db, user=user, action=action, entity_type="afe", record_id=afe.id, entity_label=payload.afe_code, summary=summary, request=request)
        imported += 1
    _record_audit(
        db, user=user, action="import", entity_type="afe", record_id=None, entity_label="AFE register",
        summary=f"Imported {imported} AFEs with {len(errors)} row error(s)", request=request,
    )
    _commit(db)
    return imported, errors[:100]


def record_export(db: Session, user: User, *, module: str, fmt: str, record_count: int, include_deleted: bool, request: Request | None) -> None:
    labels = {
        "afes": "AFE register",
        "estimates": "AFE cost estimation",
        "deleted": "Deleted AFE entries",
        "afe-print": "AFE print sheet",
        "estimate-print": "AFE cost estimate print",
    }
    _record_audit(
        db, user=user, action="export", entity_type="afe_export", record_id=None, entity_label=labels[module],
        summary=f"Exported {record_count} {labels[module]} record(s) as {fmt.upper()}"
        f"{' including deleted entries' if include_deleted else ''}",
        request=request,
    )
    _commit(db)


def record_print(db: Session, organization_id: str, afe_id: str, user: User, request: Request | None) -> None:
    afe = afe_or_404(db, afe_id, organization_id)
    _record_audit(
        db, user=user, action="print", entity_type="afe_export", record_id=afe.id, entity_label=afe.afe_code,
        summary=f"Printed AFE cost estimate sheet for {afe.afe_code}", request=request,
    )
    _commit(db)
