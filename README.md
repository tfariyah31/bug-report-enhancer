AI-powered bug reporting · RAG · RAGAS Evaluation · GitHub · Jira 

# Bug Report Enhancer
An AI-powered bug report automation tool that generates structured, context-aware bug reports from plain language descriptions and uploads them directly to GitHub Issues and Jira. Includes a full evaluation suite measuring RAG retrieval accuracy, LLM output quality (RAGAS), and template generation quality.

---

## How It Works

```
You type a bug description
        ↓
LangChain + Chroma retrieves relevant context
from your feature files and API specs  (local)
        ↓
Groq free API (Llama 4 Scout) fills your
bug report template automatically
        ↓
Choose where to upload:
  → GitHub Issue  (with severity + priority labels)
  → Jira Ticket   (ADF formatted)
  → Both
  → Save locally
```

---

## Features

- Supports **Frontend** and **Backend** bug report templates
- **RAG (Retrieval-Augmented Generation)** — only relevant context is sent to the LLM, not your entire codebase
- Auto-fills **LLM Enhancement Notes**: Root Cause Hypothesis, Likely Affected Files, Suggested Fix, Regression Risk
- Auto-infers **Severity** (Critical / High / Medium / Low) and **Priority** (P0–P3)
- **RAG Confidence Scoring** — flags LOW/MEDIUM/HIGH confidence before upload
- **Quality Gate** — checks template completeness, severity, priority, and title before uploading
- **Retrieval Logging** — every run logged to `logs/retrieval_log.jsonl` with prompt version, confidence, and model
- **Prompt Versioning** — system prompts stored as versioned files, switch without code changes
- **Full Evaluation Suite** — RAG retrieval accuracy, RAGAS LLM quality, and template generation scoring
- Creates GitHub labels automatically if they don't exist
- Converts markdown to **Atlassian Document Format (ADF)** for Jira
- Runs **fully offline** except for Groq API and upload calls
- **100% free** for bug generation — uses Groq free tier (1,000 req/day)
---

## Tech Stack

| Component | Tool |
|---|---|
| Embeddings + Retrieval | LangChain + `all-MiniLM-L6-v2` |
| Vector Store | Chroma (local) |
| LLM Generation | Groq API — Llama 4 Scout (free tier) |
| RAG Evaluation | RAGAS 0.4 |
| Eval LLM | OpenAI `gpt-4o-mini` / Groq / Gemini (switchable via `.env`) |
| GitHub Integration | GitHub REST API v3 |
| Jira Integration | Jira Cloud REST API v3 |
| Local Q&A (optional) | Mistral-7B via llama.cpp + Ollama |
---

## Project Structure

```
bug-report-enhancer/
├── src/
│   ├── build_index.py          # Index data/ files into Chroma DB
│   ├── bug_reporter.py         # Core pipeline — RAG + Groq + upload
│   ├── github_uploader.py      # GitHub Issues API
│   ├── jira_uploader.py        # Jira API with ADF conversion
│   └── rag_chat.py             # Optional local Q&A chat
├── data/                       # Your knowledge files (indexed by RAG)
│   ├── LOGIN_FEATURES.md       # Feature specs
│   └── openapi.json            # API documentation
├── eval/
│   ├── test_dataset.json        # 10 ground truth test cases
│   ├── run_retrieval_eval.py    # Phase 1 — RAG file retrieval accuracy
│   ├── run_ragas_eval.py        # Phase 2 — LLM output quality (RAGAS metrics)
│   └── run_report_eval.py       # Phase 3 — Bug report template quality
│
├── db/                         # Chroma vector store (auto-generated)
├── llm_model/
│   └── mistral/                # Mistral GGUF model (for rag_chat.py)
├── bug_report_template.md      # Bug report template (FE + BE sections)
├── bug_report.md               # Last generated report (auto-generated)
├── .env                        # API keys (never commit this)
├── .env.example                # Template for .env
├── .gitignore
└── requirements.txt
```

---

## Prerequisites

