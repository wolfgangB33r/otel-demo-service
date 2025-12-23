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
    from flask import Flask, render_template_string, jsonify, request
except ImportError:
    print("ERROR: Flask not installed. Run: pip install flask")
    sys.exit(1)

load_dotenv()

app = Flask(__name__)

# Track running scenario processes
_running_scenarios = {}
_scenarios_lock = threading.Lock()


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


# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>OTEL Demo Service Control</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #1a1a1a; color: #e0e0e0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #4dabf7; margin-bottom: 30px; }
        .scenarios-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .scenario-card {
            background: #2a2a2a;
            border: 1px solid #404040;
            border-radius: 8px;
            padding: 20px;
            transition: all 0.3s ease;
        }
        .scenario-card:hover { border-color: #4dabf7; background: #333; }
        .scenario-card h3 { color: #4dabf7; margin-bottom: 10px; }
        .scenario-info { font-size: 0.9em; color: #a0a0a0; margin-bottom: 15px; }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: bold;
            margin-right: 8px;
        }
        .status-running { background: #51cf66; color: #1a1a1a; }
        .status-stopped { background: #ff6b6b; color: #fff; }
        .buttons { display: flex; gap: 10px; margin-top: 15px; }
        button {
            flex: 1;
            padding: 10px;
            border: none;
            border-radius: 4px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-start {
            background: #51cf66;
            color: #1a1a1a;
        }
        .btn-start:hover { background: #40c057; }
        .btn-stop {
            background: #ff6b6b;
            color: #fff;
        }
        .btn-stop:hover { background: #fa5252; }
        .btn-stop:disabled { background: #666; cursor: not-allowed; }
        .status-message { margin-top: 20px; padding: 15px; border-radius: 4px; display: none; }
        .status-message.show { display: block; }
        .status-message.success { background: #4c6ef5; color: #fff; }
        .status-message.error { background: #ff6b6b; color: #fff; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🌟 OTEL Demo Service Control</h1>
        
        <div id="statusMessage" class="status-message"></div>
        
        <div class="scenarios-grid" id="scenariosContainer">
            <!-- Populated by JavaScript -->
        </div>
    </div>

    <script>
        const API_BASE = '/api';
        
        async function loadScenarios() {
            try {
                const response = await fetch(API_BASE + '/scenarios');
                const scenarios = await response.json();
                renderScenarios(scenarios);
            } catch (error) {
                showMessage('Failed to load scenarios: ' + error, 'error');
            }
        }
        
        function renderScenarios(scenarios) {
            const container = document.getElementById('scenariosContainer');
            container.innerHTML = '';
            
            for (const [name, data] of Object.entries(scenarios)) {
                const card = document.createElement('div');
                card.className = 'scenario-card';
                
                const status = data.running ? 'running' : 'stopped';
                const statusClass = data.running ? 'status-running' : 'status-stopped';
                const statusText = data.running ? '🟢 Running' : '🔴 Stopped';
                
                card.innerHTML = `
                    <h3>${name}</h3>
                    <div class="scenario-info">
                        <div><strong>Path:</strong> scenarios/${name}.py</div>
                        <div><strong>Status:</strong> <span class="status-badge ${statusClass}">${statusText}</span></div>
                        ${data.pid ? `<div><strong>PID:</strong> ${data.pid}</div>` : ''}
                    </div>
                    <div class="buttons">
                        <button class="btn-start" onclick="startScenario('${name}')" ${data.running ? 'disabled' : ''}>
                            Start
                        </button>
                        <button class="btn-stop" onclick="stopScenario('${name}')" ${!data.running ? 'disabled' : ''}>
                            Stop
                        </button>
                    </div>
                `;
                container.appendChild(card);
            }
        }
        
        async function startScenario(name) {
            try {
                const response = await fetch(API_BASE + '/scenarios/' + name + '/start', {
                    method: 'POST'
                });
                const result = await response.json();
                if (result.error) {
                    showMessage('Error: ' + result.error, 'error');
                } else {
                    showMessage('✅ Scenario "' + name + '" started (PID: ' + result.pid + ')', 'success');
                    setTimeout(loadScenarios, 500);
                }
            } catch (error) {
                showMessage('Failed to start scenario: ' + error, 'error');
            }
        }
        
        async function stopScenario(name) {
            try {
                const response = await fetch(API_BASE + '/scenarios/' + name + '/stop', {
                    method: 'POST'
                });
                const result = await response.json();
                if (result.error) {
                    showMessage('Error: ' + result.error, 'error');
                } else {
                    showMessage('✅ Scenario "' + name + '" stopped', 'success');
                    setTimeout(loadScenarios, 500);
                }
            } catch (error) {
                showMessage('Failed to stop scenario: ' + error, 'error');
            }
        }
        
        function showMessage(msg, type) {
            const elem = document.getElementById('statusMessage');
            elem.textContent = msg;
            elem.className = 'status-message show ' + type;
            setTimeout(() => elem.classList.remove('show'), 4000);
        }
        
        // Load scenarios on page load and refresh every 5 seconds
        loadScenarios();
        setInterval(loadScenarios, 5000);
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    """Serve the main dashboard."""
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/scenarios", methods=["GET"])
def list_scenarios():
    """API endpoint to list all scenarios and their status."""
    return jsonify(get_scenario_status())


@app.route("/api/scenarios/<scenario_name>/start", methods=["POST"])
def api_start(scenario_name):
    """API endpoint to start a scenario."""
    return jsonify(start_scenario(scenario_name))


@app.route("/api/scenarios/<scenario_name>/stop", methods=["POST"])
def api_stop(scenario_name):
    """API endpoint to stop a scenario."""
    return jsonify(stop_scenario(scenario_name))


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
