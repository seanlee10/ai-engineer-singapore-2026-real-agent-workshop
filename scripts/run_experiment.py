#!/usr/bin/env python3
"""Run an Arize experiment against the LangGraph agent."""
import json
import os
import sys
import urllib.request

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

# Load env vars from agent/.env
env_path = os.path.join(os.path.dirname(__file__), "..", "agent", ".env")
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))

from arize import ArizeClient
from arize.experiments import EvaluationResult

DATASET_ID = "RGF0YXNldDozNDUyOTg6UW5CaQ=="  # legal-rag-bench
LANGGRAPH_URL = "http://127.0.0.1:2024"


def invoke_agent(question: str) -> dict:
    """Call the LangGraph agent via HTTP."""
    url = f"{LANGGRAPH_URL}/runs/wait"
    payload = {
        "assistant_id": "agent",
        "input": {"messages": [{"role": "user", "content": question}]},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def task(dataset_row):
    return invoke_agent(dataset_row.get("question", ""))


def get_sources(output):
    return [doc.get("metadata", {}).get("source", "") for doc in output.get("docs", [])]


def recall_at_1_evaluator(output, dataset_row):
    relevant_id = dataset_row.get("relevant_passage_id", "")
    sources = get_sources(output)
    is_hit = relevant_id in sources[:1]
    return EvaluationResult(
        score=float(is_hit),
        label="hit" if is_hit else "miss",
        explanation=f"relevant: {relevant_id}, top-1: {sources[:1]}",
    )


def recall_at_5_evaluator(output, dataset_row):
    relevant_id = dataset_row.get("relevant_passage_id", "")
    sources = get_sources(output)
    is_hit = relevant_id in sources[:5]
    rank = sources.index(relevant_id) + 1 if is_hit else None
    return EvaluationResult(
        score=float(is_hit),
        label="hit" if is_hit else "miss",
        explanation=f"relevant: {relevant_id}, rank: {rank}, top-5: {sources[:5]}",
    )


def recall_at_10_evaluator(output, dataset_row):
    relevant_id = dataset_row.get("relevant_passage_id", "")
    sources = get_sources(output)
    is_hit = relevant_id in sources[:10]
    rank = sources.index(relevant_id) + 1 if is_hit else None
    return EvaluationResult(
        score=float(is_hit),
        label="hit" if is_hit else "miss",
        explanation=f"relevant: {relevant_id}, rank: {rank}, sources: {sources}",
    )


if __name__ == "__main__":
    experiment_name = sys.argv[1] if len(sys.argv) > 1 else "ralph-experiment"
    client = ArizeClient(api_key=os.environ["ARIZE_API_KEY"])

    print(f"Running Arize experiment: {experiment_name}")
    print(f"LangGraph agent: {LANGGRAPH_URL}")
    print(f"Dataset: {DATASET_ID}")

    experiment, df = client.experiments.run(
        name=experiment_name,
        dataset=DATASET_ID,
        task=task,
        evaluators=[recall_at_1_evaluator, recall_at_5_evaluator, recall_at_10_evaluator],
        dry_run=False,
    )

    # Print metrics summary
    print("\n=== Experiment Results ===")
    for eval_name in ["recall_at_1_evaluator", "recall_at_5_evaluator", "recall_at_10_evaluator"]:
        col = f"eval.{eval_name}.score"
        if col in df.columns:
            print(f"  {eval_name}: {df[col].mean():.1%}")
