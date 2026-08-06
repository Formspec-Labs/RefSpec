"""Focused checks for the hosted (frontier) embedding batch arms."""

from __future__ import annotations

import json

import numpy as np
import pytest

from tools import benchmark_atlas_frontier_embedding_recovery as provider


def _concept(label: str, *, definition: str | None = None) -> dict[str, object]:
    return {"label": label, "altLabels": [], "definition": definition, "notes": None}


def test_env_is_parsed_without_export_prefixes_or_quotes(tmp_path) -> None:
    (tmp_path / ".env").write_text(
        'OPENAI_API_KEY="sk-test"\nexport GEMINI_API_KEY=gk-test\n# comment\n\n',
        encoding="utf-8",
    )

    env = provider.load_env(tmp_path)

    assert env["OPENAI_API_KEY"] == "sk-test"
    assert env["GEMINI_API_KEY"] == "gk-test"


def test_missing_env_fails_closed(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        provider.load_env(tmp_path)


def test_arm_texts_are_view_major_so_slices_line_up_with_concepts() -> None:
    concepts = [_concept("A"), _concept("B")]
    arm = provider.ARMS[0]

    texts = provider.arm_texts(concepts, arm)

    assert len(texts) == len(concepts) * len(provider.VIEWS)
    # The collector slices [view_index * concepts : ...], so the first block must
    # be exactly the first view over every concept in order.
    assert texts[:2] == [provider.dense.view_text(concept, provider.VIEWS[0]) for concept in concepts]


def test_instruction_prefix_is_applied_for_models_without_a_task_type_field() -> None:
    gemini2 = next(arm for arm in provider.ARMS if arm.key == "gemini-2")

    texts = provider.arm_texts([_concept("Housing")], gemini2)

    assert gemini2.task_type is None
    assert all(text.startswith(provider.GEMINI_2_INSTRUCTION) for text in texts)


def test_task_type_arms_send_no_instruction_prefix() -> None:
    retrieval = next(arm for arm in provider.ARMS if arm.key == "gemini-001-ret")

    texts = provider.arm_texts([_concept("Housing")], retrieval)

    assert retrieval.task_type == "RETRIEVAL_DOCUMENT"
    assert texts[0] == "Housing"


def test_legacy_ada_arm_omits_the_dimensions_parameter() -> None:
    ada = next(arm for arm in provider.ARMS if arm.key == "openai-ada-002")
    sized = next(arm for arm in provider.ARMS if arm.key == "openai-3-large")

    # ada-002 has a fixed width and rejects an explicit dimensions request.
    assert ada.dimensions is None
    assert sized.dimensions == provider.OUTPUT_DIMENSIONS


def test_openai_batch_lines_carry_many_inputs_and_a_recoverable_offset(tmp_path) -> None:
    captured: dict[str, object] = {}

    class _Files:
        def create(self, file, purpose):
            captured["body"] = file.read()
            return type("F", (), {"id": "file-1"})()

    class _Batches:
        def create(self, **kwargs):
            captured["endpoint"] = kwargs["endpoint"]
            captured["window"] = kwargs["completion_window"]
            return type("B", (), {"id": "batch-1"})()

    client = type("C", (), {"files": _Files(), "batches": _Batches()})()
    arm = next(arm for arm in provider.ARMS if arm.key == "openai-3-small")
    texts = [f"t{index}" for index in range(provider.OPENAI_INPUTS_PER_LINE + 5)]

    (submission,) = provider.submit_openai(client, arm, "src", texts, tmp_path)

    lines = [json.loads(line) for line in captured["body"].decode().strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["custom_id"] == "openai-3-small|src|0"
    assert lines[1]["custom_id"] == f"openai-3-small|src|{provider.OPENAI_INPUTS_PER_LINE}"
    assert len(lines[0]["body"]["input"]) == provider.OPENAI_INPUTS_PER_LINE
    assert lines[0]["body"]["dimensions"] == provider.OUTPUT_DIMENSIONS
    assert captured["endpoint"] == "/v1/embeddings"
    # The input file must outlive the completion window; a one-hour lifetime
    # made the sealed experiment's first batch process zero rows.
    assert captured["window"] == "24h"
    assert submission.stop == len(texts)


def test_openai_collection_restores_global_order_from_chunk_offsets() -> None:
    payload = "\n".join(
        json.dumps(
            {
                "custom_id": f"a|s|{offset}",
                "response": {
                    "body": {
                        "data": [
                            {"index": position, "embedding": [float(value)]} for position, value in enumerate(values)
                        ]
                    }
                },
            }
        )
        # Deliberately out of order to prove the collector sorts by offset.
        for offset, values in ((2, [3.0, 4.0]), (0, [1.0, 2.0]))
    )

    class _Client:
        batches = type(
            "B",
            (),
            {"retrieve": staticmethod(lambda _id: type("R", (), {"status": "completed", "output_file_id": "f"})())},
        )()
        files = type("F", (), {"content": staticmethod(lambda _id: type("C", (), {"text": payload})())})()

    submission = provider.Submission("a", "s", "openai", "batch-1", 0, 4)
    vectors = provider.collect_openai(_Client(), submission, expected=4)

    assert vectors.ravel().tolist() == [1.0, 2.0, 3.0, 4.0]


def test_openai_collection_rejects_a_short_result() -> None:
    class _Client:
        batches = type(
            "B",
            (),
            {"retrieve": staticmethod(lambda _id: type("R", (), {"status": "completed", "output_file_id": "f"})())},
        )()
        files = type("F", (), {"content": staticmethod(lambda _id: type("C", (), {"text": ""})())})()

    submission = provider.Submission("a", "s", "openai", "batch-1", 0, 4)

    with pytest.raises(RuntimeError, match="expected 4"):
        provider.collect_openai(_Client(), submission, expected=4)


def test_incomplete_batch_raises_so_the_poller_keeps_waiting() -> None:
    class _Client:
        batches = type("B", (), {"retrieve": staticmethod(lambda _id: type("R", (), {"status": "in_progress"})())})()

    submission = provider.Submission("a", "s", "openai", "batch-1", 0, 4)

    with pytest.raises(RuntimeError, match="in_progress"):
        provider.collect_openai(_Client(), submission, expected=4)


def test_normalise_produces_unit_rows_and_tolerates_a_zero_vector() -> None:
    vectors = np.asarray([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)

    unit = provider.normalise(vectors)

    assert np.isclose(np.linalg.norm(unit[0]), 1.0)
    assert np.all(np.isfinite(unit[1]))
