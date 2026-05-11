"""
Evaluates the quality of generated bug reports by checking:
  - Template completeness  (are all fields filled vs left as placeholders?)
  - Severity accuracy      (does inferred severity match expected?)
  - Priority accuracy      (does P0/P1/P2/P3 match expected?)
  - Component accuracy     (does affected component match expected?)
  - Title quality          (does title have [FE]/[BE] prefix?)

No API calls — purely rule-based parsing.

Usage:
    python eval/run_report_eval.py
"""

import json
import re
import time
import sys
from pathlib import Path
from datetime import datetime

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from groq import Groq

# ── Config ────────────────────────────────────────────────────────────────────

DB_DIR          = Path("db")
DATASET_PATH    = Path("eval") / "test_dataset.json"
TEMPLATE_PATH   = Path("bug_report_template.md")
RESULTS_PATH    = Path("eval") / "results" / "report_eval_report.json"
PROMPT_CONFIG   = Path("prompts") / "prompt_config.json"
EMBED_MODEL     = "all-MiniLM-L6-v2"
TOP_K           = 6
GROQ_MODEL      = "meta-llama/llama-4-scout-17b-16e-instruct"
GENERATION_DELAY = 4.0


# ── Template loading (matches bug_reporter.py exactly) ────────────────────────

def load_template(bug_type: str) -> str:
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
    return match.group(1).strip() if match else full_text


def load_prompt(bug_type: str) -> str:
    config  = json.loads(PROMPT_CONFIG.read_text())
    version = config["active_version"]
    path    = Path(config["versions"][version][bug_type])
    return path.read_text(encoding="utf-8").strip()


# ── RAG + generation (mirrors bug_reporter.py) ────────────────────────────────

def setup_rag() -> Chroma:
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    return Chroma(persist_directory=str(DB_DIR), embedding_function=embeddings)


def retrieve_context(db: Chroma, bug_description: str) -> str:
    results = db.similarity_search(bug_description, k=TOP_K)
    parts   = []
    for i, doc in enumerate(results, 1):
        filename = doc.metadata.get("filename",
                   Path(doc.metadata.get("source", "unknown")).name)
        parts.append(f"[Chunk {i} | File: {filename}]\n{doc.page_content}")
    return "\n\n---\n\n".join(parts)


def generate_report(
    bug_description: str,
    context: str,
    template: str,
    system_prompt: str,
    bug_type: str,
) -> str:
    import os
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    label       = "Frontend" if bug_type == "frontend" else "Backend"

    user_prompt = f"""Bug reported: "{bug_description}"

Relevant context retrieved from project files:
{context}

Fill out this {label} bug report template:

{template}"""

    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=2000,
    )
    return response.choices[0].message.content.strip()


# ── Evaluation checks ─────────────────────────────────────────────────────────

# Placeholder patterns that indicate an UNFILLED field
PLACEHOLDER_PATTERNS = [
    r"<!--.*?-->",                          # HTML comments
    r"\[e\.g\.[^\]]*\]",                   # [e.g. something]
    r"\[Your [^\]]*\]",                    # [Your Name/Role]
    r"\[If applicable[^\]]*\]",            # [If applicable...]
    r"\[Short[^\]]*\]",                    # [Short description]
    r"\[Paste[^\]]*\]",                    # [Paste Image...]
    r"\[Explain[^\]]*\]",                  # [Explain the...]
    r"\[What[^\]]*\]",                     # [What should...]
    r"\[Attach[^\]]*\]",                   # [Attach...]
    r"\[Link[^\]]*\]",                     # [Link to...]
    r"N/A\s*$",                            # bare N/A at end of line
]

# Required sections every report must have
REQUIRED_SECTIONS_FRONTEND = [
    "Summary",
    "Environment",
    "Steps to Reproduce",
    "Expected Behavior",
    "Actual Behavior",
    "Affected Component",
    "LLM Enhancement Notes",
    "Root Cause Hypothesis",
    "Severity",
    "Priority",
]

REQUIRED_SECTIONS_BACKEND = [
    "Summary",
    "Environment",
    "Steps to Reproduce",
    "Expected Behavior",
    "Actual Behavior",
    "Affected Component",
    "LLM Enhancement Notes",
    "Root Cause Hypothesis",
    "Severity",
    "Priority",
]


