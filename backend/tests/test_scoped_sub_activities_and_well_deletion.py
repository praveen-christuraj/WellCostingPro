"""End-to-end integration tests for scoped Well Sub Activities and per-scope Well deletion."""
import os
import tempfile

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import Organization, Permission, Role, User


PERMISSIONS = [
    *(f"daily-cost:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export", "submit", "reopen",
    )),
    *(f"afe:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
        "estimate", "submit", "review", "approve", "reopen",
    )),
    *(f"rig-well:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
    )),
    *(f"master-data:{action}" for action in (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
    )),
    "audit:read",
]


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        organization = Organization(slug="north", name="North Energy")
        db.add(organization)
        db.flush()
        permissions = [Permission(organization_id=organization.id, key=key, description=key) for key in PERMISSIONS]
        owner_role = Role(organization_id=organization.id, name="Owner", is_owner=True, permissions=permissions)
        db.add(User(
            organization_id=organization.id,
            email="owner@example.com",
            full_name="Test Owner",
            password_hash=hash_password("correct-password-123"),
            roles=[owner_role],
        ))
        db.commit()
    yield


def login(client: TestClient, organization: str = "north", email: str = "owner@example.com") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"organization": organization, "email": email, "password": "correct-password-123"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _bootstrap_master_data(client: TestClient, headers: dict[str, str]):
    currency = client.post(
        "/api/v1/master-data/currencies",
        headers=headers,
        json={"code": "USD", "name": "US Dollar", "symbol": "$"},
    )
    assert currency.status_code == 201, currency.text

    rig = client.post(
        "/api/v1/rig-well/rigs",
        headers=headers,
        json={"rig_code": "RIG-SCOPE-01", "rig_name": "Scope Test Rig", "remarks": ""},
    )
    assert rig.status_code == 201, rig.text

    block = client.post(
        "/api/v1/rig-well/blocks",
        headers=headers,
        json={"block_code": "BLK-SCOPE-01", "block_name": "Scope Test Block", "description": ""},
    )
    assert block.status_code == 201, block.text

    hole = client.post(
        "/api/v1/master-data/hole-sections",
        headers=headers,
        json={"code": "HS-175", "name": "Surface hole"},
    )
    assert hole.status_code == 201, hole.text

    phase = client.post(
        "/api/v1/master-data/phases",
        headers=headers,
        json={"code": "PH-DRL", "name": "Drilling Phase"},
    )
    assert phase.status_code == 201, phase.text

    activity = client.post(
        "/api/v1/master-data/activities",
        headers=headers,
        json={"code": "ACT-DRL", "name": "Planned Operations"},
    )
    assert activity.status_code == 201, activity.text

    vendor = client.post(
        "/api/v1/master-data/vendors",
        headers=headers,
        json={"vendor_code": "VND-SCOPE-01", "vendor_name": "Scope Oilfield Services", "category": "Drilling", "status": "active"},
    )
    assert vendor.status_code == 201, vendor.text

    service = client.post(
        "/api/v1/master-data/services",
        headers=headers,
        json={
            "service_code": "SRV-SCOPE-01",
            "service_name": "Rig Day Rate",
            "service_category": "Drilling Services",
            "service_group": "Formation Evaluation",
            "provider_type": "Third Party Services",
            "vendor_id": vendor.json()["id"],
            "description": "Rig service",
        },
    )
    assert service.status_code == 201, service.text

    return {
        "rig": rig.json(),
        "block": block.json(),
        "hole": hole.json(),
        "phase": phase.json(),
        "activity": activity.json(),
        "vendor": vendor.json(),
        "service": service.json(),
    }


def _configure_well_scope(client: TestClient, headers: dict[str, str], well_id: str, hole_id: str, phase_id: str, scope: str):
    saved = client.put(
        f"/api/v1/rig-well/wells/{well_id}/configuration",
        headers=headers,
        json={
            "scope": scope,
            "depth_unit": "m",
            "sections": [{
                "hole_section_id": hole_id,
                "from_depth": "0",
                "to_depth": "1500",
                "remarks": f"{scope} section",
                "phases": [{"phase_id": phase_id, "days": "10", "remarks": f"{scope} phase"}],
            }],
        },
    )
    assert saved.status_code == 200, saved.text
    configured = client.post(
        f"/api/v1/rig-well/wells/{well_id}/transition",
        headers=headers,
        json={"scope": scope, "action": "configure", "remarks": f"Sign off {scope} baseline"},
    )
    assert configured.status_code == 200, configured.text


