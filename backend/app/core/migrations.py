"""Schema state inspection and programmatic Alembic upgrades for first-run setup.

The application runtime never calls ``create_all``: migrations are explicit
revisions. These helpers only read the current revision, and run the very same
``alembic upgrade head`` the CLI runs when an operator agrees to migrate.
"""
from pathlib import Path
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from app.core.database import engine as default_engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
REQUIRED_TABLES = ("organizations", "users", "roles", "permissions", "user_roles", "role_permissions", "audit_logs")

# schema_status() results, ordered from "nothing exists" to "usable".
MISSING, BEHIND, READY = "missing", "behind", "ready"


def alembic_config() -> Config:
    """Alembic configuration resolved from the repository, independent of cwd."""
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    config.set_main_option("prepend_sys_path", str(BACKEND_ROOT))
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine | None = None) -> str | None:
    """Revision recorded in the database, or None when it was never migrated."""
    engine = engine or default_engine
    if not inspect(engine).has_table("alembic_version"):
        return None
    with engine.connect() as connection:
        revisions = [str(value) for value in connection.execute(text("SELECT version_num FROM alembic_version")).scalars()]
    return ", ".join(sorted(revisions)) or None


def schema_status(engine: Engine | None = None) -> str:
    """READY only when every model table exists and the database is at head."""
    engine = engine or default_engine
    existing = set(inspect(engine).get_table_names())
    present = [table for table in REQUIRED_TABLES if table in existing]
    if not present:
        return MISSING
    if len(present) < len(REQUIRED_TABLES) or current_revision(engine) != head_revision():
        return BEHIND
    return READY


def upgrade_head(engine: Engine | None = None) -> None:
    """Apply pending migrations, creating the database file/schema as needed."""
    engine = engine or default_engine
    config = alembic_config()
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    command.upgrade(config, "head")
