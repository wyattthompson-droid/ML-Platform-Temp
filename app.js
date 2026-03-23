// ML Platform Command Center — Dashboard Logic

let kpiData = null;

// Navigation
document.querySelectorAll('nav a').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        const target = link.getAttribute('href').replace('#', '');
        document.querySelectorAll('nav a').forEach(l => l.classList.remove('active'));
        link.classList.add('active');
        document.querySelectorAll('main > section').forEach(s => s.style.display = 'none');
        document.getElementById(target).style.display = 'block';
    });
});

// Load KPI data and render
async function init() {
    try {
        const response = await fetch('kpi-data.json');
        kpiData = await response.json();
        renderAllKPIs();
    } catch (err) {
        console.error('Failed to load KPI data:', err);
    }
}

function renderAllKPIs() {
    renderKPISection('northstar-kpis', kpiData.northstar);
    renderKPISection('lagging-kpis', kpiData.lagging);
    renderKPISection('leading-kpis', kpiData.leading);
}

function renderKPISection(containerId, kpis) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    kpis.forEach(kpi => {
        container.appendChild(createKPICard(kpi));
    });
}

function createKPICard(kpi) {
    const card = document.createElement('div');
    card.className = 'kpi-card';
    card.id = `kpi-${kpi.id}`;

    const displayValue = kpi.value !== null ? formatValue(kpi.value, kpi.unit) : '\u2014';
    const change = calculateChange(kpi.value, kpi.previousValue);
    const changeClass = change.direction;
    const sourceClass = kpi.source;
    const sourceLabel = kpi.source === 'github' ? 'GitHub' : 'Manual';
    const lastUpdated = kpi.lastUpdated || 'Awaiting data';

    card.innerHTML = `
        <div class="label">${kpi.label}</div>
        <div class="value">${displayValue}</div>
        <div class="change ${changeClass}">
            ${change.icon} ${change.text}
        </div>
        <div class="meta">
            <span class="source-badge ${sourceClass}">${sourceLabel}</span>
            <span>${lastUpdated}</span>
        </div>
    `;

    card.title = kpi.description;
    return card;
}

function formatValue(value, unit) {
    if (value === '\u2014' || value === null) return '\u2014';
    if (unit === '%') return `${value}%`;
    if (unit === '$') return `$${Number(value).toLocaleString()}`;
    if (unit === 'ms') return `${value}ms`;
    if (unit === 'hrs') return `${value}h`;
    if (unit === 'docs/hr') return `${Number(value).toLocaleString()}/hr`;
    if (unit === '$/doc') return `$${value}`;
    return Number(value).toLocaleString();
}

function calculateChange(current, previous) {
    if (current === null || current === '\u2014' || previous === null || previous === undefined) {
        return { direction: 'neutral', icon: '', text: 'No prior data' };
    }
    const diff = ((current - previous) / previous) * 100;
    if (diff > 0) {
        return { direction: 'positive', icon: '\u25B2', text: `+${diff.toFixed(1)}% vs prior 30d` };
    } else if (diff < 0) {
        return { direction: 'negative', icon: '\u25BC', text: `${diff.toFixed(1)}% vs prior 30d` };
    }
    return { direction: 'neutral', icon: '\u25CF', text: 'No change' };
}

// Initialize
init();