def _create_afe_with_estimate(client: TestClient, headers: dict[str, str], rig_id: str, well_id: str, service_id: str, code: str, scope: str):
    afe = client.post(
        "/api/v1/afe/afes",
        headers=headers,
        json={
            "rig_id": rig_id,
            "well_id": well_id,
            "afe_code": code,
            "afe_name": f"{scope.title()} AFE",
            "afe_type": "Completion" if scope == "completion" else "Drilling",
            "configuration_scope": scope,
            "remarks": f"{scope} budget",
        },
    )
    assert afe.status_code in (200, 201), afe.text
    afe_id = afe.json()["id"]

    estimate = client.put(
        f"/api/v1/afe/afes/{afe_id}/estimate",
        headers=headers,
        json={
            "standard_currency": "USD",
            "exchange_rates": [],
            "services": [{
                "client_key": "service-day",
                "service_id": service_id,
                "charging_basis": "Day Rate",
                "hole_section_id": None,
                "phase_id": None,
                "currency": "USD",
                "service_amount": "0",
                "remarks": "",
                "rates": [{"category": "Operation", "unit_rate": "25000"}],
                "charges": [{"category": "Operation", "quantity": "10", "quantity_unit": "days"}],
                "section_rates": [],
            }],
            "consumables": [],
            "tangibles": [],
        },
    )
    assert estimate.status_code == 200, estimate.text
    return afe.json()


