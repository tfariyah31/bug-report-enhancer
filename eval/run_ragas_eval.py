"""
Evaluates bug report quality using RAGAS 0.4 metrics.
Supports multiple LLM providers — switch via .env, no code changes needed.

Provider setup in .env:
    RAGAS_EVAL_PROVIDER=openai    # or: groq, gemini

Usage:
    python eval/run_ragas_eval.py
"""

import os
import json
import time
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
from datetime import datetime
from typing import List

from dotenv import load_dotenv
load_dotenv()

from ragas.embeddings import BaseRagasEmbeddings
from ragas.metrics import Faithfulness, AnswerRelevancy, ContextPrecision
from ragas.dataset_schema import SingleTurnSample

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from groq import Groq
from sentence_transformers import SentenceTransformer
import asyncio

# ── Config ────────────────────────────────────────────────────────────────────

DB_DIR           = Path("db")
DATASET_PATH     = Path("eval") / "test_dataset.json"
RESULTS_PATH     = Path("eval") / "results" / "ragas_report.json"
EMBED_MODEL      = "all-MiniLM-L6-v2"
TOP_K            = 6
GROQ_GEN_MODEL   = "meta-llama/llama-4-scout-17b-16e-instruct"
GENERATION_DELAY = 4.0
EVAL_PROVIDER    = os.getenv("RAGAS_EVAL_PROVIDER", "openai").lower()
EVAL_DELAY       = 3.0


# ── Provider factory ──────────────────────────────────────────────────────────

def get_evaluator_llm():
    print(f"🔌 Eval provider     : {EVAL_PROVIDER.upper()}")

    if EVAL_PROVIDER == "groq":
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
        api_key = os.getenv("GROQ_API_KEY")
        model   = os.getenv("GROQ_EVAL_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY not set in .env")
        client = AsyncOpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        print(f"   Model             : {model}")
        return llm_factory(model, provider="openai", client=client)

    elif EVAL_PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        from ragas.llms import LangchainLLMWrapper
        api_key = os.getenv("GEMINI_API_KEY")
        model   = os.getenv("GEMINI_EVAL_MODEL", "gemini-2.5-flash")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY not set in .env")
        llm = ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0.1)
        print(f"   Model             : {model}")
        return LangchainLLMWrapper(llm)

    elif EVAL_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        from ragas.llms import LangchainLLMWrapper
        api_key = os.getenv("OPENAI_API_KEY")
        model   = os.getenv("OPENAI_EVAL_MODEL", "gpt-4o-mini")
        if not api_key:
            raise EnvironmentError("OPENAI_API_KEY not set in .env")
        llm = ChatOpenAI(model=model, api_key=api_key, temperature=0.1)
        print(f"   Model             : {model}")
        return LangchainLLMWrapper(llm)

    else:
        raise ValueError(
            f"Unknown RAGAS_EVAL_PROVIDER: '{EVAL_PROVIDER}'\n"
            "Valid options: groq, gemini, openai"
        )


# ── Local embeddings ──────────────────────────────────────────────────────────

