# ML Platform Command Center

Live dashboard and documentation hub for the Data Science & ML Platform team.

## What's here

- **KPI Dashboard** — Live metrics pulled from GitHub (Apixio org) + manually tracked KPIs
- **Documentation** — OCR decision tree, Bedrock vs Databricks pricing, model availability, user personas

## View the Dashboard

Once GitHub Pages is enabled, visit: `https://wyattthompson-droid.github.io/Wyatt/`

## Updating Manual KPIs

Edit `kpi-data.json` and update the `value` and `previousValue` fields for any manual KPI. The dashboard reads from this file directly.

## Connecting GitHub KPIs

1. Generate a GitHub personal access token with `repo` and `read:org` scope
2. Enter it in the token field on the dashboard
3. Click Connect — live KPIs will populate from the Apixio org

## Adding Documentation

Add new HTML pages to the `docs/` folder and link them from `index.html`.

## Repo Structure

```
├── index.html          # Dashboard
├── styles.css          # Styling
├── app.js              # GitHub API integration + rendering
├── kpi-data.json       # Manual KPI values
├── docs/               # Documentation pages
│   ├── ocr-decision-tree.html
│   ├── bedrock-vs-databricks-pricing.html
│   ├── model-availability.html
│   └── user-personas.html
└── README.md
```
