const API_BASE = '/api';
const REFRESH_INTERVAL = 15000;
const expandedCards = new Set();
let previouslyRunning = new Set();
let lastUpdated = null;

// --- Formatters ---

function formatPatternName(name) {
    return name.replaceAll('_', ' ').replace(/^\w/, c => c.toUpperCase());
}

function formatCron(expr) {
    const parts = expr.trim().split(/\s+/);
    if (parts.length !== 5) return expr;
    const [min, hour, dom, month, dow] = parts;
    const days = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
    if (min.startsWith('*/') && hour==='*' && dom==='*' && month==='*' && dow==='*')
        return `Every ${min.slice(2)} minutes`;
    if (/^\d+$/.test(min) && /^\d+$/.test(hour) && dom==='*' && month==='*' && /^\d+$/.test(dow))
        return `Every ${days[+dow] || 'day '+dow} at ${hour.padStart(2,'0')}:${min.padStart(2,'0')}`;
    if (/^\d+$/.test(min) && /^\d+$/.test(hour) && dom==='*' && month==='*' && dow==='*')
        return `Every day at ${hour.padStart(2,'0')}:${min.padStart(2,'0')}`;
    if (/^\d+$/.test(min) && hour==='*' && dom==='*' && month==='*' && dow==='*')
        return `Every hour at :${min.padStart(2,'0')}`;
    return expr;
}

function formatDescription(lines) {
    if (!lines || !lines.length) return '';
    const rows = lines.map(line => {
        const i = line.indexOf(':');
        if (i === -1) return `<div class="desc-row"><span class="desc-val">${escapeHtml(line)}</span></div>`;
        const key = line.slice(0, i).trim();
        const val = line.slice(i + 1).trim();
        return `<div class="desc-row${key === 'Best for' ? ' desc-highlight' : ''}">
            <span class="desc-key">${escapeHtml(key)}</span>
            <span class="desc-val">${escapeHtml(val)}</span>
        </div>`;
    }).join('');
    return `<div class="scenario-description">${rows}</div>`;
}

// --- Load & render ---

async function loadScenarios() {
    try {
        const response = await fetch(API_BASE + '/scenarios');
        const scenarios = await response.json();
        lastUpdated = Date.now();
        renderScenarios(scenarios);
        updateStatusBar(scenarios);
    } catch (error) {
        showMessage('Failed to load scenarios: ' + error, 'error');
    }
}

function renderScenarios(scenarios) {
    const running = [], available = [];
    for (const [name, data] of Object.entries(scenarios)) {
        (data.running ? running : available).push([name, data]);
    }

    document.getElementById('runningSectionHeader').textContent = `Running (${running.length})`;
    document.getElementById('availableSectionHeader').textContent = `Available (${available.length})`;
    document.getElementById('runningEmpty').style.display = running.length ? 'none' : 'block';

    // Auto-expand only cards that just started running
    running.forEach(([name]) => { if (!previouslyRunning.has(name)) expandedCards.add(name); });
    previouslyRunning = new Set(running.map(([name]) => name));

    document.getElementById('runningContainer').innerHTML =
        running.map(([name, data]) => buildCardHtml(name, data)).join('');
    document.getElementById('availableContainer').innerHTML =
        available.map(([name, data]) => buildCardHtml(name, data)).join('');
}

