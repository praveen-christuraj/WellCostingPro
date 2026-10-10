import os
import tempfile

# Set the database before importing app modules (the engine is constructed at import).
_db_path = tempfile.mktemp(suffix=".sqlite3")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import AuditLog, Organization, Permission, Role, User


CAPABILITIES = [
    "master-data:read",
    "master-data:create",
    "master-data:update",
    "master-data:delete",
    "master-data:restore",
    "master-data:permanent-delete",
    "master-data:import",
    "master-data:export",
    "master-data:document-upload",
    "master-data:document-download",
    "master-data:document-delete",
    "audit:read",
]


@pytest.fixture(autouse=True)
def fresh_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for slug in ("north", "south"):
            organization = Organization(slug=slug, name=f"{slug.title()} Energy")
            db.add(organization)
            db.flush()
            permissions = [
                Permission(organization_id=organization.id, key=key, description=key) for key in CAPABILITIES
            ]
            owner_role = Role(
                organization_id=organization.id,
                name="Owner",
                is_owner=True,
                permissions=permissions,
            )
            db.add(
                User(
                    organization_id=organization.id,
                    email="owner@example.com",
                    full_name="Test Owner",
                    password_hash=hash_password("correct-password-123"),
                    roles=[owner_role],
                )
            )
        db.commit()
    yield


