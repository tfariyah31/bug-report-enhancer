"""
github_uploader.py

Can be used two ways:
  1. Called automatically by bug_reporter.py
  2. Standalone — push an already-saved bug_report.md:
        python src/github_uploader.py

Requires in .env:
    GITHUB_TOKEN=ghp_...
    GITHUB_REPO=your-username/your-repo
    GITHUB_ASSIGNEE=username   (optional)
"""

import os
import json
import re
import urllib.request
import urllib.error
from pathlib import Path

REPORT_PATH = Path("bug_report.md")

SEVERITY_LABEL_MAP = {
    "critical": {"name": "severity: critical", "color": "b60205"},
    "high":     {"name": "severity: high",     "color": "e11d48"},
    "medium":   {"name": "severity: medium",   "color": "f97316"},
    "low":      {"name": "severity: low",      "color": "facc15"},
}

PRIORITY_LABEL_MAP = {
    "P0": {"name": "priority: P0", "color": "7f0000"},
    "P1": {"name": "priority: P1", "color": "b91c1c"},
    "P2": {"name": "priority: P2", "color": "1d4ed8"},
    "P3": {"name": "priority: P3", "color": "6b7280"},
}


# ── GitHub API helper ─────────────────────────────────────────────────────────

def github_request(method: str, path: str, data: dict = None):
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError("GITHUB_TOKEN not set in .env")

    url = f"https://api.github.com{path}"
    headers = {
        "Authorization":        f"Bearer {token}",
        "Accept":               "application/vnd.github+json",
        "Content-Type":         "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"❌ GitHub API error {e.code}: {e.read().decode()}")
        return None


def ensure_label(repo: str, name: str, color: str):
    """Create label in repo if it doesn't exist yet."""
    existing = github_request("GET", f"/repos/{repo}/labels")
    if existing is None:
        return
    if name not in [l["name"] for l in existing]:
        github_request("POST", f"/repos/{repo}/labels",
                       {"name": name, "color": color, "description": ""})
        print(f"   Created label: {name}")


# ── Issue creation ────────────────────────────────────────────────────────────

def create_github_issue(
    title:    str,
    body:     str,
    severity: str = "medium",
    priority: str = "P2",
    repo:     str = None,
    assignee: str = None,
) -> str | None:
    """
    Create a GitHub issue and return its URL.
    Called by bug_reporter.py or standalone.
    """
    repo     = repo     or os.getenv("GITHUB_REPO")
    assignee = assignee or os.getenv("GITHUB_ASSIGNEE")

    if not repo:
        raise EnvironmentError(
            "GITHUB_REPO not set.\n"
            "Add to .env: GITHUB_REPO=your-username/your-repo"
        )

    labels = ["bug"]

    sev_info = SEVERITY_LABEL_MAP.get(severity.lower())
    if sev_info:
        ensure_label(repo, sev_info["name"], sev_info["color"])
        labels.append(sev_info["name"])

    pri_info = PRIORITY_LABEL_MAP.get(priority.upper())
    if pri_info:
        ensure_label(repo, pri_info["name"], pri_info["color"])
        labels.append(pri_info["name"])

    payload = {"title": title, "body": body, "labels": labels}
    if assignee:
        payload["assignees"] = [assignee]

    print(f"\n📤 Creating GitHub issue in {repo}...")
    print(f"   Title  : {title}")
    print(f"   Labels : {labels}")

    result = github_request("POST", f"/repos/{repo}/issues", payload)
    return result.get("html_url") if result else None


# ── Metadata helpers ──────────────────────────────────────────────────────────

def extract_title(report: str) -> str:
    match = re.search(r"##\s+\[(FE|BE)\]\s+(.+)", report)
    if match:
        return f"[{match.group(1)}] {match.group(2).strip()}"
    for line in report.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith("<!--"):
            return line
    return "Bug Report"


def extract_severity(report: str) -> str:
    match = re.search(r"Severity[^:]*:\s*(Critical|High|Medium|Low)", report, re.IGNORECASE)
    return match.group(1).lower() if match else "medium"


def extract_priority(report: str) -> str:
    match = re.search(r"Priority[^:]*:\s*(P[0-3])", report, re.IGNORECASE)
    return match.group(1).upper() if match else "P2"


# ── Standalone entry point ────────────────────────────────────────────────────

def main():
    if not REPORT_PATH.exists():
        print(f"❌ No bug report found at {REPORT_PATH}")
        print("   Run bug_reporter.py first to generate one.")
        return

    report   = REPORT_PATH.read_text(encoding="utf-8")
    title    = extract_title(report)
    severity = extract_severity(report)
    priority = extract_priority(report)

    print(f"📋 File     : {REPORT_PATH}")
    print(f"📝 Title    : {title}")
    print(f"🔴 Severity : {severity}")
    print(f"🎯 Priority : {priority}")

    confirm = input("\n🚀 Push to GitHub? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    url = create_github_issue(title=title, body=report,
                              severity=severity, priority=priority)
    if url:
        print(f"\n✅ Issue created: {url}")
    else:
        print("\n❌ Failed. Check GITHUB_TOKEN and GITHUB_REPO in .env")


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    main()