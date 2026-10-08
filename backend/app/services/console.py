"""Terminal prompting for first-run setup, free of domain rules.

Callers pass validators in; nothing here knows about tenants or passwords.
"""
import getpass
import sys
from collections.abc import Callable


def say(message: str = "") -> None:
    print(message, flush=True)


def is_interactive() -> bool:
    """True only when a human can actually read and answer the prompt."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):  # closed or replaced streams
        return False


def ask(prompt: str, validate: Callable[[str], str] | None = None, default: str | None = None) -> str:
    """Ask until the answer is non-empty and accepted by ``validate``."""
    while True:
        suffix = f" [{default}]" if default else ""
        answer = input(f"{prompt}{suffix}: ").strip()  # EOFError ends setup; the caller reports it
        value = answer or (default or "")
        if not value:
            say("  A value is required.")
            continue
        if validate is None:
            return value
        try:
            return validate(value)
        except ValueError as error:
            say(f"  {error}")


def ask_password(prompt: str = "Password", hint: str = "12+ characters", validate: Callable[[str], str] | None = None) -> str:
    """Ask twice, hidden, until both entries match and pass ``validate``."""
    while True:
        try:
            first = getpass.getpass(f"{prompt} ({hint}): ")
            if validate is not None:
                validate(first)
            if getpass.getpass("Confirm password: ") != first:
                say("  Passwords did not match, try again.")
                continue
        except ValueError as error:
            say(f"  {error}")
            continue
        return first


def confirm(prompt: str, default: bool = True) -> bool:
    """Yes/no question that falls back to ``default`` on an empty answer."""
    hints = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            answer = input(f"{prompt} {hints}: ").strip().lower()
        except EOFError:
            return default
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        say("  Please answer y or n.")
