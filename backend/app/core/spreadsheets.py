"""Treat exported text as data, including whitespace-prefixed spreadsheet formulas."""
import re


def safe_csv_cell(value):
    if not isinstance(value, str):
        return value
    if re.match(r"^[\s\x00-\x1f]*[=+@-]", value) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value
