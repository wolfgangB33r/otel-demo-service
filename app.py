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
import uuid
from pathlib import Path
from functools import wraps
from dotenv import load_dotenv
from croniter import croniter

try:
    from flask import Flask, render_template_string, jsonify, request, send_from_directory, session, redirect, url_for
    from werkzeug.security import generate_password_hash, check_password_hash
except ImportError:
    print("ERROR: Flask or werkzeug not installed. Run: pip install flask werkzeug")
    sys.exit(1)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())

# Admin password from environment
ADMIN_PASSWORD = os.getenv("APP_ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    print("WARNING: APP_ADMIN_PASSWORD not set.")
    exit(1)

# Simple user authentication 
ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)

# Track running scenario processes
_running_scenarios = {}
_scenarios_lock = threading.Lock()
SCENARIO_STATE_FILE = Path(".scenario_states.json")

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


def load_scenario_states():
    """Load persisted scenario enabled states from disk."""
    if not SCENARIO_STATE_FILE.exists():
        return {}

    try:
        with open(SCENARIO_STATE_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_scenario_states(states):
    """Persist scenario enabled states to disk."""
    try:
        with open(SCENARIO_STATE_FILE, "w") as f:
            json.dump(states, f)
        return True
    except Exception:
        return False


def set_scenario_enabled(scenario_name, enabled):
    """Set and persist whether a scenario should be auto-started."""
    states = load_scenario_states()
    states[scenario_name] = bool(enabled)
    return save_scenario_states(states)


def restore_enabled_scenarios():
    """Start all scenarios that were previously marked as enabled."""
    states = load_scenario_states()
    enabled_scenarios = [name for name, enabled in states.items() if enabled]

    if not enabled_scenarios:
        print("\n🔁 No persisted enabled scenarios to restore.")
        return

    print("\n🔁 Restoring persisted enabled scenarios:")
    for scenario_name in enabled_scenarios:
        result = start_scenario(scenario_name)
        if result.get("error"):
            print(f"   - {scenario_name}: failed ({result['error']})")
        else:
            print(f"   - {scenario_name}: started (PID: {result['pid']})")


def is_authenticated():
    """Check if user is logged in."""
    return session.get("logged_in", False)


def require_auth(f):
    """Decorator to require authentication for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


def start_scenario(scenario_name):
    """Start a scenario as a subprocess."""
    scenarios = discover_scenarios()
    if scenario_name not in scenarios:
        return {"error": f"Scenario '{scenario_name}' not found"}
    
    with _scenarios_lock:
        if scenario_name in _running_scenarios:
            proc = _running_scenarios[scenario_name]["process"]
            if proc.poll() is None:
                return {"error": f"Scenario '{scenario_name}' is already running"}
        
        scenario_path = scenarios[scenario_name]["path"]
        try:
            # Open log file instead of piping to avoid blocking
            log_file = open(f".scenario_{scenario_name}.log", "w")
            proc = subprocess.Popen(
                [sys.executable, scenario_path],
                text=True,
            )
            _running_scenarios[scenario_name] = {
                "process": proc,
                "pid": proc.pid,
                "status": "running",
                "log_file": log_file,
            }
            set_scenario_enabled(scenario_name, True)
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
            set_scenario_enabled(scenario_name, False)
            return {"status": "stopped", "scenario": scenario_name}
        except subprocess.TimeoutExpired:
            proc.kill()
            del _running_scenarios[scenario_name]
            set_scenario_enabled(scenario_name, False)
            return {"status": "killed", "scenario": scenario_name}
        except Exception as e:
            return {"error": str(e)}


def get_control_file(scenario_name):
    """Get path to control file for a scenario."""
    return Path(f".scenario_control_{scenario_name}.json")


def load_control_data(scenario_name):
    """Load control data from control file."""
    control_file = get_control_file(scenario_name)
    if control_file.exists():
        try:
            with open(control_file, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            return {}
    return {}


def save_control_data(scenario_name, control_data):
    """Save control data to control file."""
    control_file = get_control_file(scenario_name)
    try:
        with open(control_file, "w") as f:
            json.dump(control_data, f)
        return True
    except Exception:
        return False


def get_schedules(scenario_name):
    """Get cron scheduled pattern entries for a scenario."""
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
        normalized.append({
            "id": entry_id or uuid.uuid4().hex,
            "pattern": pattern,
            "cron": cron,
            "duration_minutes": duration_minutes,
        })
    return normalized


def add_schedule(scenario_name, pattern_name, cron, duration_minutes):
    """Add a cron schedule entry for a scenario pattern."""
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


def remove_schedule(scenario_name, schedule_id):
    """Remove a cron schedule entry from a scenario."""
    control_data = load_control_data(scenario_name)
    schedules = get_schedules(scenario_name)
    remaining = [entry for entry in schedules if entry["id"] != schedule_id]

    if len(remaining) == len(schedules):
        return {"error": f"Schedule '{schedule_id}' not found"}

    control_data["schedules"] = remaining
    if save_control_data(scenario_name, control_data):
        return {"status": "ok", "removed": schedule_id}
    return {"error": "Failed to save schedule"}


def set_rpm(scenario_name, rpm):
    """Set requests per minute for a scenario."""
    rpm = max(1, min(int(rpm), 1000))  # Clamp between 1-1000
    control_data = load_control_data(scenario_name)
    control_data["rpm"] = rpm
    if save_control_data(scenario_name, control_data):
        return {"status": "ok", "rpm": rpm}
    return {"error": "Failed to save RPM"}


def get_rpm(scenario_name):
    """Get requests per minute setting for a scenario."""
    control_data = load_control_data(scenario_name)
    return control_data.get("rpm", 10)  # Default 10 req/min


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


# Login Page HTML
LOGIN_FORM = """
<!DOCTYPE html>
<html>
<head>
    <title>OTEL Demo Service - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            color: #e0e0e0;
        }
        .login-container {
            background: #2a2a2a;
            border: 1px solid #404040;
            border-radius: 8px;
            padding: 40px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
        }
        h1 {
            color: #4dabf7;
            margin-bottom: 30px;
            text-align: center;
            font-size: 28px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 500;
            color: #a0a0a0;
            font-size: 14px;
        }
        input[type="password"] {
            width: 100%;
            padding: 12px;
            border: 1px solid #404040;
            border-radius: 4px;
            background: #1a1a1a;
            color: #e0e0e0;
            font-size: 16px;
            transition: all 0.2s;
        }
        input[type="password"]:focus {
            outline: none;
            border-color: #4dabf7;
            box-shadow: 0 0 0 3px rgba(77, 171, 247, 0.1);
        }
        button {
            width: 100%;
            padding: 12px;
            background: #4dabf7;
            color: #1a1a1a;
            border: none;
            border-radius: 4px;
            font-weight: bold;
            font-size: 16px;
            cursor: pointer;
            transition: all 0.2s;
        }
        button:hover {
            background: #5bc0de;
        }
        button:active {
            transform: scale(0.98);
        }
        .error {
            background: #ff6b6b;
            color: #fff;
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .info {
            text-align: center;
            font-size: 12px;
            color: #808080;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h1>🌟 OTEL Demo Service</h1>
        {% if error %}
            <div class="error">{{ error }}</div>
        {% endif %}
        <form method="POST">
            <div class="form-group">
                <label for="password">Admin Password</label>
                <input type="password" id="password" name="password" required autofocus>
            </div>
            <button type="submit">Login</button>
        </form>
        <div class="info">
            <p>Secure login with encrypted password hashing</p>
        </div>
    </div>
</body>
</html>
"""


# Routes
@app.route("/login", methods=["GET", "POST"])
def login():
    """Login route."""
    if request.method == "POST":
        password = request.form.get("password", "")
        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["logged_in"] = True
            return redirect(url_for("index"))
        else:
            return render_template_string(LOGIN_FORM, error="Invalid password. Please try again.")
    return render_template_string(LOGIN_FORM)


@app.route("/logout")
def logout():
    """Logout route."""
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@require_auth
def index():
    """Serve the main dashboard."""
    return send_from_directory("www", "index.html")


@app.route("/www/<path:filename>")
@require_auth
def serve_static(filename):
    """Serve static files (CSS, JS)."""
    return send_from_directory("www", filename)


@app.route("/api/scenarios", methods=["GET"])
@require_auth
def list_scenarios():
    """API endpoint to list all scenarios and their status."""
    status = get_scenario_status()
    # Add available patterns, configured schedules, and RPM
    for scenario_name in status:
        if scenario_name in PROBLEM_PATTERNS:
            status[scenario_name]["available_patterns"] = PROBLEM_PATTERNS[scenario_name]
            status[scenario_name]["schedule_entries"] = get_schedules(scenario_name)
            status[scenario_name]["rpm"] = get_rpm(scenario_name)
    return jsonify(status)


@app.route("/api/scenarios/<scenario_name>/start", methods=["POST"])
@require_auth
def api_start(scenario_name):
    """API endpoint to start a scenario."""
    return jsonify(start_scenario(scenario_name))


@app.route("/api/scenarios/<scenario_name>/stop", methods=["POST"])
@require_auth
def api_stop(scenario_name):
    """API endpoint to stop a scenario."""
    return jsonify(stop_scenario(scenario_name))


@app.route("/api/scenarios/<scenario_name>/schedules", methods=["POST"])
@require_auth
def api_add_schedule(scenario_name):
    """API endpoint to add a cron schedule for a scenario pattern."""
    if scenario_name not in PROBLEM_PATTERNS:
        return jsonify({"error": f"Unknown scenario '{scenario_name}'"}), 404

    data = request.get_json() or {}
    pattern = data.get("pattern")
    cron = data.get("cron", "")
    duration_minutes = data.get("duration_minutes", 60)
    result = add_schedule(scenario_name, pattern, cron, duration_minutes)
    status_code = 400 if result.get("error") else 200
    return jsonify(result), status_code


@app.route("/api/scenarios/<scenario_name>/schedules/<schedule_id>", methods=["DELETE"])
@require_auth
def api_remove_schedule(scenario_name, schedule_id):
    """API endpoint to remove a cron schedule from a scenario."""
    if scenario_name not in PROBLEM_PATTERNS:
        return jsonify({"error": f"Unknown scenario '{scenario_name}'"}), 404

    result = remove_schedule(scenario_name, schedule_id)
    status_code = 404 if result.get("error") else 200
    return jsonify(result), status_code


@app.route("/api/scenarios/<scenario_name>/rpm", methods=["POST"])
@require_auth
def api_set_rpm(scenario_name):
    """API endpoint to set requests per minute for a scenario."""
    data = request.get_json() or {}
    rpm = data.get("rpm", 10)
    return jsonify(set_rpm(scenario_name, rpm))


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
    print("\n🔐 Login: http://localhost:8080/login")
    print("📊 Dashboard: http://localhost:8080")
    print("📋 Discovered scenarios:")
    
    scenarios = discover_scenarios()
    if scenarios:
        for name in scenarios:
            print(f"   - {name}")
    else:
        print("   (none found - create .py files in scenarios/ folder)")
    
    print("\n📝 Default credentials:")
    print("   Password: " + ("(from APP_ADMIN_PASSWORD env var)" if ADMIN_PASSWORD != "admin" else "admin"))
    print("\n" + "=" * 60)

    restore_enabled_scenarios()
    
    try:
        app.run(host="0.0.0.0", port=8080, debug=False)
    except KeyboardInterrupt:
        cleanup()
        sys.exit(0)
