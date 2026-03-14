"""
Integration tests for the Flask API defined in app.py.

The test suite uses Flask's built-in test client.  All scenario-manager
calls that would touch the real filesystem or spawn subprocesses are patched
so these tests remain fast and hermetic.

Notes on patching targets
--------------------------
app.py does `from utils.scenario_manager import start_scenario, ...` at the
top level so the imported names live in the `app` module namespace.  Patch
`app.<name>` for those.  The remove_schedule handler performs a *local*
import inside the view function, so it must be patched at
`utils.scenario_manager.remove_schedule` instead.
"""

import json
from unittest.mock import patch

import pytest


# ===========================================================================
# Authentication
# ===========================================================================

class TestAuthentication:
    def test_unauthenticated_api_request_redirects_to_login(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        with flask_app.app.test_client() as client:
            resp = client.get("/api/scenarios")
        assert resp.status_code == 302
        assert b"/login" in resp.headers["Location"].encode()

    def test_unauthenticated_start_redirects_to_login(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        with flask_app.app.test_client() as client:
            resp = client.post("/api/scenarios/single/start")
        assert resp.status_code == 302

    def test_login_with_wrong_password_shows_error(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        with flask_app.app.test_client() as client:
            resp = client.post("/login", data={"password": "definitely_wrong"})
        assert resp.status_code == 200
        assert b"Invalid password" in resp.data

    def test_login_with_correct_password_redirects(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        with flask_app.app.test_client() as client:
            resp = client.post("/login", data={"password": "pytest-admin-test"})
        assert resp.status_code == 302

    def test_logout_clears_session_so_api_redirects(self, app_client):
        app_client.get("/logout")
        resp = app_client.get("/api/scenarios")
        assert resp.status_code == 302


# ===========================================================================
# Health endpoint  (no authentication required)
# ===========================================================================

class TestHealth:
    def test_health_is_accessible_without_login(self):
        import app as flask_app
        flask_app.app.config["TESTING"] = True
        with flask_app.app.test_client() as client:
            with patch("app.get_scenario_status", return_value={}):
                resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_returns_ok_status(self, app_client):
        with patch("app.get_scenario_status", return_value={}):
            resp = app_client.get("/api/health")
        data = json.loads(resp.data)
        assert data["status"] == "ok"

    def test_health_counts_running_scenarios(self, app_client):
        fake_status = {
            "single": {"running": True},
            "astroshop": {"running": False},
            "ai-agent-application": {"running": True},
        }
        with patch("app.get_scenario_status", return_value=fake_status):
            resp = app_client.get("/api/health")
        data = json.loads(resp.data)
        assert data["scenarios_running"] == 2
        assert "single" in data["running_scenarios"]
        assert "ai-agent-application" in data["running_scenarios"]
        assert "astroshop" not in data["running_scenarios"]

    def test_health_running_scenarios_is_empty_list_when_none_run(self, app_client):
        fake_status = {"single": {"running": False}}
        with patch("app.get_scenario_status", return_value=fake_status):
            resp = app_client.get("/api/health")
        data = json.loads(resp.data)
        assert data["running_scenarios"] == []


# ===========================================================================
# GET /api/scenarios
# ===========================================================================

class TestListScenarios:
    def test_returns_200_and_json_body(self, app_client):
        with patch("app.get_scenario_details", return_value={}):
            resp = app_client.get("/api/scenarios")
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/json")

    def test_response_contains_scenario_details(self, app_client):
        fake = {
            "single": {
                "running": False,
                "pid": None,
                "description": "line1\nline2",
                "description_lines": ["line1", "line2"],
                "available_patterns": ["slow_response"],
                "schedule_entries": [],
                "rpm": 10,
            }
        }
        with patch("app.get_scenario_details", return_value=fake):
            resp = app_client.get("/api/scenarios")
        data = json.loads(resp.data)
        assert "single" in data
        assert data["single"]["available_patterns"] == ["slow_response"]
        assert data["single"]["description_lines"] == ["line1", "line2"]

    def test_response_is_empty_dict_when_no_scenarios(self, app_client):
        with patch("app.get_scenario_details", return_value={}):
            resp = app_client.get("/api/scenarios")
        assert json.loads(resp.data) == {}


# ===========================================================================
# POST /api/scenarios/<name>/start
# ===========================================================================

class TestStartScenario:
    def test_successful_start_returns_pid(self, app_client):
        fake = {"status": "started", "scenario": "single", "pid": 1234,
                "log_file": "/tmp/x.log"}
        with patch("app.start_scenario", return_value=fake):
            resp = app_client.post("/api/scenarios/single/start")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "started"
        assert data["pid"] == 1234

    def test_start_error_propagated_in_body(self, app_client):
        fake = {"error": "Scenario 'missing' not found"}
        with patch("app.start_scenario", return_value=fake):
            resp = app_client.post("/api/scenarios/missing/start")
        data = json.loads(resp.data)
        assert "error" in data

    def test_start_passes_scenario_name_to_backend(self, app_client):
        with patch("app.start_scenario", return_value={"status": "started", "pid": 1}) as mock_start:
            app_client.post("/api/scenarios/astroshop/start")
        mock_start.assert_called_once_with("astroshop")


# ===========================================================================
# POST /api/scenarios/<name>/stop
# ===========================================================================

class TestStopScenario:
    def test_successful_stop_returns_stopped_status(self, app_client):
        fake = {"status": "stopped", "scenario": "single", "pid": 1234}
        with patch("app.stop_scenario", return_value=fake):
            resp = app_client.post("/api/scenarios/single/stop")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "stopped"

    def test_stop_error_propagated_in_body(self, app_client):
        fake = {"error": "Scenario 'single' is not running"}
        with patch("app.stop_scenario", return_value=fake):
            resp = app_client.post("/api/scenarios/single/stop")
        data = json.loads(resp.data)
        assert "error" in data

    def test_stop_passes_scenario_name_to_backend(self, app_client):
        with patch("app.stop_scenario", return_value={"status": "stopped", "pid": 1}) as mock_stop:
            app_client.post("/api/scenarios/astroshop/stop")
        mock_stop.assert_called_once_with("astroshop")


# ===========================================================================
# POST /api/scenarios/<name>/schedules
# ===========================================================================

class TestAddSchedule:
    def test_unknown_scenario_returns_404(self, app_client):
        resp = app_client.post(
            "/api/scenarios/totally_unknown_scenario/schedules",
            json={"pattern": "x", "cron": "0 0 * * 1", "duration_minutes": 60},
        )
        assert resp.status_code == 404

    def test_valid_schedule_returns_200_and_ok_status(self, app_client):
        fake_entry = {"id": "abc", "pattern": "slow_response",
                      "cron": "0 0 * * 1", "duration_minutes": 60}
        with patch("app.add_schedule", return_value={"status": "ok", "schedule": fake_entry}):
            resp = app_client.post(
                "/api/scenarios/single/schedules",
                json={"pattern": "slow_response", "cron": "0 0 * * 1", "duration_minutes": 60},
            )
        assert resp.status_code == 200
        assert json.loads(resp.data)["status"] == "ok"

    def test_invalid_schedule_returns_400(self, app_client):
        with patch("app.add_schedule", return_value={"error": "Invalid cron expression"}):
            resp = app_client.post(
                "/api/scenarios/single/schedules",
                json={"pattern": "slow_response", "cron": "bad_cron", "duration_minutes": 60},
            )
        assert resp.status_code == 400

    def test_schedule_payload_forwarded_to_backend(self, app_client):
        with patch("app.add_schedule",
                   return_value={"status": "ok", "schedule": {}}) as mock_add:
            app_client.post(
                "/api/scenarios/single/schedules",
                json={"pattern": "high_latency", "cron": "0 12 * * 5", "duration_minutes": 90},
            )
        mock_add.assert_called_once_with("single", "high_latency", "0 12 * * 5", 90)


# ===========================================================================
# DELETE /api/scenarios/<name>/schedules/<id>
# ===========================================================================

class TestRemoveSchedule:
    def test_unknown_scenario_returns_404(self, app_client):
        resp = app_client.delete("/api/scenarios/totally_unknown_scenario/schedules/some_id")
        assert resp.status_code == 404

    def test_successful_removal_returns_200(self, app_client):
        fake = {"status": "ok", "removed": "abc123", "scenario": "single"}
        with patch("utils.scenario_manager.remove_schedule", return_value=fake):
            resp = app_client.delete("/api/scenarios/single/schedules/abc123")
        assert resp.status_code == 200

    def test_missing_schedule_returns_404(self, app_client):
        fake = {"error": "Schedule 'bad_id' not found"}
        with patch("utils.scenario_manager.remove_schedule", return_value=fake):
            resp = app_client.delete("/api/scenarios/single/schedules/bad_id")
        assert resp.status_code == 404


# ===========================================================================
# POST /api/scenarios/<name>/rpm
# ===========================================================================

class TestSetRpm:
    def test_sets_rpm_and_returns_result(self, app_client):
        fake = {"status": "ok", "rpm": 55}
        with patch("app.set_rpm", return_value=fake):
            resp = app_client.post(
                "/api/scenarios/single/rpm",
                json={"rpm": 55},
            )
        assert resp.status_code == 200
        assert json.loads(resp.data)["rpm"] == 55

    def test_rpm_value_forwarded_to_backend(self, app_client):
        with patch("app.set_rpm", return_value={"status": "ok", "rpm": 30}) as mock_rpm:
            app_client.post("/api/scenarios/single/rpm", json={"rpm": 30})
        mock_rpm.assert_called_once_with("single", 30)

    def test_missing_rpm_key_defaults_to_10(self, app_client):
        with patch("app.set_rpm", return_value={"status": "ok", "rpm": 10}) as mock_rpm:
            app_client.post("/api/scenarios/single/rpm", json={})
        mock_rpm.assert_called_once_with("single", 10)
