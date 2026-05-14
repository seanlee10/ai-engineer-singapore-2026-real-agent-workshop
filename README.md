# self-rag

A self-improving RAG system for legal questions against a Victorian bench book. An autonomous agent loop evaluates retrieval quality using Arize, then iteratively improves the LangGraph agent and indexing pipeline until recall targets are met.

## Repository Structure

```
agent/              LangGraph RAG agent (OpenSearch retriever + GPT-4o-mini)
index/              OpenSearch indexing pipeline (chunking, embedding, bulk indexing)
scripts/ralph/      Autonomous improvement loop (ralph.sh + Claude Code)
scripts/            Evaluation and re-indexing scripts
skills/             Skill definitions for the Ralph agent (PRD generation, story execution)
```

## Prerequisites

1. **[Arize](https://arize.com/) account** — sign up at arize.com (free tier available)
2. **Python 3.13+** and [uv](https://docs.astral.sh/uv/)
3. **Claude Code** — install via `npm install -g @anthropic-ai/claude-code`
4. **Arize AX CLI:**
   ```bash
   pip install arize-ax-cli
   ax config set --space-id <your-space-id> --api-key <your-arize-api-key>
   ax config show  # verify profile
   ```
   Find your Space ID and API key in the Arize UI under **Settings > Space Settings > API Keys**.
5. **Arize Skills plugin for Claude Code:**
   ```bash
   claude /plugin marketplace add Arize-ai/arize-skills
   claude /plugin install arize-skills@Arize-ai-arize-skills
   ```
6. **Docker** — OpenSearch runs locally via `docker compose` (see [Index the corpus](#4-index-the-corpus))
7. **API keys** — OpenAI or Anthropic and Arize (see [Environment Variables](#environment-variables))

## Getting Started

### Quick setup

Verify and auto-fix your environment in one shot:

```bash
bash skills/setup/setup.sh check   # see what's missing
bash skills/setup/setup.sh fix     # auto-fix everything project-level
```

Or invoke the `/setup` skill inside Claude Code. The manual steps below are the
equivalent done by hand — useful if you want to understand what setup does or
fix something specific.

### 1. Clone and install dependencies

```bash
git clone <repo-url> && cd self-rag-2

# Agent
cd agent && uv sync --dev && cd ..

# Index pipeline
cd index && uv sync --dev && cd ..
```

### 2. Configure environment variables

```bash
cp agent/.env.example agent/.env
cp index/.env.example index/.env
# Edit both .env files with your credentials
```

### 3. Upload the QA dataset to Arize

Inside Claude Code, use arize-skills to download the `qa` split from [isaacus/legal-rag-bench](https://huggingface.co/datasets/isaacus/legal-rag-bench) and upload it as an Arize dataset. This dataset is used by the self-improvement loop to evaluate retrieval recall.

### 4. Index the corpus

Start local OpenSearch (single-node, security disabled, plain HTTP on `localhost:9200`):

```bash
docker compose up -d
```

Then run the indexing pipeline:

```bash
cd index
python index.py
```

This loads the legal-rag-bench corpus, chunks it, generates embeddings with `text-embedding-3-large` (1024 dims), and bulk-indexes into OpenSearch.

### 5. Start the LangGraph agent

```bash
cd agent
langgraph dev
```

The agent runs on port 2024.

### 6. Run the self-improvement loop

Start Claude Code with `--dangerously-skip-permissions` so the autonomous agent can freely edit code and run commands:

```bash
./scripts/ralph/ralph.sh --tool claude
```

Ralph drives the improvement loop:

1. Reads a PRD (`scripts/ralph/prd.json`) and picks the highest-priority failing user story
2. Implements changes in `agent/` (retrieval logic) and/or `index/` (indexing pipeline)
3. Runs quality checks (lint, typecheck, tests)
4. Commits passing changes
5. Runs an Arize experiment against the QA dataset to measure recall@1, recall@5, recall@10
6. Analyzes failures and adds new improvement stories if recall@5 < 80%
7. Repeats until recall targets are met or max iterations reached

## Architecture

### Agent

A LangGraph `StateGraph` with two nodes:

1. **retrieve** — kNN search against OpenSearch using `text-embedding-3-large` (1024 dims)
2. **call_model** — RAG prompt answered by GPT-4o-mini

Tracing via Arize OTel + `LangChainInstrumentor`.

### Index Pipeline

Loads the [legal-rag-bench](https://huggingface.co/datasets/isaacus/legal-rag-bench) corpus, chunks with `RecursiveCharacterTextSplitter`, embeds with `text-embedding-3-large` (1024 dims), and bulk-indexes into OpenSearch with HNSW cosine similarity.

### Self-Improvement Loop

```
                    ┌─────────────────────────┐
                    │   ralph.sh (loop driver) │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Pick next failing story │
                    │  from prd.json           │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Implement changes in    │
                    │  agent/ and/or index/    │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Lint, typecheck, test   │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Run Arize experiment    │
                    │  (recall@1, @5, @10)     │
                    └────────────┬────────────┘
                                 │
                         ┌───────▼───────┐
                         │ Recall@5 > 80%? │
                         └───┬───────┬───┘
                          no │       │ yes
                    ┌────────▼──┐  ┌─▼──────────┐
                    │ Add new   │  │   Done      │
                    │ stories   │  └─────────────┘
                    └─────┬─────┘
                          │
                          └──── (next iteration)
```

## Environment Variables

### Agent (`agent/.env`)

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `HOST` | Yes | OpenSearch host (e.g. `localhost`) |
| `PORT` | No | OpenSearch port (defaults to `9200`) |
| `INDEX` | Yes | OpenSearch index name (e.g. `legal-rag`) |
| `ARIZE_SPACE_ID` | No | Arize space ID |
| `ARIZE_API_KEY` | No | Arize API key |
| `ARIZE_PROJECT_NAME` | No | Arize project name |

### Index Pipeline (`index/.env`)

| Variable | Required | Description |
|---|---|---|
| `OPENSEARCH_HOST` | Yes | OpenSearch host URL (e.g. `http://localhost:9200`) |
| `OPENAI_API_KEY` | Yes | OpenAI API key for embeddings |

## Development

```bash
# Agent
cd agent
make test              # unit tests
make lint              # ruff + mypy --strict
make format            # auto-fix

# Index
cd index
uv sync --dev
```

Both Python packages use Ruff (pycodestyle, pyflakes, isort, pydocstyle) and mypy `--strict`.
