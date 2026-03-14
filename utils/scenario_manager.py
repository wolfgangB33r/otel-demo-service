import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from croniter import croniter


BASE_DIR = Path(__file__).resolve().parent.parent
SCENARIO_DIR = BASE_DIR / "scenarios"
SCENARIO_STATE_FILE = BASE_DIR / ".scenario_states.json"

PROBLEM_PATTERNS = {
    "ai-agent-application": [
        "slow_vector_search",
        "llm_rate_limit",
        "tool_failures",
        "guardrail_blocks",
        "stale_inventory_cache",
        "checkout_latency",
    ],
    "single": [
        "slow_response",
        "high_latency",
        "error_rate",
        "timeout",
    ],
    "service-tree": [
        "slow_db",
        "slow_cache",
        "auth_failures",
        "network_latency",
    ],
    "astroshop": [
        "slow_productcatalog",
        "cartservice_errors",
        "payment_timeout",
        "high_cpu_shipping",
        "memory_leak_recommendation",
        "network_latency",
    ],
}

SCENARIO_DESCRIPTIONS = {
    "ai-agent-application": [
        "Purpose: simulate a LangGraph and LangChain RAG agent running an autonomous shopfront.",
        "Topology: gateway, agent API, graph runtime, retrieval, tools, and commerce backends share one trace.",
        "Signal shape: spans include GenAI model, token, cache, tool, and guardrail observability fields.",
        "Failure modes: vector search slowness, LLM rate limits, tool failures, cache staleness, and checkout delays.",
        "Best for: validating AI agent observability, RAG flow analysis, and autonomous commerce operations.",
    ],
    "single": [
        "Purpose: emit a steady stream of spans from one synthetic service.",
        "Topology: a single process creates one primary span per simulated request.",
        "Signal shape: span attributes mark iteration count, randomness, and injected faults.",
        "Failure modes: slow responses, latency spikes, errors, and intermittent timeouts.",
        "Best for: validating OTLP ingest, dashboards, and baseline single-service alerting.",
    ],
    "service-tree": [
        "Purpose: model a compact multi-tier application with clear downstream dependencies.",
        "Topology: web calls api, which fans out to auth, cache, and database services.",
        "Signal shape: each logical service uses its own tracer resource within one trace.",
        "Failure modes: slow cache or database paths, auth failures, and network latency.",
        "Best for: testing service-flow analysis, dependency maps, and root-cause views.",
    ],
    "astroshop": [
        "Purpose: simulate the Astronomy Shop microservice estate without running the real stack.",
        "Topology: frontend coordinates cart, catalog, recommendation, checkout, payment, and more.",
        "Signal shape: traces include gRPC, Redis, and Kubernetes-style resource metadata.",
        "Failure modes: catalog slowdowns, cart errors, payment timeouts, leaks, and latency.",
        "Best for: exercising complex distributed-tracing workflows at realistic service scale.",
    ],
}


def get_control_file(scenario_name: str) -> Path:
    return BASE_DIR / f".scenario_control_{scenario_name}.json"


def get_pid_file(scenario_name: str) -> Path:
    return BASE_DIR / f".scenario_{scenario_name}.pid"


def get_log_file(scenario_name: str) -> Path:
    return BASE_DIR / f".scenario_{scenario_name}.log"


def discover_scenarios() -> dict:
    if not SCENARIO_DIR.exists():
        return {}

    scenarios = {}
    for scenario_file in sorted(SCENARIO_DIR.glob("*.py")):
        if scenario_file.name.startswith("_"):
            continue
        scenario_name = scenario_file.stem
        scenarios[scenario_name] = {
            "name": scenario_name,
            "path": str(scenario_file),
            "running": False,
            "pid": None,
        }
    return scenarios


def load_scenario_states() -> dict:
    if not SCENARIO_STATE_FILE.exists():
        return {}

    try:
        with open(SCENARIO_STATE_FILE, "r") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_scenario_states(states: dict) -> bool:
    try:
        with open(SCENARIO_STATE_FILE, "w") as file:
            json.dump(states, file)
        return True
    except Exception:
        return False


def set_scenario_enabled(scenario_name: str, enabled: bool) -> bool:
    states = load_scenario_states()
    states[scenario_name] = bool(enabled)
    return save_scenario_states(states)


def _read_pid(scenario_name: str):
    pid_file = get_pid_file(scenario_name)
    if not pid_file.exists():
        return None

    try:
        return int(pid_file.read_text().strip())
    except Exception:
        try:
            pid_file.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def _write_pid(scenario_name: str, pid: int) -> None:
    get_pid_file(scenario_name).write_text(str(pid))


