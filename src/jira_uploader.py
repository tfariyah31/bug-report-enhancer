"""
Can be used two ways:
  1. Called automatically by bug_reporter.py
  2. Standalone — push an already-saved bug_report.md:
        python src/jira_uploader.py

Requires in .env:
    JIRA_URL=https://your-domain.atlassian.net
    JIRA_EMAIL=your@email.com
    JIRA_API_TOKEN=your_token_here
    JIRA_PROJECT_KEY=PROJ
    JIRA_ASSIGNEE_ACCOUNT_ID=   (optional — Jira uses account IDs not usernames)

Get your Jira API token at: https://id.atlassian.com/manage-api-tokens
"""

import os
import json
import re
import base64
import urllib.request
import urllib.error
from pathlib import Path

REPORT_PATH = Path("bug_report.md")

SEVERITY_TO_PRIORITY = {
    "critical": "Highest",
    "high":     "High",
    "medium":   "Medium",
    "low":      "Low",
}


# ── Markdown → Atlassian Document Format (ADF) ───────────────────────────────
# Jira Cloud API v3 requires ADF for description fields.
# This converter handles the markdown patterns in your bug template.

def md_to_adf(markdown: str) -> dict:
    """
    Convert a markdown string to Atlassian Document Format (ADF) JSON.
    Handles: headings (##, ###), bullet lists, checkboxes, code blocks,
    bold (**text**), inline code, horizontal rules, and plain paragraphs.
    """
    content = []
    lines   = markdown.splitlines()
    i       = 0

    def make_text(text: str) -> list:
        """Parse inline bold and inline code into ADF marks."""
        nodes = []
        # Split on **bold** and `code`
        pattern = re.compile(r'(\*\*[^*]+\*\*|`[^`]+`)')
        parts   = pattern.split(text)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                nodes.append({
                    "type": "text",
                    "text": part[2:-2],
                    "marks": [{"type": "strong"}]
                })
            elif part.startswith("`") and part.endswith("`"):
                nodes.append({
                    "type": "text",
                    "text": part[1:-1],
                    "marks": [{"type": "code"}]
                })
            elif part:
                nodes.append({"type": "text", "text": part})
        return nodes or [{"type": "text", "text": text}]

    while i < len(lines):
        line = lines[i]

        # ── Horizontal rule ──
        if re.match(r'^---+$', line.strip()):
            content.append({"type": "rule"})
            i += 1
            continue

        # ── Code block ──
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip() or "text"
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            content.append({
                "type": "codeBlock",
                "attrs": {"language": lang},
                "content": [{"type": "text", "text": "\n".join(code_lines)}]
            })
            i += 1
            continue

        # ── Heading ## ──
        heading_match = re.match(r'^(#{1,4})\s+(.*)', line)
        if heading_match:
            level = min(len(heading_match.group(1)), 4)
            text  = heading_match.group(2).strip()
            # Strip HTML comments from headings
            text  = re.sub(r'<!--.*?-->', '', text).strip()
            if text:
                content.append({
                    "type":    "heading",
                    "attrs":   {"level": level},
                    "content": [{"type": "text", "text": text}]
                })
            i += 1
            continue

        # ── Checkbox list item ──
        if re.match(r'^\s*-\s+\[[ xX]\]', line):
            checked = bool(re.match(r'^\s*-\s+\[[xX]\]', line))
            text    = re.sub(r'^\s*-\s+\[[ xX]\]\s*', '', line)
            content.append({
                "type": "taskList",
                "attrs": {"localId": f"task-{i}"},
                "content": [{
                    "type":    "taskItem",
                    "attrs":   {"localId": f"item-{i}", "state": "DONE" if checked else "TODO"},
                    "content": make_text(text)
                }]
            })
            i += 1
            continue

        # ── Bullet list item ──
        if re.match(r'^\s*[-*]\s+', line):
            items = []
            while i < len(lines) and re.match(r'^\s*[-*]\s+', lines[i]):
                item_text = re.sub(r'^\s*[-*]\s+', '', lines[i])
                items.append({
                    "type":    "listItem",
                    "content": [{"type": "paragraph", "content": make_text(item_text)}]
                })
                i += 1
            content.append({"type": "bulletList", "content": items})
            continue

        # ── Numbered list item ──
        if re.match(r'^\s*\d+\.\s+', line):
            items = []
            while i < len(lines) and re.match(r'^\s*\d+\.\s+', lines[i]):
                item_text = re.sub(r'^\s*\d+\.\s+', '', lines[i])
                items.append({
                    "type":    "listItem",
                    "content": [{"type": "paragraph", "content": make_text(item_text)}]
                })
                i += 1
            content.append({"type": "orderedList", "content": items})
            continue

        # ── HTML comment lines (skip) ──
        if line.strip().startswith("<!--"):
            i += 1
            continue

        # ── Blank line (skip) ──
        if not line.strip():
            i += 1
            continue

        # ── Plain paragraph ──
        # Strip inline HTML comments before adding
        clean = re.sub(r'<!--.*?-->', '', line).strip()
        if clean:
            content.append({
                "type":    "paragraph",
                "content": make_text(clean)
            })
        i += 1

    return {
        "version": 1,
        "type":    "doc",
        "content": content or [{"type": "paragraph",
                                 "content": [{"type": "text", "text": " "}]}]
    }


