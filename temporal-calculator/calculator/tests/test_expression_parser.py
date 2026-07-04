"""
Unit tests for calculator.parser.expression_parser.

Two complementary verification strategies are used:

1. Explicit hand-checked cases with known expected AST shape and/or value.
2. A generic `evaluate()` helper that walks the produced AST and computes
   its numeric result, cross-checked against Python's own `eval()` (with
   '^' rewritten to '**') as an independent oracle for a broader set of
   expressions. This catches precedence/associativity bugs that hand-picked
   cases might miss.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.expression_parser import (  # noqa: E402
    BinaryOpNode,
    ExpressionParseError,
    NumberNode,
    parse_expression,
    parse_to_dict,
    tokenize,
)


# ---------------------------------------------------------------------------
# Test helper: evaluate an AST to a float, independent of any Temporal logic
# ---------------------------------------------------------------------------

def evaluate(node) -> float:
    if isinstance(node, NumberNode):
        return node.value
    if isinstance(node, BinaryOpNode):
        left = evaluate(node.left)
        right = evaluate(node.right)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            return left / right
        if node.op == "^":
            return left ** right
        raise ValueError(f"Unknown op {node.op!r}")
    raise TypeError(f"Unknown node type: {type(node)!r}")


def python_oracle(expression: str) -> float:
    """Evaluate via Python's eval as an independent ground truth."""
    py_expr = expression.replace("^", "**")
    return eval(py_expr)  # noqa: S307 - test-only, controlled input


