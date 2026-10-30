"""A small, safe formula language for Report Builder calculated columns.

Nothing here uses ``eval`` or SQL. A formula is tokenised, parsed into an
abstract syntax tree and evaluated with :class:`Decimal` arithmetic against the
report's own column values. That gives three guarantees the application needs:

* **No injection.** Only the grammar below can be expressed; a formula can
  reference a column the report already validated and nothing else.
* **Predictable blanks.** A missing reading stays blank through arithmetic
  (``5 + blank = blank``) instead of silently becoming zero. ``COALESCE`` opts
  out, and the aggregate functions ignore blanks. A division by zero blanks only
  that cell and is reported as a warning — wrap it in ``IFERROR`` to replace it.
* **Exact money.** All arithmetic is Decimal; no binary floating point.

Grammar (highest precedence last)::

    expr        := or_expr
    or_expr     := and_expr (("OR" | "||") and_expr)*
    and_expr    := not_expr (("AND" | "&&") not_expr)*
    not_expr    := ("NOT" | "!") not_expr | comparison
    comparison  := additive (("=" | "<>" | "!=" | "<" | "<=" | ">" | ">=") additive)?
    additive    := multiplicative (("+" | "-") multiplicative)*
    multiplicative := power (("*" | "/" | "%") power)*
    power       := unary ("^" unary)?
    unary       := ("+" | "-") unary | primary
    primary     := NUMBER | STRING | TRUE | FALSE | "[" column_key "]" |
                   NAME "(" [expr ("," expr)*] ")" | "(" expr ")"

``%`` between two values means **percent of** (``a ÷ b × 100``), the way cost
engineers read a variance. Use ``MOD(a, b)`` for a remainder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, DivisionByZero, InvalidOperation, ROUND_HALF_UP

MAX_FORMULA_LENGTH = 2000
MAX_NODES = 400
MAX_DEPTH = 40

FUNCTIONS = {
    "IF": (3, 3), "IFS": (2, None), "AND": (1, None), "OR": (1, None), "NOT": (1, 1),
    "ISBLANK": (1, 1), "COALESCE": (1, None), "IFERROR": (2, 2), "ABS": (1, 1), "ROUND": (1, 2),
    "SUM": (1, None), "AVG": (1, None), "MIN": (1, None), "MAX": (1, None), "COUNT": (1, None),
    "MOD": (2, 2), "PCT": (2, 2), "CONCAT": (1, None), "UPPER": (1, 1), "LOWER": (1, 1),
    "TRIM": (1, 1), "LEN": (1, 1), "LEFT": (2, 2), "RIGHT": (2, 2),
    "YEAR": (1, 1), "MONTH": (1, 1), "DAY": (1, 1), "DATEDIFF": (2, 2), "TODAY": (0, 0),
    "MAXV": (1, None), "MINV": (1, None),
}
FUNCTION_HELP = [
    ("IF(condition, then, else)", "Choose one of two values."),
    ("IFS(condition, value, …, otherwise)", "First matching condition wins."),
    ("AND(…), OR(…), NOT(x)", "Combine conditions."),
    ("ISBLANK(x)", "True when a value is missing."),
    ("COALESCE(x, fallback, …)", "First value that is not blank."),
    ("IFERROR(expression, fallback)", "Replace a failed calculation (for example ÷ 0)."),
    ("ABS(x), ROUND(x, places)", "Absolute value and half-up rounding."),
    ("SUM/AVG/MIN/MAX/COUNT(…)", "Aggregate the arguments, ignoring blanks."),
    ("MOD(a, b), PCT(a, b)", "Remainder, and a as a percentage of b."),
    ("CONCAT(…), UPPER, LOWER, TRIM, LEN, LEFT, RIGHT", "Text handling."),
    ("YEAR, MONTH, DAY, DATEDIFF(a, b)", "Date parts and whole days between two dates."),
    ("TODAY()", "The current date."),
]

TOKEN_RE = re.compile(
    r"""
    (?P<space>\s+)
  | (?P<number>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<column>\[[A-Za-z_][A-Za-z0-9_]*\])
  | (?P<identifier>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<operator><>|!=|<=|>=|==|\|\||&&|[=<>+\-*/%^!(),])
    """,
    re.VERBOSE,
)
COLUMN_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class FormulaError(ValueError):
    """The formula cannot be parsed or references something unknown."""


class EvaluationError(Exception):
    """This cell could not be calculated (only the cell is affected)."""


# ---------------------------------------------------------------------------
# Tokenising and parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    position: int


def tokenise(source: str) -> list[Token]:
    tokens: list[Token] = []
    index = 0
    while index < len(source):
        match = TOKEN_RE.match(source, index)
        if not match:
            raise FormulaError(f"Unexpected character {source[index]!r} at position {index + 1}.")
        kind = match.lastgroup or ""
        text = match.group()
        index = match.end()
        if kind == "space":
            continue
        if kind == "identifier":
            upper = text.upper()
            # AND(...) / OR(...) / NOT(...) are also functions, so a following
            # bracket keeps the name an identifier instead of an operator.
            followed_by_bracket = source[index:].lstrip().startswith("(")
            if upper in {"AND", "OR", "NOT"} and not followed_by_bracket:
                tokens.append(Token("operator", upper, match.start()))
            elif upper in {"TRUE", "FALSE"}:
                tokens.append(Token("boolean", upper, match.start()))
            else:
                tokens.append(Token("identifier", text, match.start()))
            continue
        if kind == "operator" and text == "==":
            text = "="
        tokens.append(Token(kind, text, match.start()))
    tokens.append(Token("eof", "", len(source)))
    return tokens


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0
        self.nodes = 0
        self.depth = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def count_node(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise FormulaError("This formula is too long. Split it into more than one calculated column.")

    def expect(self, value: str) -> None:
        if self.current.value != value:
            raise FormulaError(f"Expected {value!r} but found {self.current.value or 'the end of the formula'!r}.")
        self.advance()

    def parse(self):
        if self.current.kind == "eof":
            raise FormulaError("The formula is empty.")
        node = self.parse_or()
        if self.current.kind != "eof":
            raise FormulaError(f"Unexpected {self.current.value!r} at position {self.current.position + 1}.")
        return node

    def _guard(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError("This formula is nested too deeply.")
        return self.depth

    def parse_or(self):
        self._guard()
        node = self.parse_and()
        while self.current.kind == "operator" and self.current.value in {"OR", "||"}:
            self.advance()
            node = ("logic", "OR", node, self.parse_and())
            self.count_node()
        self.depth -= 1
        return node

    def parse_and(self):
        node = self.parse_not()
        while self.current.kind == "operator" and self.current.value in {"AND", "&&"}:
            self.advance()
            node = ("logic", "AND", node, self.parse_not())
            self.count_node()
        return node

    def parse_not(self):
        if self.current.kind == "operator" and self.current.value in {"NOT", "!"}:
            self.advance()
            node = ("not", self.parse_not())
            self.count_node()
            return node
        return self.parse_comparison()

    def parse_comparison(self):
        node = self.parse_additive()
        if self.current.kind == "operator" and self.current.value in {"=", "<>", "!=", "<", "<=", ">", ">="}:
            operator = self.advance().value
            node = ("compare", operator, node, self.parse_additive())
            self.count_node()
        return node

    def parse_additive(self):
        node = self.parse_multiplicative()
        while self.current.kind == "operator" and self.current.value in {"+", "-"}:
            operator = self.advance().value
            node = ("arithmetic", operator, node, self.parse_multiplicative())
            self.count_node()
        return node

    def parse_multiplicative(self):
        node = self.parse_power()
        while self.current.kind == "operator" and self.current.value in {"*", "/", "%"}:
            operator = self.advance().value
            node = ("arithmetic", operator, node, self.parse_power())
            self.count_node()
        return node

    def parse_power(self):
        node = self.parse_unary()
        if self.current.kind == "operator" and self.current.value == "^":
            self.advance()
            # Right associative, so 2 ^ 3 ^ 2 is 2 ^ 9.
            node = ("arithmetic", "^", node, self.parse_power())
            self.count_node()
        return node

    def parse_unary(self):
        if self.current.kind == "operator" and self.current.value in {"+", "-"}:
            operator = self.advance().value
            node = ("unary", operator, self.parse_unary())
            self.count_node()
            return node
        return self.parse_primary()

    def parse_primary(self):
        token = self.current
        if token.kind == "number":
            self.advance()
            return ("number", Decimal(token.value))
        if token.kind == "string":
            self.advance()
            return ("string", _unquote(token.value))
        if token.kind == "boolean":
            self.advance()
            return ("boolean", token.value == "TRUE")
        if token.kind == "column":
            self.advance()
            return ("column", token.value[1:-1])
        if token.kind == "operator" and token.value == "(":
            self.advance()
            node = self.parse_or()
            self.expect(")")
            return node
        if token.kind == "identifier":
            name = token.value.upper()
            self.advance()
            if self.current.value != "(":
                raise FormulaError(
                    f"Unknown name {token.value!r}. Column values are written like [cost_total] and quantities of a "
                    "column must be in the report."
                )
            self.advance()
            arguments = []
            if self.current.value != ")":
                while True:
                    arguments.append(self.parse_or())
                    if self.current.value == ",":
                        self.advance()
                        continue
                    break
            self.expect(")")
            if name not in FUNCTIONS:
                raise FormulaError(f"{token.value} is not one of the available functions.")
            minimum, maximum = FUNCTIONS[name]
            if len(arguments) < minimum or (maximum is not None and len(arguments) > maximum):
                expected = f"{minimum}" if minimum == maximum else f"{minimum} or more" if maximum is None else f"{minimum}–{maximum}"
                raise FormulaError(f"{name} takes {expected} argument(s), but this formula gives {len(arguments)}.")
            if name == "IFS" and len(arguments) % 2 == 0:
                raise FormulaError("IFS needs condition/value pairs and a final otherwise value (an odd number of arguments).")
            self.count_node()
            return ("function", name, arguments)
        raise FormulaError(f"Unexpected {token.value or 'end of formula'!r} at position {token.position + 1}.")


def _unquote(value: str) -> str:
    body = value[1:-1]
    return re.sub(r"\\(.)", r"\1", body)


def parse_formula(source: str):
    if not isinstance(source, str) or not source.strip():
        raise FormulaError("The formula is empty.")
    if len(source) > MAX_FORMULA_LENGTH:
        raise FormulaError(f"Formulas are limited to {MAX_FORMULA_LENGTH} characters.")
    return Parser(tokenise(source)).parse()


def referenced_columns(source: str) -> list[str]:
    """Column keys a formula uses, in first-seen order (also used for cycle checks)."""
    seen: list[str] = []
    for match in re.finditer(r"\[([A-Za-z_][A-Za-z0-9_]*)\]", source or ""):
        key = match.group(1)
        if key not in seen:
            seen.append(key)
    return seen


def validate_formula(source: str, available: set[str]) -> list[str]:
    """Return human-readable problems; an empty list means the formula is usable."""
    problems: list[str] = []
    try:
        tree = parse_formula(source)
    except FormulaError as error:
        return [str(error)]
    unknown: set[str] = set()

    def walk(node) -> None:
        if not isinstance(node, tuple):
            return
        if node and node[0] == "column":
            if node[1] not in available:
                unknown.add(node[1])
            return
        if node and node[0] == "function":
            for argument in node[2]:
                walk(argument)
            return
        for child in node[1:]:
            walk(child)

    walk(tree)
    for key in sorted(unknown):
        problems.append(f"[{key}] is not a column of this report. Add the column first, then refer to it.")
    return problems


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def to_decimal(value) -> Decimal | None:
    if is_blank(value):
        return None
    if isinstance(value, bool):
        return Decimal(1) if value else Decimal(0)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def to_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if is_blank(value):
        return None
    text = str(value).strip()[:10]
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


def to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
        return "0" if text in {"-0", ""} else text
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def truthy(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value != 0
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in {"", "0", "false", "no", "n"}


def compare_values(left, right) -> int | None:
    """-1/0/1, or None when either side is blank. Numbers compare numerically."""
    if is_blank(left) or is_blank(right):
        return None
    left_decimal, right_decimal = to_decimal(left), to_decimal(right)
    if left_decimal is not None and right_decimal is not None:
        return (left_decimal > right_decimal) - (left_decimal < right_decimal)
    left_date, right_date = to_date(left), to_date(right)
    if left_date is not None and right_date is not None:
        return (left_date > right_date) - (left_date < right_date)
    left_text, right_text = to_text(left).strip().lower(), to_text(right).strip().lower()
    return (left_text > right_text) - (left_text < right_text)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _number(value, name: str) -> Decimal:
    if is_blank(value):
        raise EvaluationError(f"{name} is blank")
    number = to_decimal(value)
    if number is None:
        raise EvaluationError(f"{name} is not a number")
    return number


def _arithmetic(operator: str, left, right):
    if operator == "+" and (isinstance(left, str) or isinstance(right, str)):
        # Text + text joins, which keeps CONCAT-style formulas natural.
        if isinstance(left, str) or isinstance(right, str):
            if is_blank(left) and is_blank(right):
                return None
            return to_text(left) + to_text(right)
    if is_blank(left) or is_blank(right):
        return None
    first, second = to_decimal(left), to_decimal(right)
    if first is None or second is None:
        raise EvaluationError("a value in this formula is not a number")
    try:
        if operator == "+":
            return first + second
        if operator == "-":
            return first - second
        if operator == "*":
            return first * second
        if operator == "/":
            if second == 0:
                raise EvaluationError("division by zero")
            return first / second
        if operator == "%":
            # Percent of: a ÷ b × 100.
            if second == 0:
                raise EvaluationError("division by zero (percent of)")
            return first / second * Decimal(100)
        if operator == "^":
            if second == second.to_integral_value() and abs(second) <= 100:
                return first ** int(second)
            raise EvaluationError("power must be a whole number between -100 and 100")
    except (DivisionByZero, InvalidOperation, OverflowError) as error:
        raise EvaluationError(f"arithmetic failed ({error})") from error
    raise EvaluationError(f"unsupported operator {operator}")


def _round(value, places) -> Decimal:
    number = _number(value, "ROUND")
    digits = int(_number(places, "ROUND places")) if places is not None else 0
    digits = max(-10, min(10, digits))
    quant = Decimal(1).scaleb(-digits)
    return number.quantize(quant, rounding=ROUND_HALF_UP)


def _aggregate(name: str, values: list):
    numbers = [number for number in (to_decimal(value) for value in values) if number is not None]
    if name == "COUNT":
        return Decimal(sum(1 for value in values if not is_blank(value)))
    if not numbers:
        return None
    if name == "SUM":
        return sum(numbers, Decimal(0))
    if name == "AVG":
        return sum(numbers, Decimal(0)) / Decimal(len(numbers))
    if name in {"MIN", "MINV"}:
        return min(numbers)
    if name in {"MAX", "MAXV"}:
        return max(numbers)
    raise EvaluationError(f"unsupported aggregate {name}")


def evaluate(node, values: dict):
    """Evaluate a parsed formula against ``values`` (column key → value)."""
    kind = node[0]
    if kind == "number":
        return node[1]
    if kind == "string":
        return node[1]
    if kind == "boolean":
        return node[1]
    if kind == "column":
        return values.get(node[1])
    if kind == "unary":
        value = evaluate(node[2], values)
        if is_blank(value):
            return None
        number = _number(value, "value")
        return -number if node[1] == "-" else number
    if kind == "not":
        return not truthy(evaluate(node[1], values))
    if kind == "logic":
        left = truthy(evaluate(node[2], values))
        right_node = node[3]
        if node[1] == "AND":
            return left and truthy(evaluate(right_node, values))
        return left or truthy(evaluate(right_node, values))
    if kind == "compare":
        left = evaluate(node[2], values)
        right = evaluate(node[3], values)
        outcome = compare_values(left, right)
        if outcome is None:
            return None
        return {
            "=": outcome == 0,
            "<>": outcome != 0,
            "!=": outcome != 0,
            "<": outcome < 0,
            "<=": outcome <= 0,
            ">": outcome > 0,
            ">=": outcome >= 0,
        }[node[1]]
    if kind == "arithmetic":
        return _arithmetic(node[1], evaluate(node[2], values), evaluate(node[3], values))
    if kind == "function":
        return _call(node[1], node[2], values)
    raise EvaluationError(f"unsupported formula element {kind}")


def _call(name: str, arguments: list, values: dict):
    if name == "IF":
        return evaluate(arguments[1], values) if truthy(evaluate(arguments[0], values)) else evaluate(arguments[2], values)
    if name == "IFS":
        for index in range(0, len(arguments) - 1, 2):
            if truthy(evaluate(arguments[index], values)):
                return evaluate(arguments[index + 1], values)
        return evaluate(arguments[-1], values)
    if name == "IFERROR":
        try:
            return evaluate(arguments[0], values)
        except EvaluationError:
            return evaluate(arguments[1], values)
    if name == "AND":
        return all(truthy(evaluate(argument, values)) for argument in arguments)
    if name == "OR":
        return any(truthy(evaluate(argument, values)) for argument in arguments)
    if name == "NOT":
        return not truthy(evaluate(arguments[0], values))
    if name == "ISBLANK":
        return is_blank(evaluate(arguments[0], values))

    evaluated = [evaluate(argument, values) for argument in arguments]
    if name == "COALESCE":
        for value in evaluated:
            if not is_blank(value):
                return value
        return None
    if name in {"SUM", "AVG", "MIN", "MAX", "MINV", "MAXV", "COUNT"}:
        return _aggregate(name, evaluated)
    if name == "ABS":
        return abs(_number(evaluated[0], "ABS"))
    if name == "ROUND":
        return _round(evaluated[0], evaluated[1] if len(evaluated) > 1 else None)
    if name == "MOD":
        first, second = _number(evaluated[0], "MOD"), _number(evaluated[1], "MOD")
        if second == 0:
            raise EvaluationError("division by zero (MOD)")
        return first % second
    if name == "PCT":
        first, second = _number(evaluated[0], "PCT"), _number(evaluated[1], "PCT")
        if second == 0:
            raise EvaluationError("division by zero (PCT)")
        return first / second * Decimal(100)
    if name == "CONCAT":
        return "".join(to_text(value) for value in evaluated)
    if name == "UPPER":
        return to_text(evaluated[0]).upper()
    if name == "LOWER":
        return to_text(evaluated[0]).lower()
    if name == "TRIM":
        return to_text(evaluated[0]).strip()
    if name == "LEN":
        return Decimal(len(to_text(evaluated[0])))
    if name == "LEFT":
        return to_text(evaluated[0])[: int(_number(evaluated[1], "LEFT"))]
    if name == "RIGHT":
        count = int(_number(evaluated[1], "RIGHT"))
        text = to_text(evaluated[0])
        return text[-count:] if count else ""
    if name in {"YEAR", "MONTH", "DAY"}:
        moment = to_date(evaluated[0])
        if moment is None:
            return None
        return Decimal(getattr(moment, name.lower()))
    if name == "DATEDIFF":
        first, second = to_date(evaluated[0]), to_date(evaluated[1])
        if first is None or second is None:
            return None
        return Decimal((second - first).days)
    if name == "TODAY":
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}-{today.day:02d}"
    raise EvaluationError(f"{name} is not implemented")
