"""
Unit and integration tests for utils/scenario_manager.py.

Tests are grouped into classes by the subsystem they exercise:
  - Metadata        – static PROBLEM_PATTERNS / SCENARIO_DESCRIPTIONS
  - Discovery       – discover_scenarios()
  - ScenarioStates  – load/save/set scenario-enabled state
  - PidFile         – _read_pid / _write_pid / _remove_pid_file
  - IsPidRunning    – is_pid_running()
  - LogExcerpt      – _read_log_excerpt()
  - ControlData     – load/save_control_data()
  - Rpm             – set_rpm() / get_rpm()
  - Schedules       – get_schedules() / add_schedule() / remove_schedule()
  - ScenarioDetails – get_scenario_details()
  - ProcessLifecycle – start_scenario() / stop_scenario()  [real subprocesses]
"""

import json
import os

import pytest

import utils.scenario_manager as sm


# ===========================================================================
# Metadata
# ===========================================================================

class TestMetadata:
    def test_all_pattern_groups_have_at_least_one_entry(self):
        for name, patterns in sm.PROBLEM_PATTERNS.items():
            assert len(patterns) >= 1, f"'{name}' should have at least one pattern"

    def test_every_pattern_scenario_has_a_description(self):
        for name in sm.PROBLEM_PATTERNS:
            assert name in sm.SCENARIO_DESCRIPTIONS, f"Missing description for '{name}'"

    def test_all_descriptions_are_exactly_five_lines(self):
        for name, lines in sm.SCENARIO_DESCRIPTIONS.items():
            assert len(lines) == 5, f"'{name}' should have exactly 5 description lines, got {len(lines)}"

    def test_ai_agent_application_in_problem_patterns(self):
        assert "ai-agent-application" in sm.PROBLEM_PATTERNS

    def test_ai_agent_key_patterns_present(self):
        patterns = sm.PROBLEM_PATTERNS["ai-agent-application"]
        for expected in ("slow_vector_search", "llm_rate_limit", "tool_failures", "guardrail_blocks"):
            assert expected in patterns

    def test_list_problem_patterns_is_sorted(self):
        result = sm.list_problem_patterns()
        assert list(result.keys()) == sorted(result.keys())

    def test_list_problem_patterns_matches_problem_patterns_exactly(self):
        result = sm.list_problem_patterns()
        assert set(result.keys()) == set(sm.PROBLEM_PATTERNS.keys())
        for name, patterns in result.items():
            assert patterns == list(sm.PROBLEM_PATTERNS[name])


# ===========================================================================
# Scenario discovery
# ===========================================================================

class TestDiscoverScenarios:
    def test_discovers_all_expected_real_scenarios(self):
        discovered = sm.discover_scenarios()
        for name in ("single", "service-tree", "astroshop", "ai-agent-application"):
            assert name in discovered, f"Expected scenario '{name}' not found"

    def test_discovers_only_py_files(self, patched_base):
        (patched_base / "scenarios" / "alpha.py").write_text("")
        (patched_base / "scenarios" / "readme.txt").write_text("")
        (patched_base / "scenarios" / "data.json").write_text("{}")
        result = sm.discover_scenarios()
        assert set(result.keys()) == {"alpha"}

    def test_skips_underscore_prefixed_files(self, patched_base):
        (patched_base / "scenarios" / "_internal.py").write_text("")
        (patched_base / "scenarios" / "public.py").write_text("")
        result = sm.discover_scenarios()
        assert "_internal" not in result
        assert "public" in result

    def test_empty_scenarios_dir_returns_empty_dict(self, patched_base):
        assert sm.discover_scenarios() == {}

    def test_missing_scenarios_dir_returns_empty_dict(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sm, "SCENARIO_DIR", tmp_path / "does_not_exist")
        assert sm.discover_scenarios() == {}

    def test_entry_schema_is_correct(self, patched_base):
        (patched_base / "scenarios" / "demo.py").write_text("")
        entry = sm.discover_scenarios()["demo"]
        assert entry["name"] == "demo"
        assert entry["path"].endswith("demo.py")
        assert entry["running"] is False
        assert entry["pid"] is None


# ===========================================================================
# Scenario state persistence
# ===========================================================================

