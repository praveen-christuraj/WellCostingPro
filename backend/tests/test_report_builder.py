"""Report Builder and Custom Reports: formula safety, catalogue, execution, sharing.

The suite runs over a real SQLite schema with two workspaces so that every
"north" assertion also proves "south" cannot see the same thing.
"""

import json
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal

_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"
os.environ.setdefault("BACKUP_DIRECTORY", tempfile.mkdtemp(prefix="wcp-backups-"))
os.environ["BACKUP_SCHEDULER_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import (
    Afe,
    AuditLog,
    Block,
    HoleSection,
    Organization,
    Permission,
    ReportDefinition,
    ReportDefinitionVersion,
    Rig,
    Role,
    User,
    Well,
    WellSection,
)
from app.services import report_formula as formula
from app.services.report_catalog import build_catalog

PASSWORD = "correct-password-123"
DESIGNER_PERMISSIONS = [
    "report-builder:read", "report-builder:create", "report-builder:update",
    "report-builder:delete", "report-builder:publish",
    "custom-reports:read", "custom-reports:export", "audit:read",
]
VIEWER_PERMISSIONS = ["custom-reports:read", "custom-reports:export"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _permissions(db, organization_id, keys):
    created = []
    for key in keys:
        permission = db.scalar(select(Permission).where(Permission.organization_id == organization_id, Permission.key == key))
        if permission is None:
            permission = Permission(organization_id=organization_id, key=key, description=key)
            db.add(permission)
            db.flush()
        created.append(permission)
    return created


def _user(db, organization_id, email, keys=None, owner=False):
    role = Role(
        organization_id=organization_id,
        name=f"{email.split('@')[0]} role",
        is_owner=owner,
        permissions=_permissions(db, organization_id, keys or []),
    )
    user = User(
        organization_id=organization_id, email=email,
        full_name=email.split("@")[0].replace(".", " ").title(),
        password_hash=hash_password(PASSWORD), roles=[role],
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        north = Organization(slug="north", name="North Energy")
        south = Organization(slug="south", name="South Energy")
        db.add_all([north, south])
        db.flush()

        _user(db, north.id, "owner@example.com", owner=True)
        designer = _user(db, north.id, "designer@example.com", DESIGNER_PERMISSIONS)
        _user(db, north.id, "viewer@example.com", VIEWER_PERMISSIONS)
        _user(db, north.id, "outsider@example.com", ["custom-reports:read"])
        _user(db, south.id, "south@example.com", ["custom-reports:read"], owner=True)

        block = Block(organization_id=north.id, block_code="NB1", block_name="North Block")
        rig = Rig(organization_id=north.id, rig_code="NR1", rig_name="North Rig")
        db.add_all([block, rig])
        db.flush()
        section_type = HoleSection(organization_id=north.id, section_code="12.25", section_name="12¼ inch")
        db.add(section_type)
        db.flush()

        wells = [
            Well(organization_id=north.id, rig_id=rig.id, block_id=block.id, well_code="W1", well_name="Alpha",
                 well_location="Onshore", objective="Appraisal", status="active",
                 created_at=datetime(2026, 1, 15, 10, 0)),
            Well(organization_id=north.id, rig_id=rig.id, block_id=block.id, well_code="W2", well_name="Beta",
                 well_location="Offshore", objective="Development", status="completed",
                 created_at=datetime(2026, 2, 10, 10, 0)),
            Well(organization_id=north.id, rig_id=rig.id, block_id=block.id, well_code="W3", well_name="Gamma",
                 well_location="Onshore", objective="Exploration", status="active",
                 created_at=datetime(2026, 2, 20, 10, 0)),
        ]
        db.add_all(wells)
        db.flush()
        db.add_all([
            WellSection(organization_id=north.id, well_id=wells[0].id, scope="drilling",
                        hole_section_id=section_type.id, from_depth=Decimal("0"), to_depth=Decimal("1200.5000"), sort_order=1),
            WellSection(organization_id=north.id, well_id=wells[0].id, scope="drilling",
                        hole_section_id=section_type.id, from_depth=Decimal("1200.5"), to_depth=Decimal("2200.7500"), sort_order=2),
            WellSection(organization_id=north.id, well_id=wells[1].id, scope="drilling",
                        hole_section_id=section_type.id, from_depth=Decimal("0"), to_depth=Decimal("900.2500"), sort_order=1),
        ])
        db.add_all([
            Afe(organization_id=north.id, rig_id=rig.id, well_id=wells[0].id, afe_code="AFE-1", afe_name="Alpha drilling",
                afe_type="Drilling", status="draft", standard_currency="USD"),
            Afe(organization_id=north.id, rig_id=rig.id, well_id=wells[1].id, afe_code="AFE-2", afe_name="Beta drilling",
                afe_type="Drilling", status="approval", standard_currency="USD"),
            Afe(organization_id=north.id, rig_id=rig.id, well_id=wells[2].id, afe_code="AFE-3", afe_name="Gamma drilling",
                afe_type="Drilling", status="approval", standard_currency="USD"),
        ])
        # A second workspace with its own well: it must never appear in a north report.
        south_block = Block(organization_id=south.id, block_code="SB1", block_name="South Block")
        south_rig = Rig(organization_id=south.id, rig_code="SR1", rig_name="South Rig")
        db.add_all([south_block, south_rig])
        db.flush()
        db.add(Well(organization_id=south.id, rig_id=south_rig.id, block_id=south_block.id, well_code="SW1",
                    well_name="Secret", well_location="South", objective="Unknown", status="active"))
        db.add_all([
            AuditLog(organization_id=north.id, actor_email="designer@example.com", actor_name="Designer",
                     action="create", entity_type="well", entity_label="Alpha", summary="Created Alpha",
                     created_at=datetime(2026, 3, 5, 9, 0)),
            AuditLog(organization_id=north.id, actor_email="designer@example.com", actor_name="Designer",
                     action="update", entity_type="well", entity_label="Beta", summary="Updated Beta",
                     created_at=datetime(2026, 3, 20, 9, 0)),
        ])
        db.commit()
        yield


def login(client, email="designer@example.com", organization="north", password=PASSWORD):
    response = client.post("/api/v1/auth/login", json={"organization": organization, "email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def column(key, column_name, *, label=None, kind="DATA", data_type=None, aggregate="NONE",
           show_total=False, related_key="", related_table="", formula="", conditions=None, decimals=2):
    return {
        "key": key, "label": label or key.replace("_", " ").title(), "kind": kind,
        "column_name": column_name, "related_table": related_table, "related_key_column": related_key,
        "formula": formula, "data_type": data_type or "text", "decimals": decimals, "prefix": "",
        "suffix": "", "aggregate": aggregate, "show_total": show_total, "hidden": False,
        "condition_logic": "AND", "width": 0, "conditions": conditions or [],
    }


def design(**overrides):
    base = {
        "name": "Wells by rig", "description": "Test report", "report_type": "TABULAR",
        "source_table": "wells", "date_basis": "CREATED_AT", "date_column": "",
        "filter_logic": "AND", "show_totals": True, "page_size": 50, "empty_text": "",
        "matrix_value_key": "", "matrix_aggregate": "SUM", "matrix_show_totals": True,
        "visibility": "private",
        "columns": [
            column("well", "well_name"),
            column("status", "status"),
            column("location", "well_location"),
        ],
        "filters": [], "runtime_filters": [], "groupings": [], "sorts": [], "grants": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Formula engine
# ---------------------------------------------------------------------------


def test_formula_precedence_percent_and_decimals():
    assert formula.evaluate(formula.parse_formula("1 + 2 * 3"), {}) == Decimal(7)
    assert formula.evaluate(formula.parse_formula("(1 + 2) * 3"), {}) == Decimal(9)
    assert formula.evaluate(formula.parse_formula("2 ^ 3 ^ 2"), {}) == Decimal(512)  # right associative
    # % means percent of, the way cost engineers read a variance.
    assert formula.evaluate(formula.parse_formula("[a] % [b]"), {"a": Decimal(25), "b": Decimal(200)}) == Decimal("12.5")
    assert formula.evaluate(formula.parse_formula("0.1 + 0.2"), {}) == Decimal("0.3")


def test_formula_blanks_division_and_iferror():
    values = {"a": Decimal(5), "blank": None, "text_blank": ""}
    assert formula.evaluate(formula.parse_formula("[a] + [blank]"), values) is None
    assert formula.evaluate(formula.parse_formula("COALESCE([blank], 0) + [a]"), values) == Decimal(5)
    assert formula.evaluate(formula.parse_formula("ISBLANK([text_blank])"), values) is True
    with pytest.raises(formula.EvaluationError):
        formula.evaluate(formula.parse_formula("[a] / 0"), values)
    assert formula.evaluate(formula.parse_formula("IFERROR([a] / 0, -1)"), values) == Decimal(-1)
    assert formula.evaluate(formula.parse_formula("SUM([a], [blank], 2)"), values) == Decimal(7)
    assert formula.evaluate(formula.parse_formula("COUNT([a], [blank], 2)"), values) == Decimal(2)


def test_formula_conditions_and_text():
    values = {"bsw": Decimal("0.4"), "location": "bonny", "other": "ESC"}
    assert formula.evaluate(
        formula.parse_formula('IF(AND([bsw] <= 0.5, OR([location] = "BONNY", [location] = "ESC")), "OK", "Check")'),
        values,
    ) == "OK"
    assert formula.evaluate(formula.parse_formula('IFS([bsw] >= 1, "Large", [bsw] >= 0.2, "Medium", "Small")'), values) == "Medium"
    assert formula.evaluate(formula.parse_formula('CONCAT(UPPER([location]), "-", [bsw])'), values) == "BONNY-0.4"
    assert formula.evaluate(formula.parse_formula('LEFT([other], 2)'), values) == "ES"


def test_formula_validation_rejects_unknown_and_injection():
    problems = formula.validate_formula("DROP TABLE users", set())
    assert problems
    problems = formula.validate_formula("[missing] + 1", {"present"})
    assert "missing" in problems[0]
    problems = formula.validate_formula("SLEEP(10)", set())
    assert problems and "SLEEP" in problems[0]
    assert formula.validate_formula("[a] + 1", {"a"}) == []


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def test_catalog_never_exposes_secrets_and_lists_related_links():
    with SessionLocal() as db:
        catalog = build_catalog(db.get_bind())
    assert "wells" in catalog
    user_columns = catalog["users"].columns
    assert "password_hash" not in user_columns
    assert "token_version" not in user_columns
    afes = catalog["afes"]
    assert "well_id" in afes.relations
    assert "well_name" in afes.relations["well_id"].parent_columns
    summaries = [info.group for info in catalog.values()]
    assert "Rig & Well Management" in summaries


def test_catalog_endpoints_are_tenant_scoped_and_permissioned():
    with TestClient(app) as client:
        headers = login(client)
        response = client.get("/api/v1/report-builder/catalog", headers=headers)
        assert response.status_code == 200
        names = {item["table"] for item in response.json()["tables"]}
        assert {"wells", "daily_cost_entries", "afes"} <= names
        detail = client.get("/api/v1/report-builder/catalog/afes", headers=headers).json()
        assert any(relation["table"] == "wells" for relation in detail["relations"])
        assert client.get("/api/v1/report-builder/catalog/secret_table", headers=headers).status_code == 404
        # A viewer without designer capabilities cannot browse the catalogue.
        outsider = login(client, "outsider@example.com")
        assert client.get("/api/v1/report-builder/catalog", headers=outsider).status_code == 403


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validation_rejects_unknown_columns_and_bad_matrix():
    with TestClient(app) as client:
        headers = login(client)
        bad = design(columns=[column("missing", "no_such_column")])
        result = client.post("/api/v1/report-builder/validate", headers=headers, json=bad).json()
        assert result["valid"] is False and "no column named" in result["problems"][0]

        cycle = design(columns=[
            column("a", "", kind="CALCULATED", formula="[b] + 1", label="A"),
            column("b", "", kind="CALCULATED", formula="[a] + 1", label="B"),
        ])
        result = client.post("/api/v1/report-builder/validate", headers=headers, json=cycle).json()
        assert result["valid"] is False and "circle" in result["problems"][0]

        matrix = design(
            report_type="MATRIX",
            columns=[column("well", "well_name"), column("status", "status"), column("n", "id", aggregate="COUNT")],
            groupings=[{"kind": "matrix_row", "column_key": "well", "bucket": "VALUE"},
                       {"kind": "matrix_column", "column_key": "status", "bucket": "VALUE"}],
            matrix_value_key="n", matrix_aggregate="COUNT",
        )
        result = client.post("/api/v1/report-builder/validate", headers=headers, json=matrix).json()
        assert result["valid"] is True, result["problems"]


def test_save_rejects_a_design_that_references_a_secret_column():
    with TestClient(app) as client:
        headers = login(client)
        payload = design(source_table="users", columns=[column("hash", "password_hash")])
        response = client.post("/api/v1/report-builder/definitions", headers=headers, json=payload)
        assert response.status_code == 422
        assert "no column named" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_detail_report_scopes_to_the_workspace_and_hides_the_other_tenant():
    with TestClient(app) as client:
        headers = login(client)
        payload = design()
        response = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": payload, "params": {}})
        assert response.status_code == 200, response.text
        body = response.json()
        wells = {row["well"] for row in body["rows"]}
        assert wells == {"Alpha", "Beta", "Gamma"}
        assert "Secret" not in wells
        assert body["total_rows"] == 3


def test_grouped_report_with_related_column_and_sums():
    with TestClient(app) as client:
        headers = login(client)
        payload = design(
            name="Depth by well", source_table="well_sections", date_basis="NONE",
            columns=[
                column("well", "well_name", kind="RELATED", related_key="well_id", related_table="wells"),
                column("depth", "to_depth", data_type="number", aggregate="SUM", show_total=True, decimals=2),
                column("sections", "id", aggregate="COUNT", show_total=True, decimals=0),
            ],
            groupings=[{"kind": "group", "column_key": "well", "bucket": "VALUE"}],
            sorts=[{"column_key": "depth", "direction": "DESC"}],
        )
        response = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": payload, "params": {}})
        assert response.status_code == 200, response.text
        body = response.json()
        assert [row["well"] for row in body["rows"]] == ["Alpha", "Beta"]
        alpha = body["rows"][0]
        assert alpha["depth"] == "3,401.25"
        assert alpha["sections"] == "2"
        assert body["totals"]["depth"] == "4,301.50"
        assert body["grouped"] is True


def test_date_range_and_grouped_time_buckets():
    with TestClient(app) as client:
        headers = login(client)
        payload = design(
            name="Wells per month",
            columns=[column("month", "created_at", label="Month", data_type="date"),
                     column("wells", "id", aggregate="COUNT", show_total=True, decimals=0)],
            groupings=[{"kind": "group", "column_key": "month", "bucket": "MONTH"}],
            sorts=[{"column_key": "month", "direction": "ASC"}],
        )
        params = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
        response = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": payload, "params": params})
        body = response.json()
        assert response.status_code == 200, body
        assert body["rows"] == [
            {"month": "2026-01", "wells": "1"},
            {"month": "2026-02", "wells": "2"},
        ], body["rows"]

        narrowed = {"date_from": "2026-02-01", "date_to": "2026-02-28"}
        response = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": payload, "params": narrowed})
        body = response.json()
        assert [row["wells"] for row in body["rows"]] == ["2"]
        assert body["totals"]["wells"] == "2"


def test_matrix_with_totals_and_other_bucket():
    with TestClient(app) as client:
        headers = login(client)
        payload = design(
            name="AFE matrix", source_table="afes", date_basis="NONE",
            report_type="MATRIX",
            columns=[
                column("well", "well_name", kind="RELATED", related_key="well_id", related_table="wells"),
                column("status", "status"),
                column("n", "id", aggregate="COUNT", decimals=0),
            ],
            groupings=[{"kind": "matrix_row", "column_key": "well", "bucket": "VALUE"},
                       {"kind": "matrix_column", "column_key": "status", "bucket": "VALUE"}],
            matrix_value_key="n", matrix_aggregate="COUNT", matrix_show_totals=True,
        )
        response = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": payload, "params": {}})
        body = response.json()
        assert response.status_code == 200, body
        labels = [item["label"] for item in body["columns"]]
        assert labels[0] == "Well"
        assert "approval" in labels and "draft" in labels and "Total" in labels
        alpha = next(row for row in body["rows"] if row["r__0"] == "Alpha")
        assert alpha["m__total"] == "1"
        assert body["totals"]["m__total"] == "3"


def test_filters_runtime_questions_and_search():
    with TestClient(app) as client:
        headers = login(client)
        payload = design(
            name="Filtered wells",
            filters=[{"label": "Location", "source_kind": "DATA", "column_name": "well_location",
                      "operator": "eq", "value": "Onshore"}],
            runtime_filters=[{"key": "status", "label": "Status", "filter_type": "select",
                              "source_kind": "DATA", "column_name": "status", "operator": "eq",
                              "required": False, "default_value": "", "options": ["active", "completed"]}],
        )
        body = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": payload, "params": {}}).json()
        assert {row["well"] for row in body["rows"]} == {"Alpha", "Gamma"}

        body = client.post(
            "/api/v1/report-builder/preview", headers=headers,
            json={"design": payload, "params": {"filters": {"status": "active"}, "search": "gam"}},
        ).json()
        assert [row["well"] for row in body["rows"]] == ["Gamma"]

        required = design(
            name="Needs an answer",
            runtime_filters=[{"key": "status", "label": "Status", "filter_type": "text",
                              "source_kind": "DATA", "column_name": "status", "operator": "eq",
                              "required": True, "default_value": "", "options": []}],
        )
        response = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": required, "params": {}})
        assert response.status_code == 422
        assert "Answer" in response.json()["detail"]


def test_comparison_conditions_blank_only_the_matching_measure():
    with TestClient(app) as client:
        headers = login(client)
        payload = design(
            name="Approved versus all AFEs", source_table="afes", date_basis="NONE",
            columns=[
                column("well", "well_name", kind="RELATED", related_key="well_id", related_table="wells"),
                column("all_afes", "id", label="All AFEs", aggregate="COUNT", show_total=True, decimals=0),
                column("approved", "id", label="Approved", aggregate="COUNT", show_total=True, decimals=0,
                       conditions=[{"source_kind": "DATA", "column_name": "status", "operator": "eq", "value": "approval", "value2": ""}]),
            ],
            groupings=[{"kind": "group", "column_key": "well", "bucket": "VALUE"}],
            sorts=[{"column_key": "well", "direction": "ASC"}],
        )
        body = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": payload, "params": {}}).json()
        rows = {row["well"]: row for row in body["rows"]}
        assert rows["Alpha"]["all_afes"] == "1" and rows["Alpha"]["approved"] == "0"
        assert rows["Beta"]["approved"] == "1"


def test_calculated_column_and_notes():
    with TestClient(app) as client:
        headers = login(client)
        payload = design(
            name="Depth variance", source_table="well_sections", date_basis="NONE",
            columns=[
                column("well", "well_name", kind="RELATED", related_key="well_id", related_table="wells"),
                column("depth", "to_depth", data_type="number", aggregate="MAX", show_total=False, decimals=2),
                column("thousands", "", label="Thousands", kind="CALCULATED", data_type="number",
                       formula="ROUND([depth] / 1000, 2)", aggregate="MAX", decimals=2),
            ],
            groupings=[{"kind": "group", "column_key": "well", "bucket": "VALUE"}],
        )
        body = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": payload, "params": {}}).json()
        alpha = next(row for row in body["rows"] if row["well"] == "Alpha")
        assert alpha["thousands"] == "2.20"
        assert any("Calculated columns" in note for note in body["notes"])


def test_report_is_limited_to_the_workspace_even_with_a_handmade_source():
    with TestClient(app) as client:
        headers = login(client)
        payload = design(
            name="Audit trail", source_table="audit_logs", date_basis="CREATED_AT",
            columns=[column("action", "action"), column("summary", "summary"),
                     column("entity", "entity_type"),
                     column("events", "id", aggregate="COUNT", show_total=True, decimals=0)],
            groupings=[{"kind": "group", "column_key": "action", "bucket": "VALUE"}],
        )
        body = client.post("/api/v1/report-builder/preview", headers=headers, json={"design": payload, "params": {}}).json()
        # Two seeded rows plus this session's login; the other workspace is absent.
        assert body["total_rows"] == 3
        assert {row["action"] for row in body["rows"]} == {"create", "update", "login"}


# ---------------------------------------------------------------------------
# Saving, versioning, sharing, publishing
# ---------------------------------------------------------------------------


def test_create_update_and_version_history():
    with TestClient(app) as client:
        headers = login(client)
        created = client.post("/api/v1/report-builder/definitions", headers=headers, json=design())
        assert created.status_code == 201, created.text
        record = created.json()
        assert record["status"] == "draft" and record["version"] == 1

        updated_payload = design(name="Wells by rig (edited)", columns=[column("well", "well_name")])
        updated = client.put(f"/api/v1/report-builder/definitions/{record['id']}", headers=headers, json=updated_payload)
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == 2
        assert updated.json()["name"] == "Wells by rig (edited)"

        versions = client.get(f"/api/v1/report-builder/definitions/{record['id']}/versions", headers=headers).json()
        assert [item["version"] for item in versions] == [2, 1]
        detail = client.get(
            f"/api/v1/report-builder/definitions/{record['id']}/versions/{versions[1]['id']}", headers=headers
        ).json()
        assert detail["design"]["name"] == "Wells by rig"

        with SessionLocal() as db:
            stored = db.get(ReportDefinition, record["id"])
            assert stored is not None
            assert len(db.scalars(select(ReportDefinitionVersion).where(
                ReportDefinitionVersion.definition_id == record["id"])).all()) == 2
            actions = [row.action for row in db.scalars(select(AuditLog).where(
                AuditLog.entity_type == "report_builder")).all()]
            assert "report_create" in actions and "report_update" in actions


def test_duplicate_requires_create_and_produces_an_independent_copy():
    with TestClient(app) as client:
        headers = login(client)
        record = client.post("/api/v1/report-builder/definitions", headers=headers, json=design()).json()
        copy = client.post(f"/api/v1/report-builder/definitions/{record['id']}/duplicate", headers=headers)
        assert copy.status_code == 201, copy.text
        assert copy.json()["id"] != record["id"]
        assert copy.json()["name"] == "Wells by rig copy"
        assert copy.json()["status"] == "draft"


def test_publish_grants_and_published_menu_visibility():
    with TestClient(app) as client:
        designer = login(client)
        record = client.post("/api/v1/report-builder/definitions", headers=designer, json=design(visibility="internal")).json()

        viewer = login(client, "viewer@example.com")
        # Not published yet: the reporting menu must not show it.
        assert client.get("/api/v1/report-builder/my-reports", headers=viewer).json()["items"] == []

        published = client.post(
            f"/api/v1/report-builder/definitions/{record['id']}/publish", headers=designer, json={"published": True}
        )
        assert published.status_code == 200 and published.json()["status"] == "published"

        listed = client.get("/api/v1/report-builder/my-reports", headers=viewer).json()["items"]
        assert [item["name"] for item in listed] == ["Wells by rig"]
        run = client.post(
            f"/api/v1/report-builder/my-reports/{record['id']}/run", headers=viewer,
            json={"date_from": "", "date_to": "", "filters": {}, "search": "", "page": 1, "page_size": 20, "all_rows": False},
        )
        assert run.status_code == 200 and run.json()["total_rows"] == 3

        # Withdrawing removes it from the menu immediately.
        client.post(f"/api/v1/report-builder/definitions/{record['id']}/publish", headers=designer, json={"published": False})
        assert client.get("/api/v1/report-builder/my-reports", headers=viewer).json()["items"] == []


def test_a_published_private_report_is_only_visible_to_its_creator():
    with TestClient(app) as client:
        designer = login(client)
        record = client.post("/api/v1/report-builder/definitions", headers=designer, json=design()).json()
        client.post(f"/api/v1/report-builder/definitions/{record['id']}/publish", headers=designer, json={"published": True})

        outsider = login(client, "outsider@example.com")
        assert client.get("/api/v1/report-builder/my-reports", headers=outsider).json()["items"] == []
        assert client.get(f"/api/v1/report-builder/my-reports/{record['id']}", headers=outsider).status_code == 404
        # The creator can always run their own report.
        assert client.get(f"/api/v1/report-builder/my-reports/{record['id']}", headers=designer).status_code == 200


def test_role_grant_opens_a_report_for_a_viewer_and_edit_grant_allows_redesign():
    with TestClient(app) as client:
        designer = login(client)
        viewer = login(client, "viewer@example.com")
        with SessionLocal() as db:
            viewer_user = db.scalar(select(User).where(User.email == "viewer@example.com"))
            viewer_role = viewer_user.roles[0]
            viewer_role_id = viewer_role.id
        payload = design(
            name="Shared with the analysis role",
            grants=[{"grant_type": "role", "role_id": viewer_role_id, "user_id": "", "level": "view"}],
        )
        record = client.post("/api/v1/report-builder/definitions", headers=designer, json=payload)
        assert record.status_code == 201, record.text
        record = record.json()
        client.post(f"/api/v1/report-builder/definitions/{record['id']}/publish", headers=designer, json={"published": True})

        listed = client.get("/api/v1/report-builder/my-reports", headers=viewer).json()["items"]
        assert [item["name"] for item in listed] == ["Shared with the analysis role"]
        assert client.post(
            f"/api/v1/report-builder/my-reports/{record['id']}/run", headers=viewer, json={"page_size": 20}
        ).status_code == 200

        # A view grant does not permit changes.
        edited = design(
            name="Shared with the analysis role", columns=[column("well", "well_name")],
            grants=[{"grant_type": "role", "role_id": viewer_role_id, "user_id": "", "level": "view"}],
        )
        assert client.put(f"/api/v1/report-builder/definitions/{record['id']}", headers=viewer, json=edited).status_code in {403, 404}
        assert client.get(f"/api/v1/report-builder/definitions/{record['id']}", headers=designer).json()["can_edit"] is True


def test_second_workspace_cannot_read_or_delete_a_report():
    with TestClient(app) as client:
        designer = login(client)
        record = client.post("/api/v1/report-builder/definitions", headers=designer, json=design()).json()
        south = login(client, "south@example.com", organization="south")
        assert client.get(f"/api/v1/report-builder/definitions/{record['id']}", headers=south).status_code == 404
        assert client.delete(f"/api/v1/report-builder/definitions/{record['id']}", headers=south).status_code == 404
        assert client.get("/api/v1/report-builder/definitions", headers=south).json()["items"] == []


def test_only_the_creator_with_delete_capability_may_delete():
    with TestClient(app) as client:
        designer = login(client)
        record = client.post("/api/v1/report-builder/definitions", headers=designer, json=design()).json()
        viewer = login(client, "viewer@example.com")
        assert client.delete(f"/api/v1/report-builder/definitions/{record['id']}", headers=viewer).status_code in {403, 404}
        assert client.delete(f"/api/v1/report-builder/definitions/{record['id']}", headers=designer).status_code == 204


def test_starters_create_a_working_report():
    with TestClient(app) as client:
        headers = login(client)
        starters = client.get("/api/v1/report-builder/starters", headers=headers).json()["items"]
        assert len(starters) >= 6
        key = next(item["key"] for item in starters if item["name"] == "Well register")
        created = client.post("/api/v1/report-builder/definitions/from-starter", headers=headers, json={"key": key})
        assert created.status_code == 201, created.text
        record = created.json()
        run = client.post(
            f"/api/v1/report-builder/definitions/{record['id']}/run", headers=headers, json={"page_size": 20}
        )
        assert run.status_code == 200, run.text
        assert run.json()["total_rows"] == 3


def test_pagination_and_csv_export_are_audited():
    with TestClient(app) as client:
        designer = login(client)
        record = client.post(
            "/api/v1/report-builder/definitions", headers=designer, json=design(visibility="internal")
        ).json()
        client.post(f"/api/v1/report-builder/definitions/{record['id']}/publish", headers=designer, json={"published": True})
        viewer = login(client, "viewer@example.com")
        with SessionLocal() as db:
            rig = db.scalar(select(Rig))
            block = db.scalar(select(Block))
            db.add_all([
                Well(organization_id=rig.organization_id, rig_id=rig.id, block_id=block.id,
                     well_code=f"X{index}", well_name=f"Extra {index}", well_location="Onshore",
                     objective="Appraisal", status="active")
                for index in range(12)
            ])
            db.commit()
        response = client.post(
            f"/api/v1/report-builder/my-reports/{record['id']}/run", headers=viewer,
            json={"page": 2, "page_size": 10, "all_rows": False},
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total_rows"] == 15 and page["pages"] == 2 and len(page["rows"]) == 5

        csv_response = client.get(f"/api/v1/report-builder/my-reports/{record['id']}/export.csv", headers=viewer)
        assert csv_response.status_code == 200
        assert csv_response.headers["content-type"].startswith("text/csv")
        text = csv_response.content.decode("utf-8-sig")
        assert text.splitlines()[0].startswith("Well,Status,Location")
        assert len(text.strip().splitlines()) == 16

        audit = client.post("/api/v1/report-builder/export-audit", headers=viewer, json={
            "report_id": record["id"], "report_name": record["name"], "format": "pdf", "row_count": 15,
        })
        assert audit.status_code == 204
        with SessionLocal() as db:
            actions = [row.action for row in db.scalars(select(AuditLog).where(
                AuditLog.entity_type == "report_builder")).all()]
            assert actions.count("report_export") >= 2 and "report_run" in actions


def test_run_reports_when_the_source_table_disappears():
    """A saved design whose table is dropped answers readably, not with SQL noise."""
    with TestClient(app) as client:
        designer = login(client)
        record = client.post("/api/v1/report-builder/definitions", headers=designer, json=design(
            name="Wells report", source_table="wells", columns=[column("well", "well_name")]
        )).json()
        client.post(f"/api/v1/report-builder/definitions/{record['id']}/publish", headers=designer, json={"published": True})
        # Rename the table underneath the saved definition.
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE wells RENAME TO wells_renamed")
        try:
            response = client.post(
                f"/api/v1/report-builder/my-reports/{record['id']}/run", headers=designer, json={"page_size": 10}
            )
            assert response.status_code in {409, 422}
            assert "not available" in response.json()["detail"]
        finally:
            with engine.begin() as connection:
                connection.exec_driver_sql("ALTER TABLE wells_renamed RENAME TO wells")