def check_template_completeness(report: str, bug_type: str) -> dict:
    """
    Count unfilled placeholder fields vs total required sections.
    Returns completeness percentage and list of unfilled fields.
    """
    required = (REQUIRED_SECTIONS_FRONTEND
                if bug_type == "frontend"
                else REQUIRED_SECTIONS_BACKEND)

    # Check which required sections exist
    present = []
    missing = []
    for section in required:
        if re.search(section, report, re.IGNORECASE):
            present.append(section)
        else:
            missing.append(section)

    # Count placeholder lines (unfilled fields)
    unfilled_count = 0
    unfilled_examples = []
    for line in report.splitlines():
        for pattern in PLACEHOLDER_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                unfilled_count += 1
                if len(unfilled_examples) < 3:
                    unfilled_examples.append(line.strip()[:60])
                break

    sections_pct   = round((len(present) / len(required)) * 100, 1)
    # Score: sections present weighted 70%, unfilled penalty weighted 30%
    unfilled_penalty = min(unfilled_count * 2, 30)
    completeness_pct = max(0, round(sections_pct - unfilled_penalty, 1))

    return {
        "sections_present":    len(present),
        "sections_total":      len(required),
        "sections_pct":        sections_pct,
        "unfilled_fields":     unfilled_count,
        "unfilled_examples":   unfilled_examples,
        "completeness_pct":    completeness_pct,
        "missing_sections":    missing,
    }


def check_severity(report: str, expected: str) -> dict:
    """Extract severity from report and compare to expected."""
    match = re.search(
        r"(?:Severity|severity)[^:]*:\s*<?!?-{0,3}\s*(Critical|High|Medium|Low)",
        report, re.IGNORECASE
    )
    extracted = match.group(1).lower() if match else None
    correct   = (extracted == expected.lower()) if extracted else False

    return {
        "extracted": extracted,
        "expected":  expected.lower(),
        "correct":   correct,
    }


def check_priority(report: str, expected: str) -> dict:
    """Extract priority from report and compare to expected."""
    match = re.search(
        r"(?:Priority|priority)[^:]*:\s*<?!?-{0,3}\s*(P[0-3])",
        report, re.IGNORECASE
    )
    extracted = match.group(1).upper() if match else None
    correct   = (extracted == expected.upper()) if extracted else False

    return {
        "extracted": extracted,
        "expected":  expected.upper(),
        "correct":   correct,
    }


def check_component(report: str, expected: str) -> dict:
    """
    Fuzzy check — does the report mention the expected component?
    Splits expected into words and checks if most appear in the report.
    """
    expected_words = [w.lower() for w in expected.split()
                      if len(w) > 2]  # skip short words like "to", "or"
    if not expected_words:
        return {"found": False, "expected": expected, "match_pct": 0}

    report_lower  = report.lower()
    matched_words = [w for w in expected_words if w in report_lower]
    match_pct     = round((len(matched_words) / len(expected_words)) * 100, 1)
    found         = match_pct >= 50  # at least 50% of words present

    return {
        "found":      found,
        "expected":   expected,
        "match_pct":  match_pct,
    }


def check_title(report: str, bug_type: str) -> dict:
    """Check if title has correct [FE] or [BE] prefix."""
    prefix   = "[FE]" if bug_type == "frontend" else "[BE]"
    match    = re.search(r"##\s+\[(FE|BE)\]\s+(.+)", report)
    has_prefix  = False
    has_content = False
    title_text  = None

    if match:
        found_prefix = f"[{match.group(1)}]"
        title_text   = match.group(2).strip()
        has_prefix   = (found_prefix == prefix)
        has_content  = len(title_text) > 10  

    return {
        "has_correct_prefix": has_prefix,
        "has_content":        has_content,
        "title":              title_text,
        "expected_prefix":    prefix,
    }


# ── Score aggregation ─────────────────────────────────────────────────────────

def score_report(report: str, tc: dict) -> dict:
    """Run all checks on one generated report."""
    bug_type = tc["type"]

    completeness = check_template_completeness(report, bug_type)
    severity     = check_severity(report, tc["expected_severity"])
    priority     = check_priority(report, tc["expected_priority"])
    component    = check_component(report, tc["expected_component"])
    title        = check_title(report, bug_type)

    # Overall score — weighted
    score = round((
        (completeness["completeness_pct"] / 100) * 0.30 +  # 30% template
        (1.0 if severity["correct"]  else 0.0)  * 0.25 +  # 25% severity
        (1.0 if priority["correct"]  else 0.0)  * 0.25 +  # 25% priority
        (1.0 if component["found"]   else 0.0)  * 0.15 +  # 15% component
        (1.0 if title["has_correct_prefix"] and
                title["has_content"] else 0.0)  * 0.05    #  5% title
    ), 3)

    return {
        "completeness": completeness,
        "severity":     severity,
        "priority":     priority,
        "component":    component,
        "title":        title,
        "overall_score": score,
    }


# ── Print helpers ─────────────────────────────────────────────────────────────

def tick(val: bool) -> str:
    return "✅" if val else "❌"


