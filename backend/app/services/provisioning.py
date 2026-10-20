"""Provisioning a tenant and its owner.

The owner role *is* the platform administrator: it is immutable, is granted
every baseline capability, and cannot be managed through the ordinary RBAC
endpoints. Nothing here reads credentials from the environment or prompts a
terminal — callers decide where the values come from.
"""
import re
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Currency, Organization, Permission, Role, User

OWNER_ROLE = "Owner"
SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# Platform capabilities are seeded as tenant data, never used as hard-coded role assignments in the UI.
CAPABILITIES = {resource: actions for resource, actions in {
    "users": ("read", "create", "update", "delete"),
    "roles": ("read", "create", "update", "delete"),
    "permissions": ("read", "create", "update", "delete"),
    "assignments": ("write",),
    "audit": ("read",),
    # Other Management → Database Browser. Read shows tables and rows of this workspace;
    # export covers CSV downloads and grid/structure exports. Owners receive both by default.
    "database-browser": ("read", "export"),
    "master-data": (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
        # Vendors and PO/SO Orders keep scanned copies; document custody is separately grantable.
        "document-upload", "document-download", "document-delete",
    ),
    "rig-well": (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
        # Well plan SOW adjustments revise planned days without rewriting the
        # configured plan. Kept separate from ordinary configuration edits.
        "plan-adjust",
    ),
    # AFE register and cost estimation. Status moves are separately grantable so that
    # estimators, reviewers and approvers can be given different authority.
    "afe": (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
        "estimate", "submit", "review", "approve", "reopen",
        # SOW adjustments revise approved AFE totals without rewriting the saved
        # estimate. Recording and approving are separately grantable.
        "sow-adjust", "sow-approve",
    ),
    "daily-cost": (
        "read", "create", "update", "delete", "restore", "permanent-delete", "import", "export",
        "submit", "reopen",
        # Amend allows reopening submitted sheets well after their cost date.
        "amend",
    ),
    "costing-sets": ("read", "create", "update", "delete", "import", "export"),
}.items()}


class ProvisioningError(ValueError):
    """Rejected provisioning input, or a tenant that would be overwritten."""


def check_slug(value: str) -> str:
    slug = value.strip().lower()
    if len(slug) > 80 or not SLUG_PATTERN.fullmatch(slug):
        raise ValueError("Organization slug must be lowercase letters, numbers and hyphens")
    return slug


def check_name(value: str) -> str:
    if not 2 <= len(value.strip()) <= 160:
        raise ValueError("Workspace and owner names must be 2–160 characters")
    return value.strip()


def check_email(value: str) -> str:
    try:
        return str(TypeAdapter(EmailStr).validate_python(value.strip())).lower()
    except Exception as error:  # pydantic wraps the e-mail validator error
        raise ValueError(f"Not a valid e-mail address ({error})") from error


def check_password(value: str) -> str:
    if not 12 <= len(value) <= 128:
        raise ValueError("Password must be 12–128 characters")
    return value


def administrators(db: Session) -> list[User]:
    """Every user holding the immutable owner role, in any organization."""
    return list(db.scalars(select(User).where(User.roles.any(Role.is_owner.is_(True)))).all())


def admin_missing(db: Session) -> bool:
    return not administrators(db)


def owner_role(db: Session, organization_id: str) -> Role:
    """The tenant's immutable owner role with every provisioned capability."""
    role = db.scalar(select(Role).where(Role.organization_id == organization_id, Role.is_owner.is_(True)))
    available = {
        permission.key: permission
        for permission in db.scalars(select(Permission).where(Permission.organization_id == organization_id))
    }
    baseline_keys = [
        f"{resource}:{action}"
        for resource, actions in CAPABILITIES.items()
        for action in actions
    ]
    for key in baseline_keys:
        if key not in available:
            permission = Permission(
                organization_id=organization_id,
                key=key,
                description=f"{key.split(':', 1)[1].title()} {key.split(':', 1)[0]}",
            )
            db.add(permission)
            available[key] = permission

    if role:
        assigned = {permission.key for permission in role.permissions}
        role.permissions.extend(available[key] for key in baseline_keys if key not in assigned)
        db.flush()
        return role

    role = Role(
        organization_id=organization_id,
        name=OWNER_ROLE,
        description="Organization owner",
        is_owner=True,
        permissions=[available[key] for key in baseline_keys],
    )
    db.add(role)
    db.flush()
    return role


def ensure_default_usd_currency(db: Session, organization_id: str) -> Currency:
    """Ensure USD exists and is the workspace default currency unless another default is already set."""
    has_default = db.scalar(
        select(Currency.id).where(
            Currency.organization_id == organization_id,
            Currency.is_deleted.is_(False),
            Currency.is_default.is_(True),
        )
    )
    usd = db.scalar(
        select(Currency).where(
            Currency.organization_id == organization_id,
            Currency.currency_code == "USD",
        )
    )
    if usd is None:
        usd = Currency(
            organization_id=organization_id,
            currency_code="USD",
            currency_name="US Dollar",
            currency_symbol="$",
            description="Standard US Dollar currency",
            is_default=has_default is None,
        )
        db.add(usd)
        db.flush()
    elif not usd.is_deleted and has_default is None:
        usd.is_default = True
        db.flush()
    return usd


def provision(slug: str, name: str, email: str, password: str, owner_name: str, db: Session | None = None, attach_existing: bool = False) -> User:
    """Create an organization, its owner role and the first administrator.

    ``attach_existing`` recovers a tenant whose owner was lost instead of
    refusing the duplicate slug; it never modifies existing users.
    """
    slug, name, email, owner_name = check_slug(slug), check_name(name), check_email(email), check_name(owner_name)
    check_password(password)
    own_session = db is None
    session = db or SessionLocal()
    try:
        organization = session.scalar(select(Organization).where(Organization.slug == slug))
        if organization and not attach_existing:
            raise ProvisioningError(f"Organization slug '{slug}' already exists")
        if not organization:
            organization = Organization(slug=slug, name=name)
            session.add(organization)
            session.flush()
        ensure_default_usd_currency(session, organization.id)
        if session.scalar(select(User).where(User.organization_id == organization.id, User.email == email)):
            raise ProvisioningError(f"{email} already exists in workspace '{slug}'")
        user = User(organization_id=organization.id, email=email, full_name=owner_name, password_hash=hash_password(password), roles=[owner_role(session, organization.id)])
        session.add(user)
        session.commit()
        return user
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()