function buildCardHtml(name, data) {
    const sid = toSafeId(name);
    const isRunning = data.running;
    const activePatterns = data.active_patterns || [];
    const scheduleEntries = data.schedule_entries || [];
    const expanded = expandedCards.has(name);
    const activePatternsCount = activePatterns.length;

    const patternOptions = (data.available_patterns || []).map(p =>
        `<option value="${escapeHtml(p)}">${escapeHtml(formatPatternName(p))}</option>`
    ).join('');

    const patternRowsHtml = (data.available_patterns || []).map(p => {
        const isActive = activePatterns.includes(p);
        return `<div class="pattern-row" data-pattern="${escapeHtml(p)}">
            <span class="pattern-name">${escapeHtml(formatPatternName(p))}</span>
            <span class="pattern-active-badge"${isActive ? '' : ' style="display:none"'}>Active</span>
            <button class="btn-start-pattern"${isActive ? ' style="display:none"' : ''}${!isRunning ? ' disabled title="Start scenario first"' : ''} onclick="activatePattern('${name}','${p}')">Start</button>
            <button class="btn-stop-pattern"${isActive ? '' : ' style="display:none"'} onclick="deactivatePattern('${name}','${p}')">Stop</button>
        </div>`;
    }).join('');

    const scheduleListHtml = scheduleEntries.length
        ? scheduleEntries.map(entry => `
            <div class="schedule-item">
                <div class="schedule-item-text">
                    <span class="schedule-cron" title="${escapeHtml(entry.cron)}">${escapeHtml(formatCron(entry.cron))}</span>
                    <span class="schedule-sep">→</span>
                    <span class="schedule-pattern">${escapeHtml(formatPatternName(entry.pattern))}</span>
                    <span class="schedule-duration">for ${entry.duration_minutes} min</span>
                </div>
                <button class="btn-remove" onclick="removeSchedule('${name}','${entry.id}')">Remove</button>
            </div>`).join('')
        : '<div class="schedule-empty">No schedules configured.</div>';

    const rpm = data.rpm || 10;
    const patternSummary = activePatternsCount > 0
        ? `<span class="header-active-patterns">${activePatternsCount} active</span>`
        : '';

    return `
<div class="scenario-card${isRunning ? ' is-running' : ''}" data-name="${escapeHtml(name)}">
  <div class="card-header" onclick="toggleCard('${name}')">
    <div class="card-header-left">
      <span class="status-dot ${isRunning ? 'running' : 'stopped'}"></span>
      <h3>${escapeHtml(name)}</h3>
      ${data.pid ? `<span class="pid-badge">PID&nbsp;${data.pid}</span>` : ''}
      ${patternSummary}
    </div>
    <div class="card-header-right">
      <button class="btn-start" onclick="event.stopPropagation();startScenario('${name}')"${isRunning ? ' disabled' : ''}>Start</button>
      <button class="btn-stop" onclick="event.stopPropagation();stopScenario('${name}')"${!isRunning ? ' disabled' : ''}>Stop</button>
      <span class="card-toggle">${expanded ? '▾' : '▸'}</span>
    </div>
  </div>
  <div class="card-body${expanded ? '' : ' collapsed'}">
    ${formatDescription(data.description_lines)}
    ${(data.available_patterns || []).length ? `
    <div class="patterns-section">
      <h4>Problem Patterns</h4>
      <div class="pattern-list">${patternRowsHtml}</div>
    </div>` : ''}
    <div class="patterns-section">
      <h4>Scheduled Problems</h4>
      <div class="schedule-list">${scheduleListHtml}</div>
      <div class="schedule-form">
        <select id="pattern-${sid}">${patternOptions}</select>
        <input id="cron-${sid}" type="text" placeholder="e.g. 0 0 * * 1">
        <input id="duration-${sid}" type="number" min="1" max="10080" value="60" placeholder="Min">
        <button class="btn-add" onclick="addSchedule('${name}')">Add</button>
      </div>
      <div class="cron-help">Every Monday 00:00 = 0 0 * * 1 &nbsp;·&nbsp; Every 30 min = */30 * * * *</div>
    </div>
    <div class="rpm-section">
      <h4>Request Rate</h4>
      <div class="rpm-control">
        <input type="range" class="rpm-slider" min="1" max="100" value="${rpm}" oninput="updateRpm('${name}',this.value)">
        <span class="rpm-value" id="rpm-${name}">${rpm} req/min</span>
      </div>
    </div>
  </div>
</div>`;
}

function toggleCard(name) {
    const card = document.querySelector(`.scenario-card[data-name="${CSS.escape(name)}"]`);
    if (!card) return;
    const body = card.querySelector('.card-body');
    const toggle = card.querySelector('.card-toggle');
    const isCollapsed = body.classList.contains('collapsed');

    const availableContainer = document.getElementById('availableContainer');
    if (availableContainer && availableContainer.contains(card) && isCollapsed) {
        availableContainer.querySelectorAll('.scenario-card').forEach(other => {
            if (other === card) return;
            const otherBody = other.querySelector('.card-body');
            const otherToggle = other.querySelector('.card-toggle');
            if (otherBody && !otherBody.classList.contains('collapsed')) {
                otherBody.classList.add('collapsed');
                if (otherToggle) otherToggle.textContent = '▸';
                expandedCards.delete(other.dataset.name);
            }
        });
    }

    body.classList.toggle('collapsed', !isCollapsed);
    if (toggle) toggle.textContent = isCollapsed ? '▾' : '▸';
    if (isCollapsed) expandedCards.add(name); else expandedCards.delete(name);
}

// --- Status bar ---

function updateStatusBar(scenarios) {
    const total = Object.keys(scenarios).length;
    const runningCount = Object.values(scenarios).filter(s => s.running).length;
    const activePatternCount = Object.values(scenarios).reduce((n, s) => n + (s.active_patterns || []).length, 0);
    const scheduledCount = Object.values(scenarios).reduce((n, s) => n + (s.schedule_entries || []).length, 0);

    const parts = [
        `<span class="${runningCount > 0 ? 'stat-running' : 'stat-idle'}">${runningCount} / ${total} running</span>`
    ];
    if (activePatternCount > 0)
        parts.push(`<span>${activePatternCount} active pattern${activePatternCount !== 1 ? 's' : ''}</span>`);
    if (scheduledCount > 0)
        parts.push(`<span>${scheduledCount} schedule${scheduledCount !== 1 ? 's' : ''}</span>`);
    parts.push(`<span class="stat-refresh" id="refreshTimer">Updated just now</span>`);
    document.getElementById('statusBar').innerHTML = parts.join('<span class="stat-sep"> · </span>');
}

