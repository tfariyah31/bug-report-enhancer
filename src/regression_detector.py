"""
regression_detector.py

Checks for duplicate/similar bugs before uploading to GitHub or Jira.

- GitHub : uses GitHub's built-in issue search API
- Jira   : uses Jira's text search via JQL (summary ~ "keyword")

Called automatically by bug_reporter.py before upload.
Can also be run standalone:
    python src/regression_detector.py "Login button not working"
"""

import os
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────────────────

MAX_ISSUES      = 20      # how many recent issues to check
SIMILARITY_WARN = 0.20    # keyword overlap threshold for warning
SIMILARITY_HIGH  = 0.70   # HIGH match threshold
SIMILARITY_MED   = 0.40   # MEDIUM match threshold


# ── GitHub duplicate check ────────────────────────────────────────────────────

def _github_request(path: str):
    """Make a GitHub API GET request."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError("GITHUB_TOKEN not set in .env")

    url     = f"https://api.github.com{path}"
    headers = {
        "Authorization":        f"Bearer {token}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"   ⚠️  GitHub API error {e.code}: {e.read().decode()[:100]}")
        return None


def _keyword_similarity(text1: str, text2: str) -> float:
    """
    Simple keyword overlap similarity.
    Returns 0.0 to 1.0 — no embeddings needed, fast.
    """
    # Ignore common words
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "in",
                 "on", "at", "to", "for", "of", "and", "or", "not",
                 "with", "from", "by", "as", "it", "this", "that"}

    def keywords(text: str) -> set:
        words = text.lower().replace("-", " ").replace("_", " ").split()
        return {w.strip(".,!?[]()") for w in words
                if len(w) > 2 and w not in stopwords}

    kw1 = keywords(text1)
    kw2 = keywords(text2)

    if not kw1 or not kw2:
        return 0.0

    intersection = kw1 & kw2
    union        = kw1 | kw2
    return round(len(intersection) / len(union), 3)


def check_github(bug_description: str, repo: str = None) -> list[dict]:
    """
    Search GitHub issues for similar bugs using built-in search API.
    Returns list of similar issues with similarity scores.
    """
    repo = repo or os.getenv("GITHUB_REPO")
    if not repo:
        print("   ⚠️  GITHUB_REPO not set — skipping GitHub check")
        return []

    # Extract keywords for search query (top 3 meaningful words)
    stopwords = {"the", "a", "an", "is", "are", "was", "not", "with",
                 "from", "by", "as", "it", "this", "that", "to", "in"}
    words = [w.lower().strip(".,!?[]()") for w in bug_description.split()
             if len(w) > 3 and w.lower() not in stopwords]
    query_words = words[:4]

    if not query_words:
        return []

    # GitHub search API
    query  = " ".join(query_words) + f" repo:{repo} is:issue"
    path   = f"/search/issues?q={urllib.parse.quote(query)}&per_page={MAX_ISSUES}&sort=created&order=desc"
    result = _github_request(path)

    if not result or "items" not in result:
        return []

    similar = []
    for issue in result["items"]:
        title      = issue.get("title", "")
        body       = issue.get("body", "") or ""
        issue_text = f"{title} {title} {body[:300]}"
        score      = _keyword_similarity(bug_description, issue_text)

        
        effective_score = max(score, 0.45)

        if effective_score >= SIMILARITY_WARN:
            similar.append({
                "number":   issue["number"],
                "title":    title,
                "url":      issue["html_url"],
                "state":    issue["state"],
                "score": effective_score,
                "source":   "github",
            })

    # Sort by similarity score descending
    similar.sort(key=lambda x: x["score"], reverse=True)
    return similar[:5]  # return top 5 matches


# ── Jira duplicate check ──────────────────────────────────────────────────────

def _jira_request(path: str):
    """Make a Jira API GET request."""
    import base64
    jira_url = os.getenv("JIRA_URL", "").rstrip("/")
    email    = os.getenv("JIRA_EMAIL")
    token    = os.getenv("JIRA_API_TOKEN")

    if not all([jira_url, email, token]):
        raise EnvironmentError("JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN not set in .env")

    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    url     = f"{jira_url}/rest/api/3{path}"
    headers = {
        "Authorization": f"Basic {credentials}",
        "Accept":        "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"   ⚠️  Jira API error {e.code}: {e.read().decode()[:100]}")
        return None


def check_jira(bug_description: str, project_key: str = None) -> list[dict]:
    """
    Search Jira issues using JQL text search on summary field.
    Returns list of similar issues with similarity scores.
    """
    project_key = project_key or os.getenv("JIRA_PROJECT_KEY")
    if not project_key:
        print("   ⚠️  JIRA_PROJECT_KEY not set — skipping Jira check")
        return []

    # Extract keywords for JQL query
    stopwords = {"the", "a", "an", "is", "are", "was", "not", "with",
                 "from", "by", "as", "it", "this", "that", "to", "in"}
    words = [w.lower().strip(".,!?[]()") for w in bug_description.split()
             if len(w) > 3 and w.lower() not in stopwords]
    query_words = words[:3]

    if not query_words:
        return []

    # JQL: search summary contains any of the keywords
    keyword_conditions = " OR ".join(
        [f'summary ~ "{w}"' for w in query_words]
    )
    jql = (
        f'project = "{project_key}" '
        f'AND issuetype = Bug '
        f'AND ({keyword_conditions}) '
        f'ORDER BY created DESC'
    )

    path   = f"/search/jql?jql={urllib.parse.quote(jql)}&maxResults={MAX_ISSUES}&fields=summary,status,assignee"
    result = _jira_request(path)

    if not result or "issues" not in result:
        return []

    jira_url = os.getenv("JIRA_URL", "").rstrip("/")
    similar  = []

    for issue in result["issues"]:
        fields  = issue.get("fields", {})
        summary = fields.get("summary", "")
        status  = fields.get("status", {}).get("name", "Unknown")
        score   = _keyword_similarity(bug_description, summary)

        if score >= SIMILARITY_WARN:
            similar.append({
                "key":    issue["key"],
                "title":  summary,
                "url":    f"{jira_url}/browse/{issue['key']}",
                "state":  status,
                "score":  score,
                "source": "jira",
            })

    similar.sort(key=lambda x: x["score"], reverse=True)
    return similar[:5]


# ── Display + decision ────────────────────────────────────────────────────────

def _similarity_label(score: float) -> str:
    if score >= SIMILARITY_HIGH:
        return "HIGH   ❌"
    elif score >= SIMILARITY_MED:
        return "MEDIUM ⚠️ "
    return "LOW    ✅"

def display_and_confirm(
    similar_issues: list[dict],
    destination: str,
) -> bool:
    """
    Display similar issues and ask user to confirm upload.
    Returns True if user wants to proceed, False to cancel.
    """
    
    has_significant = any(i["score"] >= SIMILARITY_MED for i in similar_issues)

    if not has_significant:
        print(f"\n   ℹ️  Low similarity matches found — likely not duplicates")
        for issue in similar_issues:
            ref = f"#{issue['number']}" if issue["source"] == "github" else issue["key"]
            print(f"   {ref} — {issue['title'][:55]}")
        return True  
    
    print(f"\n   {'─' * 55}")
    print(f"   ⚠️  Similar issues found in {destination}:")
    print(f"   {'─' * 55}")

    for issue in similar_issues:
        label = _similarity_label(issue["score"])
        if issue["source"] == "github":
            ref = f"#{issue['number']}"
        else:
            ref = issue["key"]

        print(f"   {label}  {ref} ({int(issue['score']*100)}% match)")
        print(f"            {issue['title'][:60]}")
        print(f"            {issue['url']}")
        print(f"            Status: {issue['state']}")
        print()

    print(f"   {'─' * 55}")
    print("   Options:")
    print("   [1] Proceed — not a duplicate")
    print("   [2] Cancel  — skip upload")
    print(f"   {'─' * 55}")

    choice = input("   Enter choice (1/2): ").strip()
    return choice == "1"


def run_regression_check(
    bug_description: str,
    destination: str,          # "github", "jira", or "both"
) -> bool:
    """
    Main entry point called by bug_reporter.py.
    Returns True if upload should proceed, False if cancelled.
    """
    print(f"\n🔎 Regression Check ({destination.upper()})")

    all_similar = []

    if destination in ("github", "both"):
        print("   Searching GitHub issues...")
        github_similar = check_github(bug_description)
        all_similar.extend(github_similar)
        if not github_similar:
            print("   ✅ No similar GitHub issues found")

    if destination in ("jira", "both"):
        print("   Searching Jira issues...")
        jira_similar = check_jira(bug_description)
        all_similar.extend(jira_similar)
        if not jira_similar:
            print("   ✅ No similar Jira issues found")

    if not all_similar:
        return True

    return display_and_confirm(all_similar, destination)


# ── Standalone entry point ────────────────────────────────────────────────────

def main():
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    if len(sys.argv) < 2:
        print("Usage: python src/regression_detector.py \"bug description\"")
        print("       python src/regression_detector.py \"bug description\" github")
        print("       python src/regression_detector.py \"bug description\" jira")
        sys.exit(1)

    bug_description = sys.argv[1]
    destination     = sys.argv[2] if len(sys.argv) > 2 else "both"

    print(f"\n🔎 Checking for similar bugs: \"{bug_description}\"")
    proceed = run_regression_check(bug_description, destination)

    if proceed:
        print("\n✅ No blocking duplicates found — safe to create new issue.")
    else:
        print("\n🚫 Upload cancelled.")


if __name__ == "__main__":
    main()