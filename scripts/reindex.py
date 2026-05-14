#!/usr/bin/env python3
"""Re-index the legal-rag-bench corpus into OpenSearch with configurable chunking.

Uses RecursiveCharacterTextSplitter (or heading-based splitting) for chunking,
text-embedding-3-large for embeddings (3072 dims), and blue/green deployment
with alias swapping.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from opensearchpy import OpenSearch, helpers


def _load_env() -> None:
    """Load environment variables from agent/.env if present."""
    env_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "agent", ".env"
    )
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(
                        key.strip(), value.strip().strip('"').strip("'")
                    )


def _get_os_client() -> OpenSearch:
    """Create OpenSearch client from env vars."""
    return OpenSearch(
        hosts=[{"host": os.environ["HOST"], "port": int(os.environ.get("PORT", "9200"))}],
        use_ssl=False,
        verify_certs=False,
    )


def _get_next_index_name(client: OpenSearch, prefix: str = "self_ralph") -> str:
    """Determine next index version by checking existing indices."""
    indices = client.cat.indices(format="json")
    existing = [
        idx["index"]
        for idx in indices
        if idx["index"].startswith(prefix + "_v")
    ]
    if not existing:
        return f"{prefix}_v1"
    versions = []
    for name in existing:
        try:
            v = int(name.split("_v")[-1])
            versions.append(v)
        except ValueError:
            continue
    next_v = max(versions) + 1 if versions else 1
    return f"{prefix}_v{next_v}"


def _create_index(client: OpenSearch, index_name: str, dims: int = 3072) -> None:
    """Create OpenSearch index with kNN vector field."""
    body: dict[str, Any] = {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 256,
            },
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "properties": {
                "chunk": {"type": "text"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dims,
                    "method": {
                        "engine": "lucene",
                        "space_type": "cosinesimil",
                        "name": "hnsw",
                        "parameters": {},
                    },
                },
                "metadata": {
                    "properties": {
                        "source": {"type": "keyword"},
                        "title": {"type": "text"},
                        "footnotes": {"type": "text"},
                        "section_path": {"type": "text"},
                    }
                },
            }
        },
    }
    client.indices.create(index=index_name, body=body)
    print(f"Created index: {index_name}")


def _load_corpus(corpus_path: str) -> list[dict[str, str]]:
    """Load corpus CSV with columns: id, title, text, footnotes."""
    with open(corpus_path) as f:
        reader = csv.DictReader(f)
        return list(reader)


def _derive_section_path(title: str) -> str:
    """Derive hierarchical section path from a numbered title.

    E.g. "7.3.18.1 Child under aged 16" -> "7 > 7.3 > 7.3.18 > 7.3.18.1"
    """
    m = re.match(r"([\d.]+)", title)
    if not m:
        return title.strip()
    num = m.group(1).rstrip(".")
    parts = num.split(".")
    return " > ".join(".".join(parts[: i + 1]) for i in range(len(parts)))


def _split_heading_based(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[tuple[str, str]]:
    """Split text at markdown heading boundaries.

    Returns (heading, body) tuples. If a section exceeds chunk_size,
    it is further split using RecursiveCharacterTextSplitter.
    """
    fallback = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    lines = text.split("\n")
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in lines:
        if line.strip().startswith("#"):
            if current_lines or current_heading:
                sections.append((current_heading, current_lines))
            current_heading = line.strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines or current_heading:
        sections.append((current_heading, current_lines))

    result: list[tuple[str, str]] = []
    for heading, body_lines in sections:
        body = "\n".join(body_lines).strip()
        section_text = f"{heading}\n{body}".strip() if heading else body
        if not section_text:
            continue

        if len(section_text) <= chunk_size:
            result.append((heading, section_text))
        else:
            sub_texts = fallback.split_text(section_text)
            for sub_text in sub_texts:
                result.append((heading, sub_text))

    return result


def _chunk_corpus(
    docs: list[dict[str, str]],
    chunk_size: int,
    chunk_overlap: int,
    title_prefix: bool = False,
    footnote_enrichment: bool = False,
    heading_based: bool = False,
) -> list[dict[str, Any]]:
    """Split corpus documents into chunks, preserving metadata.

    When heading_based is True, splits at markdown heading boundaries
    instead of using fixed character splitting.

    When title_prefix is True, the section title is prepended to each
    individual chunk so that every chunk carries its section context.

    When footnote_enrichment is True, footnotes are appended to each
    chunk.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[dict[str, Any]] = []
    for doc in docs:
        text = doc.get("text", "")
        title = doc.get("title", "")
        source_id = doc.get("id", "")
        footnotes = doc.get("footnotes", "")
        section_path = _derive_section_path(title)

        if heading_based:
            sections = _split_heading_based(text, chunk_size, chunk_overlap)
            for i, (_heading, chunk_text) in enumerate(sections):
                enriched_text = chunk_text
                if title_prefix and title:
                    enriched_text = f"{title}\n\n{enriched_text}"
                if footnote_enrichment and footnotes:
                    enriched_text = f"{enriched_text}\n\nFootnotes: {footnotes}"
                chunks.append({
                    "chunk": enriched_text,
                    "metadata": {
                        "source": source_id,
                        "title": title,
                        "footnotes": footnotes,
                        "section_path": section_path,
                    },
                    "chunk_index": i,
                })
        else:
            split_texts = splitter.split_text(text)
            for i, chunk_text in enumerate(split_texts):
                enriched_text = chunk_text
                if title_prefix and title:
                    enriched_text = f"{title}\n\n{enriched_text}"
                if footnote_enrichment and footnotes:
                    enriched_text = f"{enriched_text}\n\nFootnotes: {footnotes}"
                chunks.append({
                    "chunk": enriched_text,
                    "metadata": {
                        "source": source_id,
                        "title": title,
                        "footnotes": footnotes,
                        "section_path": section_path,
                    },
                    "chunk_index": i,
                })

    return chunks


