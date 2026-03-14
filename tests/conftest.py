"""
Shared pytest fixtures and path bootstrapping.

APP_ADMIN_PASSWORD must be set at module-load time (before any test module
imports app.py, which calls sys.exit(1) if the variable is absent).
"""
import os
import sys
from pathlib import Path

# Set before any test-module-level `import app` occurs.
os.environ.setdefault("APP_ADMIN_PASSWORD", "pytest-admin-test")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


# ---------------------------------------------------------------------------
# Filesystem isolation helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_base(tmp_path):
    """Temporary project root with an empty scenarios directory."""
    (tmp_path / "scenarios").mkdir()
    return tmp_path


@pytest.fixture()
def patched_base(tmp_base, monkeypatch):
    """
    Redirect all scenario_manager module-level path variables to tmp_base so
    tests do not touch or depend on real workspace files.
    """
    import utils.scenario_manager as sm
    monkeypatch.setattr(sm, "BASE_DIR", tmp_base)
    monkeypatch.setattr(sm, "SCENARIO_DIR", tmp_base / "scenarios")
    monkeypatch.setattr(sm, "SCENARIO_STATE_FILE", tmp_base / ".scenario_states.json")
    return tmp_base


# ---------------------------------------------------------------------------
# Scenario script fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_scenario(patched_base):
    """
    Write a minimal long-running scenario script into the patched scenarios
    directory.  The script loops indefinitely and attempts graceful SIGTERM
    handling (falls back silently on Windows where the signal may not fire).
    """
    (patched_base / "scenarios" / "fake_scenario.py").write_text(
        "import time, signal\n"
        "running = True\n"
        "def _stop(s, f): global running; running = False\n"
        "try:\n"
        "    signal.signal(signal.SIGTERM, _stop)\n"
        "    signal.signal(signal.SIGINT, _stop)\n"
        "except Exception: pass\n"
        "while running:\n"
        "    time.sleep(0.05)\n",
        encoding="utf-8",
    )
    return patched_base


@pytest.fixture()
def crash_scenario(patched_base):
    """Scenario script that exits immediately with code 2."""
    (patched_base / "scenarios" / "crash_scenario.py").write_text(
        "import sys; sys.exit(2)\n",
        encoding="utf-8",
    )
    return patched_base


@pytest.fixture()
def started_fake(fake_scenario):
    """
    Start fake_scenario and yield the start-result dict.
    Guarantees that stop_scenario is called in teardown even if the test
    itself fails partway through.
    """
    from utils.scenario_manager import start_scenario, stop_scenario

    result = start_scenario("fake_scenario", startup_wait_seconds=0.5)
    yield result
    # Teardown: best-effort stop; errors are expected if test already stopped it.
    stop_scenario("fake_scenario")


# ---------------------------------------------------------------------------
# Flask test client
# ---------------------------------------------------------------------------

@pytest.fixture()
def app_client():
    """Authenticated Flask test client."""
    import app as flask_app

    flask_app.app.config["TESTING"] = True
    with flask_app.app.test_client() as client:
        client.post("/login", data={"password": "pytest-admin-test"})
        yield client