class TestScenarioStates:
    def test_save_and_load_roundtrip(self, patched_base):
        states = {"alpha": True, "beta": False}
        sm.save_scenario_states(states)
        assert sm.load_scenario_states() == states

    def test_load_returns_empty_when_file_missing(self, patched_base):
        assert sm.load_scenario_states() == {}

    def test_load_returns_empty_on_corrupt_json(self, patched_base):
        sm.SCENARIO_STATE_FILE.write_text("NOT JSON", encoding="utf-8")
        assert sm.load_scenario_states() == {}

    def test_set_enabled_true_persists(self, patched_base):
        sm.set_scenario_enabled("demo", True)
        assert sm.load_scenario_states()["demo"] is True

    def test_set_enabled_false_persists(self, patched_base):
        sm.set_scenario_enabled("demo", False)
        assert sm.load_scenario_states()["demo"] is False

    def test_set_enabled_overwrites_previous_value(self, patched_base):
        sm.set_scenario_enabled("demo", True)
        sm.set_scenario_enabled("demo", False)
        assert sm.load_scenario_states()["demo"] is False


# ===========================================================================
# PID file helpers
# ===========================================================================

class TestPidFile:
    def test_write_then_read_roundtrip(self, patched_base):
        sm._write_pid("x", 12345)
        assert sm._read_pid("x") == 12345

    def test_read_returns_none_when_file_missing(self, patched_base):
        assert sm._read_pid("missing") is None

    def test_read_returns_none_for_corrupt_content(self, patched_base):
        (patched_base / ".scenario_x.pid").write_text("not_a_number", encoding="utf-8")
        assert sm._read_pid("x") is None

    def test_remove_deletes_pid_file(self, patched_base):
        sm._write_pid("x", 1)
        sm._remove_pid_file("x")
        assert not (patched_base / ".scenario_x.pid").exists()

    def test_remove_missing_pid_file_does_not_raise(self, patched_base):
        sm._remove_pid_file("nonexistent")  # must not raise


# ===========================================================================
# PID liveness
# ===========================================================================

class TestIsPidRunning:
    def test_zero_pid_returns_false(self):
        assert sm.is_pid_running(0) is False

    def test_negative_pid_returns_false(self):
        assert sm.is_pid_running(-1) is False

    def test_none_pid_returns_false(self):
        assert sm.is_pid_running(None) is False  # type: ignore[arg-type]

    def test_current_process_returns_true(self):
        assert sm.is_pid_running(os.getpid()) is True

    def test_nonexistent_pid_returns_false(self):
        # PID 2^24-1 is astronomically unlikely to be in use
        assert sm.is_pid_running(16_777_215) is False


# ===========================================================================
# get_running_pid
# ===========================================================================

class TestGetRunningPid:
    def test_returns_none_when_no_pid_file(self, patched_base):
        assert sm.get_running_pid("unknown") is None

    def test_returns_none_and_removes_file_for_dead_pid(self, patched_base):
        sm._write_pid("dead", 16_777_215)
        assert sm.get_running_pid("dead") is None
        assert sm._read_pid("dead") is None  # file was cleaned up

    def test_returns_pid_for_running_process(self, patched_base):
        sm._write_pid("live", os.getpid())
        assert sm.get_running_pid("live") == os.getpid()


# ===========================================================================
# Log excerpt helper
# ===========================================================================

class TestReadLogExcerpt:
    def test_returns_empty_string_when_file_missing(self, patched_base):
        assert sm._read_log_excerpt("missing") == ""

    def test_reads_full_content_when_below_limit(self, patched_base):
        (patched_base / ".scenario_x.log").write_text("hello world", encoding="utf-8")
        assert sm._read_log_excerpt("x") == "hello world"

    def test_truncates_to_max_chars(self, patched_base):
        (patched_base / ".scenario_x.log").write_text("A" * 2000, encoding="utf-8")
        excerpt = sm._read_log_excerpt("x", max_chars=100)
        assert len(excerpt) == 100

    def test_returns_trailing_section_when_truncated(self, patched_base):
        content = "START" + "B" * 900 + "END"
        (patched_base / ".scenario_x.log").write_text(content, encoding="utf-8")
        excerpt = sm._read_log_excerpt("x", max_chars=50)
        assert excerpt.endswith("END")


# ===========================================================================
# Control data
# ===========================================================================

class TestControlData:
    def test_save_and_load_roundtrip(self, patched_base):
        data = {"rpm": 50, "schedules": [], "slow_response": True}
        sm.save_control_data("demo", data)
        assert sm.load_control_data("demo") == data

    def test_load_returns_empty_when_file_missing(self, patched_base):
        assert sm.load_control_data("nothing") == {}

    def test_load_returns_empty_for_corrupt_json(self, patched_base):
        sm.get_control_file("demo").write_text("CORRUPT", encoding="utf-8")
        assert sm.load_control_data("demo") == {}

    def test_save_overwrites_previous_data(self, patched_base):
        sm.save_control_data("demo", {"rpm": 10})
        sm.save_control_data("demo", {"rpm": 99})
        assert sm.load_control_data("demo")["rpm"] == 99


