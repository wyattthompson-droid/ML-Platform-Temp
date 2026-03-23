# ML Platform Command Center

Live dashboard and documentation hub for the Data Science & ML Platform team.

## View the Dashboard

https://wyattthompson-droid.github.io/ML-Platform-Temp/

## What's here

- **KPI Dashboard** — GitHub-sourced metrics auto-refresh every 6 hours via GitHub Actions. Manual KPIs updated via `kpi-data.json`.
- **Documentation** — OCR decision tree, Bedrock vs Databricks pricing, model availability, user personas

## How KPIs update

**GitHub KPIs** (PRs, model updates, deployment time) are refreshed automatically every 6 hours by a GitHub Actions workflow. The workflow queries the Apixio org and writes results to `kpi-data.json`.

**Manual KPIs** (inference errors, Databricks cost, OCR metrics) — edit `kpi-data.json` and update the `value` and `previousValue` fields.

## Setup: GitHub Actions Token

For the auto-refresh to work, add a repository secret:

1. Go to repo **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `KPI_GITHUB_TOKEN`
4. Value: A GitHub personal access token with `repo` and `read:org` scope, authorized for the Apixio org via SSO

## Adding Documentation

Add new HTML pages to the `docs/` folder and link them from `index.html`.

## Repo Structure

```
├── index.html                         # Dashboard
├── styles.css                         # Styling
├── app.js                             # Rendering logic
├── kpi-data.json                      # All KPI values (auto + manual)
├── .github/workflows/refresh-kpis.yml # Auto-refresh workflow
├── docs/                              # Documentation pages
│   ├── ocr-decision-tree.html
│   ├── bedrock-vs-databricks-pricing.html
│   ├── model-availability.html
│   └── user-personas.html
└── README.md
```
