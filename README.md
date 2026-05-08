# Bug Report Enhancer

An AI-powered bug report automation tool that generates structured, context-aware bug reports from plain English descriptions and uploads them directly to **GitHub Issues** or **Jira** — fully free, runs locally.

---

## How It Works

```
You type a plain English bug description
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
- Creates GitHub labels automatically if they don't exist
- Converts markdown to **Atlassian Document Format (ADF)** for Jira
- Runs **fully offline** except for Groq API and upload calls
- **100% free** — uses Groq free tier (1,000 req/day)

---

## Tech Stack

| Component | Tool |
|---|---|
| Embeddings + Retrieval | LangChain + `all-MiniLM-L6-v2` |
| Vector Store | Chroma (local) |
| LLM Generation | Groq API — Llama 4 Scout (free tier) |
| GitHub Integration | GitHub REST API v3 |
| Jira Integration | Jira Cloud REST API v3 |
| Local Q&A (optional) | Mistral-7B via llama.cpp |

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

### Upload options

After generation you'll be prompted:

```
Where would you like to upload this bug report?
  [1] GitHub Issue only
  [2] Jira Ticket only
  [3] Both GitHub + Jira
  [4] Skip — keep locally only
```

---

## GitHub Labels Created Automatically

| Label | Color |
|---|---|
| `bug` | default |
| `severity: critical` | dark red |
| `severity: high` | red |
| `severity: medium` | orange |
| `severity: low` | yellow |
| `priority: P0` | dark red |
| `priority: P1` | red |
| `priority: P2` | blue |
| `priority: P3` | grey |

---

## When to Re-index

Re-run `build_index.py` only when you add, update, or remove files in `data/`:

```bash
rm -rf db
python src/build_index.py
```

---

## Groq Free Tier Limits

| Model | Tokens/min | Requests/day |
|---|---|---|
| Llama 4 Scout | 30,000 | 1,000 |

Each bug report uses ~1,500–2,500 tokens after RAG retrieval — effectively **400+ bug reports/day for free**.

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

## Troubleshooting

**`torch` install fails**
→ Make sure you're using Python 3.11. Python 3.12+ has no torch wheels yet.
```bash
python --version   # must be 3.11.x
```

**`No module named 'langchain.text_splitter'`**
→ Install the updated package:
```bash
pip install langchain-text-splitters
```

**`No module named 'langchain.schema'`**
→ Use `langchain-core` instead:
```bash
pip install langchain-core
```

**Chroma DB deprecation warning about `db.persist()`**
→ Safe to ignore — Chroma 0.4+ auto-persists. The warning doesn't affect functionality.

---

## License

MIT
