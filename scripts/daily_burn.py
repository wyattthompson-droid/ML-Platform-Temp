#!/usr/bin/env python3
"""ML Platform Daily Burn ETL — fetches JIRA sprint data with changelogs and writes daily snapshots."""

import asyncio
import aiohttp
import json
import os
import sys
from base64 import b64encode
from datetime import datetime, timezone, timedelta
from pathlib import Path

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


# --- JIRA API ---

async def get_active_sprint(session, config, headers):
    base = config["jira"]["baseUrl"]
    board_id = config["jira"]["boardId"]
    url = f"{base}/rest/agile/1.0/board/{board_id}/sprint"
    data = await fetch_json(session, url, headers, {"state": "active", "maxResults": 1})
    sprints = data.get("values", [])
    return sprints[0] if sprints else None


async def get_sprint_issues(session, config, headers, sprint_id):
    base = config["jira"]["baseUrl"]
    board_id = config["jira"]["boardId"]
    url = f"{base}/rest/agile/1.0/board/{board_id}/sprint/{sprint_id}/issue"
    sp_field = config["jira"]["fields"]["storyPoints"]
    teams_field = config["jira"]["fields"]["teams"]

    all_issues = []
    start_at = 0

    while True:
        data = await fetch_json(session, url, headers, {
            "startAt": start_at,
            "maxResults": 50,
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


async def fetch_issue_changelog(session, headers, base, key, semaphore):
    """Fetch full changelog for a single issue with concurrency control."""
    async with semaphore:
        all_items = []
        start_at = 0
        while True:
            try:
                url = f"{base}/rest/api/2/issue/{key}/changelog"
                data = await fetch_json(session, url, headers, {
                    "startAt": start_at,
                    "maxResults": 100
                })
                values = data.get("values", data.get("histories", []))
                if not values:
                    break
                all_items.extend(values)
                start_at += len(values)
                total = data.get("total", len(all_items))
                if start_at >= total:
                    break
            except Exception as e:
                print(f"  Warning: changelog fetch failed for {key}: {e}")
                break
        return key, all_items


async def fetch_all_changelogs(session, config, headers, issues):
    """Fetch changelogs for all issues concurrently."""
    base = config["jira"]["baseUrl"]
    semaphore = asyncio.Semaphore(20)
    tasks = [fetch_issue_changelog(session, headers, base, i["key"], semaphore) for i in issues]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    changelog_map = {}
    for result in results:
        if isinstance(result, Exception):
            continue
        key, items = result
        changelog_map[key] = items
    return changelog_map


def extract_timestamps(changelog_items, config):
    """Extract startedAt and blockedAt from changelog history."""
    in_progress_statuses = set(s.lower() for s in config["jira"]["statusCategories"].get("inProgress", []))
    blocked_statuses = set(s.lower() for s in config["jira"]["statusCategories"].get("blocked", []))

    started_at = None
    blocked_at = None

    for entry in changelog_items:
        created = entry.get("created", "")
        items = entry.get("items", [])
        for item in items:
            if item.get("field") == "status":
                to_status = (item.get("toString") or "").lower()
                if to_status in in_progress_statuses:
                    if started_at is None or created < started_at:
                        started_at = created
                if to_status in blocked_statuses:
                    if blocked_at is None or created > blocked_at:
                        blocked_at = created

    return started_at, blocked_at


def enrich_issues_with_changelogs(issues, changelog_map, config):
    """Attach startedAt and blockedAt to each issue."""
    for issue in issues:
        changelog = changelog_map.get(issue["key"], [])
        started_at, blocked_at = extract_timestamps(changelog, config)
        issue["startedAt"] = started_at
        issue["blockedAt"] = blocked_at
        issue["completedAt"] = issue.get("resolved")


# --- Epics ---

async def get_epics(session, config, headers):
    base = config["jira"]["baseUrl"]
    project = config["jira"]["projectKey"]
    sp_field = config["jira"]["fields"]["storyPoints"]

    # Fetch ALL epics (not just active) for roadmap view
    teams_field = config["jira"]["fields"]["teams"]
    team_name = config["jira"].get("teamName", "")
    jql = f'project = {project} AND issuetype = Epic ORDER BY priority ASC'

    fields_list = f"summary,status,assignee,{sp_field},priority,duedate,labels,parent,fixVersions,created,{teams_field}"
    data = None
    url = None

    # Use new /rest/api/3/search/jql endpoint (old /search is deprecated 410)
    data = None
    url = f"{base}/rest/api/3/search/jql"
    try:
        async with session.post(url, headers=headers, json={
            "jql": jql, "maxResults": 100, "fields": fields_list.split(",")
        }) as resp:
            print(f"  Search API status: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
            else:
                body = await resp.text()
                print(f"  Search API response: {body[:300]}")
    except Exception as e:
        print(f"  Search API failed: {e}")

    # Fallback: try GET on /rest/api/2/search
    if data is None:
        try:
            fallback_url = f"{base}/rest/api/2/search"
            data = await fetch_json(session, fallback_url, headers, {
                "jql": jql, "maxResults": 100, "fields": fields_list
            })
            url = fallback_url
        except Exception as e:
            print(f"  All epic fetch methods failed: {e}")
            return [], []

    all_epics = []
    for issue in data.get("issues", []):
        fields = issue["fields"]
        assignee = fields.get("assignee")
        parent = fields.get("parent")
        fix_versions = fields.get("fixVersions") or []
        labels = fields.get("labels") or []

        # Extract teams
        teams_raw = fields.get(teams_field) or []
        epic_teams = [t.get("value", t.get("name", "")) for t in teams_raw] if isinstance(teams_raw, list) else []

        # Determine target quarter from fixVersions or labels
        target_quarter = None
        for fv in fix_versions:
            name = fv.get("name", "")
            if "Q" in name and "20" in name:
                target_quarter = name
                break
        if not target_quarter:
            for label in labels:
                if "Q" in label and "20" in label:
                    target_quarter = label
                    break

        # Theme/initiative from parent or labels
        theme = None
        if parent:
            theme = parent.get("fields", {}).get("summary", parent.get("key", ""))
        elif labels:
            theme = labels[0] if labels else None

        all_epics.append({
            "key": issue["key"],
            "summary": fields.get("summary", ""),
            "status": fields["status"]["name"],
            "statusCategory": fields["status"]["statusCategory"]["name"],
            "assignee": assignee["displayName"] if assignee else "Unassigned",
            "priority": fields.get("priority", {}).get("name", ""),
            "dueDate": fields.get("duedate"),
            "created": fields.get("created"),
            "labels": labels,
            "teams": epic_teams,
            "theme": theme,
            "targetQuarter": target_quarter,
        })

    # Filter to ML Platform team (if configured)
    if team_name:
        epics = [e for e in all_epics if team_name in e.get("teams", [])]
        print(f"  Filtered to '{team_name}': {len(epics)} of {len(all_epics)} epics")
    else:
        epics = all_epics

    # Fetch child counts for each epic
    search_url = f"{base}/rest/api/3/search/jql"
    for epic in epics:
        jql_children = f'"Epic Link" = {epic["key"]} OR parent = {epic["key"]}'
        try:
            async with session.post(search_url, headers=headers, json={
                "jql": jql_children, "maxResults": 200, "fields": ["status"]
            }) as resp:
                if resp.status == 200:
                    children_data = await resp.json()
                else:
                    children_data = {"issues": []}
            children = children_data.get("issues", [])
            epic["totalIssues"] = len(children)
            epic["doneIssues"] = sum(1 for c in children if c["fields"]["status"]["statusCategory"]["name"] == "Done")
        except Exception as e:
            epic["totalIssues"] = 0
            epic["doneIssues"] = 0

    # Compute health status for each epic
    today = datetime.now(timezone.utc).date()
    for epic in epics:
        epic["health"] = compute_epic_health(epic, today)

    # Separate active vs future
    active_epics = [e for e in epics if e["statusCategory"] != "Done"]
    done_epics = [e for e in epics if e["statusCategory"] == "Done"]

    return active_epics, done_epics


def compute_epic_health(epic, today):
    """Compute Red/Yellow/Green health status for an epic."""
    status_cat = epic.get("statusCategory", "")
    if status_cat == "Done":
        return "green"

    due = epic.get("dueDate")
    total = epic.get("totalIssues", 0)
    done = epic.get("doneIssues", 0)
    pct = (done / total * 100) if total > 0 else 0

    if due:
        try:
            due_date = datetime.strptime(due, "%Y-%m-%d").date()
            days_until_due = (due_date - today).days

            if days_until_due < 0:
                return "red"  # Overdue
            elif days_until_due < 14 and pct < 70:
                return "yellow"  # Due soon, behind pace
            elif days_until_due < 30 and pct < 50:
                return "yellow"  # Due in a month, less than half done
        except (ValueError, TypeError):
            pass

    # No due date — check by progress
    if total > 0 and pct < 25 and epic.get("created"):
        try:
            created = datetime.fromisoformat(epic["created"].replace("Z", "+00:00")).date()
            age = (today - created).days
            if age > 60 and pct < 25:
                return "yellow"  # Old epic with little progress
        except (ValueError, TypeError):
            pass

    if total > 0 and pct >= 50:
        return "green"

    return "future" if total == 0 else "yellow"


# --- Categorization & Metrics ---

def categorize_issues(issues, config):
    categories = config["jira"]["statusCategories"]
    categorized = {cat: [] for cat in categories}
    categorized["other"] = []

    for issue in issues:
        placed = False
        for cat, statuses in categories.items():
            if issue["status"] in statuses:
                categorized[cat].append(issue)
                placed = True
                break
        if not placed:
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
    total_points = sum(i["storyPoints"] or 0 for i in issues)
    done_points = sum(i["storyPoints"] or 0 for i in categorized.get("done", []))
    in_progress_points = sum(i["storyPoints"] or 0 for i in categorized.get("inProgress", []))
    in_review_points = sum(i["storyPoints"] or 0 for i in categorized.get("inReview", []))
    blocked_points = sum(i["storyPoints"] or 0 for i in categorized.get("blocked", []))
    todo_points = sum(i["storyPoints"] or 0 for i in categorized.get("todo", []))
    wont_do_points = sum(i["storyPoints"] or 0 for i in categorized.get("wontDo", []))

    start = sprint.get("startDate", "")
    end = sprint.get("endDate", "")
    days_remaining = None
    days_elapsed = 0

    if start:
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            days_elapsed = max(1, (datetime.now(timezone.utc) - start_dt).days)
        except (ValueError, TypeError):
            days_elapsed = 1

    if end:
        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            days_remaining = max(0, (end_dt - datetime.now(timezone.utc)).days)
        except (ValueError, TypeError):
            pass

    throughput = round(done_points / days_elapsed, 2) if days_elapsed > 0 else 0

    return {
        "totalIssues": len(issues),
        "totalPoints": total_points,
        "donePoints": done_points,
        "inProgressPoints": in_progress_points,
        "inReviewPoints": in_review_points,
        "blockedPoints": blocked_points,
        "todoPoints": todo_points,
        "wontDoPoints": wont_do_points,
        "daysRemaining": days_remaining,
        "daysElapsed": days_elapsed,
        "completionPercent": round((done_points / total_points * 100) if total_points > 0 else 0, 1),
        "throughput": throughput,
    }


def percentile(sorted_values, p):
    """Compute p-th percentile from a sorted list."""
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * (p / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return round(sorted_values[f], 1)
    return round(sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f]), 1)


def compute_flow_metrics(done_tickets, sprint):
    """Compute lead time, cycle time percentiles, throughput, and flow efficiency."""
    lead_times = []
    cycle_times = []

    for t in done_tickets:
        created = t.get("created")
        completed = t.get("completedAt")
        started = t.get("startedAt")

        if created and completed:
            try:
                c = datetime.fromisoformat(created.replace("Z", "+00:00"))
                d = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                lead_days = max(0, (d - c).total_seconds() / 86400)
                lead_times.append(lead_days)
            except (ValueError, TypeError):
                pass

        if started and completed:
            try:
                s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                d = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                cycle_days = max(0, (d - s).total_seconds() / 86400)
                cycle_times.append(cycle_days)
            except (ValueError, TypeError):
                pass

    lead_times.sort()
    cycle_times.sort()

    lead_p50 = percentile(lead_times, 50)
    lead_p85 = percentile(lead_times, 85)
    lead_p95 = percentile(lead_times, 95)
    cycle_p50 = percentile(cycle_times, 50)
    cycle_p85 = percentile(cycle_times, 85)
    cycle_p95 = percentile(cycle_times, 95)

    flow_efficiency = None
    if lead_p85 and lead_p85 > 0 and cycle_p85:
        flow_efficiency = round(cycle_p85 / lead_p85, 2)

    return {
        "leadTime": {"p50": lead_p50, "p85": lead_p85, "p95": lead_p95, "values": [round(v, 1) for v in lead_times]},
        "cycleTime": {"p50": cycle_p50, "p85": cycle_p85, "p95": cycle_p95, "values": [round(v, 1) for v in cycle_times]},
        "flowEfficiency": flow_efficiency,
        "sampleSize": len(done_tickets),
    }


# --- Snapshot Index ---

def update_snapshot_index(today):
    index_path = SNAPSHOTS_DIR / "index.json"
    index = []
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text())
        except (json.JSONDecodeError, IOError):
            index = []

    if today not in index:
        index.append(today)
        index.sort()

    index_path.write_text(json.dumps(index, indent=2))
    return index


# --- Main ETL ---

async def run_etl(date_override=None):
    config = load_config()

    email = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email or not token:
        print("Error: JIRA_EMAIL and JIRA_API_TOKEN environment variables required.")
        sys.exit(1)

    headers = jira_auth_header(email, token)
    today = date_override or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"ML Platform Daily Burn — {today}")
    print("=" * 40)

    async with aiohttp.ClientSession() as session:
        # Sprint
        print("Fetching active sprint...")
        sprint = await get_active_sprint(session, config, headers)
        if not sprint:
            print("No active sprint. Creating minimal snapshot.")
            snapshot = {
                "date": today,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "sprint": None, "tickets": {}, "summary": {},
                "epics": [], "epicHealthSummary": {"red": 0, "yellow": 0, "green": 0, "future": 0}, "flowMetrics": {},
            }
        else:
            sprint_id = sprint["id"]
            sprint_name = sprint.get("name", "Unknown Sprint")
            print(f"  Sprint: {sprint_name} (ID: {sprint_id})")

            # Issues
            print("Fetching sprint issues...")
            issues = await get_sprint_issues(session, config, headers, sprint_id)
            print(f"  Found {len(issues)} issues")

            # Changelogs
            print("Fetching changelogs...")
            changelog_map = await fetch_all_changelogs(session, config, headers, issues)
            print(f"  Fetched changelogs for {len(changelog_map)} issues")

            # Enrich
            enrich_issues_with_changelogs(issues, changelog_map, config)

            # Categorize
            categorized = categorize_issues(issues, config)
            for cat, items in categorized.items():
                if items:
                    print(f"  {cat}: {len(items)}")

            # Summary
            summary = compute_sprint_summary(sprint, categorized, issues)
            print(f"  Points: {summary['donePoints']}/{summary['totalPoints']} ({summary['completionPercent']}%)")
            print(f"  Throughput: {summary['throughput']} pts/day")

            # Flow metrics
            print("Computing flow metrics...")
            flow_metrics = compute_flow_metrics(categorized.get("done", []), sprint)
            if flow_metrics["leadTime"]["p50"]:
                print(f"  Lead Time P50: {flow_metrics['leadTime']['p50']}d, P85: {flow_metrics['leadTime']['p85']}d")
            if flow_metrics["cycleTime"]["p50"]:
                print(f"  Cycle Time P50: {flow_metrics['cycleTime']['p50']}d, P85: {flow_metrics['cycleTime']['p85']}d")

            # Epics
            print("Fetching epics...")
            active_epics, done_epics = await get_epics(session, config, headers)
            print(f"  Found {len(active_epics)} active epics, {len(done_epics)} done")
            # Health summary
            health_counts = {"red": 0, "yellow": 0, "green": 0, "future": 0}
            for e in active_epics:
                health_counts[e.get("health", "future")] += 1
            print(f"  Health: {health_counts}")

            snapshot = {
                "date": today,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "sprint": {
                    "id": sprint_id, "name": sprint_name,
                    "startDate": sprint.get("startDate"),
                    "endDate": sprint.get("endDate"),
                    "goal": sprint.get("goal", ""),
                },
                "summary": summary,
                "tickets": categorized,
                "epics": active_epics,
                "epicHealthSummary": health_counts,
                "flowMetrics": flow_metrics,
            }

    # Write snapshot
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    snapshot_path = SNAPSHOTS_DIR / f"{today}.json"
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"\nSnapshot written to {snapshot_path}")

    latest_path = SNAPSHOTS_DIR / "latest.json"
    with open(latest_path, "w") as f:
        json.dump(snapshot, f, indent=2)
    print(f"Latest snapshot written to {latest_path}")

    # Update index
    update_snapshot_index(today)
    print("Snapshot index updated")

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