# ===========================================================================
# RPM management
# ===========================================================================

class TestRpm:
    def test_set_valid_rpm_returns_ok(self, patched_base):
        result = sm.set_rpm("single", 42)
        assert result == {"status": "ok", "rpm": 42}

    def test_set_rpm_persists(self, patched_base):
        sm.set_rpm("single", 77)
        assert sm.get_rpm("single") == 77

    def test_set_rpm_clamps_to_maximum_1000(self, patched_base):
        result = sm.set_rpm("single", 9999)
        assert result["rpm"] == 1000

    def test_set_rpm_clamps_to_minimum_1(self, patched_base):
        result = sm.set_rpm("single", 0)
        assert result["rpm"] == 1

    def test_set_rpm_rejects_non_integer_string(self, patched_base):
        result = sm.set_rpm("single", "banana")
        assert "error" in result

    def test_get_rpm_returns_default_10_when_no_data(self, patched_base):
        assert sm.get_rpm("no_data") == 10


# ===========================================================================
# Schedule management
# ===========================================================================

class TestSchedules:
    def test_get_schedules_returns_empty_list_initially(self, patched_base):
        assert sm.get_schedules("single") == []

    def test_add_valid_schedule_succeeds(self, patched_base):
        result = sm.add_schedule("single", "slow_response", "0 0 * * 1", 60)
        assert result.get("status") == "ok"
        entry = result["schedule"]
        assert entry["pattern"] == "slow_response"
        assert entry["cron"] == "0 0 * * 1"
        assert entry["duration_minutes"] == 60
        assert "id" in entry

    def test_added_schedule_is_returned_by_get_schedules(self, patched_base):
        sm.add_schedule("single", "slow_response", "0 0 * * 1", 60)
        schedules = sm.get_schedules("single")
        assert len(schedules) == 1
        assert schedules[0]["pattern"] == "slow_response"

    def test_add_unknown_pattern_returns_error(self, patched_base):
        result = sm.add_schedule("single", "nonexistent_pattern", "0 0 * * 1", 60)
        assert "error" in result

    def test_add_to_unknown_scenario_returns_error(self, patched_base):
        result = sm.add_schedule("nonexistent_scenario", "slow_response", "0 0 * * 1", 60)
        assert "error" in result

    def test_add_cron_with_wrong_field_count_returns_error(self, patched_base):
        result = sm.add_schedule("single", "slow_response", "0 0 * *", 60)  # 4 fields
        assert "error" in result

    def test_add_syntactically_invalid_cron_returns_error(self, patched_base):
        result = sm.add_schedule("single", "slow_response", "99 99 99 99 99", 60)
        assert "error" in result

    def test_add_non_integer_duration_returns_error(self, patched_base):
        result = sm.add_schedule("single", "slow_response", "0 0 * * 1", "bad")
        assert "error" in result

    def test_duration_clamped_to_seven_day_maximum(self, patched_base):
        max_duration = 7 * 24 * 60
        result = sm.add_schedule("single", "slow_response", "0 0 * * 1", 999_999)
        assert result["schedule"]["duration_minutes"] == max_duration

    def test_multiple_schedules_accumulate(self, patched_base):
        sm.add_schedule("single", "slow_response", "0 0 * * 1", 30)
        sm.add_schedule("single", "high_latency", "0 12 * * 3", 60)
        assert len(sm.get_schedules("single")) == 2

    def test_remove_existing_schedule_succeeds(self, patched_base):
        sm.add_schedule("single", "slow_response", "0 0 * * 1", 30)
        entry_id = sm.get_schedules("single")[0]["id"]
        result = sm.remove_schedule("single", entry_id)
        assert result.get("status") == "ok"
        assert sm.get_schedules("single") == []

    def test_remove_nonexistent_schedule_returns_error(self, patched_base):
        result = sm.remove_schedule("single", "does_not_exist")
        assert "error" in result

    def test_get_schedules_skips_malformed_entries(self, patched_base):
        sm.save_control_data("single", {
            "schedules": [
                "not_a_dict",
                {"pattern": "slow_response"},                           # missing cron + duration
                {"pattern": "slow_response", "cron": "0 0 * * 1",
                 "duration_minutes": "bad"},                            # non-int duration
                {"pattern": "slow_response", "cron": "0 0 * * 1",
                 "duration_minutes": 60},                               # valid entry
            ]
        })
        schedules = sm.get_schedules("single")
        assert len(schedules) == 1
        assert schedules[0]["pattern"] == "slow_response"

    def test_get_schedules_assigns_id_when_missing(self, patched_base):
        sm.save_control_data("single", {
            "schedules": [
                {"pattern": "slow_response", "cron": "0 0 * * 1", "duration_minutes": 60}
                # id deliberately omitted
            ]
        })
        entry = sm.get_schedules("single")[0]
        assert len(entry["id"]) > 0