- Python 3.11 (required — torch has no wheels for 3.12+)
- Homebrew (macOS)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/tfariyah31/bug-report-enhancer.git
cd bug-report-enhancer
```

### 2. Install Python 3.11

```bash
brew install python@3.11
```

### 3. Create and activate virtual environment

```bash
python3.11 -m venv venv
source venv/bin/activate
```

### 4. Install dependencies in this order

```bash
# torch must be installed first
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Then everything else
pip install sentence-transformers
pip install langchain langchain-community langchain-chroma langchain-huggingface langchain-text-splitters
pip install chromadb pypdf groq python-dotenv

# Optional — only needed for rag_chat.py (takes 3-5 mins to compile)
pip install llama-cpp-python
```

### 5. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```env
# Groq — https://console.groq.com (free, no credit card)
GROQ_API_KEY=gsk_...

# GitHub — https://github.com/settings/tokens (scope: repo)
GITHUB_TOKEN=ghp_...
GITHUB_REPO=your-username/your-repo
GITHUB_ASSIGNEE=your-github-username   # optional

# Jira — https://id.atlassian.com/manage-api-tokens
JIRA_URL=https://your-domain.atlassian.net
JIRA_EMAIL=your@email.com
JIRA_API_TOKEN=...
JIRA_PROJECT_KEY=PROJ
JIRA_ASSIGNEE_ACCOUNT_ID=              # optional
```

### 6. Add your knowledge files to `data/`

Place your project files in `data/`. Supported formats: `.pdf`, `.md`, `.txt`, `.json`

```
data/
├── your_features.md      # Feature specs, PRD
└── openapi.json          # API documentation
```

> ⚠️ Do NOT put `bug_report_template.md` in `data/` — it lives in the project root.

### 7. Build the index

```bash
python src/build_index.py
```

You should see:
```
✅ Done! Vector database stored in: db
Files indexed:
  - your_features.md
  - openapi.json
```

---

## Usage

### Generate a Frontend bug report

```bash
python src/bug_reporter.py "Merchant can see Super Admin dashboard link in navigation bar after login"
```

### Generate a Backend bug report

```bash
python src/bug_reporter.py "Login API returns 401 with valid credentials" --type backend
```

### Upload options with Regression Detection

After generation you'll be prompted:
Before uploading to GitHub or Jira, the system automatically checks for
similar existing issues — preventing duplicate tickets.

The check only runs for the destination you choose:

```
Where would you like to upload this bug report?
  [1] GitHub Issue only → searches GitHub issues only
  [2] Jira Ticket only → searches Jira issues only
  [3] Both GitHub + Jira → searches both
  [4] Skip — keep locally only → no check, saves with unique filename
```

---

## When to Re-index

Re-run `build_index.py` only when you add, update, or remove files in `data/`:

```bash
rm -rf db
python src/build_index.py
```

---

## .gitignore

Make sure your `.gitignore` includes:

```
venv/
.env
db/
__pycache__/
*.pyc
bug_report.md
llm_model/
```

---

## Local Q&A with Mistral

To ask questions about your documents without generating bug reports:

```bash
python src/rag_chat.py
```

Requires `mistral-7b-instruct-v0.2.Q4_K_M.gguf` in `llm_model/mistral/`.
Download from [HuggingFace — TheBloke/Mistral-7B-Instruct-GGUF](https://huggingface.co/TheBloke/Mistral-7B-Instruct-GGUF).

---
---
## Evaluation

This project includes a full evaluation suite measuring quality at three levels.
Run any eval script after changing models, prompts, or chunk sizes to track improvement.

---

### Phase 1 — RAG Retrieval Accuracy

Measures whether Chroma retrieved the correct files for each bug description.

**Input:** 10 test cases from `test_dataset.json` — each with a bug description
and the expected source file that should be retrieved.

**How it works:**
1. Embeds each bug description into a vector using `all-MiniLM-L6-v2` (local, no API)
2. Searches Chroma DB for top 6 similar chunks
3. Checks whether the expected file appears in the results
4. Calculates similarity score and confidence level per test case

**AI involved:** Only the local embedding model — no LLM, no API calls, runs fully offline.

```bash
python eval/run_retrieval_eval.py
```

**Output:** Terminal report + `eval/results/retrieval_report.json`

```
TC001  ✅  LOGIN_FEATURES.md  score:0.85  [HIGH]
TC004  ✅  LOGIN_FEATURES.md  score:1.4   [LOW]
TC007  ✅  openapi.json       score:1.16  [MEDIUM]