def test_sub_activities_and_well_deletion_are_strictly_scope_specific():
    with TestClient(app) as client:
        headers = login(client)
        seed = _bootstrap_master_data(client, headers)

        # 1. Create a well that starts with both Drilling and Completion scopes.
        well_resp = client.post(
            "/api/v1/rig-well/wells",
            headers=headers,
            json={
                "rig_id": seed["rig"]["id"],
                "block_id": seed["block"]["id"],
                "well_code": "WELL-DRL-ONLY",
                "well_name": "Drilling Only Appraisal Well",
                "well_location": "OML North",
                "objective": "Drilling appraisal without completion",
            },
        )
        assert well_resp.status_code == 201, well_resp.text
        well_id = well_resp.json()["id"]

        # 2. Configure ONLY the Drilling scope, add Drilling sub-activities, AFE and a Daily Cost sheet.
        _configure_well_scope(client, headers, well_id, seed["hole"]["id"], seed["phase"]["id"], "drilling")

        drl_sub_1 = client.post(
            "/api/v1/rig-well/sub-activities",
            headers=headers,
            json={
                "well_id": well_id,
                "scope": "drilling",
                "sub_activity_code": "ops-01",
                "sub_activity_name": "Drill 17.5 in surface hole",
                "activity_id": seed["activity"]["id"],
                "responsible_party": "Not Applicable",
                "description": "Rotary drilling step",
            },
        )
        assert drl_sub_1.status_code == 201, drl_sub_1.text
        assert drl_sub_1.json()["scope"] == "drilling"
        assert drl_sub_1.json()["sub_activity_code"] == "OPS-01"

        # Duplicate code within the SAME scope is rejected (409), while the SAME code in Completion succeeds (201).
        dup_same_scope = client.post(
            "/api/v1/rig-well/sub-activities",
            headers=headers,
            json={
                "well_id": well_id,
                "scope": "drilling",
                "sub_activity_code": "OPS-01",
                "sub_activity_name": "Duplicate in drilling",
                "activity_id": seed["activity"]["id"],
                "responsible_party": "Not Applicable",
                "description": "Should conflict",
            },
        )
        assert dup_same_scope.status_code == 409

        comp_sub_same_code = client.post(
            "/api/v1/rig-well/sub-activities",
            headers=headers,
            json={
                "well_id": well_id,
                "scope": "completion",
                "sub_activity_code": "OPS-01",
                "sub_activity_name": "Run completion string",
                "activity_id": seed["activity"]["id"],
                "responsible_party": "Not Applicable",
                "description": "Completion step with identical code",
            },
        )
        assert comp_sub_same_code.status_code == 201, comp_sub_same_code.text
        assert comp_sub_same_code.json()["scope"] == "completion"

        # Scoped listing isolates Drilling vs Completion cleanly and per-scope counts match.
        drl_list = client.get(f"/api/v1/rig-well/sub-activities?well_id={well_id}&scope=drilling", headers=headers).json()
        comp_list = client.get(f"/api/v1/rig-well/sub-activities?well_id={well_id}&scope=completion", headers=headers).json()
        assert [row["id"] for row in drl_list] == [drl_sub_1.json()["id"]]
        assert [row["id"] for row in comp_list] == [comp_sub_same_code.json()["id"]]

        well_now = client.get("/api/v1/rig-well/wells", headers=headers).json()[0]
        assert well_now["drilling_sub_activity_count"] == 1
        assert well_now["completion_sub_activity_count"] == 1
        assert well_now["sub_activity_count"] == 2

        # 3. Create Drilling AFE + Daily Cost sheet referencing the Drilling sub-activity.
        drl_afe = _create_afe_with_estimate(client, headers, seed["rig"]["id"], well_id, seed["service"]["id"], "AFE-DRL-001", "drilling")
        entry = client.post(
            "/api/v1/daily-cost/entries",
            headers=headers,
            json={"well_id": well_id, "afe_id": drl_afe["id"], "cost_date": "2026-10-01", "remarks": "Day 1 drilling"},
        )
        assert entry.status_code in (200, 201), entry.text
        entry_id = entry.json()["entry"]["id"]
        baseline = client.get(f"/api/v1/daily-cost/entries/{entry_id}/baseline", headers=headers).json()
        rate = baseline["service_rates"][0]

        # Cross-scope guard: a Drilling daily cost sheet rejects a Completion sub-activity (422)!
        cross_scope_save = client.put(
            f"/api/v1/daily-cost/entries/{entry_id}",
            headers=headers,
            json={
                "remarks": "Cross-scope sub activity attempt",
                "services": [{
                    "activity_id": seed["activity"]["id"],
                    "hole_section_id": None,
                    "phase_id": None,
                    "sub_activity_id": comp_sub_same_code.json()["id"],
                    "vendor_id": seed["vendor"]["id"],
                    "quantity": "1",
                    "quantity_unit": "days",
                    "currency": "USD",
                    "override_rate": None,
                    "override_reason": "",
                    "remarks": "",
                    "service_id": seed["service"]["id"],
                    "baseline_service_rate_id": rate["id"],
                    "charging_basis": "Day Rate",
                    "charge_category": "Operation",
                }],
                "consumables": [],
                "tangibles": [],
            },
        )
        assert cross_scope_save.status_code == 422, cross_scope_save.text

        # Matching Drilling sub-activity saves cleanly (200).
        valid_save = client.put(
            f"/api/v1/daily-cost/entries/{entry_id}",
            headers=headers,
            json={
                "remarks": "Valid drilling daily line",
                "services": [{
                    "activity_id": seed["activity"]["id"],
                    "hole_section_id": None,
                    "phase_id": None,
                    "sub_activity_id": drl_sub_1.json()["id"],
                    "vendor_id": seed["vendor"]["id"],
                    "quantity": "1",
                    "quantity_unit": "days",
                    "currency": "USD",
                    "override_rate": None,
                    "override_reason": "",
                    "remarks": "",
                    "service_id": seed["service"]["id"],
                    "baseline_service_rate_id": rate["id"],
                    "charging_basis": "Day Rate",
                    "charge_category": "Operation",
                }],
                "consumables": [],
                "tangibles": [],
            },
        )
        assert valid_save.status_code == 200, valid_save.text

        # 4. While Completion still has an active Completion sub-activity, deleting Completion scope blocks with 409.
        blocked_comp_delete = client.delete(f"/api/v1/rig-well/wells/{well_id}?scope=completion", headers=headers)
        assert blocked_comp_delete.status_code == 409

        # Remove and purge ONLY the Completion sub-activity; Drilling retains its sub-activity, AFE AND daily cost sheet!
        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{comp_sub_same_code.json()['id']}?well_id={well_id}",
            headers=headers,
        ).status_code == 200
        assert client.delete(
            f"/api/v1/rig-well/sub-activities/{comp_sub_same_code.json()['id']}/permanent",
            headers=headers,
        ).status_code == 204

        # 5. Deleting Drilling scope MUST STILL FAIL (409) because Drilling has active sub-activities, AFEs and daily costs.
        blocked_drl_delete = client.delete(f"/api/v1/rig-well/wells/{well_id}?scope=drilling", headers=headers)
        assert blocked_drl_delete.status_code == 409

        # 6. Deleting Completion scope SUCCEEDS (200) even though Drilling has configured sections + sub-activities + AFE + daily cost!
        deleted_comp = client.delete(f"/api/v1/rig-well/wells/{well_id}?scope=completion", headers=headers)
        assert deleted_comp.status_code == 200, deleted_comp.text

        wells_after = client.get("/api/v1/rig-well/wells", headers=headers).json()
        assert len(wells_after) == 1
        assert wells_after[0]["drilling_is_deleted"] is False
        assert wells_after[0]["completion_is_deleted"] is True
        assert wells_after[0]["is_deleted"] is False
        assert wells_after[0]["drilling_sub_activity_count"] == 1
        assert wells_after[0]["completion_sub_activity_count"] == 0

        # Deleted Entries lists ONLY the deleted Completion scope of the well.
        deleted_entries = client.get("/api/v1/rig-well/deleted", headers=headers).json()
        assert len(deleted_entries) == 1
        assert deleted_entries[0]["entity_type"] == "well"
        assert deleted_entries[0]["id"] == well_id
        assert deleted_entries[0]["scope"] == "completion"
        assert "Completion" in deleted_entries[0]["name"]

        # Deleted Completion scope blocks new sub-activities and AFEs on Completion while Drilling stays usable.
        assert client.post(
            "/api/v1/rig-well/sub-activities",
            headers=headers,
            json={
                "well_id": well_id,
                "scope": "completion",
                "sub_activity_code": "COMP-BLOCKED",
                "sub_activity_name": "Blocked on deleted scope",
                "activity_id": seed["activity"]["id"],
                "responsible_party": "Not Applicable",
                "description": "Blocked",
            },
        ).status_code == 409

        # 7. Restore Completion scope, delete it again, and permanently purge ONLY Completion scope.
        assert client.post(f"/api/v1/rig-well/wells/{well_id}/restore?scope=completion", headers=headers).status_code == 200
        assert client.get("/api/v1/rig-well/wells", headers=headers).json()[0]["completion_is_deleted"] is False

        assert client.delete(f"/api/v1/rig-well/wells/{well_id}?scope=completion", headers=headers).status_code == 200
        purged_comp = client.delete(f"/api/v1/rig-well/wells/{well_id}/permanent?scope=completion", headers=headers)
        assert purged_comp.status_code == 204, purged_comp.text

        # Deleted Entries is now completely clear, while the well's Drilling scope + daily sheet are 100% intact!
        assert client.get("/api/v1/rig-well/deleted", headers=headers).json() == []
        well_post_purge = client.get("/api/v1/rig-well/wells", headers=headers).json()[0]
        assert well_post_purge["drilling_is_deleted"] is False
        assert well_post_purge["completion_is_deleted"] is True
        assert well_post_purge["completion_purged"] is True
        assert client.get(f"/api/v1/daily-cost/entries/{entry_id}", headers=headers).status_code == 200

        # 8. Re-activating Completion scope later restores it cleanly as an active draft scope.
        reactivated = client.post(f"/api/v1/rig-well/wells/{well_id}/scopes/completion/activate", headers=headers)
        assert reactivated.status_code == 200, reactivated.text
        assert reactivated.json()["completion_is_deleted"] is False
        assert reactivated.json()["completion_purged"] is False

        # 9. Creating a new single-scope well directly with scopes=['drilling'] marks Completion omitted from day one.
        single_scope_well = client.post(
            "/api/v1/rig-well/wells",
            headers=headers,
            json={
                "rig_id": seed["rig"]["id"],
                "block_id": seed["block"]["id"],
                "well_code": "WELL-SINGLE-SCOPE",
                "well_name": "Single Scope Well",
                "well_location": "OML East",
                "objective": "Exploration",
                "scopes": ["drilling"],
            },
        )
        assert single_scope_well.status_code == 201, single_scope_well.text
        assert single_scope_well.json()["drilling_is_deleted"] is False
        assert single_scope_well.json()["completion_is_deleted"] is True
        assert single_scope_well.json()["completion_purged"] is True

        # 10. Scoped CSV import and scoped bulk delete isolate Drilling vs Completion on a dual-scope well,
        # and deleting BOTH scopes individually emits two distinct Deleted Entries rows that can be restored
        # or purged independently until the whole well record disappears cleanly.
        dual = client.post(
            "/api/v1/rig-well/wells",
            headers=headers,
            json={
                "rig_id": seed["rig"]["id"],
                "block_id": seed["block"]["id"],
                "well_code": "WELL-DUAL-LIFECYCLE",
                "well_name": "Dual Scope Lifecycle Well",
                "well_location": "OML West",
                "objective": "Development",
            },
        ).json()
        dual_id = dual["id"]

        imp_drl = client.post(
            f"/api/v1/rig-well/sub-activities/import?well_id={dual_id}&scope=drilling",
            headers=headers,
            json={"rows": [{
                "sub_activity_code": "STEP-01",
                "sub_activity_name": "Drill pilot hole",
                "activity": "ACT-DRL",
                "responsible_party": "Not Applicable",
                "description": "Drilling import row",
            }]},
        )
        assert imp_drl.status_code == 200 and imp_drl.json()["imported_count"] == 1

        imp_comp = client.post(
            f"/api/v1/rig-well/sub-activities/import?well_id={dual_id}&scope=completion",
            headers=headers,
            json={"rows": [{
                "sub_activity_code": "STEP-01",
                "sub_activity_name": "Run packer assembly",
                "activity": "ACT-DRL",
                "responsible_party": "Not Applicable",
                "description": "Completion import row",
            }]},
        )
        assert imp_comp.status_code == 200 and imp_comp.json()["imported_count"] == 1

        drl_rows = client.get(f"/api/v1/rig-well/sub-activities?well_id={dual_id}&scope=drilling", headers=headers).json()
        comp_rows = client.get(f"/api/v1/rig-well/sub-activities?well_id={dual_id}&scope=completion", headers=headers).json()
        assert len(drl_rows) == 1 and drl_rows[0]["sub_activity_name"] == "Drill pilot hole"
        assert len(comp_rows) == 1 and comp_rows[0]["sub_activity_name"] == "Run packer assembly"

        # Bulk-deleting Completion sub-activities leaves Drilling sub-activities untouched!
        assert client.post(
            f"/api/v1/rig-well/sub-activities/bulk-delete?well_id={dual_id}&scope=completion",
            headers=headers,
            json={"ids": [comp_rows[0]["id"]]},
        ).status_code == 200
        assert len(client.get(f"/api/v1/rig-well/sub-activities?well_id={dual_id}&scope=drilling", headers=headers).json()) == 1
        assert len(client.get(f"/api/v1/rig-well/sub-activities?well_id={dual_id}&scope=completion", headers=headers).json()) == 0

        # Clean up sub-activities and bulk-delete BOTH scopes of WELL-DUAL-LIFECYCLE via scoped items.
        assert client.post(
            f"/api/v1/rig-well/sub-activities/bulk-delete?well_id={dual_id}&scope=drilling",
            headers=headers,
            json={"ids": [drl_rows[0]["id"]]},
        ).status_code == 200
        assert client.post(
            "/api/v1/rig-well/deleted/bulk-permanent-delete",
            headers=headers,
            json={"records": [
                {"entity_type": "well_sub_activity", "id": drl_rows[0]["id"]},
                {"entity_type": "well_sub_activity", "id": comp_rows[0]["id"]},
            ]},
        ).status_code == 200

        bulk_del = client.post(
            "/api/v1/rig-well/wells/bulk-delete",
            headers=headers,
            json={"items": [
                {"id": dual_id, "scope": "drilling"},
                {"id": dual_id, "scope": "completion"},
            ]},
        )
        assert bulk_del.status_code == 200 and bulk_del.json()["affected_count"] == 2

        deleted_scopes = [
            row for row in client.get("/api/v1/rig-well/deleted", headers=headers).json()
            if row["id"] == dual_id
        ]
        assert {row["scope"] for row in deleted_scopes} == {"drilling", "completion"}

        # Purge ONLY Completion first -> Drilling still remains in Deleted Entries; then purge Drilling -> Well row removed!
        assert client.delete(f"/api/v1/rig-well/wells/{dual_id}/permanent?scope=completion", headers=headers).status_code == 204
        remaining_deleted = [
            row for row in client.get("/api/v1/rig-well/deleted", headers=headers).json()
            if row["id"] == dual_id
        ]
        assert [row["scope"] for row in remaining_deleted] == ["drilling"]

        assert client.delete(f"/api/v1/rig-well/wells/{dual_id}/permanent?scope=drilling", headers=headers).status_code == 204
        assert [row for row in client.get("/api/v1/rig-well/deleted", headers=headers).json() if row["id"] == dual_id] == []
        assert all(w["id"] != dual_id for w in client.get("/api/v1/rig-well/wells", headers=headers).json())