def _embed_chunks(
    chunks: list[dict[str, Any]],
    batch_size: int = 100,
    contextual_embed: bool = False,
) -> list[dict[str, Any]]:
    """Generate embeddings for all chunks using OpenAI.

    When contextual_embed is True, the embedding input is the section title
    prepended to the chunk text, giving kNN search section context without
    modifying the stored chunk text (which stays clean for BM25).
    """
    client = OpenAI()
    total = len(chunks)

    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        if contextual_embed:
            texts = []
            for c in batch:
                title = c.get("metadata", {}).get("title", "")
                chunk_text = c["chunk"]
                if title:
                    texts.append(f"{title}\n\n{chunk_text}")
                else:
                    texts.append(chunk_text)
        else:
            texts = [c["chunk"] for c in batch]
        resp = client.embeddings.create(
            model="text-embedding-3-large",
            input=texts,
            dimensions=3072,
        )
        for j, embedding_data in enumerate(resp.data):
            chunks[i + j]["embedding"] = embedding_data.embedding
        print(f"  Embedded {min(i + batch_size, total)}/{total} chunks")

    return chunks


def _bulk_load(
    client: OpenSearch, index_name: str, chunks: list[dict[str, Any]]
) -> None:
    """Bulk load chunks into OpenSearch index."""
    actions = []
    for chunk in chunks:
        doc = {
            "chunk": chunk["chunk"],
            "embedding": chunk["embedding"],
            "metadata": chunk["metadata"],
        }
        actions.append({
            "_index": index_name,
            "_source": doc,
        })

    success, errors = helpers.bulk(client, actions, chunk_size=500)
    print(f"Loaded {success} documents, {len(errors)} errors")
    if errors:
        for e in errors[:5]:
            print(f"  Error: {e}")