...
Precision : 100%
Avg score : 1.07

```

> TC004 ("Role badge not displayed") scored LOW confidence (1.48) —
> the description is vague and barely appears in the feature file.
> This is expected behaviour — the confidence scorer correctly flags it.
---

### Phase 2 — RAGAS LLM Output Quality

Measures whether generated reports are faithful to retrieved context
and relevant to the bug description.

**Input:** 10 test cases from `test_dataset.json` — each with a bug
description and a ground truth answer.

**How it works:**
1. Retrieves top 6 chunks from Chroma for each test case (local embeddings)
2. Sends chunks + bug description to Groq → generates a short report
3. Packages each case as a RAGAS sample:
   - `user_input`          = bug description
   - `retrieved_contexts`  = retrieved chunks
   - `response`            = generated report
   - `reference`           = ground truth from test dataset
4. Scores each sample on 3 metrics using OpenAI as the evaluator judge

**AI involved:**
- **Groq (Llama 4 Scout)** — generates the report for each test case
- **OpenAI gpt-4o-mini** — acts as RAGAS judge (reads report, scores it)
- **sentence-transformers** — local embeddings for Answer Relevancy (no API)

```bash
python eval/run_ragas_eval.py
```
    
| Metric | Score |
|---|---|
| Faithfulness | 0.308 |
| Answer Relevancy | 0.739 |
| Context Precision | 0.557 |
| Overall | 0.535 |

> **Note on Faithfulness (0.359):** RAGAS penalises any statement not
> word-for-word in the retrieved chunks. Since chunks are 500 tokens,
> the LLM makes reasonable inferences beyond literal retrieval — which
> RAGAS counts against faithfulness. Increasing `chunk_size` from 500
> to 1000 in `build_index.py` and re-indexing is expected to improve
> this score significantly.


---

### Phase 3 — Bug Report Generation Quality

Measures whether the LLM fills the template correctly — right severity,
priority, component, and structure. Rule-based, no API calls needed.

**Input:** 10 test cases from `test_dataset.json` — each with a bug
description and expected values for severity, priority, and component.

**How it works:**
1. Generates a fresh bug report for each test case via Groq
2. Runs rule-based checks on the generated markdown:
   - **Template completeness** — are all required sections present?
     Are placeholder fields like `<!-- e.g. -->` still unfilled?
   - **Severity accuracy** — does extracted severity match expected?
   - **Priority accuracy** — does P0/P1/P2/P3 match expected?
   - **Component accuracy** — fuzzy match of affected component
   - **Title quality** — does title have correct `[FE]`/`[BE]` prefix?
3. Scores each check and calculates a weighted overall score

**AI involved:** Only Groq for report generation — scoring is fully
rule-based regex parsing. No LLM judge, no API costs for evaluation.


```bash
python eval/run_report_eval.py
```

| Metric | v1 | v2 |
|---|---|---|
| Template Completeness | 84.6% | 85.2% |
| Severity Accuracy | 5 / 10 (50%) | 7 / 10 (70%) |
| Priority Accuracy | 5 / 10 (50%) | 7 / 10 (70%) |
| Component Accuracy | 9 / 10 (90%) | 10 / 10 (100%) |
| Title Quality | 10 / 10 (100%) | 10 / 10 (100%) |
| Overall Score | 0.689 / 1.000 | 0.806 / 1.000 |

### Prompt Version History

| Version | Overall Score | Severity Accuracy | Change |
|---|---|---|---|
| v1 | 0.689 | 50% | Baseline |
| v2 | 0.806 | 70% | Added explicit severity/priority examples — +17 points overall |

> **Prompt versioning:** Prompts are stored as versioned files in `prompts/`.
> Switch versions by updating `active_version` in `prompts/prompt_config.json`
> — no code changes needed. Each run logs which prompt version was used
> in `logs/retrieval_log.jsonl` for full traceability.

> **Remaining failures (TC003, TC005):** Both involve RBAC violations
> where the LLM rates severity as High instead of Critical. Further
> prompt refinement tracked for v3.
---
## Why All Three Eval Scripts Are Needed

Each script answers a different question at a different level. They
cannot replace each other.

| | `run_retrieval_eval` | `run_ragas_eval` | `run_report_eval` |
|---|---|---|---|
| **Question** | Did RAG find the right file? | Is the LLM output faithful and relevant? | Did the LLM fill the template correctly? |
| **Level** | File retrieval | Chunk + generation quality | Template structure quality |
| **AI involved** | Embeddings only (local) | Groq (generation) + OpenAI (judge) | Groq (generation) only |
| **Scoring method** | Binary match check | RAGAS metrics (0–1) | Rule-based regex parsing |
| **API cost** | Free — fully offline | ~$0.02 per run (OpenAI) | Free — no judge needed |
| **Speed** | ~5 seconds | ~3 minutes | ~1 minute |
| **Good for** | CI/CD quality gate | Deep quality analysis | Prompt iteration feedback |
| **What it misses** | Chunk quality, LLM quality | Template structure, field accuracy | Semantic quality, hallucinations |

### They Can Tell Different Stories

```
Scenario A — Retrieval works, generation doesn't:
  run_retrieval_eval  : ✅ 100% precision  (right file found)
  run_ragas_eval      : ⚠️  faith: 0.35   (LLM not using context well)
  run_report_eval     : ⚠️  severity: 50%  (wrong severity inferred)
  → Fix: improve the prompt

