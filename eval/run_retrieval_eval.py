"""
Evaluates RAG retrieval quality against test dataset.
Measures whether the correct files are being retrieved for each bug.

Usage:
    python eval/run_retrieval_eval.py

Output:
    - Terminal report
    - eval/results/retrieval_report.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# ── Config ────────────────────────────────────────────────────────────────────

DB_DIR       = Path("db")
DATASET_PATH = Path("eval") / "test_dataset.json"
RESULTS_PATH = Path("eval") / "results" / "retrieval_report.json"
EMBED_MODEL  = "all-MiniLM-L6-v2"
TOP_K        = 6

# Confidence thresholds (matching bug_reporter.py)
def get_confidence(score: float) -> str:
    if score < 1.0:
        return "HIGH"
    elif score < 1.4:
        return "MEDIUM"
    return "LOW"


# ── Load resources ────────────────────────────────────────────────────────────

def load_db() -> Chroma:
    if not DB_DIR.exists():
        print(f"❌ Chroma DB not found at '{DB_DIR}'. Run build_index.py first.")
        sys.exit(1)
    print("🔍 Loading Chroma DB...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    return Chroma(persist_directory=str(DB_DIR), embedding_function=embeddings)


def load_dataset() -> list[dict]:
    if not DATASET_PATH.exists():
        print(f"❌ Test dataset not found at {DATASET_PATH}")
        sys.exit(1)
    data = json.loads(DATASET_PATH.read_text())
    print(f"📋 Loaded {len(data)} test cases\n")
    return data


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate_single(db: Chroma, test_case: dict) -> dict:
    """
    Run retrieval for one test case and check if expected file was found.
    Returns a result dict.
    """
    bug_description   = test_case["bug_description"]
    expected_chunks   = test_case["expected_chunks"]   # list of expected filenames

    # Run retrieval
    results = db.similarity_search_with_score(bug_description, k=TOP_K)

    retrieved_files = [
        doc.metadata.get("filename",
        Path(doc.metadata.get("source", "unknown")).name)
        for doc, _ in results
    ]
    scores = [round(float(score), 4) for _, score in results]
    top_score = scores[0] if scores else 999

    # Check if ALL expected files appear in retrieved results
    found    = all(exp in retrieved_files for exp in expected_chunks)
    missing  = [exp for exp in expected_chunks if exp not in retrieved_files]
    confidence = get_confidence(top_score)

    return {
        "id":               test_case["id"],
        "type":             test_case["type"],
        "bug_description":  bug_description,
        "expected_chunks":  expected_chunks,
        "retrieved_files":  list(dict.fromkeys(retrieved_files)),  
        "top_score":        top_score,
        "all_scores":       scores,
        "found":            found,
        "missing":          missing,
        "confidence":       confidence,
    }


def run_evaluation(db: Chroma, dataset: list[dict]) -> list[dict]:
    """Run evaluation on all test cases and return results."""
    results = []
    print("Running retrieval evaluation...")
    print("═" * 60)

    for tc in dataset:
        result = evaluate_single(db, tc)
        results.append(result)

        status = "✅" if result["found"] else "❌"
        files  = ", ".join(result["expected_chunks"])
        print(
            f"{result['id']}  {status}  "
            f"{files:<30}  "
            f"top score: {result['top_score']:.4f}  "
            f"[{result['confidence']}]"
        )
        if not result["found"]:
            print(f"       ⚠️  Missing: {result['missing']}")

    return results


# ── Scoring ───────────────────────────────────────────────────────────────────

def calculate_summary(results: list[dict]) -> dict:
    """Calculate overall metrics from results."""
    total      = len(results)
    passed     = sum(1 for r in results if r["found"])
    failed     = total - passed
    avg_score  = round(sum(r["top_score"] for r in results) / total, 4)
    precision  = round((passed / total) * 100, 1)

    confidence_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in results:
        confidence_counts[r["confidence"]] += 1

    # Per type breakdown
    frontend_results = [r for r in results if r["type"] == "frontend"]
    backend_results  = [r for r in results if r["type"] == "backend"]

    fe_passed = sum(1 for r in frontend_results if r["found"])
    be_passed = sum(1 for r in backend_results  if r["found"])

    return {
        "total":              total,
        "passed":             passed,
        "failed":             failed,
        "precision_pct":      precision,
        "avg_top_score":      avg_score,
        "confidence_counts":  confidence_counts,
        "frontend": {
            "total":  len(frontend_results),
            "passed": fe_passed,
            "pct":    round((fe_passed / len(frontend_results)) * 100, 1) if frontend_results else 0
        },
        "backend": {
            "total":  len(backend_results),
            "passed": be_passed,
            "pct":    round((be_passed / len(backend_results)) * 100, 1) if backend_results else 0
        }
    }


def print_summary(summary: dict) -> None:
    """Print formatted summary to terminal."""
    print("═" * 60)
    print(f"\n{'RETRIEVAL EVALUATION SUMMARY':^60}")
    print("─" * 60)
    print(f"  Total test cases  : {summary['total']}")
    print(f"  Passed            : {summary['passed']} / {summary['total']}")
    print(f"  Precision         : {summary['precision_pct']}%")
    print(f"  Avg top score     : {summary['avg_top_score']}  (lower = better)")
    print(f"\n  By type:")
    print(f"    Frontend  : {summary['frontend']['passed']}/{summary['frontend']['total']}  ({summary['frontend']['pct']}%)")
    print(f"    Backend   : {summary['backend']['passed']}/{summary['backend']['total']}  ({summary['backend']['pct']}%)")
    print(f"\n  Confidence breakdown:")
    cc = summary['confidence_counts']
    print(f"    HIGH    ✅ : {cc['HIGH']}")
    print(f"    MEDIUM  ⚠️  : {cc['MEDIUM']}")
    print(f"    LOW     ❌ : {cc['LOW']}")


# ── Save results ──────────────────────────────────────────────────────────────

def save_results(results: list[dict], summary: dict) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "timestamp":  datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "embed_model": EMBED_MODEL,
        "top_k":       TOP_K,
        "summary":     summary,
        "results":     results,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2))
    print(f"\n  Results saved → {RESULTS_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    db      = load_db()
    dataset = load_dataset()
    results = run_evaluation(db, dataset)
    summary = calculate_summary(results)
    print_summary(summary)
    save_results(results, summary)
    print("\nDone ✅\n")


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    main()