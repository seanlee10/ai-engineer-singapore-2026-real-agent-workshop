import os
import json
import time

import requests
from datasets import load_dataset
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

# Config
INDEX_NAME = "legal-rag"
OPENSEARCH_HOST = os.environ["OPENSEARCH_HOST"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
EMBEDDING_BATCH_SIZE = 50
BULK_BATCH_SIZE = 100


def load_documents():
    ds = load_dataset("isaacus/legal-rag-bench", "corpus", split="test")
    documents = []
    for row in ds:
        text = row["title"] + "\n\n" + row["text"]
        footnotes = row.get("footnotes")
        if footnotes and footnotes.strip():
            text += "\n\n" + footnotes
        documents.append({
            "text": text,
            "metadata": {
                "source": row["id"],
                "title": row["title"],
                "footnotes": footnotes if footnotes and footnotes.strip() else "",
            },
        })
    print(f"Loaded {len(documents)} documents")
    return documents


def chunk_documents(documents):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=["\n\n", "\n", " "],
    )
    chunks = []
    for doc in documents:
        splits = splitter.split_text(doc["text"])
        for split in splits:
            chunks.append({
                "chunk": split,
                "metadata": doc["metadata"],
            })
    print(f"Created {len(chunks)} chunks from {len(documents)} documents")
    return chunks


def generate_embeddings(texts):
    """Embed a single batch of texts. Returns list of embedding vectors."""
    response = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "text-embedding-3-large",
            "input": texts,
            "dimensions": 1024,
        },
    )
    response.raise_for_status()
    data = response.json()["data"]
    return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]


def embed_chunks(chunks):
    """Embed all chunks in batches with retry on rate limits."""
    total_batches = (len(chunks) + EMBEDDING_BATCH_SIZE - 1) // EMBEDDING_BATCH_SIZE
    for i in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[i : i + EMBEDDING_BATCH_SIZE]
        texts = [c["chunk"] for c in batch]
        batch_num = i // EMBEDDING_BATCH_SIZE + 1

        retries = 0
        while True:
            try:
                embeddings = generate_embeddings(texts)
                break
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and retries < 3:
                    delay = (2 ** retries) * 1
                    print(f"  Rate limited, retrying in {delay}s...")
                    time.sleep(delay)
                    retries += 1
                else:
                    raise

        for j, embedding in enumerate(embeddings):
            chunks[i + j]["embedding"] = embedding

        print(f"  Embedded batch {batch_num}/{total_batches}")

    print(f"Embedded {len(chunks)} chunks")
    return chunks


def create_index():
    """Delete and recreate the workshop index."""
    # Delete index if it exists (404 is expected and harmless)
    delete_resp = requests.delete(
        f"{OPENSEARCH_HOST}/{INDEX_NAME}",
    )
    if delete_resp.status_code not in (200, 404):
        delete_resp.raise_for_status()

    # Create index with mapping
    mapping = {
        "settings": {"index.knn": True},
        "mappings": {
            "properties": {
                "chunk": {"type": "text"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 1024,
                    "method": {
                        "engine": "lucene",
                        "space_type": "cosinesimil",
                        "name": "hnsw",
                        "parameters": {},
                    },
                },
                "metadata": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "keyword"},
                        "title": {"type": "text"},
                        "footnotes": {"type": "text"},
                    },
                },
            }
        },
    }

    response = requests.put(
        f"{OPENSEARCH_HOST}/{INDEX_NAME}",
        headers={"Content-Type": "application/json"},
        json=mapping,
    )
    response.raise_for_status()
    print(f"Created index '{INDEX_NAME}'")


def bulk_index(chunks):
    """Bulk index chunks into OpenSearch with retry on failure."""
    total_batches = (len(chunks) + BULK_BATCH_SIZE - 1) // BULK_BATCH_SIZE
    failed_chunks = []

    for i in range(0, len(chunks), BULK_BATCH_SIZE):
        batch = chunks[i : i + BULK_BATCH_SIZE]
        batch_num = i // BULK_BATCH_SIZE + 1

        bulk_data = []
        for chunk in batch:
            action = {"index": {"_index": INDEX_NAME}}
            doc = {
                "chunk": chunk["chunk"],
                "embedding": chunk["embedding"],
                "metadata": chunk["metadata"],
            }
            bulk_data.append(json.dumps(action))
            bulk_data.append(json.dumps(doc))

        bulk_body = "\n".join(bulk_data) + "\n"

        success = False
        for attempt in range(3):
            try:
                response = requests.post(
                    f"{OPENSEARCH_HOST}/_bulk",
                    headers={"Content-Type": "application/x-ndjson"},
                    data=bulk_body,
                )
                if response.status_code >= 400:
                    print(f"  Error in batch {batch_num} (attempt {attempt + 1}): {response.status_code}")
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                else:
                    result = response.json()
                    if result.get("errors"):
                        for item in result["items"]:
                            if "error" in item.get("index", {}):
                                print(f"  Doc error: {item['index']['error']}")
                    success = True
                    break
            except Exception as e:
                print(f"  Exception in batch {batch_num} (attempt {attempt + 1}): {e}")
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue

        if not success:
            print(f"  FAILED batch {batch_num} after 3 attempts")
            failed_chunks.extend(batch)

        print(f"  Indexed batch {batch_num}/{total_batches}")

    if failed_chunks:
        print(f"WARNING: {len(failed_chunks)} chunks failed to index")
    print(f"Bulk indexing complete: {len(chunks) - len(failed_chunks)}/{len(chunks)} chunks indexed")
    return failed_chunks


def main():
    print("=== Index Pipeline ===\n")

    print("Stage 1: Loading dataset...")
    documents = load_documents()

    print("\nStage 2: Chunking documents...")
    chunks = chunk_documents(documents)

    print("\nStage 3: Embedding chunks...")
    chunks = embed_chunks(chunks)

    print("\nStage 4: Indexing into OpenSearch...")
    create_index()
    bulk_index(chunks)

    print(f"\n=== Done! {len(chunks)} chunks indexed into '{INDEX_NAME}' ===")


if __name__ == "__main__":
    main()
