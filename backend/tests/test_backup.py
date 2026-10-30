"""Backup & Recovery: archives, verification, retention, the two-person restore.

Every test runs against a real SQLite schema and a temporary archive root, so a
round trip is proven end to end instead of mocked.
"""

import hashlib
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_db_path = tempfile.mktemp(suffix=".sqlite3")
sys_backup_root = tempfile.mkdtemp(prefix="wcp-test-backups-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db_path}"
os.environ["SECRET_KEY"] = "test-only-secret-do-not-deploy-12345"
os.environ["BACKUP_DIRECTORY"] = sys_backup_root
os.environ["BACKUP_SCHEDULER_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models import (
    AuditLog,
    BackupJob,
    BackupRestoreRequest,
    BackupSettings,
    Block,
    Organization,
    Permission,
    Rig,
    Role,
    User,
    Vendor,
    Well,
)
from app.services import backup as service

PASSWORD = "correct-password-123"
FULL_PERMISSIONS = [
    "backup:read", "backup:create", "backup:download", "backup:delete", "backup:settings",
    "backup:restore-request", "backup:restore-approve", "backup:restore-execute",
    "audit:read", "master-data:read",
]


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
        organization_id=organization_id, name=f"{email.split('@')[0]} role", is_owner=owner,
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
def fresh_database(tmp_path):
    get_settings().backup_directory = str(tmp_path / "archives")
    get_settings().backup_scheduler_enabled = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        north = Organization(slug="north", name="North Energy")
        south = Organization(slug="south", name="South Energy")
        db.add_all([north, south])
        db.flush()
        _user(db, north.id, "owner@example.com", owner=True)
        _user(db, north.id, "requester@example.com", FULL_PERMISSIONS)
        _user(db, north.id, "reviewer@example.com", FULL_PERMISSIONS)
        _user(db, south.id, "south@example.com", owner=True)
        block = Block(organization_id=north.id, block_code="NB1", block_name="North Block")
        rig = Rig(organization_id=north.id, rig_code="NR1", rig_name="North Rig")
        db.add_all([block, rig])
        db.flush()
        db.add(Well(organization_id=north.id, rig_id=rig.id, block_id=block.id, well_code="W1",
                    well_name="Alpha", well_location="Onshore", objective="Appraisal", status="active"))
        db.add(Vendor(organization_id=north.id, vendor_code="V1", vendor_name="Acme", vendor_type="Third party"))
        db.commit()
        yield


def login(client, email="requester@example.com", organization="north"):
    response = client.post("/api/v1/auth/login", json={"organization": organization, "email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def take_backup(client, headers, *, description="Nightly", scope="workspace"):
    response = client.post("/api/v1/backup/jobs", headers=headers, json={"description": description, "scope": scope})
    assert response.status_code in {200, 201}, response.text
    return response.json()


SETTINGS = {
    "enabled": False, "schedule_mode": "daily", "interval_value": 1, "run_time": "02:00",
    "retention_days": 30, "keep_minimum": 5, "backup_directory": "", "scope": "workspace",
    "compression_enabled": True,
}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_defaults_and_schedule_calculation():
    with TestClient(app) as client:
        headers = login(client)
        defaults = client.get("/api/v1/backup/settings", headers=headers).json()
        assert defaults["keep_minimum"] == 5
        assert defaults["allowed_scope"] == "workspace"
        assert defaults["multi_tenant"] is True
        assert defaults["folder"] == "north"

        payload = dict(SETTINGS, enabled=True, schedule_mode="hours", interval_value=6, backup_directory="north-archives")
        updated = client.put("/api/v1/backup/settings", headers=headers, json=payload)
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["enabled"] is True and body["schedule_mode"] == "hours"
        assert body["folder"] == "north-archives"
        assert body["next_run_at"] is not None
        next_run = datetime.fromisoformat(body["next_run_at"].replace("Z", "+00:00"))
        assert timedelta(hours=5) < next_run - datetime.now(timezone.utc) < timedelta(hours=7)

        daily = client.put("/api/v1/backup/settings", headers=headers, json=dict(SETTINGS, enabled=True))
        assert daily.status_code == 200
        next_run = datetime.fromisoformat(daily.json()["next_run_at"].replace("Z", "+00:00"))
        assert (next_run.hour, next_run.minute) == (2, 0)

        with SessionLocal() as db:
            actions = [row.action for row in db.scalars(select(AuditLog).where(AuditLog.entity_type == "backup")).all()]
            assert "backup_settings" in actions


def test_settings_reject_a_path_and_an_unknown_field():
    with TestClient(app) as client:
        headers = login(client)
        assert client.put("/api/v1/backup/settings", headers=headers, json=dict(SETTINGS, backup_directory="../etc")).status_code == 422
        assert client.put("/api/v1/backup/settings", headers=headers, json=dict(SETTINGS, unexpected=1)).status_code == 422


def test_settings_need_the_settings_capability():
    with TestClient(app) as client:
        with SessionLocal() as db:
            _user(db, db.scalar(select(Organization).where(Organization.slug == "north")).id,
                  "reader@example.com", ["backup:read"])
            db.commit()
        reader = login(client, "reader@example.com")
        assert client.get("/api/v1/backup/settings", headers=reader).status_code == 200
        assert client.put("/api/v1/backup/settings", headers=reader, json=SETTINGS).status_code == 403
        assert client.post("/api/v1/backup/jobs", headers=reader, json={"description": ""}).status_code == 403


# ---------------------------------------------------------------------------
# Taking, verifying, downloading and deleting an archive
# ---------------------------------------------------------------------------


def test_workspace_backup_writes_a_readable_archive():
    with TestClient(app) as client:
        headers = login(client)
        job = take_backup(client, headers, description="Before the upgrade")
        assert job["status"] == "completed", job
        assert job["backup_number"].startswith("BKP-")
        assert job["table_count"] > 20
        assert job["row_count"] > 0
        assert job["file_size_bytes"] > 0
        assert len(job["checksum_sha256"]) == 64
        assert job["format_version"] >= 1
        assert job["requested_by_display"] == "Requester"
        assert job["can_download"] is True and job["can_restore"] is True

        tables = client.get(f"/api/v1/backup/jobs/{job['id']}/tables", headers=headers).json()
        names = {item["table_name"] for item in tables}
        assert {"wells", "vendors", "blocks", "rigs"} <= names
        assert "organizations" not in names  # the workspace itself is preserved, never replaced

        verified = client.post(f"/api/v1/backup/jobs/{job['id']}/verify", headers=headers)
        assert verified.status_code == 200, verified.text
        assert verified.json()["matched"] is True
        assert verified.json()["status"] == "completed"

        download = client.get(f"/api/v1/backup/jobs/{job['id']}/download", headers=headers)
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/gzip"
        assert download.headers["content-disposition"].startswith("attachment;")
        assert download.content[:2] == b"\x1f\x8b"
        archive_bytes = download.content
        assert len(archive_bytes) == job["file_size_bytes"], (len(archive_bytes), job["file_size_bytes"])
        assert hashlib.sha256(archive_bytes).hexdigest() == job["checksum_sha256"]

        with SessionLocal() as db:
            actions = [row.action for row in db.scalars(select(AuditLog).where(AuditLog.entity_type == "backup")).all()]
            assert {"backup_request", "backup_start", "backup_complete", "backup_verify", "backup_download"} <= set(actions)

        # The uploaded copy is a full archive again: registered, counted and restorable.
        imported = client.post(
            "/api/v1/backup/jobs/import", headers=headers,
            files={"file": (job["file_name"], archive_bytes, "application/gzip")},
            data={"description": "Imported from the vault"},
        )
        assert imported.status_code in {200, 201}, imported.text
        assert imported.json()["status"] == "completed"
        assert imported.json()["checksum_sha256"] == job["checksum_sha256"]
        assert imported.json()["table_count"] == job["table_count"]
        assert imported.json()["trigger_source"] == "import"
        imported_tables = client.get(f"/api/v1/backup/jobs/{imported.json()['id']}/tables", headers=headers).json()
        assert len(imported_tables) == job["table_count"]
        assert sum(item["row_count"] for item in imported_tables) == job["row_count"]

        with SessionLocal() as db:
            stored = db.get(BackupJob, job["id"])
            assert stored is not None and Path(stored.file_path).exists()
            assert stored.row_count == job["row_count"]
            assert db.scalar(select(func.count()).select_from(AuditLog)) > 0


def test_a_tampered_archive_is_reported_as_a_checksum_mismatch():
    with TestClient(app) as client:
        headers = login(client)
        job = take_backup(client, headers)
        with SessionLocal() as db:
            path = Path(db.get(BackupJob, job["id"]).file_path)
        original = path.read_bytes()
        path.write_bytes(original[:-8] + b"tampered")

        result = client.post(f"/api/v1/backup/jobs/{job['id']}/verify", headers=headers)
        assert result.status_code == 200
        assert result.json()["matched"] is False
        assert result.json()["status"] == "checksum_mismatch"
        listed = client.get("/api/v1/backup/jobs", headers=headers).json()["items"][0]
        assert listed["status"] == "checksum_mismatch"

        # A corrupted archive can never start a restore.
        response = client.post("/api/v1/backup/restore-requests", headers=headers,
                               json={"backup_job_id": job["id"], "reason": "Need the old data back", "business_impact": ""})
        assert response.status_code == 409


def test_only_one_backup_runs_at_a_time_and_full_scope_is_refused_multi_tenant():
    with TestClient(app) as client:
        headers = login(client)
        take_backup(client, headers)
        with SessionLocal() as db:
            job = db.scalars(select(BackupJob)).first()
            job.status = "running"
            db.commit()
        blocked = client.post("/api/v1/backup/jobs", headers=headers, json={"description": ""})
        assert blocked.status_code == 409
        assert "still running" in blocked.json()["detail"]

        with SessionLocal() as db:
            db.get(BackupJob, job.id).status = "completed"
            db.commit()
        full = client.post("/api/v1/backup/jobs", headers=headers, json={"description": "", "scope": "full"})
        assert full.status_code == 409
        assert "more than one workspace" in full.json()["detail"]


def test_download_and_delete_are_capability_gated_and_tenant_scoped():
    with TestClient(app) as client:
        headers = login(client)
        job = take_backup(client, headers)
        south = login(client, "south@example.com", organization="south")
        assert client.get(f"/api/v1/backup/jobs/{job['id']}/download", headers=south).status_code == 404
        assert client.get(f"/api/v1/backup/jobs/{job['id']}/tables", headers=south).status_code == 404
        assert client.delete(f"/api/v1/backup/jobs/{job['id']}", headers=south).status_code == 404
        assert client.get("/api/v1/backup/jobs", headers=south).json()["items"] == []

        with SessionLocal() as db:
            path = Path(db.get(BackupJob, job["id"]).file_path)
        assert client.delete(f"/api/v1/backup/jobs/{job['id']}", headers=headers).status_code == 204
        assert not path.exists()
        assert client.get("/api/v1/backup/jobs", headers=headers).json()["items"] == []


# ---------------------------------------------------------------------------
# The two-person restore
# ---------------------------------------------------------------------------


def _approved_request(client, requester, reviewer, job_id):
    created = client.post(
        "/api/v1/backup/restore-requests", headers=requester,
        json={"backup_job_id": job_id, "reason": "Recover a vendor deleted by mistake", "business_impact": "None"},
    )
    assert created.status_code == 201, created.text
    request = created.json()
    approved = client.post(f"/api/v1/backup/restore-requests/{request['id']}/approve", headers=reviewer,
                           json={"remarks": "Checked the ticket"})
    assert approved.status_code == 200, approved.text
    return approved.json()


def test_restore_round_trip_brings_back_deleted_rows_and_removes_later_ones():
    with TestClient(app) as client:
        requester = login(client)
        reviewer = login(client, "reviewer@example.com")
        job = take_backup(client, requester)

        with SessionLocal() as db:
            db.delete(db.scalar(select(Vendor)))
            db.add(Vendor(organization_id=db.scalar(select(Organization).where(Organization.slug == "north")).id,
                          vendor_code="V9", vendor_name="Added later", vendor_type="Inhouse"))
            db.commit()

        request = _approved_request(client, requester, reviewer, job["id"])
        assert request["status"] == "approved"
        assert request["confirmation_phrase"] == f"RESTORE {job['backup_number']}"
        assert request["can_execute"] is False  # not validated yet

        validation = client.post(f"/api/v1/backup/restore-requests/{request['id']}/validate", headers=reviewer)
        assert validation.status_code == 200, validation.text
        assert validation.json()["validation"]["status"] in {"passed", "passed_with_warnings"}
        ready = client.get("/api/v1/backup/restore-requests", headers=reviewer).json()["items"][0]
        assert ready["status"] == "validated" and ready["can_execute"] is True
        assert any(item["table_name"] == "vendors" for item in validation.json()["tables"])

        wrong = client.post(f"/api/v1/backup/restore-requests/{request['id']}/execute", headers=reviewer,
                            json={"confirmation_text": "RESTORE", "remarks": ""})
        assert wrong.status_code == 422
        assert "Type exactly" in wrong.json()["detail"]

        executed = client.post(
            f"/api/v1/backup/restore-requests/{request['id']}/execute", headers=reviewer,
            json={"confirmation_text": f"RESTORE {job['backup_number']}", "remarks": "Restored as agreed"},
        )
        assert executed.status_code == 200, executed.text
        body = executed.json()
        assert body["status"] == "restored"
        assert body["tables_restored"] > 20
        assert body["rows_restored"] > 0
        assert body["pre_restore_backup_number"].startswith("BKP-")
        assert body["executed_by_display"] == "Reviewer"

        with SessionLocal() as db:
            vendors = {row.vendor_code for row in db.scalars(select(Vendor)).all()}
            assert vendors == {"V1"}
            actions = {row.action for row in db.scalars(select(AuditLog).where(AuditLog.entity_type == "backup")).all()}
            assert {"restore_complete", "restore_approve", "restore_validate"} <= actions
            # The audit trail survives its own restore.
            assert db.scalar(select(func.count()).select_from(AuditLog)) > 5
            # The safety archive is a complete, downloadable backup.
            safety = db.scalar(select(BackupJob).where(BackupJob.trigger_source == "pre-restore"))
            assert safety is not None and safety.status == "completed"
            assert Path(safety.file_path).exists()
            validation_row = service.request_validations(db, request["id"])[-1]
            assert validation_row.status in {"passed", "passed_with_warnings"}

        # Approving a second time is refused: the workflow is finished.
        again = client.post(f"/api/v1/backup/restore-requests/{request['id']}/approve", headers=reviewer, json={"remarks": ""})
        assert again.status_code == 409


def test_restore_requires_two_people_and_one_open_request():
    with TestClient(app) as client:
        requester = login(client)
        reviewer = login(client, "reviewer@example.com")
        job = take_backup(client, requester)

        created = client.post(
            "/api/v1/backup/restore-requests", headers=requester,
            json={"backup_job_id": job["id"], "reason": "Rebuild the workspace from last night", "business_impact": ""},
        ).json()
        assert created["status"] == "pending_approval"
        assert created["can_approve"] is False  # never your own request

        self_review = client.post(f"/api/v1/backup/restore-requests/{created['id']}/approve", headers=requester,
                                  json={"remarks": ""})
        assert self_review.status_code == 403

        duplicate = client.post(
            "/api/v1/backup/restore-requests", headers=requester,
            json={"backup_job_id": job["id"], "reason": "Rebuild the workspace again", "business_impact": ""},
        )
        assert duplicate.status_code == 409
        assert "already open" in duplicate.json()["detail"]

        # A request blocks deletion of the archive it points at.
        assert client.delete(f"/api/v1/backup/jobs/{job['id']}", headers=requester).status_code == 409

        # Executing before approval/validation is refused.
        early = client.post(f"/api/v1/backup/restore-requests/{created['id']}/execute", headers=reviewer,
                            json={"confirmation_text": f"RESTORE {job['backup_number']}", "remarks": ""})
        assert early.status_code == 409

        cancelled = client.post(f"/api/v1/backup/restore-requests/{created['id']}/cancel", headers=requester,
                                json={"remarks": "No longer needed"})
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        assert client.delete(f"/api/v1/backup/jobs/{job['id']}", headers=requester).status_code == 204


def test_rejected_request_cannot_be_validated_or_executed():
    with TestClient(app) as client:
        requester = login(client)
        reviewer = login(client, "reviewer@example.com")
        job = take_backup(client, requester)
        created = client.post(
            "/api/v1/backup/restore-requests", headers=requester,
            json={"backup_job_id": job["id"], "reason": "Not actually required", "business_impact": ""},
        ).json()
        rejected = client.post(f"/api/v1/backup/restore-requests/{created['id']}/reject", headers=reviewer,
                               json={"remarks": "Use the export instead"})
        assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
        assert client.post(f"/api/v1/backup/restore-requests/{created['id']}/validate", headers=reviewer).status_code == 409
        assert client.post(f"/api/v1/backup/restore-requests/{created['id']}/execute", headers=reviewer,
                           json={"confirmation_text": "RESTORE x", "remarks": ""}).status_code == 409
        assert rejected.json()["review_remarks"] == "Use the export instead"


def test_restore_request_list_and_validation_history():
    with TestClient(app) as client:
        requester = login(client)
        reviewer = login(client, "reviewer@example.com")
        job = take_backup(client, requester)
        request = _approved_request(client, requester, reviewer, job["id"])
        client.post(f"/api/v1/backup/restore-requests/{request['id']}/validate", headers=reviewer)
        client.post(f"/api/v1/backup/restore-requests/{request['id']}/validate", headers=reviewer)

        listed = client.get("/api/v1/backup/restore-requests", headers=requester).json()
        assert listed["total"] == 1
        item = listed["items"][0]
        assert item["request_number"].startswith("BRR-")
        assert item["latest_validation_status"] in {"passed", "passed_with_warnings"}

        history = client.get(f"/api/v1/backup/restore-requests/{request['id']}/validations", headers=requester).json()
        assert len(history) == 2

        overview = client.get("/api/v1/backup/overview", headers=requester).json()
        assert overview["open_requests"] == 1
        assert overview["completed"] >= 1
        assert overview["readiness"]["directory_writable"] is True


# ---------------------------------------------------------------------------
# Retention and the scheduler
# ---------------------------------------------------------------------------


def test_cleanup_honours_the_minimum_keep_and_never_touches_a_live_request():
    with TestClient(app) as client:
        headers = login(client)
        client.put("/api/v1/backup/settings", headers=headers,
                   json=dict(SETTINGS, retention_days=1, keep_minimum=2))
        first = take_backup(client, headers, description="Oldest")
        second = take_backup(client, headers, description="Middle")
        third = take_backup(client, headers, description="Newest")
        with SessionLocal() as db:
            old = datetime.now(timezone.utc) - timedelta(days=10)
            for number in (first["backup_number"], second["backup_number"]):
                row = db.scalar(select(BackupJob).where(BackupJob.backup_number == number))
                row.created_at = old
            db.commit()
            paths = {number: Path(db.scalar(select(BackupJob).where(BackupJob.backup_number == number)).file_path)
                     for number in (first["backup_number"], second["backup_number"], third["backup_number"])}

        dry = client.post("/api/v1/backup/cleanup?dry_run=true", headers=headers).json()
        assert dry["deleted_count"] == 1 and dry["dry_run"] is True
        assert paths[first["backup_number"]].exists()

        applied = client.post("/api/v1/backup/cleanup", headers=headers).json()
        assert applied["kept_count"] == 2
        assert not paths[first["backup_number"]].exists()
        assert paths[second["backup_number"]].exists()

        # A backup referenced by an open request survives retention.
        open_request = client.post(
            "/api/v1/backup/restore-requests", headers=headers,
            json={"backup_job_id": second["id"], "reason": "Keep this archive for the audit", "business_impact": ""},
        )
        assert open_request.status_code == 201
        with SessionLocal() as db:
            db.scalar(select(BackupJob).where(BackupJob.backup_number == second["backup_number"])).created_at = old
            db.commit()
        client.post("/api/v1/backup/cleanup", headers=headers)
        assert paths[second["backup_number"]].exists()


def test_scheduler_takes_a_due_backup_once_and_advances_the_schedule():
    with TestClient(app) as client:
        headers = login(client)
        payload = dict(SETTINGS, enabled=True, schedule_mode="daily", run_time="03:30")
        client.put("/api/v1/backup/settings", headers=headers, json=payload)
        with SessionLocal() as db:
            row = db.scalar(select(BackupSettings))
            row.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            db.commit()

        assert service.run_due_backups() == 1
        assert service.run_due_backups() == 0
        with SessionLocal() as db:
            job = db.scalar(select(BackupJob).where(BackupJob.trigger_source == "scheduled"))
            assert job is not None and job.status == "completed"
            settings = db.scalar(select(BackupSettings))
            assert settings.last_run_at is not None
            assert service.as_utc(settings.next_run_at) > datetime.now(timezone.utc)

        # A disabled schedule never starts a backup, however overdue it is.
        client.put("/api/v1/backup/settings", headers=headers, json=dict(SETTINGS, enabled=False))
        with SessionLocal() as db:
            row = db.scalar(select(BackupSettings))
            row.next_run_at = datetime.now(timezone.utc) - timedelta(days=1)
            db.commit()
        assert service.run_due_backups() == 0


def test_readiness_reports_an_unwritable_directory(tmp_path):
    with TestClient(app) as client:
        headers = login(client)
        get_settings().backup_directory = str(tmp_path / "missing" / "deeper")
        body = client.get("/api/v1/backup/readiness", headers=headers).json()
        assert body["directory_writable"] is True  # created on demand
        assert not any("not writable" in warning for warning in body["warnings"])

        get_settings().backup_directory = "/proc/definitely-not-writable"
        body = client.get("/api/v1/backup/readiness", headers=headers).json()
        assert body["directory_writable"] is False
        assert any("writable" in warning for warning in body["warnings"])


def test_restore_rejects_an_archive_from_another_workspace():
    with TestClient(app) as client:
        requester = login(client)
        job = take_backup(client, requester)
        archive = client.get(f"/api/v1/backup/jobs/{job['id']}/download", headers=requester).content
        south = login(client, "south@example.com", organization="south")
        response = client.post(
            "/api/v1/backup/jobs/import", headers=south,
            files={"file": ("north.jsonl.gz", archive, "application/gzip")},
            data={"description": "Wrong workspace"},
        )
        assert response.status_code == 403
        assert "different workspace" in response.json()["detail"]


def test_import_rejects_a_file_that_is_not_an_archive():
    with TestClient(app) as client:
        headers = login(client)
        response = client.post(
            "/api/v1/backup/jobs/import", headers=headers,
            files={"file": ("notes.jsonl.gz", b"not a gzip archive", "application/gzip")},
            data={"description": ""},
        )
        assert response.status_code == 422
        assert "archive" in response.json()["detail"].lower()
