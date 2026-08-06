"""E3 frontier half: hosted embedding arms over the ablated Atlas corpus, via Batch.

Runs the same ablated corpus as the local dense sweep through OpenAI and Google
hosted embedding models, using each provider's asynchronous Batch tier rather
than synchronous calls.  The sealed provider experiment in the candidate ledger
priced its arms at the standard rate because it never used a batch tier; both
providers now discount batch work by 50%, and Google exposes
``asyncBatchEmbedContent`` on every current embedding model.

Arms are submitted in parallel and polled together, because batch jobs are
independent and latency-bound rather than CPU-bound.  This is the opposite of
the local sweep, where model families run strictly one after another to stay
inside memory.

Ranking reuses ``benchmark_atlas_dense_relation_recovery.blockwise_min_ranks``
and writes the identical compact ``npz`` layout, so hosted arms drop straight
into the frontier stage beside the local ones.

Job identifiers are persisted as soon as a submission returns, so a collection
pass can resume against work already paid for instead of resubmitting it.

Credentials are read from the workspace ``.env`` and never logged.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import benchmark_atlas_dense_relation_recovery as dense

VIEWS = dense.VIEWS

#: Shared output width.  The sealed provider comparison used 768 dimensions on
#: every arm, and both providers support Matryoshka truncation to it.
OUTPUT_DIMENSIONS = 768

#: ``gemini-embedding-2`` takes its task instruction in the prompt rather than
#: through the ``task_type`` field its predecessor uses.
GEMINI_2_INSTRUCTION = "task: semantic similarity | text: "


@dataclass(frozen=True, slots=True)
class Arm:
    key: str
    provider: str
    model: str
    task_type: str | None = None
    instruction: str = ""
    dimensions: int | None = OUTPUT_DIMENSIONS
    rate_per_million_batch: float = 0.0


ARMS: tuple[Arm, ...] = (
    Arm("openai-3-small", "openai", "text-embedding-3-small", rate_per_million_batch=0.010),
    Arm("openai-3-large", "openai", "text-embedding-3-large", rate_per_million_batch=0.065),
    Arm("openai-ada-002", "openai", "text-embedding-ada-002", dimensions=None, rate_per_million_batch=0.050),
    Arm(
        "gemini-001-sim",
        "google",
        "gemini-embedding-001",
        task_type="SEMANTIC_SIMILARITY",
        rate_per_million_batch=0.075,
    ),
    Arm(
        "gemini-001-ret", "google", "gemini-embedding-001", task_type="RETRIEVAL_DOCUMENT", rate_per_million_batch=0.075
    ),
    Arm("gemini-2", "google", "gemini-embedding-2", instruction=GEMINI_2_INSTRUCTION, rate_per_million_batch=0.100),
    Arm(
        "gemini-2-preview",
        "google",
        "gemini-embedding-2-preview",
        instruction=GEMINI_2_INSTRUCTION,
        rate_per_million_batch=0.100,
    ),
)

#: One OpenAI batch line carries many inputs; one Google job carries many
#: contents.  Both are bounded so a single failure costs one chunk, not an arm.
OPENAI_INPUTS_PER_LINE = 200
GOOGLE_CONTENTS_PER_JOB = 5_000


@dataclass
class Submission:
    """One provider job covering a contiguous slice of one arm's text list."""

    arm: str
    source: str
    provider: str
    job_id: str
    start: int
    stop: int
    extra: dict[str, Any] = field(default_factory=dict)


