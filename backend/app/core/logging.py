"""Logging configuration with secret redaction.

Application and access logs are collected centrally, so a credential must never
reach them in the first place. Passwords, reset codes, bearer tokens, cookies and
API keys are masked in every record; SQLAlchemy's engine logger is kept below
INFO unless an operator explicitly turns it on, because bound parameters can
contain business and personal data.
"""
import logging
import re

_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|reset_code|authorization|cookie|api[_-]?key|session)"
    r"(\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;&\"']+)"
)
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")


def scrub(text: str) -> str:
    text = _SECRET_PATTERN.sub(r"\1\2***", text)
    return _BEARER.sub(r"\1 ***", text)


class RedactionFilter(logging.Filter):
    """Mask secrets in the rendered message, and drop ``args`` that could leak."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a malformed record must not break logging
            return True
        scrubbed = scrub(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Install one console handler and the redaction filter on noisy loggers."""
    redaction = RedactionFilter()
    root = logging.getLogger()
    if not any(isinstance(existing, RedactionFilter) for handler in root.handlers for existing in handler.filters):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        handler.addFilter(redaction)
        root.handlers = [handler]
        root.setLevel(level)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "sqlalchemy.engine", "app"):
        logger = logging.getLogger(name)
        logger.addFilter(redaction)
    # Bound SQL parameters are business data; never echo them by default.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