# ---------------------------------------------------------------------------
# Tokenizer tests
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_simple_tokens(self):
        assert tokenize("1 + 2") == ["1", "+", "2"]

    def test_no_spaces(self):
        assert tokenize("1+2*3") == ["1", "+", "2", "*", "3"]

    def test_decimals(self):
        assert tokenize("1.5 + 2.25") == ["1.5", "+", "2.25"]

    def test_parentheses(self):
        assert tokenize("(1+2)*3") == ["(", "1", "+", "2", ")", "*", "3"]

    def test_empty_raises(self):
        with pytest.raises(ExpressionParseError):
            tokenize("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ExpressionParseError):
            tokenize("   ")

    def test_invalid_character_raises(self):
        with pytest.raises(ExpressionParseError):
            tokenize("1 + a")

    def test_invalid_character_percent(self):
        with pytest.raises(ExpressionParseError):
            tokenize("1 % 2")


# ---------------------------------------------------------------------------
# Parser: explicit hand-checked cases
# ---------------------------------------------------------------------------

class TestParseExplicitCases:
    def test_single_number(self):
        ast = parse_expression("42")
        assert ast == NumberNode(42.0)

    def test_simple_addition(self):
        ast = parse_expression("1 + 2")
        assert ast == BinaryOpNode("+", NumberNode(1.0), NumberNode(2.0))

    def test_precedence_mult_over_add(self):
        # 1 + 2 * 3 -> 1 + (2 * 3)
        ast = parse_expression("1 + 2 * 3")
        expected = BinaryOpNode(
            "+", NumberNode(1.0), BinaryOpNode("*", NumberNode(2.0), NumberNode(3.0))
        )
        assert ast == expected
        assert evaluate(ast) == 7.0

    def test_parentheses_override_precedence(self):
        # (1 + 2) * 3 -> (1 + 2) * 3
        ast = parse_expression("(1 + 2) * 3")
        expected = BinaryOpNode(
            "*", BinaryOpNode("+", NumberNode(1.0), NumberNode(2.0)), NumberNode(3.0)
        )
        assert ast == expected
        assert evaluate(ast) == 9.0

    def test_power_right_associative(self):
        # 2 ^ 3 ^ 2 -> 2 ^ (3 ^ 2) = 2 ^ 9 = 512, NOT (2^3)^2 = 64
        ast = parse_expression("2 ^ 3 ^ 2")
        expected = BinaryOpNode(
            "^", NumberNode(2.0), BinaryOpNode("^", NumberNode(3.0), NumberNode(2.0))
        )
        assert ast == expected
        assert evaluate(ast) == 512.0

    def test_left_associative_subtraction(self):
        # 10 - 3 - 2 -> (10 - 3) - 2 = 5, NOT 10 - (3 - 2) = 9
        ast = parse_expression("10 - 3 - 2")
        assert evaluate(ast) == 5.0

    def test_the_assignment_example_expression(self):
        # From the spec: "1 + 5^3 * (2 - 5)"
        # = 1 + 125 * (-3) = 1 - 375 = -374
        ast = parse_expression("1 + 5^3 * (2 - 5)")
        assert evaluate(ast) == -374.0

    def test_unary_minus_leading(self):
        ast = parse_expression("-5 + 3")
        assert evaluate(ast) == -2.0

    def test_unary_minus_after_open_paren(self):
        ast = parse_expression("(-5 + 3) * 2")
        assert evaluate(ast) == -4.0

    def test_unary_minus_after_operator(self):
        # 4 * -2 -> 4 * (0 - 2) = -8
        ast = parse_expression("4 * -2")
        assert evaluate(ast) == -8.0

    def test_nested_parentheses(self):
        ast = parse_expression("((1 + 2) * (3 - 1)) / 2")
        assert evaluate(ast) == 3.0

    def test_division(self):
        ast = parse_expression("10 / 4")
        assert evaluate(ast) == 2.5


# ---------------------------------------------------------------------------
# Parser: malformed input handling
# ---------------------------------------------------------------------------

class TestParseErrors:
    def test_mismatched_missing_close_paren(self):
        with pytest.raises(ExpressionParseError):
            parse_expression("(1 + 2")

    def test_mismatched_extra_close_paren(self):
        with pytest.raises(ExpressionParseError):
            parse_expression("1 + 2)")

    def test_missing_operand_trailing_operator(self):
        with pytest.raises(ExpressionParseError):
            parse_expression("1 +")

    def test_two_numbers_no_operator(self):
        with pytest.raises(ExpressionParseError):
            parse_expression("1 2")

    def test_empty_parentheses(self):
        with pytest.raises(ExpressionParseError):
            parse_expression("()")

    def test_empty_expression(self):
        with pytest.raises(ExpressionParseError):
            parse_expression("")


# ---------------------------------------------------------------------------
# Serialization: AST -> dict, for crossing the Temporal wire
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_number_to_dict(self):
        assert NumberNode(3.0).to_dict() == {"type": "number", "value": 3.0}

    def test_binary_op_to_dict_shape(self):
        d = parse_to_dict("1 + 2")
        assert d == {
            "type": "binary_op",
            "op": "+",
            "left": {"type": "number", "value": 1.0},
            "right": {"type": "number", "value": 2.0},
        }

    def test_parse_to_dict_is_json_serializable(self):
        import json

        d = parse_to_dict("1 + 5^3 * (2 - 5)")
        # Should not raise
        json.dumps(d)


# ---------------------------------------------------------------------------
# Cross-checked against Python's own evaluator as an oracle
# ---------------------------------------------------------------------------

ORACLE_EXPRESSIONS = [
    "1 + 1",
    "2 * 3 + 4",
    "2 * (3 + 4)",
    "10 - 2 - 3",
    "2 ^ 2 ^ 3",
    "(2 ^ 2) ^ 3",
    "1 + 5^3 * (2 - 5)",
    "((1 + 2) * (3 - 1)) / 2",
    "100 / 5 / 2",
    "3 + 4 * 2 / (1 - 5) ^ 2 ^ 3",
    "-3 + 4",
    "5 * -3",
    "(1 + 2) * (3 + 4) - 5 / 5",
]


@pytest.mark.parametrize("expression", ORACLE_EXPRESSIONS)
def test_matches_python_oracle(expression):
    ast = parse_expression(expression)
    ours = evaluate(ast)
    expected = python_oracle(expression)
    assert ours == pytest.approx(expected), (
        f"Mismatch for {expression!r}: ours={ours}, python={expected}"
    )
