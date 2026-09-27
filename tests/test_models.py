"""Tests for duration parsing and job models."""

import pytest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from pulse_guard.models import parse_duration_to_seconds


def test_parse_duration_units():
    assert parse_duration_to_seconds("30s") == 30
    assert parse_duration_to_seconds("15m") == 900
    assert parse_duration_to_seconds("2h") == 7200
    assert parse_duration_to_seconds("1d") == 86400
    assert parse_duration_to_seconds("2w") == 1209600


def test_parse_integer_passthrough():
    assert parse_duration_to_seconds(3600) == 3600
    assert parse_duration_to_seconds("60") == 60


def test_parse_invalid_duration():
    with pytest.raises(ValueError):
        parse_duration_to_seconds("invalid")
    with pytest.raises(ValueError):
        parse_duration_to_seconds("10x")
