"""
Expression parser for the distributed calculator.

Responsibility (and ONLY this):
  Take a math expression string, e.g. "1 + 5^3 * (2 - 5)", and produce a
  deterministic Abstract Syntax Tree (AST) that respects standard operator
  precedence and parentheses.

This module has ZERO knowledge of Temporal, Kubernetes, task queues, or
workers. It is pure, deterministic Python and is unit-testable in complete
isolation. The AST it produces is later walked by the Temporal Workflow,
which maps each operator node to a task queue.

Design notes:
  - We use the shunting-yard algorithm to convert infix tokens directly into
    an AST (rather than flat RPN), because the Workflow needs a tree it can
    recursively walk node-by-node, scheduling one Activity per node and
    waiting for the result before proceeding to the parent.
  - Supported binary operators: + - * / ^
  - '^' (power) is right-associative; all others are left-associative.
  - Unary minus is supported (e.g. "-5 + 3") by rewriting it as (0 - 5) + 3
    at parse time, so the AST and downstream Activities only ever need to
    know about binary operators.
  - The AST nodes are plain, JSON-serializable dataclasses, since Temporal
    workflow inputs/outputs cross the wire and must be serializable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Union


# ---------------------------------------------------------------------------
# AST node definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NumberNode:
    """A leaf node holding a literal numeric value."""
    value: float

    def to_dict(self) -> dict:
        return {"type": "number", "value": self.value}


@dataclass(frozen=True)
class BinaryOpNode:
    """
    An internal node representing `left <op> right`.

    `op` is one of '+', '-', '*', '/', '^' and is exactly what the Workflow
    will use to look up the correct Temporal Task Queue.
    """
    op: str
    left: "AstNode"
    right: "AstNode"

    def to_dict(self) -> dict:
        return {
            "type": "binary_op",
            "op": self.op,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }


AstNode = Union[NumberNode, BinaryOpNode]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ExpressionParseError(ValueError):
    """Raised for any malformed input expression."""


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_REGEX = re.compile(
    r"""
    \s*(?:
        (?P<NUMBER>\d+(?:\.\d+)?)   |
        (?P<OP>[+\-*/^])            |
        (?P<LPAREN>\()              |
        (?P<RPAREN>\))
    )
    """,
    re.VERBOSE,
)


def tokenize(expression: str) -> list[str]:
    """
    Convert a raw expression string into a flat list of token strings.

    Numbers are kept as strings here (converted to float later) so this
    function stays a pure lexer with no semantic knowledge.
    """
    if not expression or not expression.strip():
        raise ExpressionParseError("Expression is empty.")

    tokens: list[str] = []
    pos = 0
    length = len(expression)

    while pos < length:
        if expression[pos].isspace():
            pos += 1
            continue

        match = _TOKEN_REGEX.match(expression, pos)
        if not match or match.end() == pos:
            raise ExpressionParseError(
                f"Unexpected character {expression[pos]!r} at position {pos} "
                f"in expression: {expression!r}"
            )

        token = match.group(0).strip()
        tokens.append(token)
        pos = match.end()

    if not tokens:
        raise ExpressionParseError("No tokens found in expression.")

    return tokens


# ---------------------------------------------------------------------------
# Shunting-yard: infix tokens -> AST
# ---------------------------------------------------------------------------

# (precedence, is_right_associative)
_OPERATORS: dict[str, tuple[int, bool]] = {
    "+": (1, False),
    "-": (1, False),
    "*": (2, False),
    "/": (2, False),
    "^": (3, True),
}


def _is_number_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", token))


def parse_expression(expression: str) -> AstNode:
    """
    Parse a math expression string into an AST, applying standard operator
    precedence, right-associativity for '^', parentheses, and unary minus.

    Raises ExpressionParseError on any malformed input (mismatched
    parentheses, invalid tokens, missing operands, etc).
    """
    tokens = tokenize(expression)

    output_stack: list[AstNode] = []
    operator_stack: list[str] = []

    # Tracks whether the *next* token, if it is '-', should be treated as
    # unary. True at the start of the expression, right after '(', or right
    # after a binary operator.
    expect_unary_context = True

    def apply_operator(op: str) -> None:
        if len(output_stack) < 2:
            raise ExpressionParseError(
                f"Operator {op!r} is missing operand(s) in expression: "
                f"{expression!r}"
            )
        right = output_stack.pop()
        left = output_stack.pop()
        output_stack.append(BinaryOpNode(op=op, left=left, right=right))

    def top_op_should_apply_before(new_op: str) -> bool:
        if not operator_stack or operator_stack[-1] == "(":
            return False
        top_prec, _ = _OPERATORS[operator_stack[-1]]
        new_prec, new_right_assoc = _OPERATORS[new_op]
        if new_right_assoc:
            return top_prec > new_prec
        return top_prec >= new_prec

    i = 0
    n = len(tokens)
    while i < n:
        token = tokens[i]

        if _is_number_token(token):
            output_stack.append(NumberNode(value=float(token)))
            expect_unary_context = False

        elif token == "(":
            operator_stack.append("(")
            expect_unary_context = True

        elif token == ")":
            while operator_stack and operator_stack[-1] != "(":
                apply_operator(operator_stack.pop())
            if not operator_stack:
                raise ExpressionParseError(
                    f"Mismatched parentheses in expression: {expression!r}"
                )
            operator_stack.pop()  # discard the matching '('
            expect_unary_context = False

        elif token in _OPERATORS:
            if token == "-" and expect_unary_context:
                # Unary minus: rewrite as (0 - operand).
                # We push a synthetic 0 and treat this exactly like a binary
                # '-', reusing all the same precedence machinery.
                output_stack.append(NumberNode(value=0.0))
                operator_stack.append("-")
                expect_unary_context = True
            else:
                while top_op_should_apply_before(token):
                    apply_operator(operator_stack.pop())
                operator_stack.append(token)
                expect_unary_context = True

        else:
            raise ExpressionParseError(
                f"Unrecognized token {token!r} in expression: {expression!r}"
            )

        i += 1

    while operator_stack:
        op = operator_stack.pop()
        if op == "(":
            raise ExpressionParseError(
                f"Mismatched parentheses in expression: {expression!r}"
            )
        apply_operator(op)

    if len(output_stack) != 1:
        raise ExpressionParseError(
            f"Malformed expression, could not reduce to a single result: "
            f"{expression!r}"
        )

    return output_stack[0]


def parse_to_dict(expression: str) -> dict:
    """
    Convenience wrapper: parse an expression and return the AST as a plain
    JSON-serializable dict, ready to be passed as a Temporal Workflow input.
    """
    return parse_expression(expression).to_dict()