# ── Jira API helper ───────────────────────────────────────────────────────────

def jira_request(method: str, path: str, data: dict = None):
    jira_url = os.getenv("JIRA_URL", "").rstrip("/")
    email    = os.getenv("JIRA_EMAIL")
    token    = os.getenv("JIRA_API_TOKEN")

    if not all([jira_url, email, token]):
        raise EnvironmentError(
            "Missing Jira credentials.\n"
            "Set JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN in your .env"
        )

    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    url     = f"{jira_url}/rest/api/3{path}"
    headers = {
        "Authorization": f"Basic {credentials}",
        "Accept":        "application/json",
        "Content-Type":  "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req  = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"❌ Jira API error {e.code}: {e.read().decode()}")
        return None


# ── Issue creation ────────────────────────────────────────────────────────────

def create_jira_issue(
    title:       str,
    body:        str,
    severity:    str = "medium",
    project_key: str = None,
    assignee_id: str = None,
) -> str | None:
    """
    Create a Jira Bug ticket and return its URL.
    Called by bug_reporter.py or standalone.
    """
    project_key = project_key or os.getenv("JIRA_PROJECT_KEY")
    assignee_id = assignee_id or os.getenv("JIRA_ASSIGNEE_ACCOUNT_ID")

    if not project_key:
        raise EnvironmentError(
            "JIRA_PROJECT_KEY not set.\n"
            "Add to .env: JIRA_PROJECT_KEY=PROJ"
        )

    jira_priority = SEVERITY_TO_PRIORITY.get(severity.lower(), "Medium")
    adf_body      = md_to_adf(body)

    payload = {
        "fields": {
            "project":     {"key": project_key},
            "summary":     title,
            "description": adf_body,
            "issuetype":   {"name": "Bug"},
            "priority":    {"name": jira_priority},
        }
    }

    if assignee_id:
        payload["fields"]["assignee"] = {"accountId": assignee_id}

    print(f"\n📤 Creating Jira ticket in project {project_key}...")
    print(f"   Summary  : {title}")
    print(f"   Priority : {jira_priority}")

    result = jira_request("POST", "/issue", payload)

    if result and "key" in result:
        jira_url   = os.getenv("JIRA_URL", "").rstrip("/")
        ticket_url = f"{jira_url}/browse/{result['key']}"
        print(f"   Ticket   : {result['key']}")
        return ticket_url

    return None


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


# ── Standalone entry point ────────────────────────────────────────────────────

def main():
    if not REPORT_PATH.exists():
        print(f"❌ No bug report found at {REPORT_PATH}")
        print("   Run bug_reporter.py first to generate one.")
        return

    report   = REPORT_PATH.read_text(encoding="utf-8")
    title    = extract_title(report)
    severity = extract_severity(report)

    print(f"📋 File     : {REPORT_PATH}")
    print(f"📝 Title    : {title}")
    print(f"🔴 Severity : {severity}")

    confirm = input("\n🚀 Push to Jira? (y/n): ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    url = create_jira_issue(title=title, body=report, severity=severity)
    if url:
        print(f"\n✅ Jira ticket created: {url}")
    else:
        print("\n❌ Failed. Check JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY in .env")


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    main()