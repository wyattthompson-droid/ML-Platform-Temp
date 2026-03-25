// ML Platform Command Center — Dashboard Logic

let kpiData = null;

// Navigation — only handle hash links, let real page links navigate normally
document.querySelectorAll('nav a').forEach(link => {
    const href = link.getAttribute('href');
    if (!href.startsWith('#')) return; // Let real links (daily-burn.html) navigate normally

    link.addEventListener('click', (e) => {
        e.preventDefault();
        const target = href.replace('#', '');
        document.querySelectorAll('nav a').forEach(l => l.classList.remove('active'));
        link.classList.add('active');
        document.querySelectorAll('main > section').forEach(s => s.style.display = 'none');
        document.getElementById(target).style.display = 'block';
        window.location.hash = target;
    });
});

// Handle hash on page load (e.g., coming from daily-burn.html with index.html#docs)
function handleHash() {
    const hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById(hash)) {
        document.querySelectorAll('nav a').forEach(l => l.classList.remove('active'));
        const matchingLink = document.querySelector(`nav a[href="#${hash}"]`);
        if (matchingLink) matchingLink.classList.add('active');
        document.querySelectorAll('main > section').forEach(s => s.style.display = 'none');
        document.getElementById(hash).style.display = 'block';
    }
}
handleHash();
window.addEventListener('hashchange', handleHash);

// PR detail data for tooltips
let modelPRs = [];
let allPRs = [];

// Load KPI data and render
async function init() {
    try {
        const [kpiRes, modelRes, allRes] = await Promise.all([
            fetch('kpi-data.json'),
            fetch('model-prs.json').catch(() => ({ json: () => [] })),
            fetch('all-prs.json').catch(() => ({ json: () => [] }))
        ]);
        kpiData = await kpiRes.json();
        modelPRs = await modelRes.json();
        allPRs = await allRes.json();
        renderAllKPIs();
    } catch (err) {
        console.error('Failed to load KPI data:', err);
    }
}

function buildTooltipSummary(kpiId) {
    let prs = [];
    if (kpiId === 'model-updates-prod') prs = modelPRs;
    else if (kpiId === 'num-prs' || kpiId === 'deployment-time') prs = allPRs;
    else return null;

    if (prs.length === 0) return null;

    const repos = [...new Set(prs.map(p => p.repo))];
    const latest = prs[0];
    const latestDate = new Date(latest.merged_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

    if (kpiId === 'model-updates-prod') {
        return `${prs.length} model PRs across ${repos.length} repos. Latest: "${latest.title}" (${latest.repo}, ${latestDate})`;
    } else if (kpiId === 'num-prs') {
        return `${prs.length} PRs merged across ${repos.length} repos. Latest: "${latest.title}" (${latest.repo}, ${latestDate})`;
    } else if (kpiId === 'deployment-time') {
        return `Based on ${prs.length} merged PRs across ${repos.length} repos. Click for full list.`;
    }
    return null;
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

// Map KPI IDs to detail page views
const kpiDetailLinks = {
    'model-updates-prod': 'details.html#model',
    'num-prs': 'details.html#all',
    'deployment-time': 'details.html#all',
};

function createKPICard(kpi) {
    const card = document.createElement('div');
    card.className = 'kpi-card';
    card.id = `kpi-${kpi.id}`;

    const detailLink = kpiDetailLinks[kpi.id];
    if (detailLink) {
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => window.location.href = detailLink);
    }

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

    // Add hover tooltip
    const tooltip = buildTooltipSummary(kpi.id);
    if (tooltip) {
        const tipEl = document.createElement('div');
        tipEl.className = 'kpi-tooltip';
        tipEl.textContent = tooltip;
        card.appendChild(tipEl);
        card.classList.add('has-tooltip');
    } else {
        card.title = kpi.description;
    }

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
