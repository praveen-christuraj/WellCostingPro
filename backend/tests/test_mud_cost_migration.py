"""Upgrade real legacy mud measurements without losing historical rows."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


def test_calculated_stock_migration_preserves_measurements_and_rebuilds_openings(tmp_path):
    database = tmp_path / "mud.sqlite3"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(target):
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=backend,
                       env=environment, check=True, capture_output=True, text=True)

    migrate("c1d4a7b8e2f9")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("INSERT INTO organizations (id, slug, name, created_at) VALUES ('org', 'legacy', 'Legacy', CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO rigs (id, organization_id, rig_code, rig_name, created_at, updated_at) VALUES ('rig', 'org', 'R-1', 'Rig', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO wells (id, organization_id, rig_id, well_code, well_name, well_location, block, objective, created_at, updated_at) VALUES ('well', 'org', 'rig', 'W-1', 'Well', 'Location', 'Block', 'Objective', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO hole_sections (id, organization_id, section_code, section_name, created_at, updated_at) VALUES ('hole', 'org', 'H-1', 'Hole', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        for identity, date, section in (("first", "2026-10-15", "section"), ("later", "2026-10-17", "section"), ("other", "2026-10-18", "other")):
            connection.execute("""
                INSERT INTO mud_cost_entries
                    (id, organization_id, rig_id, rig_code_snapshot, rig_name_snapshot,
                     well_id, well_code_snapshot, well_name_snapshot, section_id,
                     hole_section_id, section_scope, section_code_snapshot, section_name_snapshot,
                     section_from_depth, section_to_depth, entry_date, created_at, updated_at)
                VALUES (?, 'org', 'rig', 'R-1', 'Rig', 'well', 'W-1', 'Well', ?, 'hole',
                        'drilling', 'H-1', 'Hole', 0, 100, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (identity, section, date))
        for entry, code, category, amount in (
            ("first", "opening_stock", "opening_stock", 100),
            ("first", "extra_obm_received", "receipt", 25),
            ("first", "actual_closing_stock", "closing_stock", 999),
            ("later", "opening_stock", "opening_stock", 999),
            ("later", "shakers", "consumption_losses", 5),
            ("later", "actual_closing_stock", "closing_stock", 900),
            ("other", "opening_stock", "opening_stock", 500),
        ):
            connection.execute("""
                INSERT INTO mud_cost_entry_lines
                    (id, organization_id, entry_id, line_code, category, line_label, amount, remarks, sort_order, created_at, updated_at)
                VALUES (?, 'org', ?, ?, ?, ?, ?, 'Legacy remark', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (f"{entry}-{code}", entry, code, category, code, amount))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE mud_cost_entry_lines SET remarks = '' WHERE amount > 0")
    migrate("head")
    migrate("head")
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        openings = dict(connection.execute("SELECT entry_id, amount FROM mud_cost_entry_lines WHERE line_code = 'opening_stock'"))
        assert openings == {"first": 100, "later": 125, "other": 500}
        assert connection.execute("SELECT amount, remarks FROM mud_cost_entry_lines WHERE id = 'first-actual_closing_stock'").fetchone() == (999, "Legacy remark")
        connection.execute("UPDATE mud_cost_entry_lines SET remarks = ''")
        connection.execute("UPDATE mud_cost_entry_lines SET amount = -1 WHERE id = 'later-opening_stock'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE mud_cost_entry_lines SET amount = -1 WHERE id = 'later-shakers'")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_opening_stock_permission_migration_grants_only_owners(tmp_path):
    database = tmp_path / "permissions.sqlite3"
    environment = {**os.environ, "DATABASE_URL": f"sqlite:///{database}"}
    backend = Path(__file__).resolve().parents[1]

    def migrate(action, target):
        subprocess.run([sys.executable, "-m", "alembic", action, target], cwd=backend,
                       env=environment, check=True, capture_output=True, text=True)

    migrate("upgrade", "c4a7e1b93d52")
    with sqlite3.connect(database) as connection:
        for org in ("one", "two"):
            connection.execute("INSERT INTO organizations (id, slug, name, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (org, org, org))
            for role, is_owner in (("owner", 1), ("editor", 0)):
                connection.execute("INSERT INTO roles (id, organization_id, name, description, is_owner, created_at) VALUES (?, ?, ?, '', ?, CURRENT_TIMESTAMP)", (f"{org}-{role}", org, role, is_owner))
    for _ in range(2):
        migrate("upgrade", "head")
    with sqlite3.connect(database) as connection:
        permission_ids = dict(connection.execute("SELECT organization_id, id FROM permissions WHERE key = 'mud-cost:opening-stock-update'"))
        assert set(permission_ids) == {"one", "two"}
        # Later migrations backfill their own owner capabilities too (for example the
        # fuel opening-stock permission), so assert on this capability's assignments.
        mud_assignments = set(connection.execute(
            "SELECT role_id, permission_id FROM role_permissions WHERE permission_id IN (?, ?)",
            tuple(permission_ids.values()),
        ))
        assert mud_assignments == {
            (f"{org}-owner", permission_ids[org]) for org in ("one", "two")
        }
    migrate("downgrade", "c4a7e1b93d52")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM permissions WHERE key = 'mud-cost:opening-stock-update'").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    migrate("upgrade", "head")
