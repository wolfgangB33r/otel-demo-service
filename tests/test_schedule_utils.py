"""
Unit tests for utils/schedule_utils.py.

Tests cover:
  - get_rpm()             – reading RPM with defaults, clamping, error tolerance
  - get_active_patterns() – explicit flags, cron-triggered activation, edge cases
"""

import json
from pathlib import Path

import pytest

import utils.schedule_utils as sut


AVAILABLE = ["slow_response", "high_latency", "error_rate", "timeout"]


def write_control(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# ===========================================================================
# get_rpm
# ===========================================================================

class TestGetRpm:
    def test_returns_default_10_when_file_missing(self, tmp_path):
        assert sut.get_rpm(tmp_path / "missing.json") == 10

    def test_honours_custom_default(self, tmp_path):
        assert sut.get_rpm(tmp_path / "missing.json", default=25) == 25

    def test_reads_stored_value(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"rpm": 60})
        assert sut.get_rpm(cf) == 60

    def test_clamps_zero_to_one(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"rpm": 0})
        assert sut.get_rpm(cf) == 1

    def test_clamps_negative_to_one(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"rpm": -50})
        assert sut.get_rpm(cf) == 1

    def test_clamps_above_1000_to_1000(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"rpm": 9999})
        assert sut.get_rpm(cf) == 1000

    def test_returns_default_for_corrupt_json(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        cf.write_text("NOT JSON", encoding="utf-8")
        assert sut.get_rpm(cf) == 10

    def test_returns_default_for_non_integer_rpm_value(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"rpm": "fast"})
        assert sut.get_rpm(cf) == 10

    def test_returns_default_when_rpm_key_absent(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"schedules": []})
        assert sut.get_rpm(cf) == 10


# ===========================================================================
# get_active_patterns
# ===========================================================================

class TestGetActivePatterns:
    def test_empty_control_file_returns_empty_dict(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {})
        assert sut.get_active_patterns(cf, AVAILABLE) == {}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert sut.get_active_patterns(tmp_path / "no.json", AVAILABLE) == {}

    def test_explicit_true_flag_activates_pattern(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"slow_response": True})
        result = sut.get_active_patterns(cf, AVAILABLE)
        assert result.get("slow_response") is True

    def test_explicit_false_flag_does_not_activate(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"slow_response": False})
        assert "slow_response" not in sut.get_active_patterns(cf, AVAILABLE)

    def test_unknown_key_is_ignored(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"unknown_pattern": True})
        result = sut.get_active_patterns(cf, AVAILABLE)
        assert "unknown_pattern" not in result

    def test_multiple_explicit_flags_combined(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {
            "slow_response": True,
            "error_rate": True,
            "timeout": False,
        })
        result = sut.get_active_patterns(cf, AVAILABLE)
        assert "slow_response" in result
        assert "error_rate" in result
        assert "timeout" not in result

    def test_active_cron_schedule_activates_pattern(self, tmp_path):
        # "* * * * *" fires every minute; 7-day duration means this is always active.
        cf = tmp_path / "ctrl.json"
        write_control(cf, {
            "schedules": [{
                "id": "t1",
                "pattern": "slow_response",
                "cron": "* * * * *",
                "duration_minutes": 7 * 24 * 60,
            }]
        })
        result = sut.get_active_patterns(cf, AVAILABLE)
        assert result.get("slow_response") is True

    def test_non_list_schedules_field_is_tolerated(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {"schedules": "not_a_list"})
        assert sut.get_active_patterns(cf, AVAILABLE) == {}

    def test_malformed_schedule_entries_are_skipped(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {
            "schedules": [
                "a_string_entry",
                {"pattern": "slow_response"},                                  # missing cron/duration
                {"pattern": "slow_response", "cron": "bad", "duration_minutes": 60},  # invalid cron
                {"pattern": "not_available", "cron": "* * * * *",
                 "duration_minutes": 60},                                       # unknown pattern
            ]
        })
        assert sut.get_active_patterns(cf, AVAILABLE) == {}

    def test_schedule_for_unavailable_pattern_is_ignored(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {
            "schedules": [{
                "id": "t2",
                "pattern": "nonexistent",
                "cron": "* * * * *",
                "duration_minutes": 7 * 24 * 60,
            }]
        })
        assert sut.get_active_patterns(cf, AVAILABLE) == {}

    def test_explicit_flag_and_schedule_can_coexist(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        write_control(cf, {
            "high_latency": True,
            "schedules": [{
                "id": "t3",
                "pattern": "slow_response",
                "cron": "* * * * *",
                "duration_minutes": 7 * 24 * 60,
            }],
        })
        result = sut.get_active_patterns(cf, AVAILABLE)
        assert result.get("high_latency") is True
        assert result.get("slow_response") is True

    def test_corrupt_control_file_returns_empty_dict(self, tmp_path):
        cf = tmp_path / "ctrl.json"
        cf.write_text("CORRUPT JSON", encoding="utf-8")
        assert sut.get_active_patterns(cf, AVAILABLE) == {}
