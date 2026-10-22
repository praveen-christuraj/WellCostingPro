"""End-to-end verification of standardized meter depths (feet / 3.281),
daily cost register actual depth entry (last-entered per date/well/section),
and USD default/standard currency conversion across all wells.
"""

import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.core.units import FEET_PER_METER, depth_to_meters
from app.main import app
from app.models import Organization, Role, User
from app.services import provisioning


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for slug in ("north", "south"):
            provisioning.provision(
                slug,
                f"{slug.title()} Energy",
                "admin@example.com",
                "correct-password-123",
                "Admin User",
                db=db,
            )
        db.commit()


def _login(client: TestClient, slug: str = "north") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "organization": slug,
            "email": "admin@example.com",
            "password": "correct-password-123",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_depth_to_meters_uses_exact_3_281_factor():
    assert FEET_PER_METER == Decimal("3.281")
    assert depth_to_meters(Decimal("3281"), "ft") == Decimal("1000.00")
    assert depth_to_meters(Decimal("1640.5"), "feet") == Decimal("500.00")
    assert depth_to_meters(Decimal("750"), "m") == Decimal("750.00")
    assert depth_to_meters(None, "ft") is None


def test_mixed_ft_and_m_wells_last_entered_depth_and_usd_conversion_end_to_end():
    with TestClient(app) as client:
        headers = _login(client)

        # 1. Provisioned workspace seeds USD as the default currency automatically.
        currencies = client.get("/api/v1/master-data/currencies", headers=headers).json()
        usd_rows = [row for row in currencies if row["code"] == "USD"]
        assert len(usd_rows) == 1
        assert usd_rows[0]["is_default"] is True

        # Seed master data for two wells: WELL-FT (configured in feet) and WELL-M (configured in metres + GBP AFE).
        assert client.post(
            "/api/v1/master-data/currencies",
            headers=headers,
            json={"code": "GBP", "name": "British Pound", "symbol": "£"},
        ).status_code == 201
        assert client.post(
            "/api/v1/master-data/uom",
            headers=headers,
            json={"code": "MT", "name": "Metric tonne", "symbol": "MT"},
        ).status_code == 201
        rig = client.post(
            "/api/v1/rig-well/rigs",
            headers=headers,
            json={"rig_code": "RIG-STD", "rig_name": "Standard Rig", "remarks": ""},
        ).json()
        sec_surf = client.post(
            "/api/v1/master-data/hole-sections",
            headers=headers,
            json={"code": "17-1/2", "name": "Surface Hole"},
        ).json()
        sec_inter = client.post(
            "/api/v1/master-data/hole-sections",
            headers=headers,
            json={"code": "12-1/4", "name": "Intermediate Hole"},
        ).json()
        phase_drl = client.post(
            "/api/v1/master-data/phases",
            headers=headers,
            json={"code": "DRL", "name": "Drilling"},
        ).json()
        act_drl = client.post(
            "/api/v1/master-data/activities",
            headers=headers,
            json={"code": "DRL", "name": "Drilling Ahead"},
        ).json()
        vendor = client.post(
            "/api/v1/master-data/vendors",
            headers=headers,
            json={"vendor_code": "V-01", "vendor_name": "Apex Drilling Services", "category": "Drilling", "status": "active"},
        ).json()
        service = client.post(
            "/api/v1/master-data/services",
            headers=headers,
            json={
                "service_code": "SRV-RIG",
                "service_name": "Rig Day Rate",
                "service_category": "Drilling Services",
                "provider_type": "Third Party Services",
                "vendor_id": vendor["id"],
                "description": "Rig day rate",
            },
        ).json()
        group = client.post(
            "/api/v1/master-data/catalogue-options",
            headers=headers,
            json={"list_key": "mud_chemical_group", "value": "Weighting agent"},
        ).json()
        chem = client.post(
            "/api/v1/master-data/mud-chemicals",
            headers=headers,
            json={
                "chemical_code": "BAR-01",
                "chemical_name": "Barite",
                "group_id": group["id"],
                "part_number": "BAR-01",
                "uom": "MT",
                "unit_rate": "250.00",
                "currency": "USD",
                "effective_date": "2026-01-15",
            },
        ).json()

        # Create WELL-FT in feet: 0 -> 3281 ft (1000.00 m), 3281 -> 6562 ft (2000.00 m).
        block_b1 = client.post(
            "/api/v1/rig-well/blocks", headers=headers,
            json={"block_code": "B1", "block_name": "Block B1", "description": ""},
        ).json()
        well_ft = client.post(
            "/api/v1/rig-well/wells",
            headers=headers,
            json={
                "rig_id": rig["id"],
                "block_id": block_b1["id"],
                "well_code": "WELL-FT",
                "well_name": "Foot Well",
                "well_location": "Offshore Block 1",
                "objective": "Exploration",
                "remarks": "",
            },
        ).json()
        cfg_ft = client.put(
            f"/api/v1/rig-well/wells/{well_ft['id']}/configuration",
            headers=headers,
            json={
                "depth_unit": "ft",
                "sections": [
                    {
                        "hole_section_id": sec_surf["id"],
                        "from_depth": "0",
                        "to_depth": "3281",
                        "remarks": "",
                        "phases": [{"phase_id": phase_drl["id"], "days": "5", "remarks": ""}],
                    },
                    {
                        "hole_section_id": sec_inter["id"],
                        "from_depth": "3281",
                        "to_depth": "6562",
                        "remarks": "",
                        "phases": [{"phase_id": phase_drl["id"], "days": "7", "remarks": ""}],
                    },
                ],
            },
        )
        assert cfg_ft.status_code == 200, cfg_ft.text
        cfg_ft_data = cfg_ft.json()
        assert cfg_ft_data["depth_unit"] == "ft"
        assert cfg_ft_data["standard_depth_unit"] == "m"
        assert Decimal(cfg_ft_data["total_depth_m"]) == Decimal("2000.00")
        assert Decimal(cfg_ft_data["sections"][0]["to_depth_m"]) == Decimal("1000.00")
        assert Decimal(cfg_ft_data["sections"][1]["to_depth_m"]) == Decimal("2000.00")
        assert client.post(
            f"/api/v1/rig-well/wells/{well_ft['id']}/transition",
            headers=headers,
            json={"action": "configure", "remarks": "Configured"},
        ).status_code == 200
        sub_ft_id = client.post(
            "/api/v1/rig-well/sub-activities",
            headers=headers,
            json={
                "well_id": well_ft["id"],
                "sub_activity_code": "SA-DRL-FT",
                "sub_activity_name": "Drill Surface/Inter",
                "activity_id": act_drl["id"],
                "responsible_party": "Operator",
                "description": "Drill surface & intermediate",
            },
        ).json()["id"]

        # Create WELL-M in metres: 0 -> 500 m.
        block_b2 = client.post(
            "/api/v1/rig-well/blocks", headers=headers,
            json={"block_code": "B2", "block_name": "Block B2", "description": ""},
        ).json()
        well_m = client.post(
            "/api/v1/rig-well/wells",
            headers=headers,
            json={
                "rig_id": rig["id"],
                "block_id": block_b2["id"],
                "well_code": "WELL-M",
                "well_name": "Metre Well",
                "well_location": "Offshore Block 2",
                "objective": "Development",
                "remarks": "",
            },
        ).json()
        cfg_m = client.put(
            f"/api/v1/rig-well/wells/{well_m['id']}/configuration",
            headers=headers,
            json={
                "depth_unit": "m",
                "sections": [
                    {
                        "hole_section_id": sec_surf["id"],
                        "from_depth": "0",
                        "to_depth": "500",
                        "remarks": "",
                        "phases": [{"phase_id": phase_drl["id"], "days": "4", "remarks": ""}],
                    }
                ],
            },
        )
        assert cfg_m.status_code == 200, cfg_m.text
        assert client.post(
            f"/api/v1/rig-well/wells/{well_m['id']}/transition",
            headers=headers,
            json={"action": "configure", "remarks": "Configured"},
        ).status_code == 200
        sub_m_id = client.post(
            "/api/v1/rig-well/sub-activities",
            headers=headers,
            json={
                "well_id": well_m["id"],
                "sub_activity_code": "SA-DRL-M",
                "sub_activity_name": "Drill Metre Well",
                "activity_id": act_drl["id"],
                "responsible_party": "Operator",
                "description": "Drill surface hole",
            },
        ).json()["id"]

        # Create & save AFE on WELL-FT leaving standard_currency="" -> defaults automatically to USD!
        afe_ft = client.post(
            "/api/v1/afe/afes",
            headers=headers,
            json={
                "rig_id": rig["id"],
                "well_id": well_ft["id"],
                "afe_code": "AFE-FT-USD",
                "afe_name": "Foot Drilling AFE",
                "afe_type": "Drilling",
                "remarks": "",
            },
        ).json()
        save_afe_ft = client.put(
            f"/api/v1/afe/afes/{afe_ft['id']}/estimate",
            headers=headers,
            json={
                "standard_currency": "",
                "exchange_rates": [],
                "services": [
                    {
                        "client_key": "srv-1",
                        "service_id": service["id"],
                        "charging_basis": "Day Rate",
                        "hole_section_id": sec_surf["id"],
                        "phase_id": phase_drl["id"],
                        "currency": "USD",
                        "service_amount": "0",
                        "remarks": "",
                        "rates": [{"category": "Operation", "unit_rate": "1000"}],
                        "charges": [{"category": "Operation", "quantity": "5", "quantity_unit": "days"}],
                        "section_rates": [],
                    }
                ],
                "consumables": [
                    {
                        "client_key": "cons-1",
                        "category": "Mud Chemicals",
                        "hole_section_id": sec_surf["id"],
                        "estimated_amount": "5000",
                        "currency": "USD",
                        "remarks": "",
                    }
                ],
                "tangibles": [],
            },
        )
        assert save_afe_ft.status_code == 200, save_afe_ft.text
        assert save_afe_ft.json()["summary"]["currency"]["standard_currency"] == "USD"
        assert Decimal(save_afe_ft.json()["well"]["total_depth_m"]) == Decimal("2000.00")

        afe_m = client.post(
            "/api/v1/afe/afes",
            headers=headers,
            json={
                "rig_id": rig["id"],
                "well_id": well_m["id"],
                "afe_code": "AFE-M-GBP",
                "afe_name": "Metre GBP AFE",
                "afe_type": "Drilling",
                "remarks": "",
            },
        ).json()
        save_afe_m = client.put(
            f"/api/v1/afe/afes/{afe_m['id']}/estimate",
            headers=headers,
            json={
                "standard_currency": "GBP",
                "exchange_rates": [],
                "services": [
                    {
                        "client_key": "srv-gbp",
                        "service_id": service["id"],
                        "charging_basis": "Day Rate",
                        "hole_section_id": sec_surf["id"],
                        "phase_id": phase_drl["id"],
                        "currency": "GBP",
                        "service_amount": "0",
                        "remarks": "",
                        "rates": [{"category": "Operation", "unit_rate": "800"}],
                        "charges": [{"category": "Operation", "quantity": "4", "quantity_unit": "days"}],
                        "section_rates": [],
                    }
                ],
                "consumables": [],
                "tangibles": [],
            },
        )
        assert save_afe_m.status_code == 200, save_afe_m.text

        # Create daily sheet on WELL-FT (USD) and verify:
        #   - EUR line without exchange_rate is rejected with 422 asking for USD conversion rate.
        #   - EUR line with exchange_rate=1.10 succeeds and converts to USD ($1,100.00).
        #   - Multiple depths entered on (2026-10-12, WELL-FT, 17-1/2) in feet take the LAST entered value,
        #     even when the last entered depth is shallower (2296.7 ft / 3.281 = 700.00 m after 2624.8 ft = 800.00 m).
        entry_ft = client.post(
            "/api/v1/daily-cost/entries",
            headers=headers,
            json={"well_id": well_ft["id"], "afe_id": afe_ft["id"], "cost_date": "2026-10-12"},
        )
        assert entry_ft.status_code == 201, entry_ft.text
        entry_ft_id = entry_ft.json()["entry"]["id"]
        rate_ft_id = client.get(
            f"/api/v1/daily-cost/entries/{entry_ft_id}/baseline", headers=headers
        ).json()["service_rates"][0]["id"]

        missing_fx = client.put(
            f"/api/v1/daily-cost/entries/{entry_ft_id}",
            headers=headers,
            json={
                "remarks": "Missing FX test",
                "services": [],
                "consumables": [],
                "tangibles": [],
                "other_expenses": [
                    {
                        "activity_id": act_drl["id"],
                        "sub_activity_id": sub_ft_id,
                        "hole_section_id": sec_surf["id"],
                        "expense_type": "LIH",
                        "expense_description": "Stabilizer rental claim in EUR",
                        "quantity": "1",
                        "quantity_unit": "unit",
                        "unit_rate": "1000",
                        "currency": "EUR",
                        "remarks": "Stabilizer inspection charge billed in EUR",
                    }
                ],
            },
        )
        assert missing_fx.status_code == 422
        assert "currency" in missing_fx.json()["detail"].lower()

        saved_ft = client.put(
            f"/api/v1/daily-cost/entries/{entry_ft_id}",
            headers=headers,
            json={
                "remarks": "Drilling ahead & EUR claim",
                "services": [
                    {
                        "service_id": service["id"],
                        "baseline_service_rate_id": rate_ft_id,
                        "activity_id": act_drl["id"],
                        "sub_activity_id": sub_ft_id,
                        "hole_section_id": sec_surf["id"],
                        "phase_id": phase_drl["id"],
                        "charging_basis": "Day Rate",
                        "charge_category": "Operation",
                        "quantity": "1",
                        "quantity_unit": "days",
                        "currency": "USD",
                        "actual_depth": "1640.5",
                        "actual_depth_unit": "ft",
                    }
                ],
                "consumables": [
                    {
                        "category": "Mud Chemicals",
                        "item_kind": "mud_chemical",
                        "item_id": chem["id"],
                        "activity_id": act_drl["id"],
                        "sub_activity_id": sub_ft_id,
                        "hole_section_id": sec_surf["id"],
                        "quantity": "2",
                        "currency": "USD",
                        "actual_depth": "2624.8",
                        "actual_depth_unit": "ft",
                    }
                ],
                "tangibles": [],
                "other_expenses": [
                    {
                        "activity_id": act_drl["id"],
                        "sub_activity_id": sub_ft_id,
                        "hole_section_id": sec_surf["id"],
                        "expense_type": "LIH",
                        "expense_description": "Plug-back & EUR tool claim",
                        "quantity": "1",
                        "quantity_unit": "unit",
                        "unit_rate": "1000",
                        "currency": "EUR",
                        "exchange_rate": "1.10",
                        "actual_depth": "2296.7",
                        "actual_depth_unit": "ft",
                        "remarks": "Plugged back to 2296.7 ft and logged EUR claim",
                    }
                ],
            },
        )
        assert saved_ft.status_code == 200, saved_ft.text
        saved_ft_body = saved_ft.json()
        # 1640.5 ft -> 500.00 m, 2624.8 ft -> 800.00 m, 2296.7 ft -> 700.00 m (LAST entered wins!).
        assert Decimal(saved_ft_body["services"][0]["actual_depth"]) == Decimal("500.00")
        assert Decimal(saved_ft_body["consumables"][0]["actual_depth"]) == Decimal("800.00")
        assert Decimal(saved_ft_body["other_expenses"][0]["actual_depth"]) == Decimal("700.00")
        assert Decimal(saved_ft_body["entry"]["actual_depth"]) == Decimal("700.00")
        assert saved_ft_body["entry"]["depth_unit"] == "m"
        # 1000 USD service + 500 USD barite + 1100 USD (1000 EUR * 1.10) = 2600.00 USD
        assert Decimal(saved_ft_body["entry"]["total_cost"]) == Decimal("2600.00")
        assert Decimal(saved_ft_body["entry"]["total_cost_usd"]) == Decimal("2600.00")

        # Import another row on the same sheet/date/section with 2952.9 ft (= 900.00 m) ->
        # verifies existing feet depths do NOT double-divide AND new imported depth becomes last-entered!
        imp = client.post(
            f"/api/v1/daily-cost/entries/{entry_ft_id}/import",
            headers=headers,
            json={
                "rows": [
                    {
                        "line_type": "consumable",
                        "category": "Mud Chemicals",
                        "item_code": "BAR-01",
                        "activity_code": "DRL",
                        "sub_activity_code": "SA-DRL-FT",
                        "section_code": "17-1/2",
                        "quantity": "1",
                        "currency": "USD",
                        "actual_depth": "2952.9",
                        "actual_depth_unit": "ft",
                    }
                ],
            },
        )
        assert imp.status_code == 200, imp.text
        day_after_import = client.get(
            f"/api/v1/daily-cost/entries/{entry_ft_id}", headers=headers
        ).json()
        assert Decimal(day_after_import["services"][0]["actual_depth"]) == Decimal("500.00")
        assert Decimal(day_after_import["entry"]["actual_depth"]) == Decimal("900.00")

        # Record GBP sheet on WELL-M with usd_exchange_rate=1.25 (800 GBP * 1.25 = 1000.00 USD) and 320 m depth.
        entry_m = client.post(
            "/api/v1/daily-cost/entries",
            headers=headers,
            json={
                "well_id": well_m["id"],
                "afe_id": afe_m["id"],
                "cost_date": "2026-10-12",
                "usd_exchange_rate": "1.25",
            },
        )
        assert entry_m.status_code == 201, entry_m.text
        entry_m_id = entry_m.json()["entry"]["id"]
        rate_m_id = client.get(
            f"/api/v1/daily-cost/entries/{entry_m_id}/baseline", headers=headers
        ).json()["service_rates"][0]["id"]
        saved_m = client.put(
            f"/api/v1/daily-cost/entries/{entry_m_id}",
            headers=headers,
            json={
                "remarks": "Metre well day 1",
                "services": [
                    {
                        "service_id": service["id"],
                        "baseline_service_rate_id": rate_m_id,
                        "activity_id": act_drl["id"],
                        "sub_activity_id": sub_m_id,
                        "hole_section_id": sec_surf["id"],
                        "phase_id": phase_drl["id"],
                        "charging_basis": "Day Rate",
                        "charge_category": "Operation",
                        "quantity": "1",
                        "quantity_unit": "days",
                        "currency": "GBP",
                        "actual_depth": "320",
                        "actual_depth_unit": "m",
                    }
                ],
                "consumables": [],
                "tangibles": [],
                "other_expenses": [],
            },
        )
        assert saved_m.status_code == 200, saved_m.text
        assert Decimal(saved_m.json()["entry"]["total_cost"]) == Decimal("800.00")
        assert Decimal(saved_m.json()["entry"]["total_cost_usd"]) == Decimal("1000.00")
        assert Decimal(saved_m.json()["entry"]["actual_depth"]) == Decimal("320.00")

        # Verify Business Dashboard:
        #   - Default currency is USD
        #   - ZERO "Wells use different depth units" error!
        #   - Planned depth = 2000.00 m + 500.00 m = 2500.00 m
        #   - Actual depth = 900.00 m + 320.00 m = 1220.00 m
        #   - Standardized USD actual across BOTH wells = $2,850.00 + $1,000.00 = $3,850.00!
        dash = client.get("/api/v1/dashboard/business", headers=headers)
        assert dash.status_code == 200, dash.text
        dash_body = dash.json()
        assert dash_body["currency"] == "USD"
        assert dash_body["default_currency"] == "USD"
        assert all(alert["kind"] != "mixed_depth_units" for alert in dash_body["alerts"])
        assert all("different depth units" not in alert["title"] for alert in dash_body["alerts"])
        assert dash_body["kpis"]["depth_unit"] == "m"
        assert Decimal(dash_body["kpis"]["planned_depth"]) == Decimal("2500.00")
        assert Decimal(dash_body["kpis"]["actual_depth"]) == Decimal("1220.00")
        assert Decimal(dash_body["kpis"]["actual_amount"]) == Decimal("3850.00")

        by_code = {row["well_code"]: row for row in dash_body["wells"]}
        assert by_code["WELL-FT"]["depth_unit"] == "m"
        assert by_code["WELL-FT"]["configured_depth_unit"] == "ft"
        assert Decimal(by_code["WELL-FT"]["planned_depth"]) == Decimal("2000.00")
        assert Decimal(by_code["WELL-FT"]["actual_depth"]) == Decimal("900.00")
        assert Decimal(by_code["WELL-FT"]["actual_amount"]) == Decimal("2850.00")
        assert by_code["WELL-M"]["depth_unit"] == "m"
        assert Decimal(by_code["WELL-M"]["planned_depth"]) == Decimal("500.00")
        assert Decimal(by_code["WELL-M"]["actual_depth"]) == Decimal("320.00")
        assert Decimal(by_code["WELL-M"]["actual_amount"]) == Decimal("1000.00")