# ===========================================================================
# Scenario details
# ===========================================================================

class TestScenarioDetails:
    """These tests use the real scenarios directory (no patching) to verify
    the full enriched payload returned by get_scenario_details()."""

    def test_known_scenarios_present(self):
        details = sm.get_scenario_details()
        for name in sm.PROBLEM_PATTERNS:
            assert name in details

    def test_description_lines_is_five_elements(self):
        details = sm.get_scenario_details()
        for name in sm.PROBLEM_PATTERNS:
            assert len(details[name]["description_lines"]) == 5

    def test_description_string_equals_joined_lines(self):
        details = sm.get_scenario_details()
        for name in sm.PROBLEM_PATTERNS:
            assert details[name]["description"] == "\n".join(details[name]["description_lines"])

    def test_available_patterns_match_problem_patterns(self):
        details = sm.get_scenario_details()
        for name in sm.PROBLEM_PATTERNS:
            assert details[name]["available_patterns"] == sm.PROBLEM_PATTERNS[name]

    def test_rpm_is_an_integer(self):
        details = sm.get_scenario_details()
        for name in sm.PROBLEM_PATTERNS:
            assert isinstance(details[name]["rpm"], int)

    def test_schedule_entries_is_a_list(self):
        details = sm.get_scenario_details()
        for name in sm.PROBLEM_PATTERNS:
            assert isinstance(details[name]["schedule_entries"], list)

    def test_running_field_is_boolean(self):
        details = sm.get_scenario_details()
        for name in sm.PROBLEM_PATTERNS:
            assert isinstance(details[name]["running"], bool)


# ===========================================================================
# Process lifecycle  (integration – spawns real subprocesses)
# ===========================================================================

class TestProcessLifecycle:
    def test_start_unknown_scenario_returns_error(self, patched_base):
        result = sm.start_scenario("no_such_scenario")
        assert "error" in result
        assert "not found" in result["error"]

    def test_start_already_running_scenario_returns_error(self, patched_base):
        # Fake a running process by pointing the PID file at our own process.
        (patched_base / "scenarios" / "demo.py").write_text("")
        sm._write_pid("demo", os.getpid())
        result = sm.start_scenario("demo")
        assert "error" in result
        assert "already running" in result["error"]

    def test_start_crash_returns_error_with_exit_code(self, crash_scenario):
        result = sm.start_scenario("crash_scenario", startup_wait_seconds=0.5)
        assert "error" in result
        assert result.get("exit_code") == 2

    def test_start_crash_error_includes_log_file_path(self, crash_scenario):
        result = sm.start_scenario("crash_scenario", startup_wait_seconds=0.5)
        assert "log_file" in result

    def test_start_stable_process_reports_started(self, started_fake):
        assert started_fake.get("status") == "started"

    def test_start_stable_process_returns_positive_pid(self, started_fake):
        pid = started_fake.get("pid")
        assert isinstance(pid, int)
        assert pid > 0

    def test_started_process_is_alive(self, started_fake):
        assert sm.is_pid_running(started_fake["pid"]) is True

    def test_start_writes_pid_file(self, started_fake):
        assert sm._read_pid("fake_scenario") == started_fake["pid"]

    def test_stop_terminates_process(self, started_fake):
        pid = started_fake["pid"]
        result = sm.stop_scenario("fake_scenario")
        assert result.get("status") in {"stopped", "killed"}
        assert sm.is_pid_running(pid) is False

    def test_stop_removes_pid_file(self, started_fake):
        sm.stop_scenario("fake_scenario")
        assert sm._read_pid("fake_scenario") is None

    def test_stop_marks_scenario_disabled(self, started_fake):
        sm.stop_scenario("fake_scenario")
        states = sm.load_scenario_states()
        assert states.get("fake_scenario") is False

    def test_stop_not_running_returns_error(self, patched_base):
        result = sm.stop_scenario("not_running_scenario")
        assert "error" in result
        assert "not running" in result["error"]
