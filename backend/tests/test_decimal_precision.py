"""Cross-module regression coverage for the ten-decimal entry contract."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Numeric

import app.models  # noqa: F401 - registers every model with Base.metadata
from app.core.database import Base
from app.core.precision import Decimal10
from app.core.units import depth_to_meters
from app.domain.afe_costing import money as afe_money
from app.schemas.afe import (
    ConsumableLineOut,
    ExchangeRateIn,
    ExchangeRateOut,
    RateIn,
    ServiceLineOut,
    TangibleLineOut,
)
from app.schemas.catalogue import FuelRevise
from app.schemas.daily_cost import DailyCostEntryCreate
from app.schemas.mud_cost import MudCostLineIn
from app.schemas.rig_well import ConfigurationPhaseIn, ConfigurationSectionIn
from app.schemas.sow_adjustment import AfeSowServiceLineIn, PlanPhaseIn
from app.services.catalogue import final_cost
from app.services.daily_cost import _fx, _money, _rate


TEN_PLACES = "1.1234567890"
ELEVEN_PLACES = "1.12345678901"


def test_shared_decimal_contract_accepts_ten_places_and_rejects_eleven():
    adapter = TypeAdapter(Decimal10)
    assert adapter.validate_python(TEN_PLACES) == Decimal(TEN_PLACES)
    with pytest.raises(ValidationError):
        adapter.validate_python(ELEVEN_PLACES)


@pytest.mark.parametrize(
    ("schema", "valid", "field"),
    [
        (ConfigurationPhaseIn, {"phase_id": "phase", "days": TEN_PLACES}, "days"),
        (
            ConfigurationSectionIn,
            {
                "hole_section_id": "section", "from_depth": TEN_PLACES, "to_depth": "2.1234567890",
                "phases": [{"phase_id": "phase", "days": "1"}],
            },
            "from_depth",
        ),
        (FuelRevise, {"unit_rate": TEN_PLACES, "currency": "USD", "reason": "precision correction"}, "unit_rate"),
        (RateIn, {"category": "Operation", "unit_rate": TEN_PLACES}, "unit_rate"),
        (ExchangeRateIn, {"currency_code": "EUR", "rate": TEN_PLACES}, "rate"),
        (MudCostLineIn, {"line_code": "opening_stock", "amount": TEN_PLACES}, "amount"),
        (
            DailyCostEntryCreate,
            {"well_id": "well", "afe_id": "afe", "cost_date": date(2026, 10, 20), "usd_exchange_rate": TEN_PLACES},
            "usd_exchange_rate",
        ),
        (
            AfeSowServiceLineIn,
            {
                "service_id": "service", "charging_basis": "Day Rate",
                "currency": "USD", "service_amount": TEN_PLACES,
            },
            "service_amount",
        ),
        (
            PlanPhaseIn,
            {"phase_id": "phase", "days": TEN_PLACES},
            "days",
        ),
    ],
)
def test_float_entry_schemas_share_the_ten_decimal_limit(schema, valid, field):
    assert getattr(schema.model_validate(valid), field) == Decimal(TEN_PLACES)
    invalid = {**valid, field: ELEVEN_PLACES}
    with pytest.raises(ValidationError):
        schema.model_validate(invalid)


def test_all_decimal_database_columns_retain_ten_places():
    decimal_columns = [
        column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Numeric)
    ]
    assert decimal_columns
    assert all((column.type.precision, column.type.scale) == (28, 10) for column in decimal_columns)


def test_calculation_helpers_do_not_round_before_ten_places():
    value = Decimal(TEN_PLACES)
    assert afe_money(value) == value
    assert _money(value) == value
    assert _rate(value) == value
    assert _fx(value) == value
    assert final_cost(value, Decimal("100")) == value
    assert depth_to_meters(value, "m") == value


@pytest.mark.parametrize(
    ("model", "values", "expected"),
    [
        (ServiceLineOut, {"service_amount": Decimal("0E-10")}, '"service_amount":"0.0000000000"'),
        (
            ConsumableLineOut,
            {
                "quantity": Decimal("12.0000000000"),
                "override_rate": Decimal("0E-10"),
                "estimated_amount": Decimal("0.7300000000"),
            },
            '"estimated_amount":"0.7300000000"',
        ),
        (TangibleLineOut, {"quantity": Decimal("1E+2")}, '"quantity":"100"'),
        (ExchangeRateOut, {"currency_code": "EUR", "rate": Decimal("1.2300000000")}, '"rate":"1.2300000000"'),
    ],
)
def test_afe_editable_decimal_responses_use_plain_notation(model, values, expected):
    serialized = model.model_construct(**values).model_dump_json()
    assert expected in serialized
    assert "E-" not in serialized
    assert "E+" not in serialized

