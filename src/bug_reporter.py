"""
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
    5. Runs an automated quality gate to check for completeness, severity/priority detection, and RAG confidence
    6. Saves bug_report.md to project root
    7. Asks: GitHub / Jira / Both / Skip
"""

import sys
import os
import re
import argparse
import json
from pathlib import Path
from datetime import datetime

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from groq import Groq

# ── Config  ───────────────────────────────────────────────────────────────────

DB_DIR        = Path("db")
TEMPLATE_PATH = Path("bug_report_template.md")
OUTPUT_PATH   = Path("bug_report.md")
EMBED_MODEL   = "all-MiniLM-L6-v2"   
TOP_K         = 6
GROQ_MODEL    = "meta-llama/llama-4-scout-17b-16e-instruct"
PROMPT_CONFIG_PATH = Path("prompts") / "prompt_config.json"


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


# ── Prompt loading ───────────────────────────────────────────────────────────
def load_prompt(bug_type: str) -> tuple[str, str]:
    """
    Load system prompt from versioned file.
    Returns (prompt_text, version_string).
    """
    if not PROMPT_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Prompt config not found at {PROMPT_CONFIG_PATH}\n"
            "Make sure prompts/prompt_config.json exists."
        )

    config  = json.loads(PROMPT_CONFIG_PATH.read_text())
    version = config["active_version"]
    path    = Path(config["versions"][version][bug_type])

    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    prompt_text = path.read_text(encoding="utf-8").strip()
    print(f"📄 Prompt version  : {version} ({path.name})")
    return prompt_text, version

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

def call_groq(
    bug_description: str,
    context: str,
    template: str,
    bug_type: str,
    system_prompt: str,      
) -> str:
    """Send bug description + retrieved context to Groq → get filled template."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY not set.\n"
            "Add it to your .env file:  GROQ_API_KEY=gsk_..."
        )

    client = Groq(api_key=api_key)
    label  = "Frontend" if bug_type == "frontend" else "Backend"

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


QUALITY_THRESHOLD = 0.70   # minimum score to auto-pass

def run_quality_gate(report: str, sources: list[dict], bug_type: str) -> tuple[float, bool]:
    """
    Run automated quality checks on generated report.
    Returns (score, passed).
    """
    checks = {}

    # 1. Template completeness
    required = [
        "Summary", "Environment", "Steps to Reproduce",
        "Expected Behavior", "Actual Behavior",
        "Affected Component", "Severity", "Priority"
    ]
    present = sum(1 for s in required
                  if re.search(s, report, re.IGNORECASE))
    checks["completeness"] = round(present / len(required), 2)

    # 2. Severity detected
    sev_match = re.search(
        r"Severity[^:]*:\s*(Critical|High|Medium|Low)", report, re.IGNORECASE
    )
    checks["severity"] = 1.0 if sev_match else 0.0

    # 3. Priority detected
    pri_match = re.search(
        r"Priority[^:]*:\s*(P[0-3])", report, re.IGNORECASE
    )
    checks["priority"] = 1.0 if pri_match else 0.0

    # 4. RAG confidence
    top_score = sources[0]["score"] if sources else 999
    if top_score < 1.0:
        checks["rag_confidence"] = 1.0
    elif top_score < 1.4:
        checks["rag_confidence"] = 0.5
    else:
        checks["rag_confidence"] = 0.0

    # 5. Title quality
    title_match = re.search(r"##\s+\[(FE|BE)\]\s+\S+", report)
    checks["title"] = 1.0 if title_match else 0.0

    # Weighted score
    score = round(
        checks["completeness"]   * 0.35 +
        checks["severity"]       * 0.20 +
        checks["priority"]       * 0.20 +
        checks["rag_confidence"] * 0.15 +
        checks["title"]          * 0.10,
        3
    )
    passed = score >= QUALITY_THRESHOLD

    # Print gate results
    print(f"\n📊 Quality Gate")
    print(f"   Template complete  : {'✅' if checks['completeness'] >= 0.8 else '⚠️ '} "
          f"{round(checks['completeness']*100)}%")
    print(f"   Severity detected  : {'✅' if checks['severity'] else '❌'} "
          f"{sev_match.group(1).lower() if sev_match else 'not found'}")
    print(f"   Priority detected  : {'✅' if checks['priority'] else '❌'} "
          f"{pri_match.group(1).upper() if pri_match else 'not found'}")
    print(f"   RAG confidence     : {'✅' if checks['rag_confidence']==1.0 else '⚠️ ' if checks['rag_confidence']==0.5 else '❌'} "
          f"{'HIGH' if top_score < 1.0 else 'MEDIUM' if top_score < 1.4 else 'LOW'}")
    print(f"   Title quality      : {'✅' if checks['title'] else '❌'}")
    print(f"   {'─'*35}")
    print(f"   Quality Score      : {score} / 1.00  "
          f"{'✅ PASS' if passed else '❌ BELOW THRESHOLD'}")

    if not passed:
        print(f"\n   ⚠️  Score below {QUALITY_THRESHOLD} threshold.")
        print(f"   Tips: add more context to your description,")
        print(f"         or add more docs to data/ and re-index.")

    return score, passed

# ── Logging ────────────────────────────────────────────────────────────

def log_retrieval(
    bug_description: str,
    report_type: str,
    sources: list[dict],
    confidence: str, 
    prompt_version: str,      
) -> None:
    """Append one retrieval log entry to logs/retrieval_log.jsonl."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    top_score = sources[0]["score"] if sources else None

    entry = {
        "timestamp":       datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "bug_description": bug_description,
        "report_type":     report_type,
        "prompt_version":  prompt_version,
        "chunks_retrieved": [
            {"file": s["filename"], "score": s["score"]}
            for s in sources
        ],
        "top_chunk_score": top_score,
        "confidence":      confidence,        # ← add this
        "total_chunks":    len(sources),
        "groq_model":      GROQ_MODEL,
    }

    log_path = log_dir / "retrieval_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    print(f"📝 Retrieval logged → {log_path}")


