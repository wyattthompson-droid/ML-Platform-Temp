// ML Platform Command Center — Dashboard Logic

let kpiData = null;
let githubToken = null;

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

    const displayValue = kpi.value !== null ? formatValue(kpi.value, kpi.unit) : '—';
    const change = calculateChange(kpi.value, kpi.previousValue);
    const changeClass = change.direction;
    const sourceClass = kpi.source;
    const sourceLabel = kpi.source === 'github' ? 'GitHub' : 'Manual';
    const lastUpdated = kpi.lastUpdated || 'Not connected';

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
    if (value === '—' || value === null) return '—';
    if (unit === '%') return `${value}%`;
    if (unit === '$') return `$${Number(value).toLocaleString()}`;
    if (unit === 'ms') return `${value}ms`;
    if (unit === 'hrs') return `${value}h`;
    if (unit === 'docs/hr') return `${Number(value).toLocaleString()}/hr`;
    if (unit === '$/doc') return `$${value}`;
    return Number(value).toLocaleString();
}

function calculateChange(current, previous) {
    if (current === null || current === '—' || previous === null || previous === undefined) {
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

// GitHub API Integration
async function loadGitHubKPIs() {
    const tokenInput = document.getElementById('github-token');
    githubToken = tokenInput.value.trim();

    if (!githubToken) {
        alert('Please enter a GitHub personal access token to load live KPIs.');
        return;
    }

    const org = kpiData.github_config.org;
    const repos = kpiData.github_config.repos;

    try {
        document.getElementById('last-refresh').textContent = 'Loading...';

        // If no specific repos configured, fetch all repos in the org
        let repoList = repos;
        if (repoList.length === 0) {
            repoList = await fetchOrgRepos(org);
        }

        const now = new Date();
        const thirtyDaysAgo = new Date(now - 30 * 24 * 60 * 60 * 1000);
        const sixtyDaysAgo = new Date(now - 60 * 24 * 60 * 60 * 1000);

        // Fetch PRs for current and prior period
        const currentPRs = await fetchPRsForPeriod(org, repoList, thirtyDaysAgo, now);
        const priorPRs = await fetchPRsForPeriod(org, repoList, sixtyDaysAgo, thirtyDaysAgo);

        // Update PR count
        updateKPI('leading', 'num-prs', currentPRs.length, priorPRs.length);

        // Estimate model updates (PRs with keywords in title/body)
        const modelKeywords = /model|checkpoint|artifact|weight|training|fine.?tun/i;
        const currentModelPRs = currentPRs.filter(pr => modelKeywords.test(pr.title) || modelKeywords.test(pr.body || ''));
        const priorModelPRs = priorPRs.filter(pr => modelKeywords.test(pr.title) || modelKeywords.test(pr.body || ''));
        updateKPI('northstar', 'model-updates-prod', currentModelPRs.length, priorModelPRs.length);

        // Deployment time (average PR open to merge, in hours)
        const mergedCurrent = currentPRs.filter(pr => pr.merged_at);
        if (mergedCurrent.length > 0) {
            const avgHours = mergedCurrent.reduce((sum, pr) => {
                const opened = new Date(pr.created_at);
                const merged = new Date(pr.merged_at);
                return sum + (merged - opened) / (1000 * 60 * 60);
            }, 0) / mergedCurrent.length;

            const mergedPrior = priorPRs.filter(pr => pr.merged_at);
            let priorAvgHours = null;
            if (mergedPrior.length > 0) {
                priorAvgHours = mergedPrior.reduce((sum, pr) => {
                    const opened = new Date(pr.created_at);
                    const merged = new Date(pr.merged_at);
                    return sum + (merged - opened) / (1000 * 60 * 60);
                }, 0) / mergedPrior.length;
            }
            updateKPI('leading', 'deployment-time', Math.round(avgHours), priorAvgHours ? Math.round(priorAvgHours) : null);
        }

        const timestamp = now.toLocaleString();
        document.getElementById('last-refresh').textContent = `Last refreshed: ${timestamp}`;

    } catch (err) {
        console.error('GitHub API error:', err);
        document.getElementById('last-refresh').textContent = 'Error loading data — check token permissions';
    }
}

async function fetchOrgRepos(org) {
    const repos = [];
    let page = 1;
    const perPage = 100;

    // Fetch up to 3 pages (300 repos) to stay within rate limits
    while (page <= 3) {
        const response = await fetch(
            `https://api.github.com/orgs/${org}/repos?per_page=${perPage}&page=${page}&sort=pushed`,
            { headers: { 'Authorization': `token ${githubToken}` } }
        );
        if (!response.ok) throw new Error(`GitHub API ${response.status}: ${response.statusText}`);
        const data = await response.json();
        if (data.length === 0) break;
        repos.push(...data.map(r => r.name));
        if (data.length < perPage) break;
        page++;
    }
    return repos;
}

async function fetchPRsForPeriod(org, repos, since, until) {
    const allPRs = [];
    const sinceISO = since.toISOString();

    // Sample up to 20 most recently pushed repos to stay within rate limits
    const reposToCheck = repos.slice(0, 20);

    for (const repo of reposToCheck) {
        try {
            const response = await fetch(
                `https://api.github.com/repos/${org}/${repo}/pulls?state=closed&sort=updated&direction=desc&per_page=50`,
                { headers: { 'Authorization': `token ${githubToken}` } }
            );
            if (!response.ok) continue;
            const prs = await response.json();
            const filtered = prs.filter(pr => {
                const mergedAt = pr.merged_at ? new Date(pr.merged_at) : null;
                return mergedAt && mergedAt >= since && mergedAt < until;
            });
            allPRs.push(...filtered);
        } catch (e) {
            console.warn(`Skipping ${repo}:`, e.message);
        }
    }
    return allPRs;
}

function updateKPI(section, id, currentValue, previousValue) {
    const sectionData = kpiData[section];
    const kpi = sectionData.find(k => k.id === id);
    if (kpi) {
        kpi.value = currentValue;
        kpi.previousValue = previousValue;
        kpi.lastUpdated = new Date().toLocaleDateString();
    }
    renderAllKPIs();
}

// Initialize
init();
