"""
Main demo service application that offers a simple HTTP server on port 8080
to select and manage different demo scenarios.

Allows users to:
- Select between demo scenarios from the scenarios/ folder
- Start/stop scenarios as subprocesses
- Toggle problem patterns for each scenario
- Monitor running scenarios
"""

import os
import sys
import json
import subprocess
import threading
import glob
from pathlib import Path
from dotenv import load_dotenv

try:
    from flask import Flask, render_template_string, jsonify, request, send_from_directory
except ImportError:
    print("ERROR: Flask not installed. Run: pip install flask")
    sys.exit(1)

load_dotenv()

app = Flask(__name__)

# Track running scenario processes
_running_scenarios = {}
_scenarios_lock = threading.Lock()

# Problem patterns for each scenario
PROBLEM_PATTERNS = {
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


def discover_scenarios():
    """Discover all scenario .py files in scenarios/ folder."""
    scenario_dir = Path("scenarios")
    if not scenario_dir.exists():
        return {}
    
    scenarios = {}
    for scenario_file in scenario_dir.glob("*.py"):
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


def start_scenario(scenario_name):
    """Start a scenario as a subprocess."""
    scenarios = discover_scenarios()
    if scenario_name not in scenarios:
        return {"error": f"Scenario '{scenario_name}' not found"}
    
    with _scenarios_lock:
        if scenario_name in _running_scenarios:
            proc = _running_scenarios[scenario_name]["process"]
            if proc.poll() is None:  # Still running
                return {"error": f"Scenario '{scenario_name}' is already running"}
        
        scenario_path = scenarios[scenario_name]["path"]
        try:
            proc = subprocess.Popen(
                [sys.executable, scenario_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _running_scenarios[scenario_name] = {
                "process": proc,
                "pid": proc.pid,
                "status": "running",
            }
            return {"status": "started", "pid": proc.pid, "scenario": scenario_name}
        except Exception as e:
            return {"error": str(e)}


def stop_scenario(scenario_name):
    """Stop a running scenario."""
    with _scenarios_lock:
        if scenario_name not in _running_scenarios:
            return {"error": f"Scenario '{scenario_name}' is not running"}
        
        proc = _running_scenarios[scenario_name]["process"]
        try:
            proc.terminate()
            proc.wait(timeout=5)
            del _running_scenarios[scenario_name]
            return {"status": "stopped", "scenario": scenario_name}
        except subprocess.TimeoutExpired:
            proc.kill()
            del _running_scenarios[scenario_name]
            return {"status": "killed", "scenario": scenario_name}
        except Exception as e:
            return {"error": str(e)}


def get_control_file(scenario_name):
    """Get path to control file for a scenario."""
    return Path(f".scenario_control_{scenario_name}.json")


def load_patterns(scenario_name):
    """Load current patterns from control file."""
    control_file = get_control_file(scenario_name)
    if control_file.exists():
        try:
            with open(control_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_patterns(scenario_name, patterns):
    """Save patterns to control file."""
    control_file = get_control_file(scenario_name)
    try:
        with open(control_file, "w") as f:
            json.dump(patterns, f)
        return True
    except Exception:
        return False


def toggle_pattern(scenario_name, pattern_name, enabled):
    """Toggle a problem pattern for a scenario."""
    patterns = load_patterns(scenario_name)
    patterns[pattern_name] = enabled
    if save_patterns(scenario_name, patterns):
        return {"status": "ok", "pattern": pattern_name, "enabled": enabled}
    return {"error": "Failed to save pattern"}


def get_scenario_status():
    """Get status of all scenarios."""
    scenarios = discover_scenarios()
    
    with _scenarios_lock:
        for name, data in scenarios.items():
            if name in _running_scenarios:
                proc = _running_scenarios[name]["process"]
                if proc.poll() is None:
                    data["running"] = True
                    data["pid"] = proc.pid
                else:
                    data["running"] = False
                    data["pid"] = None
    
    return scenarios


@app.route("/")
def index():
    """Serve the main dashboard."""
    return send_from_directory("www", "index.html")


@app.route("/www/<path:filename>")
def serve_static(filename):
    """Serve static files (CSS, JS)."""
    return send_from_directory("www", filename)


@app.route("/api/scenarios", methods=["GET"])
def list_scenarios():
    """API endpoint to list all scenarios and their status."""
    status = get_scenario_status()
    # Add available patterns and current states
    for scenario_name in status:
        if scenario_name in PROBLEM_PATTERNS:
            status[scenario_name]["patterns"] = PROBLEM_PATTERNS[scenario_name]
            status[scenario_name]["pattern_states"] = load_patterns(scenario_name)
    return jsonify(status)


@app.route("/api/scenarios/<scenario_name>/start", methods=["POST"])
def api_start(scenario_name):
    """API endpoint to start a scenario."""
    return jsonify(start_scenario(scenario_name))


@app.route("/api/scenarios/<scenario_name>/stop", methods=["POST"])
def api_stop(scenario_name):
    """API endpoint to stop a scenario."""
    return jsonify(stop_scenario(scenario_name))


@app.route("/api/scenarios/<scenario_name>/pattern/<pattern_name>", methods=["POST"])
def api_toggle_pattern(scenario_name, pattern_name):
    """API endpoint to toggle a problem pattern."""
    data = request.get_json() or {}
    enabled = data.get("enabled", False)
    return jsonify(toggle_pattern(scenario_name, pattern_name, enabled))


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "scenarios_running": len(_running_scenarios)})


def cleanup():
    """Clean up running processes on shutdown."""
    print("\nShutting down...")
    with _scenarios_lock:
        for scenario_name, data in list(_running_scenarios.items()):
            try:
                data["process"].terminate()
                data["process"].wait(timeout=2)
            except Exception as e:
                try:
                    data["process"].kill()
                except Exception:
                    pass
    print("All scenarios stopped.")


if __name__ == "__main__":
    print("=" * 60)
    print("OTEL Demo Service Control Panel")
    print("=" * 60)
    print("\n📊 Dashboard: http://localhost:8080")
    print("📋 Discovered scenarios:")
    
    scenarios = discover_scenarios()
    if scenarios:
        for name in scenarios:
            print(f"   - {name}")
    else:
        print("   (none found - create .py files in scenarios/ folder)")
    
    print("\n" + "=" * 60)
    
    try:
        app.run(host="0.0.0.0", port=8080, debug=False)
    except KeyboardInterrupt:
        cleanup()
        sys.exit(0)