def _swap_alias(client: OpenSearch, alias: str, new_index: str) -> None:
    """Atomically swap alias to point to new index."""
    # Get current alias targets
    try:
        current = client.indices.get_alias(name=alias)
        actions: list[dict[str, Any]] = []
        for old_index in current:
            actions.append({"remove": {"index": old_index, "alias": alias}})
        actions.append({"add": {"index": new_index, "alias": alias}})
        client.indices.update_aliases(body={"actions": actions})
        print(f"Swapped alias '{alias}': {list(current.keys())} -> {new_index}")
    except Exception:
        # Alias doesn't exist yet, just create it
        client.indices.put_alias(index=new_index, name=alias)
        print(f"Created alias '{alias}' -> {new_index}")


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Re-index corpus with new chunking")
    parser.add_argument(
        "--corpus",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "index",
            "legal-rag-bench-corpus.csv",
        ),
        help="Path to corpus CSV",
    )
    parser.add_argument("--chunk-size", type=int, default=400, help="Chunk size in chars")
    parser.add_argument(
        "--chunk-overlap", type=int, default=100, help="Chunk overlap in chars"
    )
    parser.add_argument("--alias", default="ralphton", help="OpenSearch alias name")
    parser.add_argument(
        "--title-prefix",
        action="store_true",
        help="Prepend section title to each chunk before embedding",
    )
    parser.add_argument(
        "--footnote-enrichment",
        action="store_true",
        help="Append footnotes to each chunk before embedding",
    )
    parser.add_argument(
        "--heading-based",
        action="store_true",
        help="Use heading-based chunking instead of recursive character splitting",
    )
    parser.add_argument(
        "--contextual-embed",
        action="store_true",
        help="Prepend section title to chunk text for embedding only (not stored)",
    )
    parser.add_argument(
        "--skip-swap", action="store_true", help="Skip alias swap (for testing)"
    )
    args = parser.parse_args()

    _load_env()
    for var in ("OPENAI_API_KEY", "HOST"):
        if var not in os.environ:
            print(f"Error: {var} not set", file=sys.stderr)
            sys.exit(1)

    os_client = _get_os_client()

    try:
        # 1. Determine next index version
        new_index = _get_next_index_name(os_client)
        print(f"\n=== Re-indexing corpus ===")
        print(f"New index: {new_index}")
        print(f"Chunk size: {args.chunk_size}, overlap: {args.chunk_overlap}")
        print(f"Title prefix: {args.title_prefix}")

        # 2. Load and chunk corpus
        print(f"\nLoading corpus from {args.corpus}...")
        docs = _load_corpus(args.corpus)
        print(f"Loaded {len(docs)} documents")

        print("Chunking...")
        chunks = _chunk_corpus(
            docs, args.chunk_size, args.chunk_overlap,
            args.title_prefix, args.footnote_enrichment,
            args.heading_based,
        )
        print(f"Created {len(chunks)} chunks")

        # 3. Create new index
        _create_index(os_client, new_index)

        # 4. Embed chunks
        print("\nEmbedding chunks...")
        start = time.time()
        chunks = _embed_chunks(chunks, contextual_embed=args.contextual_embed)
        elapsed = time.time() - start
        print(f"Embedding took {elapsed:.1f}s")

        # 5. Bulk load
        print("\nLoading into OpenSearch...")
        _bulk_load(os_client, new_index, chunks)

        # Wait for index refresh
        os_client.indices.refresh(index=new_index)
        count = os_client.count(index=new_index)
        print(f"Index {new_index} has {count['count']} documents")

        # 6. Swap alias
        if not args.skip_swap:
            print(f"\nSwapping alias '{args.alias}'...")
            _swap_alias(os_client, args.alias, new_index)
        else:
            print(f"\nSkipping alias swap (--skip-swap)")

        print("\nDone!")
        print(json.dumps({
            "index": new_index,
            "chunk_size": args.chunk_size,
            "chunk_overlap": args.chunk_overlap,
            "total_docs": len(docs),
            "total_chunks": len(chunks),
            "title_prefix": args.title_prefix,
            "footnote_enrichment": args.footnote_enrichment,
            "heading_based": args.heading_based,
            "contextual_embed": args.contextual_embed,
        }, indent=2))

    finally:
        os_client.close()


if __name__ == "__main__":
    main()
