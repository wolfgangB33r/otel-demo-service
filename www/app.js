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
        
        const scenarioId = toSafeId(name);
        const scheduleEntries = data.schedule_entries || [];
        const descriptionLines = data.description_lines || [];
        const activePatterns = data.active_patterns || [];
        const patternOptions = (data.available_patterns || []).map(pattern =>
            `<option value="${escapeHtml(pattern)}">${escapeHtml(pattern)}</option>`
        ).join('');
        const descriptionHtml = descriptionLines.length
            ? `
                <div class="scenario-description">
                    ${descriptionLines.map(line => `<div class="scenario-description-line">${escapeHtml(line)}</div>`).join('')}
                </div>
            `
            : '';

        const patternRowsHtml = (data.available_patterns || []).map(p => {
            const isActive = activePatterns.includes(p);
            const badge = isActive ? '<span class="pattern-active-badge">Active</span>' : '';
            const btn = isActive
                ? `<button class="btn-stop-pattern" onclick="deactivatePattern('${name}', '${p}')">Stop</button>`
                : `<button class="btn-start-pattern" onclick="activatePattern('${name}', '${p}')">Start Now</button>`;
            return `<div class="pattern-row"><span class="pattern-name">${escapeHtml(p)}</span>${badge}${btn}</div>`;
        }).join('');
        const activePatternsHtml = (data.available_patterns || []).length ? `
            <div class="patterns-section">
                <h4>Problem Patterns</h4>
                <div class="pattern-list">${patternRowsHtml}</div>
            </div>
        ` : '';

        const schedulesHtml = `
            <div class="patterns-section">
                <h4>Scheduled Problems</h4>
                <div class="schedule-list">
                    ${scheduleEntries.length ? scheduleEntries.map(entry => `
                        <div class="schedule-item">
                            <span>${escapeHtml(entry.cron)} → ${escapeHtml(entry.pattern)} for ${entry.duration_minutes} min</span>
                            <button class="btn-remove" onclick="removeSchedule('${name}', '${entry.id}')">Remove</button>
                        </div>
                    `).join('') : '<div class="schedule-empty">No schedules configured.</div>'}
                </div>
                <div class="schedule-form">
                    <select id="pattern-${scenarioId}">
                        ${patternOptions}
                    </select>
                    <input id="cron-${scenarioId}" type="text" placeholder="Cron (e.g. 0 0 * * 1)">
                    <input id="duration-${scenarioId}" type="number" min="1" max="10080" value="60" placeholder="Minutes">
                    <button class="btn-add" onclick="addSchedule('${name}')">Add</button>
                </div>
                <div class="cron-help">Examples: Monday 00:00 = 0 0 * * 1, Tuesday 13:00 = 0 13 * * 2</div>
            </div>
        `;
        
        const currentRpm = data.rpm || 10;
        const rpmHtml = `
            <div class="rpm-section">
                <h4>Request Rate</h4>
                <div class="rpm-control">
                    <input type="range" class="rpm-slider" min="1" max="100" value="${currentRpm}" 
                           oninput="updateRpm('${name}', this.value)">
                    <span class="rpm-value" id="rpm-${name}">${currentRpm} req/min</span>
                </div>
            </div>
        `;
        
        card.innerHTML = `
            <h3>${name}</h3>
            ${descriptionHtml}
            <div class="scenario-info">
                <div><strong>Path:</strong> scenarios/${name}.py</div>
                <div><strong>Status:</strong> <span class="status-badge ${statusClass}">${statusText}</span></div>
                ${data.pid ? `<div><strong>PID:</strong> ${data.pid}</div>` : ''}
            </div>
            ${activePatternsHtml}
            ${schedulesHtml}
            ${rpmHtml}
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
        }
    } catch (error) {
        showMessage('Failed to start scenario: ' + error, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
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
        }
    } catch (error) {
        showMessage('Failed to stop scenario: ' + error, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

async function updateRpm(scenarioName, rpm) {
    rpm = parseInt(rpm);
    document.getElementById('rpm-' + scenarioName).textContent = rpm + ' req/min';
    try {
        const response = await fetch(API_BASE + '/scenarios/' + scenarioName + '/rpm', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({rpm: rpm})
        });
        const result = await response.json();
        if (result.error) {
            showMessage('Error: ' + result.error, 'error');
        }
    } catch (error) {
        showMessage('Failed to update RPM: ' + error, 'error');
    }
}

async function addSchedule(scenarioName) {
    const scenarioId = toSafeId(scenarioName);
    const patternElem = document.getElementById('pattern-' + scenarioId);
    const cronElem = document.getElementById('cron-' + scenarioId);
    const durationElem = document.getElementById('duration-' + scenarioId);

    const pattern = patternElem ? patternElem.value : '';
    const cron = cronElem ? cronElem.value.trim() : '';
    const durationMinutes = durationElem ? parseInt(durationElem.value, 10) : 60;

    if (!pattern || !cron || !durationMinutes || durationMinutes < 1) {
        showMessage('Please provide pattern, cron schedule and duration (minutes).', 'error');
        return;
    }

    try {
        const response = await fetch(API_BASE + '/scenarios/' + scenarioName + '/schedules', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                pattern: pattern,
                cron: cron,
                duration_minutes: durationMinutes
            })
        });
        const result = await response.json();
        if (result.error) {
            showMessage('Error: ' + result.error, 'error');
        } else {
            showMessage('✅ Schedule added for "' + pattern + '"', 'success');
            if (cronElem) {
                cronElem.value = '';
            }
        }
    } catch (error) {
        showMessage('Failed to add schedule: ' + error, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

async function activatePattern(scenarioName, pattern) {
    try {
        const response = await fetch(API_BASE + '/scenarios/' + scenarioName + '/patterns/' + encodeURIComponent(pattern) + '/activate', {
            method: 'POST'
        });
        const result = await response.json();
        if (result.error) {
            showMessage('Error: ' + result.error, 'error');
        } else {
            showMessage('✅ Pattern "' + pattern + '" activated', 'success');
        }
    } catch (error) {
        showMessage('Failed to activate pattern: ' + error, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

async function deactivatePattern(scenarioName, pattern) {
    try {
        const response = await fetch(API_BASE + '/scenarios/' + scenarioName + '/patterns/' + encodeURIComponent(pattern) + '/deactivate', {
            method: 'POST'
        });
        const result = await response.json();
        if (result.error) {
            showMessage('Error: ' + result.error, 'error');
        } else {
            showMessage('✅ Pattern "' + pattern + '" deactivated', 'success');
        }
    } catch (error) {
        showMessage('Failed to deactivate pattern: ' + error, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

async function removeSchedule(scenarioName, scheduleId) {
    try {
        const response = await fetch(API_BASE + '/scenarios/' + scenarioName + '/schedules/' + scheduleId, {
            method: 'DELETE'
        });
        const result = await response.json();
        if (result.error) {
            showMessage('Error: ' + result.error, 'error');
        } else {
            showMessage('✅ Schedule removed', 'success');
        }
    } catch (error) {
        showMessage('Failed to remove schedule: ' + error, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

function toSafeId(value) {
    return value.replace(/[^a-zA-Z0-9_-]/g, '_');
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function showMessage(msg, type) {
    const elem = document.getElementById('statusMessage');
    elem.textContent = msg;
    elem.className = 'status-message show ' + type;
    setTimeout(() => elem.classList.remove('show'), 4000);
}

// Load scenarios on page load
loadScenarios();
