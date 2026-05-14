# ax-index

OpenSearch indexing pipeline for the [legal-rag-bench](https://huggingface.co/datasets/isaacus/legal-rag-bench) Victorian bench book corpus. Loads documents, chunks them, generates embeddings, and bulk-indexes into OpenSearch with kNN vector search.

## Setup

```bash
pip install -r requirements.txt
```

Start local OpenSearch (from the repo root):

```bash
docker compose up -d
```

Create a `.env` file:

```
OPENSEARCH_HOST=http://localhost:9200
OPENAI_API_KEY=sk-...
```

## Usage

### `index.py` — Full indexing pipeline

Loads the corpus from Hugging Face, chunks with `RecursiveCharacterTextSplitter` (1000 chars, 200 overlap), embeds with `text-embedding-3-large` (1024 dims), and bulk-indexes into OpenSearch. Recreates the index from scratch.

```bash
python index.py
```

## Index Schema

```json
{
  "chunk": "passage text",
  "embedding": [1024-dim float vector],
  "metadata": {
    "source": "1.2-c2-s2",
    "title": "1.2 Excusing Jurors",
    "footnotes": "[^2]: Ibid."
  }
}
```

- **Embedding model**: `text-embedding-3-large` at 1024 dimensions
- **Vector search**: HNSW with cosine similarity via Lucene
- **Source ID format**: `<section>-c<chunk>-s<sub>` (e.g. `7.3.2-c5-s1`)
