"""Provision an organization and its first owner. Run: python -m app.seed --help"""
import argparse
import getpass
import re
from sqlalchemy import select
from pydantic import EmailStr, TypeAdapter
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models import Organization, User, Role, Permission

# Platform capabilities are seeded as tenant data, never used as hard-coded role assignments in the UI.
CAPABILITIES = {resource: actions for resource, actions in {
    "users": ("read", "create", "update"),
    "roles": ("read", "create", "update", "delete"),
    "permissions": ("read", "create", "update", "delete"),
    "assignments": ("write",),
}.items()}


def provision(slug: str, name: str, email: str, password: str, owner_name: str):
    if len(slug) > 80 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError("Organization slug must be lowercase letters, numbers and hyphens")
    if not 2 <= len(name.strip()) <= 160 or not 2 <= len(owner_name.strip()) <= 160:
        raise ValueError("Workspace and owner names must be 2–160 characters")
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must be 12–128 characters")
    email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    with SessionLocal() as db:
        if db.scalar(select(Organization).where(Organization.slug == slug)):
            raise ValueError("Organization slug already exists")
        org = Organization(slug=slug, name=name)
        db.add(org)
        db.flush()
        permissions = [Permission(organization_id=org.id, key=f"{resource}:{action}", description=f"{action.title()} {resource}") for resource, actions in CAPABILITIES.items() for action in actions]
        role = Role(organization_id=org.id, name="Owner", description="Organization owner", is_owner=True, permissions=permissions)
        db.add(User(organization_id=org.id, email=email.lower(), full_name=owner_name.strip(), password_hash=hash_password(password), roles=[role]))
        db.commit()
    print(f"Provisioned workspace '{slug}' and owner {email.lower()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create a tenant and its first owner (run migrations first)")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--owner-name", required=True)
    args = parser.parse_args()
    provision(args.slug, args.name, args.email, getpass.getpass("Owner password (12+ characters): "), args.owner_name)