def print_results(all_results: list[dict], dataset: list[dict]) -> dict:
    print("\n" + "═" * 70)
    print(f"{'BUG REPORT GENERATION EVALUATION':^70}")
    print("─" * 70)
    print(f"  {'ID':<7} {'Complete':>9} {'Severity':>10} "
          f"{'Priority':>10} {'Component':>11} {'Score':>7}")
    print("─" * 70)

    for r in all_results:
        tc    = next(t for t in dataset if t["id"] == r["id"])
        c     = r["checks"]
        score = r["overall_score"]

        sev_str  = (f"{tick(c['severity']['correct'])} "
                    f"{c['severity']['extracted'] or '???':<8}")
        pri_str  = (f"{tick(c['priority']['correct'])} "
                    f"{c['priority']['extracted'] or '???':<4}")
        comp_str = f"{tick(c['component']['found'])} {c['component']['match_pct']}%"
        comp_str = f"{tick(c['completeness']['completeness_pct'] >= 70)} "
                   

        print(f"  {r['id']:<7} "
              f"{c['completeness']['completeness_pct']:>7.1f}%  "
              f"  {tick(c['severity']['correct'])} {(c['severity']['extracted'] or '???'):<9}"
              f"  {tick(c['priority']['correct'])} {(c['priority']['extracted'] or '???'):<5}"
              f"  {tick(c['component']['found'])} {c['component']['match_pct']:>4.0f}%"
              f"  {score:.3f}")

    # Summary
    def avg(key_fn):
        vals = [key_fn(r) for r in all_results]
        return round(sum(vals) / len(vals), 3)

    avg_completeness = avg(lambda r: r["checks"]["completeness"]["completeness_pct"])
    sev_correct      = sum(1 for r in all_results if r["checks"]["severity"]["correct"])
    pri_correct      = sum(1 for r in all_results if r["checks"]["priority"]["correct"])
    comp_correct     = sum(1 for r in all_results if r["checks"]["component"]["found"])
    title_correct    = sum(1 for r in all_results
                           if r["checks"]["title"]["has_correct_prefix"]
                           and r["checks"]["title"]["has_content"])
    avg_score        = avg(lambda r: r["overall_score"])
    total            = len(all_results)

    print("─" * 70)
    print(f"\n  {'SUMMARY':}")
    print(f"    Template Completeness : {avg_completeness:.1f}%")
    print(f"    Severity Accuracy     : {sev_correct}/{total}  "
          f"({round(sev_correct/total*100, 1)}%)")
    print(f"    Priority Accuracy     : {pri_correct}/{total}  "
          f"({round(pri_correct/total*100, 1)}%)")
    print(f"    Component Accuracy    : {comp_correct}/{total}  "
          f"({round(comp_correct/total*100, 1)}%)")
    print(f"    Title Quality         : {title_correct}/{total}  "
          f"({round(title_correct/total*100, 1)}%)")
    print(f"    Overall Score         : {avg_score:.3f} / 1.000")
    print("═" * 70)

    return {
        "avg_completeness_pct": avg_completeness,
        "severity_accuracy":    round(sev_correct / total * 100, 1),
        "priority_accuracy":    round(pri_correct / total * 100, 1),
        "component_accuracy":   round(comp_correct / total * 100, 1),
        "title_accuracy":       round(title_correct / total * 100, 1),
        "overall_score":        avg_score,
    }


# ── Save ──────────────────────────────────────────────────────────────────────

def save_results(all_results: list[dict], summary: dict) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "timestamp":  datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "groq_model": GROQ_MODEL,
        "summary":    summary,
        "results":    all_results,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2))
    print(f"\n  Results saved → {RESULTS_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import os
    from dotenv import load_dotenv
    load_dotenv()

    if not DB_DIR.exists():
        print("❌ Chroma DB not found. Run build_index.py first.")
        sys.exit(1)

    dataset = json.loads(DATASET_PATH.read_text())
    print("=" * 70)
    print(f"{'BUG REPORT ENHANCER — REPORT GENERATION EVAL':^70}")
    print("=" * 70)
    print(f"📋 Test cases  : {len(dataset)}")
    print(f"🤖 Model       : {GROQ_MODEL}")
    print(f"📏 Checks      : completeness, severity, priority, component, title\n")

    db = setup_rag()

    all_results = []

    for i, tc in enumerate(dataset):
        print(f"  [{i+1}/{len(dataset)}] Generating report for {tc['id']}...")

        template      = load_template(tc["type"])
        system_prompt = load_prompt(tc["type"])
        context       = retrieve_context(db, tc["bug_description"])
        report        = generate_report(
            tc["bug_description"], context, template, system_prompt, tc["type"]
        )

        checks = score_report(report, tc)

        # Print quick summary per test case
        c = checks
        print(f"        complete:{c['completeness']['completeness_pct']}%  "
              f"sev:{tick(c['severity']['correct'])}({c['severity']['extracted'] or '?'})  "
              f"pri:{tick(c['priority']['correct'])}({c['priority']['extracted'] or '?'})  "
              f"comp:{tick(c['component']['found'])}  "
              f"score:{c['overall_score']}")

        all_results.append({
            "id":            tc["id"],
            "bug_description": tc["bug_description"],
            "type":          tc["type"],
            "overall_score": checks["overall_score"],
            "checks":        checks,
        })

        if i < len(dataset) - 1:
            time.sleep(GENERATION_DELAY)

    summary = print_results(all_results, dataset)
    save_results(all_results, summary)
    print("\nDone ✅\n")


if __name__ == "__main__":
    main()