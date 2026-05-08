"""
bug_reporter.py

Usage:
    python src/bug_reporter.py "User first name update not working from user profile"
    python src/bug_reporter.py "POST /api/orders returns 500" --type backend

Options:
    --type frontend   (default) Generate a Frontend bug report
    --type backend    Generate a Backend bug report

What it does:
    1. Loads your bug_report_template.md from data/
    2. Queries the existing Chroma DB for relevant chunks (PRD, Jira stories, feature files)
    3. Sends those chunks + bug description to Groq free API (Llama 4 Scout)
    4. Fills the template including the LLM Enhancement Notes section automatically
    5. Saves bug_report.md to project root
    6. Asks: GitHub / Jira / Both / Skip
"""

import sys
import os
import re
import argparse
from pathlib import Path
from datetime import datetime

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from groq import Groq

# ── Config (matched exactly to your build_index.py) ───────────────────────────

DB_DIR        = Path("db")
TEMPLATE_PATH = Path("bug_report_template.md")
OUTPUT_PATH   = Path("bug_report.md")
EMBED_MODEL   = "all-MiniLM-L6-v2"   # same as your build_index.py
TOP_K         = 6
GROQ_MODEL    = "meta-llama/llama-4-scout-17b-16e-instruct"


# ── Template loading ──────────────────────────────────────────────────────────

def load_template(bug_type: str) -> str:
    """
    Extract Frontend or Backend section from bug_report_template.md.
    Strips the outer ```markdown ... ``` fences that wrap each section.
    """
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(
            f"Bug template not found at {TEMPLATE_PATH}\n"
            "Make sure bug_report_template.md is in your data/ folder."
        )

    full_text = TEMPLATE_PATH.read_text(encoding="utf-8")

    if bug_type == "frontend":
        match = re.search(
            r"## Frontend Bug Report\s*```markdown(.*?)```",
            full_text, re.DOTALL | re.IGNORECASE
        )
    else:
        match = re.search(
            r"##\s*⚙️\s*Backend Bug Report\s*```markdown(.*?)```",
            full_text, re.DOTALL | re.IGNORECASE
        )

    if match:
        return match.group(1).strip()

    print("⚠️  Could not isolate template section — using full template.")
    return full_text


# ── RAG retrieval ─────────────────────────────────────────────────────────────

def retrieve_context(bug_description: str) -> tuple[str, list[dict]]:
    """
    Query your Chroma DB (built by build_index.py) for top-K relevant chunks.
    Returns (formatted_context_string, list_of_source_metadata).
    """
    if not DB_DIR.exists():
        raise FileNotFoundError(
            f"Chroma DB not found at '{DB_DIR}'.\n"
            "Run:  python src/build_index.py"
        )

    print("🔍 Loading Chroma DB...")
    embedding_function = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    db = Chroma(persist_directory=str(DB_DIR), embedding_function=embedding_function)

    print(f"🔍 Retrieving top {TOP_K} chunks for: \"{bug_description}\"")
    results = db.similarity_search_with_score(bug_description, k=TOP_K)

    context_parts = []
    sources = []

    for i, (doc, score) in enumerate(results, 1):
        filename = doc.metadata.get("filename",
                   Path(doc.metadata.get("source", "unknown")).name)
        page     = doc.metadata.get("page", "N/A")
        context_parts.append(
            f"[Chunk {i} | File: {filename} | Page: {page}]\n{doc.page_content}"
        )
        sources.append({
            "filename": filename,
            "page":     page,
            "score":    round(float(score), 4),
        })
        print(f"   [{i}] {filename}  page:{page}  score:{score:.4f}")

    return "\n\n---\n\n".join(context_parts), sources


# ── Groq API call ─────────────────────────────────────────────────────────────

def call_groq(bug_description: str, context: str, template: str, bug_type: str) -> str:
    """Send bug description + retrieved context to Groq → get filled template."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY not set.\n"
            "Add it to your .env file:  GROQ_API_KEY=gsk_..."
        )

    client = Groq(api_key=api_key)
    label  = "Frontend" if bug_type == "frontend" else "Backend"

    system_prompt = f"""You are a senior QA engineer specialising in {label} bugs.
Your task is to fill in a structured bug report template precisely and professionally.

Rules:
1. Use the retrieved context (PRD, Jira stories, feature files) to populate:
   - Summary, Expected Behavior, Affected Component(s), Related Issues / PRs
   - LLM Enhancement Notes section: Root Cause Hypothesis, Likely Affected Files,
     Suggested Fix Direction, Regression Risk, Severity, Priority
2. For fields you cannot determine (e.g. exact browser version, specific user ID,
   screenshot links), keep the HTML comment placeholder as-is — do NOT invent values.
3. Severity inference:
   Critical = core feature completely broken for all users
   High     = major feature broken, workaround exists
   Medium   = partial issue, most users unaffected
   Low      = cosmetic or minor inconvenience
