"""Exercise migration against legacy records, not just ORM-created tables."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_vendor_service_migration_preserves_records_and_constraints(tmp_path):
    database = tmp_path / 'migration.sqlite3'
    environment = {**os.environ, 'DATABASE_URL': f'sqlite:///{database}'}
    backend = Path(__file__).resolve().parents[1]

    def migrate(target):
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', target], cwd=backend,
                       env=environment, check=True, capture_output=True, text=True)

    migrate('c6e2a9b41f70')
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO organizations (id, slug, name, created_at) VALUES ('org', 'legacy', 'Legacy', CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO vendors (id, organization_id, vendor_code, vendor_name, created_at, updated_at) VALUES ('vendor', 'org', 'V-1', 'Existing supplier', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
        for identity, provider, vendor in [('internal', 'In House Services', None), ('external', 'Third Party Services', 'vendor')]:
            connection.execute("INSERT INTO services (id, organization_id, service_code, service_name, service_category, provider_type, vendor_id, created_at, updated_at) VALUES (?, 'org', ?, ?, 'Drilling Services', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                               (identity, identity.upper(), identity, provider, vendor))
    migrate('head')
    migrate('head')
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT vendor_type FROM vendors').fetchone() == ('Third party',)
        assert connection.execute('SELECT service_code, vendor_id FROM services ORDER BY id').fetchall() == [('EXTERNAL', 'vendor'), ('INTERNAL', None)]
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []
        indexes = {row[1] for row in connection.execute('PRAGMA index_list(services)')}
        assert 'uq_services_org_name_ci' in indexes
        connection.execute("UPDATE vendors SET vendor_type = 'Inhouse' WHERE id = 'vendor'")
        connection.execute("UPDATE services SET vendor_id = 'vendor' WHERE id = 'internal'")
        for invalid in [
            "UPDATE vendors SET vendor_type = 'Unknown'",
            "UPDATE services SET service_name = 'EXTERNAL' WHERE id = 'internal'",
            "UPDATE services SET vendor_id = NULL WHERE id = 'external'",
        ]:
            try:
                connection.execute(invalid)
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError(f'Constraint was lost: {invalid}')
