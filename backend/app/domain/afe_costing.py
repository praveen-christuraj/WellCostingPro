"""AFE cost estimation engine.

Pure, framework-free pricing rules. The service layer converts stored rows or a
validated request into the immutable inputs below, and this module returns the
priced result. Nothing here reads or writes the database.

Rules
-----
* Charge categories are fixed. Mobilization, Demobilization and Fixed Charge are
  one-time per service line. The other categories are day-based.
* Day Rate services charge ``days x unit rate`` per day-based category. Hours
  convert with ``/ 24``. An explicit Operation quantity replaces the planned
  Operation days; otherwise the planned days of the line's scope are used.
* A well-wide Day Rate line (no section) is split across the configured sections
  by each section's planned days, so every section shows its own share.
* Per Section Rate charges one amount per (section, optional phase). Per Service
  Rate charges one lump sum for its section and phase.
* Consumables and tangibles cost ``quantity x effective rate``. The effective
  rate is the override when one is entered, otherwise the captured rate.
* Sections and phases must come from the well configuration. Anything outside it
  is reported as a warning and is never silently priced into a section.
* Money is rounded to 2 decimals (half-up) per component; days and rates to 4.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

ONE_TIME_CATEGORIES: tuple[str, ...] = ("Mobilization", "Demobilization", "Fixed Charge")
DAY_CATEGORIES: tuple[str, ...] = ("Operation", "Standby", "Personnel-Operation", "Personnel-Standby", "Others")
CHARGE_CATEGORIES: tuple[str, ...] = (
    "Mobilization",
    "Demobilization",
    "Operation",
    "Standby",
    "Personnel-Operation",
    "Personnel-Standby",
    "Fixed Charge",
    "Others",
)

BASIS_DAY_RATE = "Day Rate"
BASIS_PER_SERVICE = "Per Service Rate"
BASIS_PER_SECTION = "Per Section Rate"
CHARGING_BASES: tuple[str, ...] = (BASIS_DAY_RATE, BASIS_PER_SERVICE, BASIS_PER_SECTION)

UNIT_DAYS = "days"
UNIT_HOURS = "hours"
HOURS_PER_DAY = Decimal("24")

CONSUMABLE_LUMP_SUM: tuple[str, ...] = ("Mud Chemicals", "Cement Additives", "Fuel")
CONSUMABLE_DRILL_BITS = "Drill Bits"
CONSUMABLE_CATEGORIES: tuple[str, ...] = CONSUMABLE_LUMP_SUM + (CONSUMABLE_DRILL_BITS,)

GROUP_SERVICES = "Services"
GROUP_CONSUMABLES = "Consumables"
GROUP_TANGIBLES = "Tangibles"

WELL_LEVEL_LABEL = "Well-level (not section-specific)"

_MONEY = Decimal("0.01")
_QTY = Decimal("0.0001")


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_MONEY, rounding=ROUND_HALF_UP)


def _qty(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_QTY, rounding=ROUND_HALF_UP)


def effective_rate(captured: Decimal, override: Decimal | None) -> Decimal:
    """The override wins when entered; otherwise the captured master-data rate applies."""

    return Decimal(override) if override is not None else Decimal(captured)


def normalize_days(quantity: Decimal, unit: str) -> Decimal:
    """Return the quantity in days. Hours convert with ``/ 24``; days pass through."""

    value = Decimal(quantity)
    if unit == UNIT_HOURS:
        value = value / HOURS_PER_DAY
    return _qty(value)


# ---------------------------------------------------------------------------
# Well configuration scope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseScope:
    phase_id: str
    label: str
    days: Decimal


@dataclass(frozen=True)
class SectionScope:
    section_id: str
    label: str
    phases: tuple[PhaseScope, ...] = ()

    @property
    def days(self) -> Decimal:
        return sum((phase.days for phase in self.phases), Decimal("0"))

    def phase(self, phase_id: str | None) -> PhaseScope | None:
        if phase_id is None:
            return None
        return next((phase for phase in self.phases if phase.phase_id == phase_id), None)


@dataclass(frozen=True)
class WellScope:
    """The planned sections and phases of a well, as configured."""

    sections: tuple[SectionScope, ...] = ()

    @property
    def total_days(self) -> Decimal:
        return sum((section.days for section in self.sections), Decimal("0"))

    def section(self, section_id: str | None) -> SectionScope | None:
        if section_id is None:
            return None
        return next((section for section in self.sections if section.section_id == section_id), None)

    def planned_days(self, section_id: str | None, phase_id: str | None) -> Decimal:
        """Planned days for a scope. Unknown scopes have no planned days."""

        if section_id is None:
            return self.total_days
        section = self.section(section_id)
        if section is None:
            return Decimal("0")
        if phase_id is None:
            return section.days
        phase = section.phase(phase_id)
        return phase.days if phase is not None else Decimal("0")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateInput:
    category: str
    unit_rate: Decimal


@dataclass(frozen=True)
class ChargeInput:
    category: str
    quantity: Decimal
    unit: str = UNIT_DAYS


@dataclass(frozen=True)
class SectionRateInput:
    section_id: str
    phase_id: str | None
    amount: Decimal


@dataclass(frozen=True)
class ServiceLine:
    key: str
    label: str
    charging_basis: str
    currency: str = ""
    section_id: str | None = None
    phase_id: str | None = None
    service_amount: Decimal = Decimal("0")
    rates: tuple[RateInput, ...] = ()
    charges: tuple[ChargeInput, ...] = ()
    section_rates: tuple[SectionRateInput, ...] = ()

    def rate_for(self, category: str) -> Decimal:
        for rate in self.rates:
            if rate.category == category:
                return Decimal(rate.unit_rate)
        return Decimal("0")


@dataclass(frozen=True)
class ConsumableLine:
    key: str
    label: str
    category: str
    section_id: str
    phase_id: str | None = None
    quantity: Decimal = Decimal("1")
    captured_rate: Decimal = Decimal("0")
    override_rate: Decimal | None = None
    estimated_amount: Decimal | None = None
    currency: str = ""


@dataclass(frozen=True)
class TangibleLine:
    key: str
    label: str
    quantity: Decimal = Decimal("1")
    captured_rate: Decimal = Decimal("0")
    override_rate: Decimal | None = None
    currency: str = ""
    uom: str = ""


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Component:
    group: str
    category: str
    description: str
    amount: Decimal
    section_id: str | None = None
    phase_id: str | None = None
    quantity: Decimal | None = None
    rate: Decimal | None = None
    unit: str = ""


@dataclass(frozen=True)
class LineResult:
    key: str
    group: str
    label: str
    amount: Decimal
    currency: str
    components: tuple[Component, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class SectionSummary:
    section_id: str | None
    label: str
    planned_days: Decimal
    services: Decimal
    consumables: Decimal
    tangibles: Decimal

    @property
    def total(self) -> Decimal:
        return money(self.services + self.consumables + self.tangibles)


@dataclass(frozen=True)
class EstimateResult:
    services: tuple[LineResult, ...]
    consumables: tuple[LineResult, ...]
    tangibles: tuple[LineResult, ...]
    by_section: tuple[SectionSummary, ...]
    services_total: Decimal
    consumables_total: Decimal
    tangibles_total: Decimal
    totals_by_currency: tuple[tuple[str, Decimal], ...]
    warnings: tuple[str, ...]

    @property
    def total(self) -> Decimal:
        return money(self.services_total + self.consumables_total + self.tangibles_total)


# ---------------------------------------------------------------------------
# Line pricing
# ---------------------------------------------------------------------------


def _section_text(section: SectionScope | None, phase: PhaseScope | None) -> str:
    return " · ".join(text for text in (section.label if section else "", phase.label if phase else "") if text) or "whole well"


def _day_component(
    category: str,
    days: Decimal,
    rate: Decimal,
    section: SectionScope | None,
    phase: PhaseScope | None,
    scope_label: str,
) -> Component:
    amount = money(days * rate)
    return Component(
        group=GROUP_SERVICES,
        category=category,
        description=f"{category} — {days} day(s) @ {_qty(rate)} · {scope_label}",
        amount=amount,
        section_id=section.section_id if section else None,
        phase_id=phase.phase_id if phase else None,
        quantity=days,
        rate=_qty(rate),
        unit="day",
    )


def _daily_components(line: ServiceLine, well: WellScope, warnings: list[str]) -> list[Component]:
    scope_section = well.section(line.section_id)
    scope_phase = scope_section.phase(line.phase_id) if scope_section else None
    entries: list[tuple[str, Decimal, Decimal]] = []
    explicit_operation = Decimal("0")

    for charge in line.charges:
        if charge.category in ONE_TIME_CATEGORIES:
            warnings.append(f"{charge.category} is a one-time charge; the entered quantity was ignored")
            continue
        days = normalize_days(charge.quantity, charge.unit)
        if days == 0:
            continue
        rate = line.rate_for(charge.category)
        if rate == 0:
            warnings.append(f"{charge.category}: {days} day(s) entered without a unit rate, so not priced")
            continue
        entries.append((charge.category, days, rate))
        if charge.category == "Operation":
            explicit_operation += days

    operation_rate = line.rate_for("Operation")
    if explicit_operation == 0 and operation_rate != 0:
        planned = well.planned_days(line.section_id, line.phase_id)
        if planned == 0:
            warnings.append("Operation rate entered but the well configuration has no planned days for this scope")
        else:
            entries.append(("Operation", planned, operation_rate))

    components: list[Component] = []
    for category, days, rate in entries:
        if line.section_id is not None:
            if scope_section is None:
                warnings.append("Section is not in the well configuration; days are shown as well-level")
            components.append(
                _day_component(
                    category,
                    days,
                    rate,
                    scope_section,
                    scope_phase,
                    _section_text(scope_section, scope_phase),
                )
            )
            continue

        # Well-wide: split across the configured sections by their planned days.
        weighted = [section for section in well.sections if section.days > 0]
        total_weight = sum((section.days for section in weighted), Decimal("0"))
        if total_weight == 0:
            warnings.append("Well-wide day rate has no planned days in the configuration to split across")
            components.append(_day_component(category, days, rate, None, None, WELL_LEVEL_LABEL))
            continue
        for section in weighted:
            share = _qty(days * section.days / total_weight)
            components.append(_day_component(category, share, rate, section, None, section.label))
    return components


def _one_time_components(line: ServiceLine, well: WellScope) -> list[Component]:
    section = well.section(line.section_id)
    phase = section.phase(line.phase_id) if section else None
    components: list[Component] = []
    for category in ONE_TIME_CATEGORIES:
        rate = line.rate_for(category)
        if rate == 0:
            continue
        components.append(
            Component(
                group=GROUP_SERVICES,
                category=category,
                description=f"{category} — charged once · {_section_text(section, phase)}",
                amount=money(rate),
                section_id=section.section_id if section else None,
                phase_id=phase.phase_id if phase else None,
                quantity=Decimal("1"),
                rate=_qty(rate),
                unit="lump sum",
            )
        )
    return components


def estimate_service(line: ServiceLine, well: WellScope) -> LineResult:
    warnings: list[str] = []
    section = well.section(line.section_id)
    phase = section.phase(line.phase_id) if section else None
    if line.section_id is not None and section is None:
        warnings.append("Section is not in the well configuration")
    if line.phase_id is not None:
        if section is None:
            warnings.append("Phase cannot be used without a section from the well configuration")
        elif phase is None:
            warnings.append("Phase is not planned under this section in the well configuration")

    components: list[Component] = []
    if line.charging_basis == BASIS_DAY_RATE:
        components.extend(_daily_components(line, well, warnings))
        components.extend(_one_time_components(line, well))
    elif line.charging_basis == BASIS_PER_SECTION:
        if not line.section_rates:
            warnings.append("Per Section Rate service has no section amount entered")
        for entry in line.section_rates:
            entry_section = well.section(entry.section_id)
            if entry_section is None:
                warnings.append("A section rate refers to a section that is not in the well configuration")
                continue
            entry_phase = None
            if entry.phase_id is not None:
                entry_phase = entry_section.phase(entry.phase_id)
                if entry_phase is None:
                    warnings.append(f"A section rate refers to a phase not planned under {entry_section.label}")
                    continue
            components.append(
                Component(
                    group=GROUP_SERVICES,
                    category="Per Section Rate",
                    description=f"Per section rate — {_section_text(entry_section, entry_phase)}",
                    amount=money(entry.amount),
                    section_id=entry_section.section_id,
                    phase_id=entry_phase.phase_id if entry_phase else None,
                    quantity=Decimal("1"),
                    rate=_qty(entry.amount),
                    unit="section",
                )
            )
    else:
        if line.service_amount == 0:
            warnings.append("Per Service Rate service has no price entered")
        components.append(
            Component(
                group=GROUP_SERVICES,
                category="Per Service Rate",
                description=f"Per service price — {_section_text(section, phase)}",
                amount=money(line.service_amount),
                section_id=section.section_id if section else None,
                phase_id=phase.phase_id if phase else None,
                quantity=Decimal("1"),
                rate=_qty(line.service_amount),
                unit="service",
            )
        )

    amount = money(sum((component.amount for component in components), Decimal("0")))
    return LineResult(
        key=line.key,
        group=GROUP_SERVICES,
        label=line.label,
        amount=amount,
        currency=line.currency,
        components=tuple(components),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def estimate_consumable(line: ConsumableLine, well: WellScope) -> LineResult:
    warnings: list[str] = []
    section = well.section(line.section_id)
    if section is None:
        warnings.append("Section is not in the well configuration; priced as well-level")
    phase = None
    if line.phase_id is not None:
        phase = section.phase(line.phase_id) if section else None
        if phase is None:
            warnings.append("Phase is not planned under this section in the well configuration")
    scope = _section_text(section, phase)

    if line.category == CONSUMABLE_DRILL_BITS:
        rate = effective_rate(line.captured_rate, line.override_rate)
        if rate == 0:
            warnings.append("Drill bit has no unit rate in master data and no override entered")
        amount = money(Decimal(line.quantity) * rate)
        component = Component(
            group=GROUP_CONSUMABLES,
            category=CONSUMABLE_DRILL_BITS,
            description=f"{line.label} — {line.quantity} bit(s) @ {money(rate)} · {scope}",
            amount=amount,
            section_id=section.section_id if section else None,
            phase_id=phase.phase_id if phase else None,
            quantity=Decimal(line.quantity),
            rate=_qty(rate),
            unit="bit",
        )
    else:
        estimate = Decimal(line.estimated_amount or 0)
        if estimate == 0:
            warnings.append(f"{line.category} has no estimated amount entered")
        amount = money(estimate)
        component = Component(
            group=GROUP_CONSUMABLES,
            category=line.category,
            description=f"{line.category} — lump-sum estimate · {scope}",
            amount=amount,
            section_id=section.section_id if section else None,
            phase_id=phase.phase_id if phase else None,
            unit="lump sum",
        )

    return LineResult(
        key=line.key,
        group=GROUP_CONSUMABLES,
        label=line.label,
        amount=amount,
        currency=line.currency,
        components=(component,),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def estimate_tangible(line: TangibleLine) -> LineResult:
    warnings: list[str] = []
    rate = effective_rate(line.captured_rate, line.override_rate)
    if rate == 0:
        warnings.append("No unit rate captured from master data and no override entered")
    amount = money(Decimal(line.quantity) * rate)
    overridden = line.override_rate is not None
    component = Component(
        group=GROUP_TANGIBLES,
        category="Override rate" if overridden else "Captured rate",
        description=f"{line.label} — {line.quantity} {line.uom or 'unit'} @ {money(rate)}",
        amount=amount,
        quantity=Decimal(line.quantity),
        rate=_qty(rate),
        unit=line.uom,
    )
    return LineResult(
        key=line.key,
        group=GROUP_TANGIBLES,
        label=line.label,
        amount=amount,
        currency=line.currency,
        components=(component,),
        warnings=tuple(dict.fromkeys(warnings)),
    )


# ---------------------------------------------------------------------------
# Estimate compilation
# ---------------------------------------------------------------------------


def compile_estimate(
    well: WellScope,
    services: Sequence[ServiceLine] = (),
    consumables: Sequence[ConsumableLine] = (),
    tangibles: Sequence[TangibleLine] = (),
) -> EstimateResult:
    service_results = tuple(estimate_service(line, well) for line in services)
    consumable_results = tuple(estimate_consumable(line, well) for line in consumables)
    tangible_results = tuple(estimate_tangible(line) for line in tangibles)

    configured = {section.section_id for section in well.sections}
    buckets: dict[str | None, dict[str, Decimal]] = {
        section.section_id: {GROUP_SERVICES: Decimal("0"), GROUP_CONSUMABLES: Decimal("0"), GROUP_TANGIBLES: Decimal("0")}
        for section in well.sections
    }
    buckets[None] = {GROUP_SERVICES: Decimal("0"), GROUP_CONSUMABLES: Decimal("0"), GROUP_TANGIBLES: Decimal("0")}
    for result in (*service_results, *consumable_results, *tangible_results):
        for component in result.components:
            bucket_id = component.section_id if component.section_id in configured else None
            buckets[bucket_id][component.group] += component.amount

    by_section = [
        SectionSummary(
            section_id=section.section_id,
            label=section.label,
            planned_days=section.days,
            services=money(buckets[section.section_id][GROUP_SERVICES]),
            consumables=money(buckets[section.section_id][GROUP_CONSUMABLES]),
            tangibles=money(buckets[section.section_id][GROUP_TANGIBLES]),
        )
        for section in well.sections
    ]
    well_level = buckets[None]
    if any(value != 0 for value in well_level.values()):
        by_section.append(
            SectionSummary(
                section_id=None,
                label=WELL_LEVEL_LABEL,
                planned_days=Decimal("0"),
                services=money(well_level[GROUP_SERVICES]),
                consumables=money(well_level[GROUP_CONSUMABLES]),
                tangibles=money(well_level[GROUP_TANGIBLES]),
            )
        )

    services_total = money(sum((result.amount for result in service_results), Decimal("0")))
    consumables_total = money(sum((result.amount for result in consumable_results), Decimal("0")))
    tangibles_total = money(sum((result.amount for result in tangible_results), Decimal("0")))

    currency_totals: dict[str, Decimal] = {}
    for result in (*service_results, *consumable_results, *tangible_results):
        currency_totals[result.currency] = currency_totals.get(result.currency, Decimal("0")) + result.amount
    totals_by_currency = tuple(
        (currency, money(amount)) for currency, amount in sorted(currency_totals.items(), key=lambda item: item[0])
    )

    warnings: list[str] = []
    for result in (*service_results, *consumable_results, *tangible_results):
        warnings.extend(f"{result.label}: {text}" for text in result.warnings)
    named_currencies = [currency or "no currency" for currency, _ in totals_by_currency]
    if len(named_currencies) > 1:
        warnings.append(
            f"Estimate mixes currencies ({', '.join(named_currencies)}); the grand total adds the amounts as entered"
        )

    return EstimateResult(
        services=service_results,
        consumables=consumable_results,
        tangibles=tangible_results,
        by_section=tuple(by_section),
        services_total=services_total,
        consumables_total=consumables_total,
        tangibles_total=tangibles_total,
        totals_by_currency=totals_by_currency,
        warnings=tuple(dict.fromkeys(warnings)),
    )