Scenario B — Generation works, retrieval doesn't:
  run_retrieval_eval  : ❌ 70% precision   (wrong file retrieved)
  run_ragas_eval      : ⚠️  precision: 0.4 (irrelevant chunks)
  run_report_eval     : ⚠️  complete: 60%  (missing context = gaps)
  → Fix: add more docs to data/ or improve descriptions

Scenario C — Everything working:
  run_retrieval_eval  : ✅ 100% precision
  run_ragas_eval      : ✅ relevancy: 0.74
  run_report_eval     : ✅ overall: 0.806
  → Safe to ship
```

### When to Run Each

```
Every bug report    →  Quality gate in bug_reporter.py (instant, free)
After prompt change →  run_report_eval.py (fast, free, measures impact)
After adding docs   →  run_retrieval_eval.py (confirms new docs indexed correctly)
Deep quality audit  →  run_ragas_eval.py (costs ~$0.02, run occasionally)
```

### Eval Provider Switching

Switch evaluation LLM with one line in `.env` — no code changes:

```bash
# Current
RAGAS_EVAL_PROVIDER=openai
OPENAI_EVAL_MODEL=gpt-4o-mini

# Switch to Groq (when Dev tier available)
RAGAS_EVAL_PROVIDER=groq
GROQ_EVAL_MODEL=meta-llama/llama-4-scout-17b-16e-instruct

# Switch to Gemini
RAGAS_EVAL_PROVIDER=gemini
GEMINI_EVAL_MODEL=gemini-2.5-flash
```

---

### Running All Evals

```bash
# Run all three in sequence
python eval/run_retrieval_eval.py
python eval/run_ragas_eval.py
python eval/run_report_eval.py

# Results saved to
eval/results/retrieval_report.json
eval/results/ragas_report.json
eval/results/report_eval_report.json
```

---

## Author

**Tasnim Fariyah** — 14 years in QA engineering

[![GitHub](https://img.shields.io/badge/GitHub-tfariyah31-181717?logo=github)](https://github.com/tfariyah31)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-tasnim--fariyah-0A66C2?logo=linkedin)](https://www.linkedin.com/in/tasnim-fariyah/)