function tickRefreshTimer() {
    const el = document.getElementById('refreshTimer');
    if (!el || !lastUpdated) return;
    const secs = Math.round((Date.now() - lastUpdated) / 1000);
    el.textContent = secs < 5 ? 'Updated just now' : `Updated ${secs}s ago`;
}

// --- API actions ---

async function startScenario(name) {
    try {
        const res = await fetch(`${API_BASE}/scenarios/${name}/start`, {method: 'POST'});
        const result = await res.json();
        if (result.error) showMessage('Error: ' + result.error, 'error');
        else showMessage(`Scenario "${name}" started (PID: ${result.pid})`, 'success');
    } catch (e) {
        showMessage('Failed to start scenario: ' + e, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

async function stopScenario(name) {
    try {
        const res = await fetch(`${API_BASE}/scenarios/${name}/stop`, {method: 'POST'});
        const result = await res.json();
        if (result.error) showMessage('Error: ' + result.error, 'error');
        else showMessage(`Scenario "${name}" stopped`, 'success');
    } catch (e) {
        showMessage('Failed to stop scenario: ' + e, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

async function updateRpm(scenarioName, rpm) {
    rpm = parseInt(rpm);
    const el = document.getElementById('rpm-' + scenarioName);
    if (el) el.textContent = rpm + ' req/min';
    try {
        const res = await fetch(`${API_BASE}/scenarios/${scenarioName}/rpm`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({rpm})
        });
        const result = await res.json();
        if (result.error) showMessage('Error: ' + result.error, 'error');
    } catch (e) {
        showMessage('Failed to update RPM: ' + e, 'error');
    }
}

async function addSchedule(scenarioName) {
    const sid = toSafeId(scenarioName);
    const pattern = document.getElementById('pattern-' + sid)?.value;
    const cron = document.getElementById('cron-' + sid)?.value.trim();
    const duration = parseInt(document.getElementById('duration-' + sid)?.value, 10);
    if (!pattern || !cron || !duration || duration < 1) {
        showMessage('Please provide pattern, cron schedule, and duration.', 'error');
        return;
    }
    try {
        const res = await fetch(`${API_BASE}/scenarios/${scenarioName}/schedules`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({pattern, cron, duration_minutes: duration})
        });
        const result = await res.json();
        if (result.error) showMessage('Error: ' + result.error, 'error');
        else showMessage(`Schedule added for "${formatPatternName(pattern)}"`, 'success');
    } catch (e) {
        showMessage('Failed to add schedule: ' + e, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

async function activatePattern(scenarioName, pattern) {
    try {
        const res = await fetch(`${API_BASE}/scenarios/${scenarioName}/patterns/${encodeURIComponent(pattern)}/activate`, {method: 'POST'});
        const result = await res.json();
        if (result.error) showMessage('Error: ' + result.error, 'error');
        else showMessage(`Pattern "${formatPatternName(pattern)}" activated`, 'success');
    } catch (e) {
        showMessage('Failed to activate pattern: ' + e, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

async function deactivatePattern(scenarioName, pattern) {
    try {
        const res = await fetch(`${API_BASE}/scenarios/${scenarioName}/patterns/${encodeURIComponent(pattern)}/deactivate`, {method: 'POST'});
        const result = await res.json();
        if (result.error) showMessage('Error: ' + result.error, 'error');
        else showMessage(`Pattern "${formatPatternName(pattern)}" deactivated`, 'success');
    } catch (e) {
        showMessage('Failed to deactivate pattern: ' + e, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

async function removeSchedule(scenarioName, scheduleId) {
    try {
        const res = await fetch(`${API_BASE}/scenarios/${scenarioName}/schedules/${scheduleId}`, {method: 'DELETE'});
        const result = await res.json();
        if (result.error) showMessage('Error: ' + result.error, 'error');
        else showMessage('Schedule removed', 'success');
    } catch (e) {
        showMessage('Failed to remove schedule: ' + e, 'error');
    } finally {
        setTimeout(loadScenarios, 300);
    }
}

// --- Utilities ---

function toSafeId(value) {
    return value.replace(/[^a-zA-Z0-9_-]/g, '_');
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function showMessage(msg, type) {
    const el = document.getElementById('statusMessage');
    el.textContent = msg;
    el.className = 'status-message show ' + type;
    setTimeout(() => el.classList.remove('show'), 4000);
}

// --- Boot ---
loadScenarios();
setInterval(loadScenarios, REFRESH_INTERVAL);
setInterval(tickRefreshTimer, 5000);