def _remove_pid_file(scenario_name: str) -> None:
    try:
        get_pid_file(scenario_name).unlink(missing_ok=True)
    except Exception:
        pass


def is_pid_running(pid: int) -> bool:
    if not pid or pid <= 0:
        return False

    if os.name == "nt":
        try:
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == still_active
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def get_running_pid(scenario_name: str):
    pid = _read_pid(scenario_name)
    if not pid:
        return None
    if is_pid_running(pid):
        return pid
    _remove_pid_file(scenario_name)
    return None


def _read_log_excerpt(scenario_name: str, max_chars: int = 800) -> str:
    log_file = get_log_file(scenario_name)
    if not log_file.exists():
        return ""

    try:
        content = log_file.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""

    if len(content) <= max_chars:
        return content
    return content[-max_chars:]


def start_scenario(scenario_name: str, startup_wait_seconds: float = 1.0) -> dict:
    scenarios = discover_scenarios()
    if scenario_name not in scenarios:
        return {"error": f"Scenario '{scenario_name}' not found"}

    pid = get_running_pid(scenario_name)
    if pid:
        return {"error": f"Scenario '{scenario_name}' is already running", "pid": pid}

    scenario_path = scenarios[scenario_name]["path"]
    log_handle = None
    try:
        log_handle = open(get_log_file(scenario_name), "a", buffering=1, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "-u", scenario_path],
            cwd=str(BASE_DIR),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
            env=env,
        )

        deadline = time.monotonic() + max(0.0, startup_wait_seconds)
        while time.monotonic() < deadline:
            exit_code = proc.poll()
            if exit_code is not None:
                _remove_pid_file(scenario_name)
                set_scenario_enabled(scenario_name, False)
                log_handle.flush()
                log_excerpt = _read_log_excerpt(scenario_name)
                error_message = f"Scenario '{scenario_name}' exited during startup with code {exit_code}"
                if log_excerpt:
                    error_message += f". Log output:\n{log_excerpt}"
                return {
                    "error": error_message,
                    "scenario": scenario_name,
                    "exit_code": exit_code,
                    "log_file": str(get_log_file(scenario_name)),
                }
            time.sleep(0.1)

        _write_pid(scenario_name, proc.pid)
        set_scenario_enabled(scenario_name, True)
        return {
            "status": "started",
            "scenario": scenario_name,
            "pid": proc.pid,
            "log_file": str(get_log_file(scenario_name)),
        }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        if log_handle:
            log_handle.close()