class LocalEmbeddings(BaseRagasEmbeddings):
    """Local sentence-transformers — no API calls, no rate limits."""
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def embed_query(self, text: str) -> List[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()

    async def aembed_query(self, text: str) -> List[float]:
        return self.embed_query(text)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.embed_documents(texts)


# ── RAG + generation ──────────────────────────────────────────────────────────

def setup_rag() -> Chroma:
    print("🔍 Loading Chroma DB...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    return Chroma(persist_directory=str(DB_DIR), embedding_function=embeddings)


def retrieve_context(db: Chroma, bug_description: str) -> list[str]:
    results = db.similarity_search(bug_description, k=TOP_K)
    return [doc.page_content for doc in results]


def generate_report(bug_description: str, context: list[str]) -> str:
    """Always uses Groq for generation — fast and cheap."""
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    context_str = "\n\n---\n\n".join(context)
    prompt = f"""You are a QA engineer. Using ONLY the context below, \
write a detailed bug report.

Bug: "{bug_description}"

Context:
{context_str}

Include:
1. Expected behavior per the documentation
2. Actual incorrect behavior
3. Affected component or endpoint
4. Severity with reasoning

Base every statement strictly on the provided context."""

    response = groq_client.chat.completions.create(
        model=GROQ_GEN_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=400,
    )
    return response.choices[0].message.content.strip()


def build_samples(dataset: list[dict], db: Chroma) -> list[SingleTurnSample]:
    samples = []
    print(f"\n🤖 Generating reports ({len(dataset)} test cases)...")
    print(f"   Model   : {GROQ_GEN_MODEL}")
    print(f"   Delay   : {GENERATION_DELAY}s between calls\n")

    for i, tc in enumerate(dataset):
        print(f"   {tc['id']}: {tc['bug_description'][:55]}...")
        context = retrieve_context(db, tc["bug_description"])
        answer  = generate_report(tc["bug_description"], context)
        samples.append(SingleTurnSample(
            user_input=tc["bug_description"],
            retrieved_contexts=context,
            response=answer,
            reference=tc["ground_truth"],
        ))
        if i < len(dataset) - 1:
            time.sleep(GENERATION_DELAY)

    return samples


# ── Manual scoring ────────────────────────────────────────────────────────────

async def score_one(
    sample: SingleTurnSample,
    metric,
    evaluator_embeddings,
) -> float | None:
    try:
        if hasattr(metric, "embeddings"):
            metric.embeddings = evaluator_embeddings
        result = await metric.single_turn_ascore(sample)
        return round(float(result), 3)
    except Exception as e:
        print(f"      ⚠️  {metric.name} error: {str(e)[:80]}")
        return None


def run_evaluation(
    samples: list[SingleTurnSample],
    dataset: list[dict],
    evaluator_llm,
    evaluator_embeddings,
) -> list[dict]:
    """Score each sample individually — no parallel jobs, no timeouts."""
    metrics = [
        Faithfulness(),
        AnswerRelevancy(embeddings=evaluator_embeddings),
        ContextPrecision(),
    ]

    for metric in metrics:
        metric.llm = evaluator_llm

    total_calls = len(samples) * len(metrics)
    print(f"\n📊 Scoring {len(samples)} samples × {len(metrics)} metrics = {total_calls} calls")
    print(f"   Provider : {EVAL_PROVIDER.upper()}")
    print(f"   Delay    : {EVAL_DELAY}s between calls\n")

    results = []
    call_count = 0

    for i, sample in enumerate(samples):
        tc_id = dataset[i]["id"] if i < len(dataset) else f"TC{i+1:03d}"
        print(f"   [{i+1}/{len(samples)}] Scoring {tc_id}...")

        scores = {}
        for metric in metrics:
            score = asyncio.run(score_one(sample, metric, evaluator_embeddings))
            scores[metric.name] = score
            call_count += 1
            print(f"      {metric.name:25s}: {score}")
            if call_count < total_calls:
                time.sleep(EVAL_DELAY)

        # All 3 metrics saved consistently
        results.append({
            "id":                tc_id,
            "bug_description":   dataset[i].get("bug_description", ""),
            "faithfulness":      scores.get("faithfulness"),
            "answer_relevancy":  scores.get("answer_relevancy"),
            "context_precision": scores.get("context_precision"),
        })

    return results


# ── Print + save ──────────────────────────────────────────────────────────────

def print_and_save(results: list[dict]) -> dict:
    print("\n" + "═" * 70)
    print(f"{'RAGAS EVALUATION RESULTS':^70}")
    print("─" * 70)

    for r in results:
        def fmt(v):
            return f"{v:.3f}" if v is not None else " nan "
        print(f"  {r['id']}  "
              f"faith:{fmt(r['faithfulness'])}  "
              f"relevancy:{fmt(r['answer_relevancy'])}  "
              f"precision:{fmt(r['context_precision'])}")

    def safe_mean(key):
        vals = [r[key] for r in results if r[key] is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    faith_avg = safe_mean("faithfulness")
    relev_avg = safe_mean("answer_relevancy")
    prec_avg  = safe_mean("context_precision")
    valid     = [v for v in [faith_avg, relev_avg, prec_avg] if v is not None]
    overall   = round(sum(valid) / len(valid), 3) if valid else None

    print("─" * 70)
    print(f"  AVERAGES")
    print(f"    Faithfulness       : {faith_avg}")
    print(f"    Answer Relevancy   : {relev_avg}")
    print(f"    Context Precision  : {prec_avg}")
    print(f"    Overall Score      : {overall}")
    print("═" * 70)

    averages = {
        "faithfulness":      faith_avg,
        "answer_relevancy":  relev_avg,
        "context_precision": prec_avg,
        "overall":           overall,
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "timestamp":     datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "eval_provider": EVAL_PROVIDER,
        "groq_model":    GROQ_GEN_MODEL,
        "embed_model":   EMBED_MODEL,
        "averages":      averages,
        "per_case":      results,
    }
    RESULTS_PATH.write_text(json.dumps(output, indent=2))
    print(f"\n  Results saved → {RESULTS_PATH}")

    return averages


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not DB_DIR.exists():
        print("❌ Chroma DB not found. Run build_index.py first.")
        return

    dataset = json.loads(DATASET_PATH.read_text())

    print("=" * 70)
    print(f"{'BUG REPORT ENHANCER — RAGAS EVALUATION':^70}")
    print("=" * 70)
    print(f"📋 Test cases        : {len(dataset)}")

    evaluator_llm        = get_evaluator_llm()
    evaluator_embeddings = LocalEmbeddings(EMBED_MODEL)
    print(f"🧮 Embeddings        : {EMBED_MODEL} (local)\n")

    db      = setup_rag()
    samples = build_samples(dataset, db)
    results = run_evaluation(samples, dataset, evaluator_llm, evaluator_embeddings)
    print_and_save(results)

    print("\nDone ✅\n")


if __name__ == "__main__":
    main()