def login(client: TestClient, organization: str = "north") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "organization": organization,
            "email": "owner@example.com",
            "password": "correct-password-123",
        },
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def add_vendor(client: TestClient, headers: dict[str, str], code: str = "VEND-01", **overrides) -> dict:
    payload = {
        "vendor_code": code,
        "vendor_name": f"{code} Drilling Services",
        "category": "Drilling",
        "contact_person": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+971 50 000 0000",
        "country": "UAE",
        "status": "active",
        "credit_terms_days": 30,
        "description": "Directional drilling crews",
    }
    payload.update(overrides)
    response = client.post("/api/v1/master-data/vendors", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def add_order(client: TestClient, headers: dict[str, str], vendor_id: str, number: str = "PO-2026-001", **overrides) -> dict:
    payload = {
        "order_number": number,
        "order_type": "PO",
        "vendor_id": vendor_id,
        "issue_date": "2026-01-15",
        "expiry_date": "2026-12-31",
        "status": "open",
        "description": "Rig move and 3 wells",
    }
    payload.update(overrides)
    response = client.post("/api/v1/master-data/po-so-orders", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def upload(client: TestClient, headers: dict[str, str], order_id: str, name: str, content: bytes = b"%PDF-1.4 copy", **form):
    return client.post(
        f"/api/v1/master-data/po-so-orders/{order_id}/documents",
        files={"files": (name, content, "application/pdf")},
        data=form,
        headers=headers,
    )


def test_vendors_are_tenant_scoped_validate_business_fields_and_carry_counts():
    with TestClient(app) as client:
        north = login(client)
        south = login(client, "south")

        created = add_vendor(client, north)
        assert created["vendor_code"] == "VEND-01"
        assert created["email"] == "ada@example.com"
        assert created["status"] == "active"
        assert created["order_count"] == 0

        # The same code is free in another workspace and blocked in this one.
        assert client.post(
            "/api/v1/master-data/vendors",
            json={"vendor_code": "VEND-01", "vendor_name": "South Supplier"},
            headers=south,
        ).status_code == 201
        duplicate = client.post(
            "/api/v1/master-data/vendors",
            json={"vendor_code": "vend-01", "vendor_name": "Another"},
            headers=north,
        )
        assert duplicate.status_code == 409
        assert "already exists" in duplicate.json()["detail"]

        # Business fields are validated next to the record, not silently dropped.
        bad_email = client.post(
            "/api/v1/master-data/vendors",
            json={"vendor_code": "VEND-02", "vendor_name": "Bad e-mail", "email": "not-an-email"},
            headers=north,
        )
        assert bad_email.status_code == 422
        assert "e-mail" in bad_email.json()["detail"]
        bad_site = client.patch(
            f"/api/v1/master-data/vendors/{created['id']}",
            json={"website": "ht!tp://"},
            headers=north,
        )
        assert bad_site.status_code == 422

        # Updates record only what changed.
        updated = client.patch(
            f"/api/v1/master-data/vendors/{created['id']}",
            json={"status": "inactive", "contact_person": "Grace Hopper"},
            headers=north,
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "inactive"
        assert updated.json()["contact_person"] == "Grace Hopper"
        audit = client.get("/api/v1/audit", headers=north).json()
        vendor_updates = [
            entry for entry in audit["items"]
            if entry["entity_type"] == "vendor" and entry["action"] == "update"
        ]
        assert vendor_updates and "status" in vendor_updates[0]["summary"]

        # Another workspace cannot see or touch this vendor.
        assert client.get(f"/api/v1/master-data/vendors/{created['id']}", headers=south).status_code == 404
        assert client.patch(
            f"/api/v1/master-data/vendors/{created['id']}", json={"status": "blocked"}, headers=south
        ).status_code == 404

        # Counts follow the orders and their files.
        order = add_order(client, north, created["id"])
        upload(client, north, order["id"], "PO-2026-001.pdf")
        listed = client.get("/api/v1/master-data/vendors", headers=north).json()
        assert listed[0]["order_count"] == 1
        assert listed[0]["document_count"] == 1
        assert listed[0]["latest_order_date"] == "2026-01-15"
        options = client.get("/api/v1/master-data/vendors/options", headers=north).json()
        assert options[0]["label"] == "VEND-01 — VEND-01 Drilling Services"


def test_vendor_lifecycle_protects_orders_and_deleted_entries():
    with TestClient(app) as client:
        headers = login(client)
        vendor = add_vendor(client, headers)
        order = add_order(client, headers, vendor["id"])

        # A vendor with live orders cannot be soft-deleted, and a blocked vendor
        # cannot receive new orders.
        blocked = client.patch(f"/api/v1/master-data/vendors/{vendor['id']}", json={"status": "blocked"}, headers=headers)
        assert blocked.status_code == 200
        refused = client.post(
            "/api/v1/master-data/po-so-orders",
            json={"order_number": "PO-NEW", "order_type": "PO", "vendor_id": vendor["id"]},
            headers=headers,
        )
        assert refused.status_code == 409
        assert "blocked" in refused.json()["detail"]
        assert client.patch(f"/api/v1/master-data/vendors/{vendor['id']}", json={"status": "active"}, headers=headers).status_code == 200

        refused_delete = client.delete(f"/api/v1/master-data/vendors/{vendor['id']}", headers=headers)
        assert refused_delete.status_code == 409
        assert "active PO/SO" in refused_delete.json()["detail"]

        # Bulk delete refuses the whole batch rather than partially deleting.
        other = add_vendor(client, headers, "VEND-02")
        bulk = client.post(
            "/api/v1/master-data/vendors/bulk-delete",
            json={"ids": [vendor["id"], other["id"]]},
            headers=headers,
        )
        assert bulk.status_code == 409
        assert client.get("/api/v1/master-data/vendors", headers=headers).json().__len__() == 2

        # Once the order is in deleted entries the vendor can go too.
        assert client.delete(f"/api/v1/master-data/po-so-orders/{order['id']}", headers=headers).status_code == 200
        assert client.delete(f"/api/v1/master-data/vendors/{vendor['id']}", headers=headers).status_code == 200

        # Permanent deletion needs the order rows gone first.
        stuck = client.delete(f"/api/v1/master-data/vendors/{vendor['id']}/permanent", headers=headers)
        assert stuck.status_code == 409
        assert client.delete(f"/api/v1/master-data/po-so-orders/{order['id']}/permanent", headers=headers).status_code == 204
        assert client.delete(f"/api/v1/master-data/vendors/{vendor['id']}/permanent", headers=headers).status_code == 204
        assert [row["vendor_code"] for row in client.get("/api/v1/master-data/vendors", headers=headers).json()] == ["VEND-02"]


def test_amendments_form_a_revision_chain_and_carry_files_forward():
    with TestClient(app) as client:
        headers = login(client)
        vendor = add_vendor(client, headers)
        original = add_order(client, headers, vendor["id"])
        upload(client, headers, original["id"], "PO-2026-001.pdf", b"original copy")

        # The original cannot be duplicated; amendments need a note.
        duplicate = client.post(
            "/api/v1/master-data/po-so-orders",
            json={"order_number": "PO-2026-001", "order_type": "PO", "vendor_id": vendor["id"]},
            headers=headers,
        )
        assert duplicate.status_code == 409
        assert "Create amendment" in duplicate.json()["detail"]
        note_missing = client.post(
            f"/api/v1/master-data/po-so-orders/{original['id']}/amendment",
            json={"revision_note": "   "},
            headers=headers,
        )
        assert note_missing.status_code == 422

        first = client.post(
            f"/api/v1/master-data/po-so-orders/{original['id']}/amendment",
            json={"revision_note": "Added 2 extra wells", "issue_date": "2026-03-01"},
            headers=headers,
        )
        assert first.status_code == 201, first.text
        revision_one = first.json()
        assert revision_one["revision_number"] == 1
        assert revision_one["is_current"] is True
        assert revision_one["parent_order_id"] == original["id"]
        assert revision_one["issue_date"] == "2026-03-01"
        assert revision_one["description"] == original["description"]  # carried over
        assert revision_one["document_count"] == 1  # files copied into the amendment
        assert revision_one["revision_count"] == 2

        second = client.post(
            f"/api/v1/master-data/po-so-orders/{revision_one['id']}/amendment",
            json={"revision_note": "Scope reduced", "copy_documents": False},
            headers=headers,
        ).json()
        assert second["revision_number"] == 2
        assert second["document_count"] == 0
        assert second["revision_count"] == 3

        # Only the newest revision is current, and history is readable.
        listing = client.get("/api/v1/master-data/po-so-orders", headers=headers).json()
        assert [row["is_current"] for row in listing] == [False, False, True]
        history = client.get(f"/api/v1/master-data/po-so-orders/{second['id']}/revisions", headers=headers).json()
        assert [row["revision_number"] for row in history] == [0, 1, 2]
        assert history[1]["revision_note"] == "Added 2 extra wells"

        # Restoring an older revision makes it current again.
        assert client.delete(f"/api/v1/master-data/po-so-orders/{second['id']}", headers=headers).status_code == 200
        restored = client.post(f"/api/v1/master-data/po-so-orders/{second['id']}/restore", headers=headers).json()
        assert restored["is_current"] is True

        # Renaming keeps the whole chain together.
        renamed = client.patch(
            f"/api/v1/master-data/po-so-orders/{original['id']}",
            json={"order_number": "po-2026-900"},
            headers=headers,
        )
        assert renamed.status_code == 200
        assert {row["order_number"] for row in client.get("/api/v1/master-data/po-so-orders", headers=headers).json()} == {"PO-2026-900"}

        # An amendment chain keeps its vendor.
        moved = client.patch(
            f"/api/v1/master-data/po-so-orders/{revision_one['id']}",
            json={"vendor_id": add_vendor(client, headers, "VEND-09")["id"]},
            headers=headers,
        )
        assert moved.status_code == 409
        assert "cannot change" in moved.json()["detail"]


def test_document_upload_download_guard_and_recover():
    with TestClient(app) as client:
        headers = login(client)
        vendor = add_vendor(client, headers)
        order = add_order(client, headers, vendor["id"])

        rejected_type = upload(client, headers, order["id"], "payload.exe", b"MZ")
        assert rejected_type.status_code == 422
        assert "accepted file type" in rejected_type.json()["detail"]
        empty = upload(client, headers, order["id"], "empty.pdf", b"")
        assert empty.status_code == 422
        assert "empty" in empty.json()["detail"]

        created = upload(client, headers, order["id"], "PO-2026-001.pdf", b"%PDF-1.4 signed copy", document_kind="signed_copy", label="Signed by client")
        assert created.status_code == 201, created.text
        result = created.json()
        assert result["uploaded_count"] == 1 and result["rejected_count"] == 0
        assert result["items"][0]["accepted"] is True
        document = next(
            item
            for item in client.get(f"/api/v1/master-data/po-so-orders/{order['id']}/documents", headers=headers).json()
            if item["id"] == result["items"][0]["document_id"]
        )
        assert document["document_kind"] == "signed_copy"
        assert document["size_bytes"] == len(b"%PDF-1.4 signed copy")
        assert document["checksum_sha256"]
        assert document["uploaded_by_name"] == "Test Owner"

        duplicate = upload(client, headers, order["id"], "copy-again.pdf", b"%PDF-1.4 signed copy")
        assert duplicate.status_code == 422
        assert "identical file" in duplicate.json()["detail"]

        downloaded = client.get(f"/api/v1/master-data/po-so-orders/documents/{document['id']}", headers=headers)
        assert downloaded.status_code == 200
        assert downloaded.content == b"%PDF-1.4 signed copy"
        assert "attachment" in downloaded.headers["content-disposition"]
        preview = client.get(
            f"/api/v1/master-data/po-so-orders/documents/{document['id']}",
            params={"inline": True},
            headers=headers,
        )
        assert "inline" in preview.headers["content-disposition"]

        edited = client.patch(
            f"/api/v1/master-data/po-so-orders/documents/{document['id']}",
            json={"notes": "Client counter-signed copy", "document_kind": "correspondence"},
            headers=headers,
        )
        assert edited.status_code == 200
        assert edited.json()["notes"] == "Client counter-signed copy"
        assert edited.json()["document_kind"] == "correspondence"

        removed = client.delete(f"/api/v1/master-data/po-so-orders/documents/{document['id']}", headers=headers)
        assert removed.status_code == 200
        assert client.get(f"/api/v1/master-data/po-so-orders/{order['id']}/documents", headers=headers).json() == []
        hidden = client.get(
            f"/api/v1/master-data/po-so-orders/{order['id']}/documents",
            params={"include_deleted": True},
            headers=headers,
        ).json()
        assert [row["is_deleted"] for row in hidden] == [True]

        assert client.post(
            f"/api/v1/master-data/po-so-orders/documents/{document['id']}/restore", headers=headers
        ).status_code == 200
        assert len(client.get(f"/api/v1/master-data/po-so-orders/{order['id']}/documents", headers=headers).json()) == 1
        client.delete(f"/api/v1/master-data/po-so-orders/documents/{document['id']}", headers=headers)
        purge_refused = client.get(
            f"/api/v1/master-data/po-so-orders/documents/{document['id']}", headers=headers
        )
        assert purge_refused.status_code == 200  # still downloadable until purged
        assert client.delete(
            f"/api/v1/master-data/po-so-orders/documents/{document['id']}/permanent", headers=headers
        ).status_code == 204
        assert client.get(
            f"/api/v1/master-data/po-so-orders/documents/{document['id']}", headers=headers
        ).status_code == 404

        # Every custody action is on the audit trail.
        actions = {
            entry["action"]
            for entry in client.get("/api/v1/audit", headers=headers).json()["items"]
            if entry["entity_type"] == "po_so_document"
        }
        assert {"document_upload", "document_download", "document_delete", "document_restore"} <= actions


def test_a_partially_rejected_upload_reports_every_file():
    with TestClient(app) as client:
        headers = login(client)
        vendor = add_vendor(client, headers)
        order = add_order(client, headers, vendor["id"])

        response = client.post(
            f"/api/v1/master-data/po-so-orders/{order['id']}/documents",
            files=[
                ("files", ("good.pdf", b"%PDF-1.4 good copy", "application/pdf")),
                ("files", ("virus.exe", b"MZ", "application/octet-stream")),
                ("files", ("blank.pdf", b"", "application/pdf")),
            ],
            headers=headers,
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["uploaded_count"] == 1
        assert result["rejected_count"] == 2
        by_name = {item["file_name"]: item for item in result["items"]}
        assert by_name["good.pdf"]["accepted"] is True
        assert "accepted file type" in by_name["virus.exe"]["message"]
        assert "empty" in by_name["blank.pdf"]["message"]
        # Only the accepted file is stored.
        stored = client.get(f"/api/v1/master-data/po-so-orders/{order['id']}/documents", headers=headers).json()
        assert [row["file_name"] for row in stored] == ["good.pdf"]


def test_bulk_document_upload_matches_file_names_to_orders():
    with TestClient(app) as client:
        headers = login(client)
        vendor = add_vendor(client, headers)
        original = add_order(client, headers, vendor["id"], "PO-2026-001")
        amendment = client.post(
            f"/api/v1/master-data/po-so-orders/{original['id']}/amendment",
            json={"revision_note": "Extended scope", "copy_documents": False},
            headers=headers,
        ).json()

        response = client.post(
            "/api/v1/master-data/po-so-orders/documents/bulk",
            files=[
                ("files", ("PO-2026-001.pdf", b"file for the current revision", "application/pdf")),
                ("files", ("PO-2026-001__0.pdf", b"file for the original revision", "application/pdf")),
                ("files", ("PO-2026-001 Rev 1.pdf", b"file for revision one", "application/pdf")),
                ("files", ("UNKNOWN-999.pdf", b"nothing matches this", "application/pdf")),
            ],
            data={"document_kind": "po_copy"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["uploaded_count"] == 3
        assert result["rejected_count"] == 1
        assert "No active PO/SO number matches" in result["items"][-1]["message"]
        assert result["items"][1]["revision_number"] == 0
        assert result["items"][2]["revision_number"] == 1
        assert result["items"][0]["revision_number"] == 1  # the current revision

        assert len(client.get(f"/api/v1/master-data/po-so-orders/{original['id']}/documents", headers=headers).json()) == 1
        assert len(client.get(f"/api/v1/master-data/po-so-orders/{amendment['id']}/documents", headers=headers).json()) == 2


def test_imports_accept_aliases_report_row_errors_and_stay_in_the_workspace():
    with TestClient(app) as client:
        north = login(client)
        south = login(client, "south")

        vendor_import = client.post(
            "/api/v1/master-data/vendors/import",
            json={
                "rows": [
                    # legacy headers from the reference system
                    {"vendor_code": "vend-10", "vendor_name": "Legacy Supplier", "contact": "Sam", "description": "imported"},
                    {"code": "VEND-11", "name": "New headers", "status": "on hold", "credit_terms_days": "45 days"},
                    {"vendor_code": "VEND-12", "vendor_name": "Bad status", "status": "maybe"},
                    {"vendor_code": "", "vendor_name": "No code"},
                ]
            },
            headers=north,
        )
        assert vendor_import.status_code == 200
        summary = vendor_import.json()
        assert summary["imported_count"] == 2
        assert summary["error_count"] == 2
        assert any("not recognized" in message for message in summary["errors"])
        assert any("vendor code is required" in message.lower() or "vendor_code" in message for message in summary["errors"])
        held = next(row for row in client.get("/api/v1/master-data/vendors", headers=north).json() if row["vendor_code"] == "VEND-11")
        assert held["status"] == "blocked"
        assert held["credit_terms_days"] == 45

        # Re-importing the same code updates and restores instead of failing.
        again = client.post(
            "/api/v1/master-data/vendors/import",
            json={"rows": [{"vendor_code": "VEND-10", "vendor_name": "Legacy Supplier Renamed"}]},
            headers=north,
        )
        assert again.json()["imported_count"] == 1
        assert client.get("/api/v1/master-data/vendors", headers=south).json() == []

        order_import = client.post(
            "/api/v1/master-data/po-so-orders/import",
            json={
                "rows": [
                    {"order_number": "po-700", "po_type": "purchase order", "vendor_code": "vend-10", "effective_date": "15/01/2026", "remarks": "legacy headers"},
                    {"order_number": "SO-701", "order_type": "SO", "vendor_code": "VEND-10", "issue_date": "46000", "status": "issued"},
                    {"order_number": "PO-702", "order_type": "PO", "vendor_code": "MISSING", "issue_date": "2026-02-01"},
                    {"order_number": "PO-703", "order_type": "PO", "vendor_code": "VEND-11", "issue_date": "2026-02-01"},
                    {"order_number": "PO-700", "order_type": "PO", "vendor_code": "VEND-10", "issue_date": "not a date"},
                ]
            },
            headers=north,
        )
        result = order_import.json()
        assert result["imported_count"] == 2, result
        assert result["error_count"] == 3, result
        assert any("not an active vendor" in message for message in result["errors"])
        assert any("blocked" in message for message in result["errors"])
        assert any("Unrecognized date" in message for message in result["errors"])

        orders = client.get("/api/v1/master-data/po-so-orders", headers=north).json()
        assert {row["order_number"] for row in orders} == {"PO-700", "SO-701"}
        excel_serial = next(row for row in orders if row["order_number"] == "SO-701")
        assert excel_serial["issue_date"] == "2025-12-09"  # Excel serial 46000
        assert excel_serial["order_type"] == "SO"
        assert client.get("/api/v1/master-data/po-so-orders", headers=south).json() == []


def test_module_dashboard_counts_vendors_orders_and_documents():
    with TestClient(app) as client:
        headers = login(client)
        vendor = add_vendor(client, headers)
        order = add_order(client, headers, vendor["id"])
        upload(client, headers, order["id"], "PO-2026-001.pdf", b"scan")
        add_vendor(client, headers, "VEND-03", status="blocked")

        overview = client.get("/api/v1/master-data/vendor-po/overview", headers=headers).json()
        assert overview["vendors_active"] == 1
        assert overview["vendors_blocked"] == 1
        assert overview["orders_active"] == 1
        assert overview["documents_active"] == 1
        assert overview["storage_bytes"] == len(b"scan")
        assert next(item["count"] for item in overview["orders_by_type"] if item["key"] == "PO") == 1
        assert overview["top_vendors"][0]["vendor_code"] == "VEND-01"

        activity = client.get("/api/v1/master-data/vendor-po/activity", headers=headers).json()
        assert activity and activity[0]["entity_label"].startswith(("Vendors", "PO/SO"))

        # The module dashboard covers the eight master-data types, and exports are audited.
        module_overview = client.get("/api/v1/master-data/overview", headers=headers).json()
        assert module_overview["module_count"] == 13
        assert {module["key"] for module in module_overview["modules"]} >= {"services", "vendors", "po-so-orders"}
        assert client.post(
            "/api/v1/master-data/export-audit",
            json={"module": "po-so-orders", "format": "xlsx", "record_count": 1, "include_deleted": False},
            headers=headers,
        ).status_code == 204
        assert client.post(
            "/api/v1/master-data/export-audit",
            json={"module": "nope", "format": "xlsx", "record_count": 1},
            headers=headers,
        ).status_code == 404


def test_permissions_gate_vendor_order_and_document_actions():
    with SessionLocal() as db:
        organization = db.scalar(select(Organization).where(Organization.slug == "north"))
        permissions = {
            permission.key: permission
            for permission in db.scalars(select(Permission).where(Permission.organization_id == organization.id))
        }
        limited = Role(
            organization_id=organization.id,
            name="Procurement reader",
            permissions=[
                permissions["master-data:read"],
                permissions["master-data:document-download"],
            ],
        )
        db.add(
            User(
                organization_id=organization.id,
                email="reader@example.com",
                full_name="Reader",
                password_hash=hash_password("correct-password-123"),
                roles=[limited],
            )
        )
        db.commit()

    with TestClient(app) as client:
        owner = login(client)
        reader = {
            "Authorization": "Bearer "
            + client.post(
                "/api/v1/auth/login",
                json={"organization": "north", "email": "reader@example.com", "password": "correct-password-123"},
            ).json()["access_token"]
        }
        vendor = add_vendor(client, owner)
        order = add_order(client, owner, vendor["id"])
        document = {"id": upload(client, owner, order["id"], "PO-2026-001.pdf").json()["items"][0]["document_id"]}

        assert client.get("/api/v1/master-data/vendors", headers=reader).status_code == 200
        assert client.get("/api/v1/master-data/po-so-orders", headers=reader).status_code == 200
        assert client.get(f"/api/v1/master-data/po-so-orders/documents/{document['id']}", headers=reader).status_code == 200
        assert client.post(
            "/api/v1/master-data/vendors",
            json={"vendor_code": "VEND-99", "vendor_name": "Nope"},
            headers=reader,
        ).status_code == 403
        assert client.post(
            f"/api/v1/master-data/po-so-orders/{order['id']}/documents",
            files={"files": ("x.pdf", b"data", "application/pdf")},
            headers=reader,
        ).status_code == 403
        assert client.delete(f"/api/v1/master-data/po-so-orders/{order['id']}", headers=reader).status_code == 403


def test_deleting_an_order_keeps_its_files_until_the_order_is_purged():
    with TestClient(app) as client:
        headers = login(client)
        vendor = add_vendor(client, headers)
        order = add_order(client, headers, vendor["id"])
        document_id = upload(client, headers, order["id"], "PO-2026-001.pdf").json()["items"][0]["document_id"]
        document = {"id": document_id}

        assert client.delete(f"/api/v1/master-data/po-so-orders/{order['id']}", headers=headers).status_code == 200
        assert client.get("/api/v1/master-data/po-so-orders", headers=headers).json() == []
        assert len(client.get("/api/v1/master-data/po-so-orders/deleted", headers=headers).json()) == 1
        # The scan is still retrievable while the order sits in deleted entries.
        assert client.get(f"/api/v1/master-data/po-so-orders/documents/{document['id']}", headers=headers).status_code == 200

        assert client.delete(f"/api/v1/master-data/po-so-orders/{order['id']}/permanent", headers=headers).status_code == 204
        assert client.get(f"/api/v1/master-data/po-so-orders/documents/{document['id']}", headers=headers).status_code == 404

        audit_summaries = [
            entry["summary"]
            for entry in client.get("/api/v1/audit", headers=headers).json()["items"]
            if entry["action"] == "permanent_delete" and entry["entity_type"] == "po_so_order"
        ]
        assert any("1 attached file" in summary for summary in audit_summaries)


def test_audit_entries_are_recorded_for_every_vendor_and_order_action():
    with TestClient(app) as client:
        headers = login(client)
        vendor = add_vendor(client, headers)
        order = add_order(client, headers, vendor["id"])
        client.patch(f"/api/v1/master-data/po-so-orders/{order['id']}", json={"status": "closed"}, headers=headers)
        client.post(
            f"/api/v1/master-data/po-so-orders/{order['id']}/amendment",
            json={"revision_note": "Rate change", "copy_documents": False},
            headers=headers,
        )
        entries = client.get("/api/v1/audit", headers=headers).json()["items"]
        actions = {(entry["entity_type"], entry["action"]) for entry in entries}
        assert ("vendor", "create") in actions
        assert ("po_so_order", "create") in actions
        assert ("po_so_order", "update") in actions
        assert ("po_so_order", "amend") in actions
        amendment = next(entry for entry in entries if entry["action"] == "amend")
        assert "Rate change" in amendment["summary"]
        assert amendment["ip_address"] or amendment["ip_address"] == ""
