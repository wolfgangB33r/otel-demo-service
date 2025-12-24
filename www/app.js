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
        
        let patternsHtml = '';
        if (data.patterns && data.patterns.length > 0) {
            patternsHtml = `
                <div class="patterns-section">
                    <h4>Problem Patterns</h4>
                    <div class="pattern-grid">
                        ${data.patterns.map(pattern => `
                            <div class="pattern-toggle">
                                <label class="toggle-switch">
                                    <input type="checkbox" onchange="togglePattern('${name}', '${pattern}', this.checked)" ${data.pattern_states && data.pattern_states[pattern] ? 'checked' : ''}>
                                    <span class="toggle-slider"></span>
                                </label>
                                <span>${pattern}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        
        card.innerHTML = `
            <h3>${name}</h3>
            <div class="scenario-info">
                <div><strong>Path:</strong> scenarios/${name}.py</div>
                <div><strong>Status:</strong> <span class="status-badge ${statusClass}">${statusText}</span></div>
                ${data.pid ? `<div><strong>PID:</strong> ${data.pid}</div>` : ''}
            </div>
            ${patternsHtml}
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

async function togglePattern(scenarioName, patternName, enabled) {
    try {
        const response = await fetch(API_BASE + '/scenarios/' + scenarioName + '/pattern/' + patternName, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({enabled: enabled})
        });
        const result = await response.json();
        if (result.error) {
            showMessage('Error: ' + result.error, 'error');
        } else {
            showMessage('✅ Pattern "' + patternName + '" ' + (enabled ? 'enabled' : 'disabled'), 'success');
        }
    } catch (error) {
        showMessage('Failed to toggle pattern: ' + error, 'error');
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
