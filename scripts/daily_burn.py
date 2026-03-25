#!/usr/bin/env python3
"""ML Platform Daily Burn ETL — fetches JIRA sprint data and writes a daily snapshot."""

import asyncio
import aiohttp
import json
import os
import sys
from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "daily-burn.json"
SNAPSHOTS_DIR = ROOT / "snapshots"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def jira_auth_header(email, token):
    creds = b64encode(f"{email}:{token}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}


async def fetch_json(session, url, headers, params=None):
    async with session.get(url, headers=headers, params=params) as resp:
        if resp.status == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            print(f"  Rate limited, waiting {retry_after}s...")
            await asyncio.sleep(retry_after)
            return await fetch_json(session, url, headers, params)
        resp.raise_for_status()
        return await resp.json()


async def get_active_sprint(session, config, headers):
    """Get the active sprint for the board."""
    base = config["jira"]["baseUrl"]
    board_id = config["jira"]["boardId"]
    url = f"{base}/rest/agile/1.0/board/{board_id}/sprint"
    data = await fetch_json(session, url, headers, {"state": "active", "maxResults": 1})
    sprints = data.get("values", [])
    if not sprints:
        print("No active sprint found.")
        return None
    return sprints[0]


async def get_sprint_issues(session, config, headers, sprint_id):
    """Fetch all issues in the sprint."""
    base = config["jira"]["baseUrl"]
    board_id = config["jira"]["boardId"]
    url = f"{base}/rest/agile/1.0/board/{board_id}/sprint/{sprint_id}/issue"

    sp_field = config["jira"]["fields"]["storyPoints"]
    teams_field = config["jira"]["fields"]["teams"]

    all_issues = []
    start_at = 0
    max_results = 50

    while True:
        data = await fetch_json(session, url, headers, {
            "startAt": start_at,
            "maxResults": max_results,
            "fields": f"summary,status,assignee,issuetype,priority,{sp_field},{teams_field},created,resolutiondate"
        })
        issues = data.get("issues", [])
        if not issues:
            break

        for issue in issues:
            fields = issue["fields"]
            assignee = fields.get("assignee")
            teams_raw = fields.get(teams_field) or []
            team_names = [t.get("value", t.get("name", "")) for t in teams_raw] if isinstance(teams_raw, list) else []

            all_issues.append({
                "key": issue["key"],
                "summary": fields.get("summary", ""),
                "status": fields["status"]["name"],
                "statusCategory": fields["status"]["statusCategory"]["name"],
                "assignee": assignee["displayName"] if assignee else "Unassigned",
                "issueType": fields["issuetype"]["name"],
                "priority": fields.get("priority", {}).get("name", ""),
                "storyPoints": fields.get(sp_field),
                "teams": team_names,
                "created": fields.get("created"),
                "resolved": fields.get("resolutiondate"),
            })

        start_at += len(issues)
        if start_at >= data.get("total", 0):
            break

    return all_issues


async def get_epics(session, config, headers):
    """Fetch active epics for the project."""
    base = config["jira"]["baseUrl"]
    project = config["jira"]["projectKey"]
    sp_field = config["jira"]["fields"]["storyPoints"]

    jql = f'project = {project} AND issuetype = Epic AND status not in (Done, Closed, Resolved) ORDER BY priority ASC'
    url = f"{base}/rest/api/3/search"

    data = await fetch_json(session, url, headers, {
        "jql": jql,
        "maxResults": 50,
        "fields": f"summary,status,assignee,{sp_field},priority"
    })

    epics = []
    for issue in data.get("issues", []):
        fields = issue["fields"]
        assignee = fields.get("assignee")
        epics.append({
            "key": issue["key"],
            "summary": fields.get("summary", ""),
            "status": fields["status"]["name"],
            "assignee": assignee["displayName"] if assignee else "Unassigned",
            "priority": fields.get("priority", {}).get("name", ""),
        })

    # For each epic, get child issue counts
    for epic in epics:
        jql_children = f'"Epic Link" = {epic["key"]} OR parent = {epic["key"]}'
        children_data = await fetch_json(session, url, headers, {
            "jql": jql_children,
            "maxResults": 0,
            "fields": "status"
        })
        # Need actual issues to count done vs total
        children_data = await fetch_json(session, url, headers, {
            "jql": jql_children,
            "maxResults": 200,
            "fields": "status"
        })
        children = children_data.get("issues", [])
        total = len(children)
        done = sum(1 for c in children if c["fields"]["status"]["statusCategory"]["name"] == "Done")
        epic["totalIssues"] = total
        epic["doneIssues"] = done

    return epics


def categorize_issues(issues, config):
    """Group issues by status category."""
    categories = config["jira"]["statusCategories"]
    categorized = {cat: [] for cat in categories}
    categorized["other"] = []

    for issue in issues:
        placed = False
        for cat, statuses in categories.items():
            if issue["status"] in statuses or issue["statusCategory"].lower() == cat.lower():
                categorized[cat].append(issue)
                placed = True
                break
        if not placed:
            # Fall back to JIRA's statusCategory
            jira_cat = issue["statusCategory"].lower()
            if jira_cat == "to do":
                categorized["todo"].append(issue)
            elif jira_cat == "in progress":
                categorized["inProgress"].append(issue)
            elif jira_cat == "done":
                categorized["done"].append(issue)
            else:
                categorized["other"].append(issue)

    return categorized


def compute_sprint_summary(sprint, categorized, issues):
    """Compute sprint-level metrics."""
    total_points = sum(i["storyPoints"] or 0 for i in issues)
    done_points = sum(i["storyPoints"] or 0 for i in categorized.get("done", []))
    in_progress_points = sum(i["storyPoints"] or 0 for i in categorized.get("inProgress", []))

    start = sprint.get("startDate", "")
    end = sprint.get("endDate", "")
    days_remaining = None
    if end:
        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            days_remaining = max(0, (end_dt - datetime.now(timezone.utc)).days)
        except (ValueError, TypeError):
            pass

    return {
        "totalIssues": len(issues),
        "totalPoints": total_points,
        "donePoints": done_points,
        "inProgressPoints": in_progress_points,
        "daysRemaining": days_remaining,
        "completionPercent": round((done_points / total_points * 100) if total_points > 0 else 0, 1),
    }


async def run_etl(date_override=None):
    config = load_config()

    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email or not token:
        print("Error: JIRA_EMAIL and JIRA_API_TOKEN environment variables required.")
        print("See .env.example for setup.")
        sys.exit(1)

    headers = jira_auth_header(email, token)
    today = date_override or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"ML Platform Daily Burn — {today}")
    print("=" * 40)

    async with aiohttp.ClientSession() as session:
        # Fetch sprint
        print("Fetching active sprint...")
        sprint = await get_active_sprint(session, config, headers)
        if not sprint:
            print("No active sprint. Creating minimal snapshot.")
            snapshot = {
                "date": today,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "sprint": None,
                "tickets": {},
                "summary": {},
                "epics": [],
            }
        else:
            sprint_id = sprint["id"]
            sprint_name = sprint.get("name", "Unknown Sprint")
            print(f"  Sprint: {sprint_name} (ID: {sprint_id})")

            # Fetch issues
            print("Fetching sprint issues...")
            issues = await get_sprint_issues(session, config, headers, sprint_id)
            print(f"  Found {len(issues)} issues")

            # Categorize
            categorized = categorize_issues(issues, config)
            for cat, items in categorized.items():
                if items:
                    print(f"  {cat}: {len(items)}")

            # Summary
            summary = compute_sprint_summary(sprint, categorized, issues)
            print(f"  Points: {summary['donePoints']}/{summary['totalPoints']} ({summary['completionPercent']}%)")
            if summary["daysRemaining"] is not None:
                print(f"  Days remaining: {summary['daysRemaining']}")

            # Fetch epics
            print("Fetching epics...")
            epics = await get_epics(session, config, headers)
            print(f"  Found {len(epics)} active epics")

            snapshot = {
                "date": today,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "sprint": {
                    "id": sprint_id,
                    "name": sprint_name,
                    "startDate": sprint.get("startDate"),
                    "endDate": sprint.get("endDate"),
                    "goal": sprint.get("goal", ""),
                },
                "summary": summary,
                "tickets": categorized,
                "epics": epics,
            }

    # Write snapshot
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    snapshot_path = SNAPSHOTS_DIR / f"{today}.json"
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"\nSnapshot written to {snapshot_path}")

    # Also write latest.json for the dashboard to load
    latest_path = SNAPSHOTS_DIR / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"Latest snapshot written to {latest_path}")

    return snapshot


def main():
    date_override = None
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            date_override = sys.argv[idx + 1]

    asyncio.run(run_etl(date_override))


if __name__ == "__main__":
    main()