4. Priority: P0=Critical, P1=High, P2=Medium, P3=Low
5. Keep the EXACT markdown structure and headings. Do not add or remove sections.
6. Return ONLY the filled template — no preamble, no explanation."""

    user_prompt = f"""Bug reported: "{bug_description}"

Relevant context retrieved from project files:
{context}

Fill out this {label} bug report template:

{template}"""

    print(f"\n🤖 Calling Groq API ({GROQ_MODEL})...")
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=2000,
    )
    return response.choices[0].message.content.strip()


# ── Metadata extraction ───────────────────────────────────────────────────────

def extract_title(report: str) -> str:
    """Extract ## [FE] or ## [BE] title line."""
    match = re.search(r"##\s+\[(FE|BE)\]\s+(.+)", report)
    if match:
        return f"[{match.group(1)}] {match.group(2).strip()}"
    for line in report.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line
    return "Bug Report"


def extract_severity(report: str) -> str:
    match = re.search(
        r"\*\*Severity\*\*:?.*?<!--.*?-->\s*(Critical|High|Medium|Low)",
        report, re.IGNORECASE | re.DOTALL
    )
    if not match:
        match = re.search(r"Severity[^:]*:\s*(Critical|High|Medium|Low)",
                          report, re.IGNORECASE)
    return match.group(1).lower() if match else "medium"


def extract_priority(report: str) -> str:
    match = re.search(
        r"\*\*Priority\*\*:?.*?<!--.*?-->\s*(P[0-3])",
        report, re.IGNORECASE | re.DOTALL
    )
    if not match:
        match = re.search(r"Priority[^:]*:\s*(P[0-3])", report, re.IGNORECASE)
    return match.group(1).upper() if match else "P2"


# ── Save report ───────────────────────────────────────────────────────────────

def save_report(report: str, sources: list[dict], bug_description: str) -> Path:
    header = (
        f"<!-- Generated by bug_reporter.py -->\n"
        f"<!-- Input: {bug_description} -->\n"
        f"<!-- Date: {datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n"
    )

    source_section = "\n\n---\n\n## 🔍 RAG Sources Used\n\n"
    source_section += "| File | Page | Similarity Score |\n"
    source_section += "|------|------|------------------|\n"
    for s in sources:
        source_section += f"| `{s['filename']}` | {s['page']} | {s['score']} |\n"

    OUTPUT_PATH.write_text(header + report + source_section, encoding="utf-8")
    print(f"\n✅ Bug report saved → {OUTPUT_PATH.resolve()}")
    return OUTPUT_PATH


# ── Upload handler ────────────────────────────────────────────────────────────

def handle_upload(title: str, report: str, severity: str, priority: str = "P2"):
    print("\n" + "─" * 50)
    print("Where would you like to upload this bug report?")
    print("  [1] GitHub Issue only")
    print("  [2] Jira Ticket only")
    print("  [3] Both GitHub + Jira")
    print("  [4] Skip — keep locally only")
    print("─" * 50)
    choice = input("Enter choice (1/2/3/4): ").strip()

    if choice in ("1", "3"):
        try:
            from github_uploader import create_github_issue
            url = create_github_issue(title=title, body=report, severity=severity, priority=priority)
            if url:
                print(f"✅ GitHub issue created: {url}")
        except ImportError:
            print("❌ github_uploader.py not found in src/")
        except Exception as e:
            print(f"❌ GitHub upload failed: {e}")

    if choice in ("2", "3"):
        try:
            from jira_uploader import create_jira_issue
            url = create_jira_issue(title=title, body=report, severity=severity)
            if url:
                print(f"✅ Jira ticket created: {url}")
        except ImportError:
            print("❌ jira_uploader.py not found in src/")
        except Exception as e:
            print(f"❌ Jira upload failed: {e}")

    if choice == "4":
        print(f"💾 Saved locally: {OUTPUT_PATH.resolve()}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a structured bug report using RAG + Groq"
    )
    parser.add_argument("description", help="Plain-English bug description")
    parser.add_argument(
        "--type", choices=["frontend", "backend"], default="frontend",
        help="Bug report type (default: frontend)"
    )
    args = parser.parse_args()

    print(f"\n📋 Bug description : {args.description}")
    print(f"📂 Report type     : {args.type}\n")

    template          = load_template(args.type)
    context, sources  = retrieve_context(args.description)
    report            = call_groq(args.description, context, template, args.type)
    save_report(report, sources, args.description)

    title    = extract_title(report)
    severity = extract_severity(report)
    priority = extract_priority(report)

    print(f"\n📝 Title    : {title}")
    print(f"🔴 Severity : {severity}")
    print(f"🎯 Priority : {priority}")

    handle_upload(title, report, severity, priority)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    main()