"""Canonical service groups shared by Master Data, AFE and Daily Cost reporting.

The tuple order is the report order. AFE cost estimates and Daily Cost reports
always list services group by group in this sequence, then naturally by service
code inside each group. Keep ``frontend/src/lib/serviceGroups.ts`` in step with
this file; the API returns the canonical labels, so only the ordering is mirrored.
"""

from typing import Any

SERVICE_GROUPS = (
    "Rig Operations",
    "Formation Evaluation",
    "Well Services",
    "Land Facilities and Preparation",
    "Miscellaneous Services",
    "Supervisions",
)
DEFAULT_SERVICE_GROUP = "Miscellaneous Services"

SERVICE_GROUP_RANK = {group: index for index, group in enumerate(SERVICE_GROUPS)}
UNCLASSIFIED_RANK = len(SERVICE_GROUPS)

# Accept the everyday spellings and abbreviations used in spreadsheets. The
# misspelling of "Miscellaneous" is accepted deliberately: legacy workbooks use it.
_SERVICE_GROUP_ALIASES = {
    "rig": "Rig Operations",
    "rig operation": "Rig Operations",
    "rig operations": "Rig Operations",
    "rig ops": "Rig Operations",
    "formation": "Formation Evaluation",
    "formation evaluation": "Formation Evaluation",
    "formation evaluation services": "Formation Evaluation",
    "evaluation": "Formation Evaluation",
    "well service": "Well Services",
    "well services": "Well Services",
    "land facilities": "Land Facilities and Preparation",
    "land facilities & preparation": "Land Facilities and Preparation",
    "land facilities and prep": "Land Facilities and Preparation",
    "land facilities and preparation": "Land Facilities and Preparation",
    "land prep": "Land Facilities and Preparation",
    "land preparation": "Land Facilities and Preparation",
    "facilities and preparation": "Land Facilities and Preparation",
    "misc": "Miscellaneous Services",
    "misc services": "Miscellaneous Services",
    "miscellaneous": "Miscellaneous Services",
    "miscellaneous service": "Miscellaneous Services",
    "miscellaneous services": "Miscellaneous Services",
    "micellaneous": "Miscellaneous Services",
    "micellaneous services": "Miscellaneous Services",
    "miscellenous services": "Miscellaneous Services",
    "supervision": "Supervisions",
    "supervision services": "Supervisions",
    "supervisions": "Supervisions",
    "supervisory": "Supervisions",
    "supervisory services": "Supervisions",
}


def _normalized_key(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return " ".join(value.strip().casefold().replace("_", " ").replace("-", " ").split())


def normalize_service_group(value: Any) -> Any:
    """Return the canonical group label, or the trimmed input for validation to reject."""
    key = _normalized_key(value)
    if key in _SERVICE_GROUP_ALIASES:
        return _SERVICE_GROUP_ALIASES[key]
    return value.strip() if isinstance(value, str) else value


def service_group_rank(value: str | None) -> int:
    """Position used to sort services in reports; unknown groups sort last."""
    return SERVICE_GROUP_RANK.get((value or "").strip(), UNCLASSIFIED_RANK)
