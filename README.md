# Incident RCA RAG Agent

An agent-based retrieval-augmented generation (RAG) assistant that answers questions about system incidents and their root cause analyses (RCA). The user asks a question in natural language, the agent finds related incident records with semantic search, and it returns an answer with the root cause, the resolution and the source incident IDs.

I built this project during my internship on the Cognitive Product Development team at Etiya (July 2026).

## Features

- **Semantic search** over incident records stored in Qdrant, using `all-MiniLM-L6-v2` embeddings. Matching is based on meaning, not keywords.
- **Agent with function calling.** The LLM decides which tool to call for each question: `search_incidents` for incident questions, `search_memory` for questions about the conversation.
- **Two-layer memory, isolated per session:**
  - *Chronological memory (JSONL):* a full, ordered log of the conversation. Used for questions like "what did I just ask?".
  - *Semantic memory (Mem0):* finds past conversations with similar meaning. Used for questions like "did we talk about this before?".
  - Every record has a `session_id`, so chats do not mix with each other.
- **Payload filtering** by `service` and `severity`. Filters are set from the UI. The LLM does not guess filters from the question text.
- **Source citation.** Every answer has an `Answer` / `Source` format, with incident IDs (for example `INC-1016`) or "past conversation" as the source.
- **LLM-as-judge evaluation** that measures answer correctness and source correctness separately.
- **HTTP API (FastAPI)** with `/ask`, `GET /history/{session_id}` and `DELETE /history/{session_id}`.
- **Web chat UI** with a sidebar of past chats, per-message filters and chat deletion.
- **Error handling.** Tool calls, the agent call and memory writes are handled separately, so a temporary Qdrant or Mem0 failure does not crash the request.
- **Docker Compose** setup that starts the app and Qdrant with one command.

## Architecture

```
CSV -> Parquet -> Embedding -> Qdrant
                                  |
Web UI (session_id) --> FastAPI (/ask, /history) --> Agent (function calling)
                                                        |- search_incidents --> Qdrant (semantic search + filters)
                                                        `- search_memory ----> JSONL + Mem0 (filtered by session_id)
                                                        |
                                                        v
                                              Answer with sources --> saved to memory (with session_id)
```

## Tech Stack

| Part | Tool |
|------|------|
| Vector database | Qdrant (Docker) |
| Embeddings | sentence-transformers, `all-MiniLM-L6-v2` (384 dimensions, cosine) |
| LLM | Groq: `llama-3.3-70b-versatile` (RAG answers and judge), `openai/gpt-oss-120b` (agent) |
| Semantic memory | Mem0 (managed platform) |
| API | FastAPI + Uvicorn |
| Data format | Parquet (PyArrow), batch upsert with a generator |
| Containers | Docker, Docker Compose |

## Project Structure

| File | Purpose |
|------|---------|
| `create_collection.py` | Creates the Qdrant collection (384 dimensions, cosine distance). |
| `csv_to_parquet.py` | Converts the CSV dataset to Parquet for batch processing. |
| `embed_and_upsert.py` | Reads the Parquet file in batches, creates embeddings and writes them to Qdrant. |
| `rag.py` | Core RAG logic: retrieval, context building, session-based memory (read, write, delete) and the LLM call. Can also run on its own. |
| `agent.py` | Agent layer that selects tools with function calling. Includes an interactive terminal mode. |
| `main.py` | FastAPI app. Exposes the agent over HTTP and serves the web UI. |
| `static/index.html` | Web chat UI. |
| `eval.py` | LLM-as-judge evaluation pipeline. |
| `data/rca_dataset.csv` | 100 synthetic incident/RCA records. |
| `data/test_cases.jsonl`, `data/test_memory.jsonl` | Evaluation test cases and the memory used during evaluation. |
| `docs/test-scenarios.tr.md` | Manual test scenarios with expected answers (in Turkish). |

## Setup

### Requirements

- Python 3.11
- Docker
- A Groq API key and a Mem0 API key

### Option 1: Docker

1. Copy `.env.example` to `.env` and add your API keys.
2. Start the app and Qdrant:
   ```bash
   docker compose up -d --build
   ```
   The first build takes a while because it downloads PyTorch (CPU) and the embedding model. The model is stored in the image, so later starts are fast.
3. Load the data (only the first time, or when the Qdrant volume is empty):
   ```bash
   pip install -r requirements.txt
   python csv_to_parquet.py
   python create_collection.py
   python embed_and_upsert.py
   ```
4. Open `http://localhost:8000/`.

