"""End-to-end smoke test for the self-improving RAG orchestrator.

Starts the orchestrator, creates an experiment with legal-rag-bench data,
polls until completion, and prints final metrics.

Usage:
    uv run python scripts/smoke_test.py
    uv run python scripts/smoke_test.py --iterations 3
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

try:
    import urllib.request
    import urllib.error
    import urllib.parse
except ImportError:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR_DIR = REPO_ROOT / "orchestrator"
INDEX_DIR = REPO_ROOT / "index"
CORPUS_FILE = INDEX_DIR / "legal-rag-bench-corpus.csv"
QA_FILE = INDEX_DIR / "legal-rag-bench-qa.csv"

BASE_URL = "http://127.0.0.1:{port}"
POLL_INTERVAL = 15  # seconds between status checks
TIMEOUT = 600  # 10 minutes


def find_free_port() -> int:
    """Find an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(base_url: str, timeout: int = 30) -> None:
    """Wait until the orchestrator's /health endpoint responds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{base_url}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    raise TimeoutError(f"Orchestrator did not start within {timeout}s")


def create_experiment(
    base_url: str, name: str, max_iterations: int
) -> dict[str, str]:
    """Create an experiment via multipart POST to /experiments."""
    boundary = "----SmokeTestBoundary"
    parts: list[bytes] = []

    # Form fields
    for field_name, value in [
        ("name", name),
        ("domain_hint", "legal"),
        ("max_iterations", str(max_iterations)),
    ]:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )

    # Corpus file
    corpus_data = CORPUS_FILE.read_bytes()
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="corpus_files"; '
        f'filename="{CORPUS_FILE.name}"\r\n'
        f"Content-Type: text/csv\r\n\r\n".encode()
        + corpus_data
        + b"\r\n"
    )

    # QA file
    qa_data = QA_FILE.read_bytes()
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="qa_pairs_file"; '
        f'filename="{QA_FILE.name}"\r\n'
        f"Content-Type: text/csv\r\n\r\n".encode()
        + qa_data
        + b"\r\n"
    )

    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        f"{base_url}/experiments",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def poll_experiment(
    base_url: str, experiment_id: str, timeout: int = TIMEOUT
) -> dict[str, object]:
    """Poll GET /experiments/{id} until completed, error, or timeout."""
    deadline = time.time() + timeout
    terminal_statuses = {"Complete", "Stopped"}

    while time.time() < deadline:
        req = urllib.request.Request(f"{base_url}/experiments/{experiment_id}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        status = data.get("status", "")
        current_iter = data.get("currentIteration", 0)
        print(f"  Status: {status} | Iteration: {current_iter}")

        if status in terminal_statuses:
            return data
        if status == "error":
            return data

        time.sleep(POLL_INTERVAL)

    raise TimeoutError(
        f"Experiment did not complete within {timeout}s"
    )


METRIC_NAMES = [
    ("hallucinationRate", "Hallucination"),
    ("faithfulness", "Faithfulness"),
    ("recallAt1", "Recall@1"),
    ("recallAt5", "Recall@5"),
    ("answerRelevance", "AnswerRel"),
    ("contextRelevance", "ContextRel"),
]


def print_metrics(experiment: dict[str, object]) -> None:
    """Print final status and per-iteration metrics table."""
    iterations = experiment.get("iterations", [])
    if not iterations:
        print("\n  No iterations completed.")
        return

    print(f"\n  Final Status: {experiment.get('status')}")
    print(f"  Iterations:   {len(iterations)}")

    # Per-iteration metrics table
    header = f"  {'Iter':>4}  " + "  ".join(f"{name:>13}" for _, name in METRIC_NAMES)
    print(f"\n{header}")
    print(f"  {'----':>4}  " + "  ".join("-" * 13 for _ in METRIC_NAMES))

    for it in iterations:
        metrics = it.get("metrics", {})
        num = it.get("number", "?")
        values = "  ".join(
            f"{metrics.get(key, 0):>13.4f}" for key, _ in METRIC_NAMES
        )
        print(f"  {num:>4}  {values}")


def print_config_changes(experiment: dict[str, object]) -> None:
    """Print config changes made at each iteration."""
    iterations = experiment.get("iterations", [])
    print("\n  Config changes per iteration:")

    for it in iterations:
        num = it.get("number", "?")
        diff = it.get("configDiff", [])
        if not diff:
            print(f"    Iteration {num}: (baseline / no changes)")
        else:
            print(f"    Iteration {num}:")
            for change in diff:
                param = change.get("parameter", "?")
                old = change.get("oldValue", "?")
                new = change.get("newValue", "?")
                print(f"      {param}: {old} -> {new}")


def verify_results(experiment: dict[str, object]) -> list[str]:
    """Run verifications and return list of failure messages (empty = all pass)."""
    failures: list[str] = []
    iterations = experiment.get("iterations", [])

    # Verify metrics are non-zero for all 6 metrics in every iteration
    for it in iterations:
        num = it.get("number", "?")
        metrics = it.get("metrics", {})
        for key, name in METRIC_NAMES:
            val = metrics.get(key, 0)
            if val == 0:
                failures.append(
                    f"Iteration {num}: {name} is zero"
                )

    # Verify at least one config parameter changed between iteration 1 and 2
    if len(iterations) >= 2:
        second_iter = iterations[1]
        diff = second_iter.get("configDiff", [])
        if not diff:
            failures.append(
                "No config changes between iteration 1 and iteration 2"
            )
    else:
        failures.append(
            f"Expected at least 2 iterations, got {len(iterations)}"
        )

    return failures


def main() -> int:
    """Run the smoke test."""
    parser = argparse.ArgumentParser(description="Self-improving RAG smoke test")
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Max iterations for the experiment (default: 1)",
    )
    args = parser.parse_args()

    # Validate data files exist
    for path in [CORPUS_FILE, QA_FILE]:
        if not path.exists():
            print(f"ERROR: Required data file not found: {path}")
            return 1

    port = find_free_port()
    base_url = BASE_URL.format(port=port)
    experiment_name = f"smoke-test-{int(time.time())}"

    print(f"Starting orchestrator on port {port}...")
    server_proc = subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "orchestrator.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(ORCHESTRATOR_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        wait_for_server(base_url)
        print("Orchestrator is ready.\n")

        print(f"Creating experiment '{experiment_name}' with max_iterations={args.iterations}...")
        result = create_experiment(base_url, experiment_name, args.iterations)
        experiment_id = result["id"]
        print(f"  Experiment ID: {experiment_id}\n")

        print("Polling for completion...")
        experiment = poll_experiment(base_url, experiment_id)
        status = experiment.get("status", "")

        print_metrics(experiment)
        print_config_changes(experiment)

        # Save results to JSON
        results_path = REPO_ROOT / "scripts" / "smoke_test_results.json"
        results_path.write_text(json.dumps(experiment, indent=2))
        print(f"\n  Results saved to: {results_path}")

        if status != "Complete":
            print(f"\n  FAILED (status: {status})")
            return 1

        # Run verifications
        failures = verify_results(experiment)
        if failures:
            print("\n  VERIFICATION FAILURES:")
            for f in failures:
                print(f"    - {f}")
            print(f"\n  FAILED ({len(failures)} verification(s) failed)")
            return 1

        print("\n  PASSED (all verifications passed)")
        return 0

    except TimeoutError as e:
        print(f"\nERROR: {e}")
        return 1
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"\nERROR: HTTP {e.code} — {body}")
        return 1
    except Exception as e:
        print(f"\nERROR: {e}")
        return 1
    finally:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
