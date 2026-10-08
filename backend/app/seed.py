"""Provision the first workspace and its owner — the platform administrator.

Guided (asks, and migrates the schema if needed):  python -m app.seed
Status for scripts and entrypoints:                python -m app.seed --check
Unattended, from SEED_* variables:                 python -m app.seed --from-env
Explicit:                                          python -m app.seed --slug acme --name "Acme Energy" \
                                                       --email owner@example.com --owner-name "Jane Smith"

Exit codes: 0 an administrator exists or was created · 1 none exists and none was created ·
2 the schema is not migrated · 3 provisioning failed.
"""
import argparse
import getpass
import sys
from app.bootstrap import SEED_HINT, Outcome, bootstrap_admin, describe, env_credentials, inspect_admin
from app.core.migrations import READY, schema_status
from app.services import console, provisioning

# Re-exported so `from app.seed import provision` keeps working; the logic lives in services.
from app.services.provisioning import CAPABILITIES, ProvisioningError, provision  # noqa: F401

EXIT_OK, EXIT_MISSING, EXIT_SCHEMA, EXIT_FAILED = 0, 1, 2, 3
EXIT_CODES = {
    Outcome.ADMIN_PRESENT: EXIT_OK, Outcome.SEEDED: EXIT_OK, Outcome.DISABLED: EXIT_OK,
    Outcome.SKIPPED: EXIT_MISSING, Outcome.DECLINED: EXIT_MISSING,
    Outcome.NEEDS_MIGRATION: EXIT_SCHEMA, Outcome.ERROR: EXIT_FAILED,
}
PROVISION_FLAGS = ("--slug", "--name", "--email", "--owner-name")


def report(result, *, quiet: bool = False) -> int:
    if not quiet or result.needs_attention:
        console.say(result.message)
    return EXIT_CODES.get(result.outcome, EXIT_FAILED)


def explicit(args) -> int:
    """Provision from command-line flags, without prompting for anything but the password."""
    missing = [flag for flag, value in zip(PROVISION_FLAGS, (args.slug, args.name, args.email, args.owner_name)) if not value]
    if missing:
        console.say(f"Provide every provisioning flag or none at all; missing: {', '.join(missing)}")
        return EXIT_FAILED
    if schema_status() != READY:
        console.say("Database schema is not migrated yet; run `alembic upgrade head` first.")
        return EXIT_SCHEMA
    try:
        password = getpass.getpass("Owner password (12+ characters): ")
    except (EOFError, KeyboardInterrupt):
        console.say("No password entered; nothing was created.")
        return EXIT_MISSING
    try:
        user = provision(args.slug, args.name, args.email, password, args.owner_name, attach_existing=args.attach_existing)
    except (ProvisioningError, ValueError) as error:
        console.say(describe(error))
        return EXIT_FAILED
    console.say(f"Provisioned workspace '{args.slug}' and owner {user.email}")
    return EXIT_OK


def guided(args) -> int:
    """Same first-run flow the API runs at startup: detect, offer, seed."""
    if not console.is_interactive() and not env_credentials():
        status = inspect_admin()
        if status.outcome is not Outcome.SKIPPED:
            return report(status, quiet=args.quiet)  # an administrator exists, or the schema needs work
        console.say(f"No interactive terminal, so nothing can be asked. {SEED_HINT}")
        console.say("Pass --slug/--name/--email/--owner-name, or set the SEED_* variables.")
        return EXIT_MISSING
    return report(bootstrap_admin(), quiet=args.quiet)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", help="Workspace slug, e.g. acme-energy")
    parser.add_argument("--name", help="Workspace display name, e.g. 'Acme Energy'")
    parser.add_argument("--email", help="Administrator e-mail")
    parser.add_argument("--owner-name", help="Administrator display name")
    parser.add_argument("--attach-existing", action="store_true", help="Add the administrator to an existing workspace slug instead of failing (lockout recovery)")
    parser.add_argument("--check", action="store_true", help="Only report whether an administrator exists; never prompts or writes")
    parser.add_argument("--from-env", action="store_true", help="Seed non-interactively from SEED_ORG_SLUG, SEED_ORG_NAME, SEED_OWNER_NAME, SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD")
    parser.add_argument("--quiet", action="store_true", help="Only print messages that need attention")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        return report(inspect_admin(), quiet=args.quiet)
    if args.from_env:
        return report(bootstrap_admin(interactive=False), quiet=args.quiet)
    if any((args.slug, args.name, args.email, args.owner_name)):
        return explicit(args)
    return guided(args)


if __name__ == "__main__":
    sys.exit(main())