def calculate_confidence(sources: list[dict]) -> tuple[str, str]:
    """
    Calculate RAG confidence based on top chunk similarity score.
    Lower score = more similar in Chroma (cosine distance).
    Returns (confidence_level, emoji_label).
    """
    if not sources:
        return "LOW", "❌"

    top_score = sources[0]["score"]

    if top_score < 1.0:
        return "HIGH", "✅"
    elif top_score < 1.4:
        return "MEDIUM", "⚠️ "
    else:
        return "LOW", "❌"


# ── Confidence Reporting ──────────────────────────────────────────────────────

def print_confidence_report(sources: list[dict]) -> str:
    """Print confidence summary and return confidence level."""
    confidence, emoji = calculate_confidence(sources)

    # Count files
    file_counts: dict[str, int] = {}
    for s in sources:
        file_counts[s["filename"]] = file_counts.get(s["filename"], 0) + 1
    files_summary = ", ".join(
        f"{fname} ({count})" for fname, count in file_counts.items()
    )

    print(f"\n{emoji} RAG Confidence  : {confidence}")
    print(f"📊 Top chunk score : {sources[0]['score']}")
    print(f"📁 Files matched   : {files_summary}")

    if confidence == "LOW":
        print("   ⚠️  Weak context match — consider adding more docs to data/")
    elif confidence == "MEDIUM":
        print("   ℹ️  Partial match — review the report before uploading")

    return confidence

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

    template                = load_template(args.type)
    system_prompt, version  = load_prompt(args.type)
    context, sources        = retrieve_context(args.description)
    report                  = call_groq(args.description, context, template, args.type, system_prompt)
    save_report(report, sources, args.description)
    confidence              = print_confidence_report(sources)
    log_retrieval(args.description, args.type, sources, confidence, version)
    
    title    = extract_title(report)
    severity = extract_severity(report)
    priority = extract_priority(report)

    print(f"\n📝 Title    : {title}")
    print(f"🔴 Severity : {severity}")
    print(f"🎯 Priority : {priority}")

    # ── Quality gate ──
    quality_score, passed = run_quality_gate(report, sources, args.type)

    if not passed:
        proceed = input("\n⚠️  Proceed anyway? (y/n): ").strip().lower()
        if proceed != "y":
            print(f"💾 Report saved locally for review: {OUTPUT_PATH}")
            return

    handle_upload(title, report, severity, priority)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    main()