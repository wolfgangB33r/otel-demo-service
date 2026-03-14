"""
Main demo service application that offers a simple HTTP server on port 8080
to select and manage different demo scenarios.

Allows users to:
- Select between demo scenarios from the scenarios/ folder
- Start/stop scenarios as subprocesses
- Schedule recurring problem scenarios with cron expressions
- Monitor running scenarios
"""

import os
import sys
from functools import wraps

from dotenv import load_dotenv

try:
    from flask import Flask, render_template_string, jsonify, request, send_from_directory, session, redirect, url_for
    from werkzeug.security import generate_password_hash, check_password_hash
except ImportError:
    print("ERROR: Flask or werkzeug not installed. Run: pip install flask werkzeug")
    sys.exit(1)

from utils.scenario_manager import (
    PROBLEM_PATTERNS,
    add_schedule,
    cleanup_running_scenarios,
    discover_scenarios,
    get_scenario_details,
    get_scenario_status,
    get_schedules,
    restore_enabled_scenarios,
    start_scenario,
    stop_scenario,
    set_rpm,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24).hex())

ADMIN_PASSWORD = os.getenv("APP_ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    print("WARNING: APP_ADMIN_PASSWORD not set.")
    sys.exit(1)

ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)


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


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login route."""
    if request.method == "POST":
        password = request.form.get("password", "")
        if check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["logged_in"] = True
            return redirect(url_for("index"))
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
    return jsonify(get_scenario_details())


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
    result = add_schedule(
        scenario_name,
        data.get("pattern"),
        data.get("cron", ""),
        data.get("duration_minutes", 60),
    )
    status_code = 400 if result.get("error") else 200
    return jsonify(result), status_code


@app.route("/api/scenarios/<scenario_name>/schedules/<schedule_id>", methods=["DELETE"])
@require_auth
def api_remove_schedule(scenario_name, schedule_id):
    """API endpoint to remove a cron schedule from a scenario."""
    if scenario_name not in PROBLEM_PATTERNS:
        return jsonify({"error": f"Unknown scenario '{scenario_name}'"}), 404

    from utils.scenario_manager import remove_schedule

    result = remove_schedule(scenario_name, schedule_id)
    status_code = 404 if result.get("error") else 200
    return jsonify(result), status_code


@app.route("/api/scenarios/<scenario_name>/rpm", methods=["POST"])
@require_auth
def api_set_rpm(scenario_name):
    """API endpoint to set requests per minute for a scenario."""
    data = request.get_json() or {}
    return jsonify(set_rpm(scenario_name, data.get("rpm", 10)))


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    running = [name for name, data in get_scenario_status().items() if data.get("running")]
    return jsonify({"status": "ok", "scenarios_running": len(running), "running_scenarios": running})


def cleanup():
    """Clean up running processes on shutdown."""
    print("\nShutting down...")
    cleanup_running_scenarios()
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

    restore_results = restore_enabled_scenarios()
    if restore_results:
        print("\n🔁 Restored enabled scenarios:")
        for result in restore_results:
            if result.get("error"):
                print(f"   - failed: {result['error']}")
            else:
                print(f"   - {result['scenario']}: started (PID: {result['pid']})")

    try:
        app.run(host="0.0.0.0", port=8080, debug=False)
    except KeyboardInterrupt:
        cleanup()
        sys.exit(0)
