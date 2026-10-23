"""Check scoped-plan and scoped-sub-activity migrations with legacy rows and foreign keys."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


def test_scoped_configuration_migration_preserves_legacy_plans_and_afes(tmp_path):
    database = tmp_path / "scopes.sqlite3"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(target, op="upgrade"):
        subprocess.run([sys.executable, "-m", "alembic", op, target], cwd=backend,
                       env=environment, check=True, capture_output=True, text=True)

    migrate("e2664cd07e88")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("INSERT INTO organizations (id, slug, name, created_at) VALUES ('org', 'legacy', 'Legacy', CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO rigs (id, organization_id, rig_code, rig_name, created_at, updated_at) VALUES ('rig', 'org', 'R-1', 'Rig', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO wells (id, organization_id, rig_id, well_code, well_name, well_location, block, objective, status, config_status, depth_unit, created_at, updated_at) VALUES ('well', 'org', 'rig', 'W-1', 'Well', 'Location', 'Block', 'Objective', 'completed', 'configured', 'ft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO hole_sections (id, organization_id, section_code, section_name, created_at, updated_at) VALUES ('hole', 'org', 'H-1', 'Hole', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO phases (id, organization_id, phase_code, phase_name, created_at, updated_at) VALUES ('phase', 'org', 'P-1', 'Phase', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO activities (id, organization_id, activity_code, activity_name, created_at, updated_at) VALUES ('act', 'org', 'DRILL', 'Drilling', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO well_sections (id, organization_id, well_id, hole_section_id, from_depth, to_depth, sort_order, created_at, updated_at) VALUES ('section', 'org', 'well', 'hole', 0, 100, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO well_phases (id, organization_id, section_id, phase_id, days, sort_order, created_at, updated_at) VALUES ('wellphase', 'org', 'section', 'phase', 10, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute(
            "INSERT INTO well_sub_activities (id, organization_id, well_id, sub_activity_code, sub_activity_name, activity_id, responsible_party, description, created_at, updated_at) "
            "VALUES ('sub-drl', 'org', 'well', 'SA-01', 'Legacy Step', 'act', 'Not Applicable', 'Legacy description', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        for identity, afe_type in (("drilling", "Drilling"), ("completion", "Completion")):
            connection.execute("INSERT INTO afes (id, organization_id, rig_id, well_id, afe_code, afe_name, afe_type, created_at, updated_at) VALUES (?, 'org', 'rig', 'well', ?, 'Existing AFE', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", (identity, identity, afe_type))
    migrate("head")
    migrate("-1", op="downgrade")
    migrate("head")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute(
            "SELECT status, config_status, depth_unit, completion_status, completion_config_status, completion_depth_unit, "
            "drilling_is_deleted, completion_is_deleted, drilling_purged, completion_purged FROM wells"
        ).fetchone() == ("completed", "configured", "ft", "active", "draft", "m", 0, 0, 0, 0)
        assert connection.execute("SELECT id, scope, to_depth FROM well_sections").fetchone() == ("section", "drilling", 100)
        assert connection.execute("SELECT section_id, days FROM well_phases").fetchone() == ("section", 10)
        assert connection.execute("SELECT id, scope, sub_activity_code FROM well_sub_activities").fetchone() == ("sub-drl", "drilling", "SA-01")
        assert connection.execute("SELECT configuration_scope FROM afes ORDER BY id").fetchall() == [("drilling",), ("drilling",)]
        # The same hole/order AND the same sub-activity code may be used in each scope,
        # while duplicates inside the same scope and invalid scope values are rejected.
        connection.execute("INSERT INTO well_sections (id, organization_id, well_id, scope, hole_section_id, from_depth, to_depth, sort_order, created_at, updated_at) VALUES ('compsection', 'org', 'well', 'completion', 'hole', 0, 200, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute(
            "INSERT INTO well_sub_activities (id, organization_id, well_id, scope, sub_activity_code, sub_activity_name, activity_id, responsible_party, description, created_at, updated_at) "
            "VALUES ('sub-comp', 'org', 'well', 'completion', 'SA-01', 'Completion Step', 'act', 'Not Applicable', 'Completion description', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        for invalid in (
            "UPDATE well_sections SET scope = 'other'",
            "UPDATE wells SET completion_config_status = 'other'",
            "UPDATE wells SET completion_status = 'other'",
            "UPDATE wells SET completion_depth_unit = 'other'",
            "UPDATE afes SET configuration_scope = 'other'",
            "UPDATE well_sections SET scope = 'drilling' WHERE id = 'compsection'",
            "UPDATE well_sub_activities SET scope = 'other'",
            "UPDATE well_sub_activities SET scope = 'drilling' WHERE id = 'sub-comp'",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(invalid)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