def load_env(workspace: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    path = workspace / ".env"
    if not path.exists():
        raise FileNotFoundError(f"no .env at {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if match:
            env[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return env


def arm_texts(concepts: list[dict[str, Any]], arm: Arm) -> list[str]:
    """Render every view for every concept as one flat, order-stable list."""
    texts: list[str] = []
    for view in VIEWS:
        for concept in concepts:
            texts.append(arm.instruction + dense.view_text(concept, view))
    return texts


def submit_openai(client: Any, arm: Arm, source: str, texts: list[str], scratch: Path) -> list[Submission]:
    lines = []
    for index in range(0, len(texts), OPENAI_INPUTS_PER_LINE):
        chunk = texts[index : index + OPENAI_INPUTS_PER_LINE]
        body: dict[str, Any] = {"model": arm.model, "input": chunk}
        if arm.dimensions:
            body["dimensions"] = arm.dimensions
        lines.append(
            json.dumps(
                {
                    "custom_id": f"{arm.key}|{source}|{index}",
                    "method": "POST",
                    "url": "/v1/embeddings",
                    "body": body,
                }
            )
        )
    path = scratch / f"{arm.key}.{source}.batch.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with path.open("rb") as handle:
        uploaded = client.files.create(file=handle, purpose="batch")
    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/embeddings",
        completion_window="24h",
        metadata={"arm": arm.key, "source": source},
    )
    return [Submission(arm.key, source, "openai", batch.id, 0, len(texts), {"input_file_id": uploaded.id})]


def submit_google(client: Any, arm: Arm, source: str, texts: list[str]) -> list[Submission]:
    from google.genai import types

    config: dict[str, Any] = {}
    if arm.task_type:
        config["task_type"] = arm.task_type
    if arm.dimensions:
        config["output_dimensionality"] = arm.dimensions

    submissions: list[Submission] = []
    for index in range(0, len(texts), GOOGLE_CONTENTS_PER_JOB):
        chunk = texts[index : index + GOOGLE_CONTENTS_PER_JOB]
        job = client.batches.create_embeddings(
            model=arm.model,
            src=types.EmbeddingsBatchJobSource(
                inlined_requests=types.EmbedContentBatch(
                    contents=chunk,
                    config=types.EmbedContentConfig(**config) if config else None,
                )
            ),
            config={"display_name": f"atlas-e3-{arm.key}-{source}-{index}"[:60]},
        )
        submissions.append(Submission(arm.key, source, "google", job.name, index, index + len(chunk)))
    return submissions


#: The synchronous Google endpoint rejects more than 100 inputs per call.
GOOGLE_SYNC_CHUNK = 100

#: Google meters ``embed_content`` per *text*, not per call, at 5,000 per minute
#: per model on the paid tier.  Packing 100 texts into one call therefore spends
#: 100 units of quota, so the sweep must be paced rather than only retried.
GOOGLE_TEXTS_PER_MINUTE = 4_200


class _Pacer:
    """Keep a rolling one-minute window under a text budget."""

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.window: deque[tuple[float, int]] = deque()

    def reserve(self, count: int) -> None:
        while True:
            now = time.monotonic()
            while self.window and now - self.window[0][0] >= 60.0:
                self.window.popleft()
            spent = sum(entry[1] for entry in self.window)
            if spent + count <= self.budget or not self.window:
                self.window.append((now, count))
                return
            time.sleep(max(0.5, 60.0 - (now - self.window[0][0])))


def embed_google_sync(client: Any, arm: Arm, texts: list[str], *, pacer: _Pacer, retries: int = 5) -> np.ndarray:
    """Embed through the synchronous endpoint, preserving request order exactly.

    The Batch path returned vectors that did not correspond to their inputs:
    ELSST rank-1 neighbours came back as ``TRUCKS``/``NEWS ITEMS`` where this
    path gives ``TRUCKS``/``COMPANY CARS``.  Responses here are positional
    within a bounded call, so ordering cannot drift.
    """
    from google.genai import types

    config: dict[str, Any] = {}
    if arm.task_type:
        config["task_type"] = arm.task_type
    if arm.dimensions:
        config["output_dimensionality"] = arm.dimensions

    vectors: list[list[float]] = []
    for index in range(0, len(texts), GOOGLE_SYNC_CHUNK):
        chunk = texts[index : index + GOOGLE_SYNC_CHUNK]
        for attempt in range(retries):
            pacer.reserve(len(chunk))
            try:
                response = client.models.embed_content(
                    model=arm.model,
                    contents=chunk,
                    config=types.EmbedContentConfig(**config) if config else None,
                )
                break
            except Exception as error:
                if attempt == retries - 1:
                    raise
                # A quota rejection needs the rolling window to drain, not a
                # short exponential backoff that retries inside the same minute.
                time.sleep(65.0 if "RESOURCE_EXHAUSTED" in str(error) else 2**attempt)
        if len(response.embeddings) != len(chunk):
            raise RuntimeError(f"{arm.key}: chunk at {index} returned {len(response.embeddings)} of {len(chunk)}")
        vectors.extend(item.values for item in response.embeddings)
    return np.asarray(vectors, dtype=np.float32)


def collect_openai(client: Any, submission: Submission, expected: int) -> np.ndarray:
    batch = client.batches.retrieve(submission.job_id)
    if batch.status != "completed":
        raise RuntimeError(f"{submission.arm}/{submission.source}: batch status {batch.status}")
    content = client.files.content(batch.output_file_id).text
    slots: dict[int, list[list[float]]] = {}
    for line in content.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        offset = int(row["custom_id"].rsplit("|", 1)[1])
        data = row["response"]["body"]["data"]
        slots[offset] = [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]
    vectors: list[list[float]] = []
    for offset in sorted(slots):
        vectors.extend(slots[offset])
    if len(vectors) != expected:
        raise RuntimeError(f"{submission.arm}/{submission.source}: got {len(vectors)} vectors, expected {expected}")
    return np.asarray(vectors, dtype=np.float32)


def collect_google(client: Any, submission: Submission) -> np.ndarray:
    job = client.batches.get(name=submission.job_id)
    if job.state.name != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(f"{submission.arm}/{submission.source}: job state {job.state.name}")
    responses = job.dest.inlined_embed_content_responses
    vectors = []
    for position, item in enumerate(responses):
        if item.error is not None:
            raise RuntimeError(f"{submission.arm}/{submission.source}: row {position} returned {item.error}")
        vectors.append(list(item.response.embedding.values))
    return np.asarray(vectors, dtype=np.float32)


def normalise(vectors: np.ndarray) -> np.ndarray:
    """L2-normalise; gemini-embedding-001 requires this for truncated widths."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def write_ranks(
    output: Path, arm: Arm, source: str, vectors: np.ndarray, concepts: int, top_k: int, block: int
) -> dict[str, Any]:
    payload: dict[str, np.ndarray] = {"conceptCount": np.asarray([concepts], dtype=np.uint32)}
    meta: dict[str, Any] = {}
    for position, view in enumerate(VIEWS):
        window = normalise(vectors[position * concepts : (position + 1) * concepts])
        ranks = dense.blockwise_min_ranks(window, top_k, block)
        codes = np.fromiter(ranks.keys(), dtype=np.uint32, count=len(ranks))
        values = np.fromiter(ranks.values(), dtype=np.uint8, count=len(ranks))
        order = np.argsort(codes, kind="stable")
        payload[f"{view}.codes"] = codes[order]
        payload[f"{view}.ranks"] = values[order]
        meta[view] = {"retainedPairs": len(ranks), "dimensions": int(window.shape[1])}
    np.savez_compressed(output / f"{arm.key}.{source}.npz", **payload)
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=ROOT.parent)
    parser.add_argument("--arm", action="append", choices=[arm.key for arm in ARMS])
    parser.add_argument("--source", action="append")
    parser.add_argument("--mode", choices=("submit", "collect", "run", "google-sync"), default="run")
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--query-block-size", type=int, default=256)
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    sources = {entry["source"]: entry for entry in corpus["sources"]}
    selected_sources = args.source or list(sources)
    arms = [arm for arm in ARMS if not args.arm or arm.key in args.arm]
    args.output.mkdir(parents=True, exist_ok=True)
    args.state.parent.mkdir(parents=True, exist_ok=True)
    scratch = args.state.parent

    env = load_env(args.workspace)
    state: dict[str, Any] = json.loads(args.state.read_text()) if args.state.exists() else {"submissions": []}
    existing = {(row["arm"], row["source"]) for row in state["submissions"]}

    openai_client = google_client = None
    if any(arm.provider == "openai" for arm in arms):
        from openai import OpenAI

        openai_client = OpenAI(api_key=env["OPENAI_API_KEY"])
    if any(arm.provider == "google" for arm in arms):
        from google import genai

        google_client = genai.Client(api_key=env["GEMINI_API_KEY"])

    if args.mode == "google-sync":
        pacer = _Pacer(GOOGLE_TEXTS_PER_MINUTE)
        for arm in (spec for spec in arms if spec.provider == "google"):
            for source in selected_sources:
                target = args.output / f"{arm.key}.{source}.npz"
                if target.exists():
                    print(f"  skip {arm.key} {source} (already present)")
                    continue
                concepts = sources[source]["concepts"]
                texts = arm_texts(concepts, arm)
                started = time.time()
                vectors = embed_google_sync(google_client, arm, texts, pacer=pacer)
                if vectors.shape[0] != len(texts):
                    raise RuntimeError(f"{arm.key}/{source}: {vectors.shape[0]} vectors for {len(texts)} texts")
                write_ranks(args.output, arm, source, vectors, len(concepts), args.top_k, args.query_block_size)
                print(
                    f"  synced {arm.key:<18} {source:<34} texts={len(texts):<6} "
                    f"dim={vectors.shape[1]} {time.time() - started:.0f}s"
                )
        return 0

    if args.mode in ("submit", "run"):
        for arm in arms:
            for source in selected_sources:
                if (arm.key, source) in existing or (args.output / f"{arm.key}.{source}.npz").exists():
                    print(f"  skip {arm.key} {source} (already submitted or collected)")
                    continue
                texts = arm_texts(sources[source]["concepts"], arm)
                if arm.provider == "openai":
                    submissions = submit_openai(openai_client, arm, source, texts, scratch)
                else:
                    submissions = submit_google(google_client, arm, source, texts)
                for submission in submissions:
                    state["submissions"].append(submission.__dict__)
                args.state.write_text(json.dumps(state, indent=2), encoding="utf-8")
                print(f"  submitted {arm.key:<18} {source:<34} texts={len(texts):<6} jobs={len(submissions)}")

    if args.mode in ("collect", "run"):
        by_arm = {arm.key: arm for arm in ARMS}
        deadline = time.time() + args.timeout_seconds
        pending = [
            row for row in state["submissions"] if not (args.output / f"{row['arm']}.{row['source']}.npz").exists()
        ]
        while pending and time.time() < deadline:
            grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for row in pending:
                grouped.setdefault((row["arm"], row["source"]), []).append(row)
            done_now = []
            for (arm_key, source), rows in sorted(grouped.items()):
                arm = by_arm[arm_key]
                concepts = len(sources[source]["concepts"])
                expected = concepts * len(VIEWS)
                try:
                    parts = []
                    for row in sorted(rows, key=lambda item: item["start"]):
                        submission = Submission(**{k: v for k, v in row.items()})
                        parts.append(
                            collect_openai(openai_client, submission, expected)
                            if arm.provider == "openai"
                            else collect_google(google_client, submission)
                        )
                    vectors = np.concatenate(parts, axis=0)
                    if vectors.shape[0] != expected:
                        raise RuntimeError(f"{arm_key}/{source}: {vectors.shape[0]} vectors, expected {expected}")
                    meta = write_ranks(args.output, arm, source, vectors, concepts, args.top_k, args.query_block_size)
                    print(f"  collected {arm_key:<18} {source:<34} dim={meta[VIEWS[0]]['dimensions']}")
                    done_now.append((arm_key, source))
                except RuntimeError as error:
                    print(f"  waiting  {arm_key:<18} {source:<34} {error}")
            pending = [row for row in pending if (row["arm"], row["source"]) not in done_now]
            if pending:
                time.sleep(args.poll_seconds)
        if pending:
            print(f"\n{len(pending)} job group(s) still incomplete; rerun with --mode collect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
