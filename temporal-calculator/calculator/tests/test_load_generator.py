"""
Tests for load_generator.random_expression - the one piece of pure logic
in the stress-test load generator. Everything else in that module talks
to a real Temporal client, which is out of scope for offline testing (same
boundary as poc_starter.py/starter.py - see VERIFICATION.md).
"""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.expression_parser import parse_expression  # noqa: E402


def _reload_load_generator(monkeypatch, **env_overrides):
    """
    load_generator.py reads its config from env vars at import time, so to
    test different configurations we need to set the env before a fresh
    import.
    """
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("load_generator", None)
    import load_generator  # noqa: PLC0415

    return load_generator


class TestRandomExpression:
    def test_default_skew_produces_mostly_addition(self, monkeypatch):
        lg = _reload_load_generator(monkeypatch)
        ops_seen = [
            lg.random_expression().split()[1] for _ in range(500)
        ]
        plus_fraction = ops_seen.count("+") / len(ops_seen)
        # STRESS_SKEW_RATIO defaults to 0.9 - allow statistical slack.
        assert plus_fraction > 0.75

    def test_every_generated_expression_is_actually_parseable(self, monkeypatch):
        lg = _reload_load_generator(monkeypatch)
        for _ in range(200):
            expr = lg.random_expression()
            # Should not raise - a load generator producing malformed
            # expressions would be silently testing nothing useful.
            parse_expression(expr)

    def test_custom_skew_op_and_ratio_respected(self, monkeypatch):
        lg = _reload_load_generator(
            monkeypatch, STRESS_SKEW_OP="^", STRESS_SKEW_RATIO="1.0"
        )
        ops_seen = {lg.random_expression().split()[1] for _ in range(50)}
        assert ops_seen == {"^"}

    def test_power_exponents_stay_small(self, monkeypatch):
        # Large exponents would make the stress test about huge-number
        # handling rather than about scheduling/throughput - confirm the
        # generator keeps them bounded.
        lg = _reload_load_generator(
            monkeypatch, STRESS_SKEW_OP="^", STRESS_SKEW_RATIO="1.0"
        )
        for _ in range(100):
            expr = lg.random_expression()
            exponent = int(expr.split()[2])
            assert 1 <= exponent <= 4

    def test_division_never_by_zero(self, monkeypatch):
        lg = _reload_load_generator(
            monkeypatch, STRESS_SKEW_OP="/", STRESS_SKEW_RATIO="1.0"
        )
        for _ in range(200):
            expr = lg.random_expression()
            divisor = int(expr.split()[2])
            assert divisor != 0