Stop with `docker compose down`. The Qdrant data stays in the volume.

### Option 2: Local development

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt

docker run -d --name qdrant_db -p 6333:6333 qdrant/qdrant

python csv_to_parquet.py
python create_collection.py
python embed_and_upsert.py

uvicorn main:app --reload
```

- Web UI: `http://localhost:8000/`
- Swagger UI: `http://localhost:8000/docs`

Terminal modes:
```bash
python rag.py      # plain RAG, no agent
python agent.py    # interactive agent
```

## Example Usage

**Direct question with filters**
```
Question: What was the root cause of the recent payment service outage?
Filters:  service=payment, severity=high

Answer: INC-1000, Payment service not responding. Root cause: the DB connection
pool was exhausted. Resolution: pool size was increased and the connection leak was fixed.
Source: INC-1000
```

**Indirect question (no shared keywords)**
```
Question: customers are complaining they got charged twice for the same order

Answer: ... INC-1016 (missing idempotency key, duplicate charge caused by retries) ...
Source: INC-1016
```

**Session isolation**
```
Same chat:      "what did I just ask?" -> "You just asked, 'why did the database replication lag spike?'"
New chat:       "what did I just ask?" -> "I don't have any earlier question in this conversation."
```

**No matching record**
```
Question: why is the recommendation widget always empty?
Filters:  service=recommendation, severity=critical

Answer: I don't know.
```

## Sessions

The web UI creates a `session_id` with `crypto.randomUUID()` for each chat and stores it in `localStorage`. The backend adds this ID to every JSONL record and to the Mem0 metadata, and all reads and searches are filtered by it.

- Chats survive a page refresh or a browser restart.
- "New chat" starts a new session that cannot see other chats.
- Deleting a chat removes it from both the JSONL file and Mem0 (hard delete).

## Memory Design: JSONL vs Mem0

I used the two as layers that complement each other, not as alternatives.

| | JSONL (my own) | Mem0 |
|---|---|---|
| Type | Chronological log | Semantic search |
| Good for | "What did I just ask?" | "Did we talk about this before?" |
| Stores | Raw question, answer, filters, session_id, time | Facts extracted by an LLM |
| Setup | No dependencies, plain file | API key and cloud service |

Mem0 extracts facts from the conversation with an LLM and then merges them with existing memories (add, update, delete). Retrieval is based on similarity, so it does not keep the order of messages. Because of this, chronological questions use JSONL and similarity questions use Mem0.

## Evaluation

```bash
python eval.py
```

Runs the cases in `data/test_cases.jsonl` and reports two metrics:
- **Answer correctness:** an LLM judge compares the answer with the expected answer by meaning.
- **Source correctness:** checks whether the cited incident IDs (or "past conversation") match the expected source.

## Problems I Solved

- **Large Docker build context:** `.dockerignore` had `.venv` instead of the real folder name `venv`, so the context was over 500 MB.
- **Platform-specific package:** `pywin32` in `requirements.txt` broke the Linux image.
- **Timeouts during install:** fixed with a longer pip timeout, retries and the CPU-only PyTorch index.
- **Model download on every start:** the embedding model is now downloaded during the build and the container runs with `HF_HUB_OFFLINE=1`.
- **Wrong memory answers:** for "what did I just ask?", the agent repeated the current message. A clear rule in the system prompt fixed this.

## Possible Improvements

- A reranking step (for example a cross-encoder) to improve retrieval quality
- Streaming answers
- A larger test set and automatic regression evaluation
- Cloud deployment

## Note on Data

The dataset is synthetic. It does not contain real customer or company incident data.
