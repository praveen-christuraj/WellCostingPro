"""The six service groups arrive without rewriting or losing existing services."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

PREVIOUS = "a7b3c9d21e60"
GROUPS = (
    "Rig Operations",
    "Formation Evaluation",
    "Well Services",
    "Land Facilities and Preparation",
    "Miscellaneous Services",
    "Supervisions",
)


def test_service_group_migration_backfills_legacy_master_data_and_daily_snapshots(tmp_path):
    database = tmp_path / "service-groups.sqlite3"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(target):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", target],
            cwd=backend, env=environment, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    migrate(PREVIOUS)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("INSERT INTO organizations (id, slug, name, created_at) VALUES ('org', 'legacy', 'Legacy', CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO rigs (id, organization_id, rig_code, rig_name, created_at, updated_at) VALUES ('rig', 'org', 'R-1', 'Rig', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute(
            "INSERT INTO wells (id, organization_id, rig_id, well_code, well_name, well_location, block, objective, created_at, updated_at) "
            "VALUES ('well', 'org', 'rig', 'W-1', 'Well', 'Location', 'Block', 'Objective', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO services (id, organization_id, service_code, service_name, service_category, provider_type, "
            "description, is_deleted, created_at, updated_at) "
            "VALUES ('service', 'org', 'SVC-1', 'Mud logging', 'Drilling Services', 'In House Services', '', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO afes (id, organization_id, rig_id, well_id, afe_code, afe_name, afe_type, created_at, updated_at) "
            "VALUES ('afe', 'org', 'rig', 'well', 'AFE-1', 'Drilling', 'Drilling', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO afe_service_lines (id, organization_id, afe_id, service_id, charging_basis, created_at, updated_at) "
            "VALUES ('afe-line', 'org', 'afe', 'service', 'Day Rate', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO daily_cost_well_rate_baselines (id, organization_id, well_id, locked_at, created_at) "
            "VALUES ('rate-baseline', 'org', 'well', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO daily_cost_baselines (id, organization_id, well_id, afe_id, rate_baseline_id, afe_code_snapshot, "
            "afe_name_snapshot, standard_currency, locked_at, created_at) "
            "VALUES ('baseline', 'org', 'well', 'afe', 'rate-baseline', 'AFE-1', 'Drilling', 'USD', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO daily_cost_baseline_budget_lines (id, organization_id, baseline_id, cost_group, budget_kind, item_key, "
            "item_code_snapshot, item_name_snapshot, source_afe_line_id) "
            "VALUES ('service-budget', 'org', 'baseline', 'Services', 'service', 'afe-line', 'SVC-1', 'Mud logging', 'afe-line')"
        )
        connection.execute(
            "INSERT INTO daily_cost_baseline_budget_lines (id, organization_id, baseline_id, cost_group, budget_kind, item_key, "
            "item_code_snapshot, item_name_snapshot, source_afe_line_id) "
            "VALUES ('bulk-budget', 'org', 'baseline', 'Consumables', 'consumable_category', 'Mud Chemicals', 'BULK-MUD', 'Mud allowance', 'afe-line')"
        )
        connection.execute(
            "INSERT INTO activities (id, organization_id, activity_code, activity_name, created_at, updated_at) "
            "VALUES ('activity', 'org', 'DRL', 'Drilling', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO daily_cost_entries (id, organization_id, rig_id, rig_code_snapshot, rig_name_snapshot, well_id, "
            "well_code_snapshot, well_name_snapshot, afe_id, afe_code_snapshot, afe_name_snapshot, afe_status_at_create, "
            "rate_baseline_id, baseline_id, daily_cost_code, cost_date, standard_currency, created_at, updated_at) "
            "VALUES ('entry', 'org', 'rig', 'R-1', 'Rig', 'well', 'W-1', 'Well', 'afe', 'AFE-1', 'Drilling', 'approved', "
            "'rate-baseline', 'baseline', 'DC-1', '2026-10-20', 'USD', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO daily_cost_service_lines (id, organization_id, entry_id, activity_id, service_id, service_code_snapshot, "
            "service_name_snapshot, charging_basis, charge_category, created_at, updated_at) "
            "VALUES ('service-line', 'org', 'entry', 'activity', 'service', 'SVC-1', 'Mud logging', 'Day Rate', 'Operation', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )

    migrate("head")
    migrate("head")  # Re-running the head must be a no-op.

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("SELECT service_group FROM services WHERE id = 'service'").fetchone() == ("Miscellaneous Services",)
        assert connection.execute("SELECT service_group FROM daily_cost_baseline_budget_lines WHERE id = 'service-budget'").fetchone() == ("Miscellaneous Services",)
        assert connection.execute("SELECT service_group FROM daily_cost_baseline_budget_lines WHERE id = 'bulk-budget'").fetchone() == ("",)
        assert connection.execute("SELECT service_group_snapshot FROM daily_cost_service_lines WHERE id = 'service-line'").fetchone() == ("Miscellaneous Services",)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE daily_cost_service_lines SET service_group_snapshot = 'Nope' WHERE id = 'service-line'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE services SET service_group = 'Not a group' WHERE id = 'service'")
        connection.execute("UPDATE services SET service_group = 'Formation Evaluation' WHERE id = 'service'")
        assert connection.execute("SELECT service_group FROM services WHERE id = 'service'").fetchone() == ("Formation Evaluation",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'uq_services_org_name_ci'"
        ).fetchone() == ("uq_services_org_name_ci",)

    downgraded = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", PREVIOUS],
        cwd=backend, env=environment, capture_output=True, text=True,
    )
    assert downgraded.returncode == 0, downgraded.stderr
    with sqlite3.connect(database) as connection:
        assert "service_group" not in {row[1] for row in connection.execute("PRAGMA table_info(services)")}
        assert "service_group" not in {
            row[1] for row in connection.execute("PRAGMA table_info(daily_cost_baseline_budget_lines)")
        }
        assert "service_group_snapshot" not in {
            row[1] for row in connection.execute("PRAGMA table_info(daily_cost_service_lines)")
        }
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'uq_services_org_name_ci'"
        ).fetchone() == ("uq_services_org_name_ci",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    migrate("head")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 1
        assert connection.execute("SELECT service_group FROM services").fetchone() == ("Miscellaneous Services",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_service_group_taxonomy_is_the_reported_order():
    from app.domain.service_groups import (
        DEFAULT_SERVICE_GROUP, SERVICE_GROUPS, normalize_service_group, service_group_rank,
    )

    assert SERVICE_GROUPS == GROUPS
    assert DEFAULT_SERVICE_GROUP == "Miscellaneous Services"
    assert normalize_service_group("micellaneous services") == "Miscellaneous Services"
    assert normalize_service_group("Land Facilities & Preparation") == "Land Facilities and Preparation"
    assert [service_group_rank(group) for group in SERVICE_GROUPS] == list(range(len(GROUPS)))
    assert service_group_rank("Unknown group") == len(GROUPS)