def _signal_scenario_process(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except Exception:
        os.kill(pid, sig)


def stop_scenario(scenario_name: str, timeout_seconds: float = 5.0) -> dict:
    pid = get_running_pid(scenario_name)
    if not pid:
        set_scenario_enabled(scenario_name, False)
        return {"error": f"Scenario '{scenario_name}' is not running"}

    try:
        _signal_scenario_process(pid, signal.SIGTERM)
    except ProcessLookupError:
        _remove_pid_file(scenario_name)
        set_scenario_enabled(scenario_name, False)
        return {"status": "stopped", "scenario": scenario_name, "pid": pid}
    except Exception as exc:
        return {"error": str(exc), "pid": pid}

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not is_pid_running(pid):
            _remove_pid_file(scenario_name)
            set_scenario_enabled(scenario_name, False)
            return {"status": "stopped", "scenario": scenario_name, "pid": pid}
        time.sleep(0.1)

    try:
        _signal_scenario_process(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception as exc:
        return {"error": str(exc), "pid": pid}

    _remove_pid_file(scenario_name)
    set_scenario_enabled(scenario_name, False)
    return {"status": "killed", "scenario": scenario_name, "pid": pid}


def restore_enabled_scenarios() -> list[dict]:
    states = load_scenario_states()
    enabled_scenarios = sorted(name for name, enabled in states.items() if enabled)
    return [start_scenario(name) for name in enabled_scenarios]


def load_control_data(scenario_name: str) -> dict:
    control_file = get_control_file(scenario_name)
    if control_file.exists():
        try:
            with open(control_file, "r") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def save_control_data(scenario_name: str, control_data: dict) -> bool:
    try:
        with open(get_control_file(scenario_name), "w") as file:
            json.dump(control_data, file)
        return True
    except Exception:
        return False


def get_schedules(scenario_name: str) -> list[dict]:
    control_data = load_control_data(scenario_name)
    schedules = control_data.get("schedules", [])
    if not isinstance(schedules, list):
        return []

    normalized = []
    for entry in schedules:
        if not isinstance(entry, dict):
            continue
        pattern = entry.get("pattern")
        cron = entry.get("cron")
        duration_minutes = entry.get("duration_minutes")
        entry_id = entry.get("id")
        try:
            duration_minutes = int(duration_minutes)
        except (TypeError, ValueError):
            continue
        if not pattern or not cron or duration_minutes < 1:
            continue
        normalized.append(
            {
                "id": entry_id or uuid.uuid4().hex,
                "pattern": pattern,
                "cron": cron,
                "duration_minutes": duration_minutes,
            }
        )
    return normalized


def add_schedule(scenario_name: str, pattern_name: str, cron: str, duration_minutes) -> dict:
    available = PROBLEM_PATTERNS.get(scenario_name, [])
    if pattern_name not in available:
        return {"error": f"Pattern '{pattern_name}' is not available for scenario '{scenario_name}'"}

    cron = str(cron).strip()
    if len(cron.split()) != 5:
        return {"error": "Cron must have exactly 5 fields (minute hour day month weekday)"}
    if not croniter.is_valid(cron):
        return {"error": "Invalid cron expression"}

    try:
        duration_minutes = int(duration_minutes)
    except (TypeError, ValueError):
        return {"error": "Duration must be an integer number of minutes"}

    duration_minutes = max(1, min(duration_minutes, 7 * 24 * 60))

    control_data = load_control_data(scenario_name)
    schedules = get_schedules(scenario_name)
    new_entry = {
        "id": uuid.uuid4().hex,
        "pattern": pattern_name,
        "cron": cron,
        "duration_minutes": duration_minutes,
    }
    schedules.append(new_entry)
    control_data["schedules"] = schedules

    if save_control_data(scenario_name, control_data):
        return {"status": "ok", "schedule": new_entry}
    return {"error": "Failed to save schedule"}


def remove_schedule(scenario_name: str, schedule_id: str) -> dict:
    control_data = load_control_data(scenario_name)
    schedules = get_schedules(scenario_name)
    remaining = [entry for entry in schedules if entry["id"] != schedule_id]

    if len(remaining) == len(schedules):
        return {"error": f"Schedule '{schedule_id}' not found"}

    control_data["schedules"] = remaining
    if save_control_data(scenario_name, control_data):
        return {"status": "ok", "removed": schedule_id, "scenario": scenario_name}
    return {"error": "Failed to save schedule"}


def set_rpm(scenario_name: str, rpm) -> dict:
    try:
        rpm = int(rpm)
    except (TypeError, ValueError):
        return {"error": "RPM must be an integer"}

    rpm = max(1, min(rpm, 1000))
    control_data = load_control_data(scenario_name)
    control_data["rpm"] = rpm
    if save_control_data(scenario_name, control_data):
        return {"status": "ok", "rpm": rpm}
    return {"error": "Failed to save RPM"}


def get_rpm(scenario_name: str) -> int:
    control_data = load_control_data(scenario_name)
    try:
        return int(control_data.get("rpm", 10))
    except (TypeError, ValueError):
        return 10


def get_scenario_status() -> dict:
    scenarios = discover_scenarios()
    for name, data in scenarios.items():
        pid = get_running_pid(name)
        data["running"] = bool(pid)
        data["pid"] = pid
    return scenarios


def get_scenario_details() -> dict:
    status = get_scenario_status()
    for scenario_name in sorted(status):
        description_lines = SCENARIO_DESCRIPTIONS.get(scenario_name, [])
        status[scenario_name]["description_lines"] = description_lines
        status[scenario_name]["description"] = "\n".join(description_lines)
        if scenario_name in PROBLEM_PATTERNS:
            status[scenario_name]["available_patterns"] = PROBLEM_PATTERNS[scenario_name]
            status[scenario_name]["schedule_entries"] = get_schedules(scenario_name)
            status[scenario_name]["rpm"] = get_rpm(scenario_name)
    return status


def list_problem_patterns() -> dict:
    return {name: list(patterns) for name, patterns in sorted(PROBLEM_PATTERNS.items())}


def cleanup_running_scenarios() -> list[dict]:
    results = []
    for scenario_name, scenario_data in sorted(get_scenario_status().items()):
        if scenario_data.get("running"):
            results.append(stop_scenario(scenario_name))
    return results
