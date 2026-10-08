"""First-run administrator bootstrap.

A fresh clone on a new device has an empty database, so nobody can sign in.
This module detects that state and asks the operator to create the first owner
account. It is deliberately conservative: it never invents credentials, never
touches an existing tenant, never creates tables behind Alembic's back, and
never blocks a process that has no terminal to answer a prompt.
"""
import logging
from dataclasses import dataclass
from enum import Enum
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.migrations import READY, schema_status, upgrade_head
from app.models import User
from app.services import console, provisioning

log = logging.getLogger("app.bootstrap")

SEED_HINT = ("Create one with `cd backend && python -m app.seed`, or for an unattended first boot set "
             "SEED_ORG_SLUG, SEED_ORG_NAME, SEED_OWNER_NAME, SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD.")


def describe(error: Exception) -> str:
    """A readable message; some exceptions, such as StopIteration, stringify to nothing."""
    return str(error) or error.__class__.__name__


class Outcome(str, Enum):
    ADMIN_PRESENT = "admin_present"      # nothing to do
    SEEDED = "seeded"                    # an administrator was created now
    DECLINED = "declined"                # operator said no
    SKIPPED = "skipped"                  # missing, and no terminal to ask
    NEEDS_MIGRATION = "needs_migration"  # run `alembic upgrade head` first
    DISABLED = "disabled"                # BOOTSTRAP_ADMIN_ON_STARTUP=false
    ERROR = "error"


@dataclass(frozen=True)
class BootstrapResult:
    outcome: Outcome
    message: str
    admin_email: str | None = None

    @property
    def needs_attention(self) -> bool:
        return self.outcome not in {Outcome.ADMIN_PRESENT, Outcome.SEEDED, Outcome.DISABLED}


def env_credentials() -> dict[str, str] | None:
    """Complete SEED_* set for unattended seeding, otherwise None."""
    settings = get_settings()
    values = {"slug": settings.seed_org_slug, "name": settings.seed_org_name, "owner_name": settings.seed_owner_name,
              "email": settings.seed_admin_email, "password": settings.seed_admin_password}
    return {key: value.strip() for key, value in values.items()} if all(value.strip() for value in values.values()) else None


def _state() -> tuple[str, list[User]]:
    """Current schema state and the owner accounts it holds."""
    status = schema_status()
    if status != READY:
        return status, []
    with SessionLocal() as db:
        return status, provisioning.administrators(db)


def inspect_admin() -> BootstrapResult:
    """Read-only status for `--check`: never migrates, prompts or writes."""
    try:
        status, owners = _state()
    except Exception as error:
        return BootstrapResult(Outcome.ERROR, f"Could not read the database: {describe(error)}")
    if status != READY:
        return BootstrapResult(Outcome.NEEDS_MIGRATION, "Database schema is not migrated yet; run `cd backend && alembic upgrade head`.")
    if owners:
        return BootstrapResult(Outcome.ADMIN_PRESENT, f"{len(owners)} administrator account(s) present", admin_email=owners[0].email)
    return BootstrapResult(Outcome.SKIPPED, f"No administrator account exists, so nobody can sign in. {SEED_HINT}")


def bootstrap_admin(*, interactive: bool | None = None) -> BootstrapResult:
    """Seed the first administrator when the database has none.

    ``interactive`` overrides terminal detection, which is what tests use.
    """
    if not get_settings().bootstrap_admin_on_startup:
        return BootstrapResult(Outcome.DISABLED, "Administrator bootstrap is disabled (BOOTSTRAP_ADMIN_ON_STARTUP=false)")
    ask = console.is_interactive() if interactive is None else interactive
    try:
        return _bootstrap(ask)
    except (KeyboardInterrupt, EOFError):
        return BootstrapResult(Outcome.DECLINED, f"Administrator setup ended before it completed. {SEED_HINT}")
    except Exception as error:
        return BootstrapResult(Outcome.ERROR, f"Administrator setup failed: {describe(error)}")


def _bootstrap(ask: bool) -> BootstrapResult:
    status, owners = _state()
    if status != READY and ask and console.confirm("The database schema is not migrated yet. Run migrations now?"):
        console.say("Running database migrations (alembic upgrade head)...")
        upgrade_head()
        status, owners = _state()
    if status != READY:
        return BootstrapResult(Outcome.NEEDS_MIGRATION, "Database schema is not migrated yet; run `cd backend && alembic upgrade head`.")
    if owners:
        return BootstrapResult(Outcome.ADMIN_PRESENT, f"{len(owners)} administrator account(s) present", admin_email=owners[0].email)
    if credentials := env_credentials():
        user = provisioning.provision(credentials["slug"], credentials["name"], credentials["email"], credentials["password"], credentials["owner_name"])
        return BootstrapResult(Outcome.SEEDED, f"Seeded administrator {user.email} in workspace '{credentials['slug']}' from SEED_* variables", admin_email=user.email)
    if ask:
        return _prompt()
    return BootstrapResult(Outcome.SKIPPED, f"No administrator account exists, so nobody can sign in yet. {SEED_HINT}")


def _prompt() -> BootstrapResult:
    console.say()
    console.say("No administrator account was found in this database.")
    if not console.confirm("Create the first administrator now?"):
        return BootstrapResult(Outcome.DECLINED, f"Administrator setup skipped. {SEED_HINT}")
    console.say("Provisioning the first workspace and its owner. Nothing is written until every answer validates.")
    slug = console.ask("Workspace ID (slug, e.g. acme-energy)", provisioning.check_slug)
    name = console.ask("Workspace name (e.g. Acme Energy)", provisioning.check_name)
    owner_name = console.ask("Administrator name", provisioning.check_name)
    email = console.ask("Administrator e-mail", provisioning.check_email)
    password = console.ask_password("Administrator password", validate=provisioning.check_password)
    provisioning.provision(slug, name, email, password, owner_name)
    console.say(f"Created workspace '{slug}' and administrator {email}. Sign in with that workspace ID and the password you chose.")
    return BootstrapResult(Outcome.SEEDED, f"Seeded administrator {email} in workspace '{slug}'", admin_email=email)
