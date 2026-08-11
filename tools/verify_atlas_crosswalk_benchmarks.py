"""Independently verify the Atlas crosswalk benchmark suite against its source archive.

A builder cannot verify itself.  Whatever join, filter, or tie-break
``tools/build_atlas_crosswalk_benchmarks.py`` gets wrong, it gets consistently
wrong: it would emit the mistake into the benchmark files *and* into any
self-check written from the same code, and the two would agree.  Agreement
between a program and its own reflection is not evidence.

So this module shares no code with the builder.  It re-derives every claim the
benchmark rows make -- membership, admission, generation class, sealed judge
outcomes, concept labels, independent verdicts -- straight from the primary
evidence, and then asks whether the emitted files agree:

* ``research/evidence/atlas-3-mapping-evidence-2026-08-05/{crosswalk}/crosswalk-bundle.json``
  supplies the 365 mapping candidates per crosswalk, their evidence artifacts
  (which carry the generation class), their ``inputContext`` artifacts (which
  carry the exact ``prefLabel`` strings the sealed judges saw), and the two
  machine validations per candidate.
* ``.../{crosswalk}/relation-assertions-v2/relation-assertions.json`` supplies
  the admitted mappings -- the only authority on what "positive" means.
* ``research/evidence/atlas-crosswalk-blind-review-2026-08-06/independent/{crosswalk}.jsonl``
  supplies the third-party blind verdicts.

Two join facts are load-bearing and easy to get wrong, so they are stated here
rather than rediscovered: an ``inputContext`` artifact joins to its candidate on
the ``(source.member, target.member)`` pair -- the artifact digest does *not*
equal ``candidate.inputContextDigest`` -- and ``mappingAssertions`` name their
endpoints ``sourceConcept``/``targetConcept``, not ``sourceMember``/``targetMember``.

Ten named checks run; each reports pass/fail with specifics.  Read-only.  Exits
non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BENCHMARKS = REPO_ROOT / "research" / "evidence" / "atlas-crosswalk-benchmarks-2026-08-06"
DEFAULT_ARCHIVE = REPO_ROOT / "research" / "evidence" / "atlas-3-mapping-evidence-2026-08-05"
DEFAULT_REVIEW = REPO_ROOT / "research" / "evidence" / "atlas-crosswalk-blind-review-2026-08-06"

#: Declaration order of the three crosswalks in the archive.
CROSSWALKS: tuple[str, ...] = ("fr-elsst", "fr-icpsr", "elsst-icpsr")

#: The four sets that must partition the candidate population.
PARTITION_SETS: tuple[str, ...] = ("positives", "hard-negatives", "controls", "disputed")

#: Every emitted evaluation set, including the non-partitioning directness view.
ALL_SETS: tuple[str, ...] = (*PARTITION_SETS, "directness")

#: Generation classes that mark a candidate as a seeded control.
CONTROL_CLASSES = frozenset({"randomNegativeControl", "siblingDistractor"})

#: Row counts the suite claims, per set.
EXPECTED_ROWS: Mapping[str, int] = {
    "positives": 582,
    "hard-negatives": 157,
    "controls": 270,
    "disputed": 86,
    "directness": 1095,
}

#: Size of the candidate population the four partition sets must cover.
EXPECTED_TOTAL = 1095

#: Minimum number of rows per set whose labels must be re-derived from source.
MIN_LABEL_SAMPLE = 50

#: Maximum number of individual failures printed per check.
MAX_DETAIL = 12

# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _short_urn(value: Any) -> str:
    """Reduce ``urn:ref:independence-group:openai`` to ``openai``."""
    text = "" if value is None else str(value)
    return text.rsplit(":", 1)[-1] if ":" in text else text


def _relation_key(value: Any) -> str:
    """Reduce a relation to its local name so URI and short forms compare equal."""
    text = ("" if value is None else str(value)).strip()
    if "#" in text:
        text = text.rsplit("#", 1)[-1]
    elif "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _canonical_forms(value: Any) -> tuple[str, str]:
    """The two byte-deterministic JSON encodings a canonical writer may emit."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False),
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalise_digest(value: Any) -> str:
    text = ("" if value is None else str(value)).strip().lower()
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    return text


def _normalise_set_name(value: str) -> str:
    text = value.strip()
    text = text.removesuffix(".jsonl")
    text = text.rsplit("/", 1)[-1]
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", text)
    return text.replace("_", "-").replace(" ", "-").lower()


def _camel(value: str) -> str:
    head, *rest = value.split("-")
    return head + "".join(part.capitalize() for part in rest)


def _limited(items: Sequence[str], limit: int = MAX_DETAIL) -> list[str]:
    if len(items) <= limit:
        return list(items)
    return [*items[:limit], f"... and {len(items) - limit} more"]


# --------------------------------------------------------------------------- #
# archive model (re-derived, never imported from the builder)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Judge:
    """One sealed machine validation of one candidate."""

    group: str
    outcome: str
    verdict_relation: str

    def key(self) -> tuple[str, str, str]:
        return (self.group, self.outcome, self.verdict_relation)


@dataclass(frozen=True)
class ArchiveCandidate:
    """Everything the primary evidence says about one mapping candidate."""

    crosswalk: str
    candidate_id: str
    source_member: str
    target_member: str
    generation_class: str
    judges: tuple[Judge, ...]
    source_label: str | None
    target_label: str | None
    task_id: str | None
    has_context: bool

    @property
    def is_control(self) -> bool:
        return self.generation_class in CONTROL_CLASSES

    @property
    def both_judges_support(self) -> bool:
        return len(self.judges) == 2 and all(judge.outcome == "supports" for judge in self.judges)

    @property
    def judges_disagree_on_relation(self) -> bool:
        relations = {judge.verdict_relation for judge in self.judges}
        return len(relations) > 1

    def judge_keys(self) -> tuple[tuple[str, str, str], ...]:
        return tuple(sorted(judge.key() for judge in self.judges))


@dataclass(frozen=True)
class Archive:
    """The candidate population plus the admitted mapping table."""

    candidates: dict[str, ArchiveCandidate]
    admitted: dict[tuple[str, str, str], str]

    def admitted_relation(self, crosswalk: Any, source: Any, target: Any) -> str | None:
        return self.admitted.get((str(crosswalk), str(source), str(target)))


def load_archive(directory: Path, crosswalks: Sequence[str] = CROSSWALKS) -> Archive:
    """Re-derive the candidate population and the admitted mappings from the archive."""
    candidates: dict[str, ArchiveCandidate] = {}
    admitted: dict[tuple[str, str, str], str] = {}

    for crosswalk in crosswalks:
        bundle = _read_json(directory / crosswalk / "crosswalk-bundle.json")
        artifacts = bundle.get("artifacts") or []

        evidence: dict[str, dict[str, Any]] = {}
        contexts: dict[tuple[Any, Any], dict[str, Any]] = {}
        for artifact in artifacts:
            role = artifact.get("role")
            content = artifact.get("content") or {}
            if role == "evidence":
                evidence[artifact.get("id")] = content
            elif role == "inputContext":
                payload = content.get("payload") or {}
                source = payload.get("source") or {}
                target = payload.get("target") or {}
                contexts[(source.get("member"), target.get("member"))] = {
                    "sourceLabel": source.get("prefLabel"),
                    "targetLabel": target.get("prefLabel"),
                    "taskId": payload.get("taskId"),
                }

        judges: dict[Any, list[Judge]] = collections.defaultdict(list)
        for validation in bundle.get("machineValidations") or []:
            candidate_ref = validation.get("candidate") or {}
            judges[candidate_ref.get("id")].append(
                Judge(
                    group=_short_urn(validation.get("independenceGroup")),
                    outcome=str(validation.get("outcome")),
                    verdict_relation=str(validation.get("verdictRelation")),
                )
            )

        for candidate in bundle.get("mappingCandidates") or []:
            refs = candidate.get("evidence") or []
            first = evidence.get(refs[0].get("id")) if refs else None
            pair = (candidate.get("sourceMember"), candidate.get("targetMember"))
            context = contexts.get(pair)
            record = ArchiveCandidate(
                crosswalk=crosswalk,
                candidate_id=str(candidate.get("id")),
                source_member=str(pair[0]),
                target_member=str(pair[1]),
                generation_class=str((first or {}).get("generationClass", "unknown")),
                judges=tuple(judges.get(candidate.get("id"), ())),
                source_label=(context or {}).get("sourceLabel"),
                target_label=(context or {}).get("targetLabel"),
                task_id=(context or {}).get("taskId"),
                has_context=context is not None,
            )
            candidates[record.candidate_id] = record

        assertions = _read_json(directory / crosswalk / "relation-assertions-v2" / "relation-assertions.json")
        for assertion in assertions.get("mappingAssertions") or []:
            key = (crosswalk, str(assertion.get("sourceConcept")), str(assertion.get("targetConcept")))
            admitted[key] = str(assertion.get("relation"))

    return Archive(candidates=candidates, admitted=admitted)


def load_independent(review: Path, crosswalks: Sequence[str] = CROSSWALKS) -> dict[tuple[str, int], dict[str, Any]]:
    """Blind third-party verdicts keyed by ``(crosswalk, row)``."""
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for crosswalk in crosswalks:
        path = review / "independent" / f"{crosswalk}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            number = _as_int(entry.get("row"))
            if number is not None:
                rows[(crosswalk, number)] = entry
    return rows


def load_blind(review: Path, crosswalks: Sequence[str] = CROSSWALKS) -> dict[tuple[str, int], dict[str, Any]]:
    """Blind row facts keyed by ``(crosswalk, row)``; empty when unavailable."""
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for crosswalk in crosswalks:
        path = review / "blind" / f"{crosswalk}.json"
        if not path.exists():
            continue
        for entry in _read_json(path).get("rows") or []:
            number = _as_int(entry.get("row"))
            if number is not None:
                rows[(crosswalk, number)] = entry
    return rows


# --------------------------------------------------------------------------- #
# emitted benchmark files
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Row:
    """One emitted benchmark row, with its source line for byte-level checks."""

    set_name: str
    line_no: int
    raw: str
    data: dict[str, Any]

    @property
    def crosswalk(self) -> Any:
        return self.data.get("crosswalk")

    @property
    def row_number(self) -> int | None:
        return _as_int(self.data.get("row"))

    @property
    def candidate_id(self) -> Any:
        return self.data.get("candidateId")

    def label(self) -> str:
        return f"{self.set_name}:{self.line_no} [{self.crosswalk}#{self.data.get('row')}] {self.candidate_id}"


@dataclass(frozen=True)
class BenchmarkFile:
    """One emitted ``.jsonl`` file plus the structural facts checks need."""

    name: str
    path: Path
    exists: bool
    line_count: int
    rows: tuple[Row, ...]
    parse_errors: tuple[str, ...]
    trailing_newline: bool
    blank_lines: tuple[int, ...]


def load_benchmark_file(directory: Path, name: str) -> BenchmarkFile:
    path = directory / f"{name}.jsonl"
    if not path.exists():
        return BenchmarkFile(name, path, False, 0, (), (), True, ())

    text = path.read_text(encoding="utf-8")
    trailing_newline = text.endswith("\n") or text == ""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]

    rows: list[Row] = []
    errors: list[str] = []
    blanks: list[int] = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            blanks.append(index)
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{name}.jsonl:{index}: not valid JSON ({exc.msg})")
            continue
        if not isinstance(parsed, dict):
            errors.append(f"{name}.jsonl:{index}: line is {type(parsed).__name__}, expected object")
            continue
        rows.append(Row(set_name=name, line_no=index, raw=line, data=parsed))

    return BenchmarkFile(
        name=name,
        path=path,
        exists=True,
        line_count=len(lines),
        rows=tuple(rows),
        parse_errors=tuple(errors),
        trailing_newline=trailing_newline,
        blank_lines=tuple(blanks),
    )


# --------------------------------------------------------------------------- #
# check plumbing
# --------------------------------------------------------------------------- #


@dataclass
class CheckResult:
    """Outcome of one named invariant check."""

    name: str
    passed: bool
    summary: str
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "passed": self.passed,
            "summary": self.summary,
            "failures": list(self.failures),
        }


def _result(name: str, summary: str, failures: Sequence[str]) -> CheckResult:
    return CheckResult(name=name, passed=not failures, summary=summary, failures=list(failures))


@dataclass
class Expectations:
    """Declared shape of the suite; overridable so tests need no real archive."""

    rows: dict[str, int] = field(default_factory=lambda: dict(EXPECTED_ROWS))
    total: int = EXPECTED_TOTAL
    label_sample: int = MIN_LABEL_SAMPLE


@dataclass(frozen=True)
class Context:
    """Everything the checks read, gathered once."""

    benchmarks: Path
    files: dict[str, BenchmarkFile]
    archive: Archive
    independent: dict[tuple[str, int], dict[str, Any]]
    blind: dict[tuple[str, int], dict[str, Any]]
    expectations: Expectations

    def rows(self, name: str) -> tuple[Row, ...]:
        file = self.files.get(name)
        return file.rows if file else ()

    def all_rows(self) -> Iterable[Row]:
        for name in ALL_SETS:
            yield from self.rows(name)

    def candidate(self, row: Row) -> ArchiveCandidate | None:
        key = row.candidate_id
        return self.archive.candidates.get(str(key)) if key is not None else None


# --------------------------------------------------------------------------- #
# check 1 -- partition
# --------------------------------------------------------------------------- #


def check_partition(ctx: Context) -> CheckResult:
    """The four sets must tile the candidate population exactly once each."""
    failures: list[str] = []
    owner: dict[str, str] = {}

    for name in PARTITION_SETS:
        counts: collections.Counter[str] = collections.Counter()
        for row in ctx.rows(name):
            if row.candidate_id is None:
                failures.append(f"{row.label()}: missing candidateId")
                continue
            counts[str(row.candidate_id)] += 1
        for candidate_id, count in sorted(counts.items()):
            if count > 1:
                failures.append(f"{name}: candidateId {candidate_id} appears {count} times")
            if candidate_id in owner:
                failures.append(f"candidateId {candidate_id} appears in both {owner[candidate_id]} and {name}")
            else:
                owner[candidate_id] = name

    covered = set(owner)
    archive_ids = set(ctx.archive.candidates)
    missing = sorted(archive_ids - covered)
    unknown = sorted(covered - archive_ids)
    for candidate_id in _limited(missing):
        failures.append(f"candidate never emitted: {candidate_id}")
    for candidate_id in _limited(unknown):
        failures.append(f"emitted candidateId absent from archive: {candidate_id}")
    if len(covered) != ctx.expectations.total:
        failures.append(f"partition covers {len(covered)} candidates, expected {ctx.expectations.total}")

    for row in ctx.all_rows():
        candidate = ctx.candidate(row)
        if candidate is None:
            continue
        if str(row.crosswalk) != candidate.crosswalk:
            failures.append(f"{row.label()}: crosswalk {row.crosswalk!r}, archive says {candidate.crosswalk!r}")

    directness_counts: collections.Counter[str] = collections.Counter(
        str(row.candidate_id) for row in ctx.rows("directness") if row.candidate_id is not None
    )
    repeated = sorted(cid for cid, count in directness_counts.items() if count > 1)
    for candidate_id in _limited(repeated):
        failures.append(f"directness: candidateId {candidate_id} appears more than once")
    directness_missing = sorted(archive_ids - set(directness_counts))
    for candidate_id in _limited(directness_missing):
        failures.append(f"directness: candidate never emitted: {candidate_id}")

    summary = (
        f"{len(covered)} candidates covered once across {len(PARTITION_SETS)} sets; "
        f"directness covers {len(directness_counts)}"
    )
    return _result("partition", summary, failures)


# --------------------------------------------------------------------------- #
# check 2 -- counts
# --------------------------------------------------------------------------- #


def check_counts(ctx: Context) -> CheckResult:
    """Every set must hold exactly the number of rows the suite claims."""
    failures: list[str] = []
    observed: list[str] = []

    for name in ALL_SETS:
        file = ctx.files.get(name)
        expected = ctx.expectations.rows.get(name)
        if file is None or not file.exists:
            failures.append(f"{name}.jsonl: file missing")
            observed.append(f"{name}=missing")
            continue
        observed.append(f"{name}={file.line_count}")
        if expected is not None and file.line_count != expected:
            failures.append(f"{name}.jsonl: {file.line_count} lines, expected {expected}")

    partition_total = sum(ctx.files[name].line_count for name in PARTITION_SETS if name in ctx.files)
    if partition_total != ctx.expectations.total:
        failures.append(f"partition sets total {partition_total} rows, expected {ctx.expectations.total}")

    return _result("counts", ", ".join(observed), failures)


# --------------------------------------------------------------------------- #
# check 3 -- positives are admitted
# --------------------------------------------------------------------------- #


def check_positives_admitted(ctx: Context) -> CheckResult:
    """Positives must be exactly the mappings the archive actually admitted."""
    failures: list[str] = []
    matched = 0

    for row in ctx.rows("positives"):
        relation = ctx.archive.admitted_relation(
            row.crosswalk, row.data.get("sourceMember"), row.data.get("targetMember")
        )
        if relation is None:
            failures.append(
                f"{row.label()}: pair "
                f"({row.data.get('sourceMember')!r}, {row.data.get('targetMember')!r}) "
                f"is not in mappingAssertions"
            )
            continue
        emitted = row.data.get("admittedRelation")
        if emitted is None:
            failures.append(f"{row.label()}: missing admittedRelation (archive says {relation})")
            continue
        if _relation_key(emitted) != _relation_key(relation):
            failures.append(f"{row.label()}: admittedRelation {emitted!r}, archive says {relation!r}")
            continue
        matched += 1

    total_admitted = len(ctx.archive.admitted)
    emitted_pairs = {
        (str(row.crosswalk), str(row.data.get("sourceMember")), str(row.data.get("targetMember")))
        for row in ctx.rows("positives")
    }
    unclaimed = sorted(set(ctx.archive.admitted) - emitted_pairs)
    for key in _limited(unclaimed):
        failures.append(f"admitted mapping never emitted as a positive: {key[0]} {key[1]} -> {key[2]}")

    summary = (
        f"{matched}/{len(ctx.rows('positives'))} positives matched an admitted assertion ({total_admitted} in archive)"
    )
    return _result("positives-admitted", summary, failures)


# --------------------------------------------------------------------------- #
# check 4 -- controls are never admitted
# --------------------------------------------------------------------------- #


def check_controls_never_admitted(ctx: Context) -> CheckResult:
    """Seeded controls must be control-class and must never have been admitted."""
    failures: list[str] = []
    kinds: dict[str, set[str]] = collections.defaultdict(set)

    for row in ctx.rows("controls"):
        relation = ctx.archive.admitted_relation(
            row.crosswalk, row.data.get("sourceMember"), row.data.get("targetMember")
        )
        if relation is not None:
            failures.append(f"{row.label()}: control appears in mappingAssertions as {relation}")

        emitted_class = row.data.get("generationClass")
        if emitted_class not in CONTROL_CLASSES:
            failures.append(f"{row.label()}: generationClass {emitted_class!r} is not a control class")

        candidate = ctx.candidate(row)
        if candidate is None:
            failures.append(f"{row.label()}: candidateId absent from archive")
            continue
        if not candidate.is_control:
            failures.append(f"{row.label()}: archive generationClass is {candidate.generation_class!r}, not a control")
        elif emitted_class != candidate.generation_class:
            failures.append(
                f"{row.label()}: generationClass {emitted_class!r}, archive says {candidate.generation_class!r}"
            )

        kind = row.data.get("controlKind")
        if not isinstance(kind, str) or not kind.strip():
            failures.append(f"{row.label()}: missing or empty controlKind")
        else:
            kinds[kind].add(str(candidate.generation_class))

    for kind, classes in sorted(kinds.items()):
        if len(classes) > 1:
            failures.append(f"controlKind {kind!r} spans generation classes {sorted(classes)}")

    archive_controls = {cid for cid, cand in ctx.archive.candidates.items() if cand.is_control}
    emitted_controls = {str(row.candidate_id) for row in ctx.rows("controls")}
    for candidate_id in _limited(sorted(archive_controls - emitted_controls)):
        failures.append(f"control-class candidate not emitted as a control: {candidate_id}")

    summary = f"{len(ctx.rows('controls'))} controls, {len(kinds)} controlKind values, none admitted"
    return _result("controls-never-admitted", summary, failures)


# --------------------------------------------------------------------------- #
# check 5 -- disputed really are disputed
# --------------------------------------------------------------------------- #


def _emitted_judges(row: Row) -> tuple[tuple[str, str, str], ...] | None:
    judges = row.data.get("sealedJudges")
    if not isinstance(judges, list):
        return None
    keys: list[tuple[str, str, str]] = []
    for judge in judges:
        if not isinstance(judge, dict):
            return None
        keys.append(
            (
                _short_urn(judge.get("group")),
                str(judge.get("outcome")),
                str(judge.get("verdictRelation")),
            )
        )
    return tuple(sorted(keys))


def check_disputed_are_disputed(ctx: Context) -> CheckResult:
    """Disputed rows are candidates both judges supported yet nobody admitted."""
    failures: list[str] = []
    differing = 0
    total = len(ctx.rows("disputed"))

    for row in ctx.rows("disputed"):
        judges = row.data.get("sealedJudges")
        if not isinstance(judges, list) or len(judges) != 2:
            count = len(judges) if isinstance(judges, list) else "none"
            failures.append(f"{row.label()}: {count} sealed judges, expected exactly 2")
        elif not all(isinstance(j, dict) and j.get("outcome") == "supports" for j in judges):
            outcomes = [j.get("outcome") if isinstance(j, dict) else j for j in judges]
            failures.append(f"{row.label()}: sealed outcomes {outcomes}, expected both 'supports'")

        relation = ctx.archive.admitted_relation(
            row.crosswalk, row.data.get("sourceMember"), row.data.get("targetMember")
        )
        if relation is not None:
            failures.append(f"{row.label()}: disputed row was admitted as {relation}")

        candidate = ctx.candidate(row)
        if candidate is None:
            failures.append(f"{row.label()}: candidateId absent from archive")
            continue
        if not candidate.both_judges_support:
            outcomes = [judge.outcome for judge in candidate.judges]
            failures.append(f"{row.label()}: archive sealed outcomes {outcomes}, expected both 'supports'")
        if candidate.is_control:
            failures.append(f"{row.label()}: control-class candidate ({candidate.generation_class}) filed as disputed")
        emitted = _emitted_judges(row)
        if emitted is not None and emitted != candidate.judge_keys():
            failures.append(
                f"{row.label()}: sealedJudges {list(emitted)} disagree with archive {list(candidate.judge_keys())}"
            )
        if candidate.judges_disagree_on_relation:
            differing += 1

    share = f"{differing}/{total}" if total else "0/0"
    summary = f"{total} disputed rows; {share} carry two different verdictRelation values"
    return _result("disputed-are-disputed", summary, failures)


# --------------------------------------------------------------------------- #
# check 6 -- hard negatives are genuinely rejected
# --------------------------------------------------------------------------- #


def check_hard_negatives_rejected(ctx: Context) -> CheckResult:
    """Hard negatives are real rejections: not admitted, not controls, not unanimous."""
    failures: list[str] = []

    for row in ctx.rows("hard-negatives"):
        relation = ctx.archive.admitted_relation(
            row.crosswalk, row.data.get("sourceMember"), row.data.get("targetMember")
        )
        if relation is not None:
            failures.append(f"{row.label()}: hard negative was admitted as {relation}")

        candidate = ctx.candidate(row)
        if candidate is None:
            failures.append(f"{row.label()}: candidateId absent from archive")
            continue
        if candidate.is_control:
            failures.append(
                f"{row.label()}: control-class candidate ({candidate.generation_class}) filed as hard negative"
            )
        if candidate.both_judges_support:
            relations = [judge.verdict_relation for judge in candidate.judges]
            failures.append(
                f"{row.label()}: both sealed judges support ({relations}) -- this is disputed, not rejected"
            )
        emitted = _emitted_judges(row)
        if emitted is not None and emitted != candidate.judge_keys():
            failures.append(
                f"{row.label()}: sealedJudges {list(emitted)} disagree with archive {list(candidate.judge_keys())}"
            )
        if row.data.get("generationClass") != candidate.generation_class:
            failures.append(
                f"{row.label()}: generationClass {row.data.get('generationClass')!r}, "
                f"archive says {candidate.generation_class!r}"
            )

    summary = f"{len(ctx.rows('hard-negatives'))} hard negatives, none admitted, none unanimous, none control"
    return _result("hard-negatives-rejected", summary, failures)


# --------------------------------------------------------------------------- #
# check 7 -- labels match source
# --------------------------------------------------------------------------- #


def check_labels_match_source(ctx: Context) -> CheckResult:
    """Emitted labels must be the exact strings the sealed judges were shown."""
    failures: list[str] = []
    checked: dict[str, int] = {}

    contexts: dict[tuple[str, str, str], ArchiveCandidate] = {
        (cand.crosswalk, cand.source_member, cand.target_member): cand for cand in ctx.archive.candidates.values()
    }

    for name in ALL_SETS:
        rows = ctx.rows(name)
        checked[name] = len(rows)
        for row in rows:
            candidate = ctx.candidate(row)
            source = row.data.get("sourceMember")
            target = row.data.get("targetMember")
            mismatched = candidate is not None and (
                str(source) != candidate.source_member or str(target) != candidate.target_member
            )
            if mismatched and candidate is not None:
                failures.append(
                    f"{row.label()}: members ({source!r}, {target!r}) disagree with archive "
                    f"({candidate.source_member!r}, {candidate.target_member!r})"
                )
                continue
            context = contexts.get((str(row.crosswalk), str(source), str(target)))
            if context is None:
                failures.append(f"{row.label()}: no archive inputContext for ({source!r}, {target!r})")
                continue
            if not context.has_context:
                failures.append(f"{row.label()}: archive candidate has no inputContext artifact")
                continue
            if row.data.get("sourceLabel") != context.source_label:
                failures.append(
                    f"{row.label()}: sourceLabel {row.data.get('sourceLabel')!r}, "
                    f"inputContext says {context.source_label!r}"
                )
            if row.data.get("targetLabel") != context.target_label:
                failures.append(
                    f"{row.label()}: targetLabel {row.data.get('targetLabel')!r}, "
                    f"inputContext says {context.target_label!r}"
                )
            if "taskId" in row.data and row.data.get("taskId") != context.task_id:
                failures.append(
                    f"{row.label()}: taskId {row.data.get('taskId')!r}, inputContext says {context.task_id!r}"
                )

    for name, count in checked.items():
        available = ctx.files[name].line_count if name in ctx.files else 0
        wanted = min(ctx.expectations.label_sample, available)
        if count < wanted:
            failures.append(f"{name}: only {count} rows label-checked, needed at least {wanted}")

    summary = ", ".join(f"{name}={count}" for name, count in checked.items())
    return _result("labels-match-source", f"labels re-derived for {summary}", failures)


# --------------------------------------------------------------------------- #
# check 8 -- independent verdicts joined correctly
# --------------------------------------------------------------------------- #


def check_independent_verdicts(ctx: Context) -> CheckResult:
    """The blind reviewer's verdicts must be carried across without drift."""
    failures: list[str] = []
    joined = 0

    if not ctx.independent:
        return _result(
            "independent-verdicts",
            "no independent blind-review rows available",
            ["independent/*.jsonl not found or empty; verdict claims cannot be verified"],
        )

    for row in ctx.all_rows():
        number = row.row_number
        if number is None:
            failures.append(f"{row.label()}: missing or non-integer row number")
            continue
        entry = ctx.independent.get((str(row.crosswalk), number))
        if entry is None:
            failures.append(f"{row.label()}: no independent review row for ({row.crosswalk}, {number})")
            continue
        joined += 1
        if row.data.get("independentVerdict") != entry.get("verdict"):
            failures.append(
                f"{row.label()}: independentVerdict {row.data.get('independentVerdict')!r}, "
                f"review says {entry.get('verdict')!r}"
            )
        if row.data.get("independentDirectness") != entry.get("directness"):
            failures.append(
                f"{row.label()}: independentDirectness {row.data.get('independentDirectness')!r}, "
                f"review says {entry.get('directness')!r}"
            )

        blind = ctx.blind.get((str(row.crosswalk), number))
        if blind is None:
            continue
        blind_source = (blind.get("source") or {}).get("member")
        blind_target = (blind.get("target") or {}).get("member")
        if row.data.get("sourceMember") != blind_source or row.data.get("targetMember") != blind_target:
            failures.append(
                f"{row.label()}: row number points at blind pair ({blind_source!r}, {blind_target!r}), "
                f"but the row carries ({row.data.get('sourceMember')!r}, {row.data.get('targetMember')!r})"
            )

    scope = (
        "row join cross-checked against blind rows"
        if ctx.blind
        else "blind rows unavailable, row join not cross-checked"
    )
    return _result("independent-verdicts", f"{joined} rows joined to independent verdicts; {scope}", failures)


# --------------------------------------------------------------------------- #
# check 9 -- manifest integrity
# --------------------------------------------------------------------------- #

_SET_CONTAINER_KEYS = ("sets", "evaluationSets", "datasets", "files", "evaluationFiles")
_ROW_KEYS = ("rows", "rowCount", "lines", "lineCount", "count", "records")
_DIGEST_KEYS = ("sha256", "digest", "contentDigest", "sha256Digest", "fileDigest")
_NAME_KEYS = ("set", "name", "id", "file", "path", "fileName", "filename")


def _manifest_descriptors(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Locate the per-set descriptors without assuming one manifest shape."""
    for key in _SET_CONTAINER_KEYS:
        container = manifest.get(key)
        if isinstance(container, Mapping) and container:
            found = {
                _normalise_set_name(str(name)): value for name, value in container.items() if isinstance(value, Mapping)
            }
            if found:
                return found
        if isinstance(container, list) and container:
            found = {}
            for value in container:
                if not isinstance(value, Mapping):
                    continue
                for name_key in _NAME_KEYS:
                    raw = value.get(name_key)
                    if isinstance(raw, str) and raw.strip():
                        found[_normalise_set_name(raw)] = value
                        break
            if found:
                return found

    found = {}
    for name in ALL_SETS:
        for key in (name, _camel(name), f"{name}.jsonl"):
            value = manifest.get(key)
            if isinstance(value, Mapping):
                found[name] = value
                break
    return found


def _first_value(descriptor: Mapping[str, Any], keys: Sequence[str], predicate: Callable[[Any], bool]) -> Any:
    for key in keys:
        if key in descriptor and predicate(descriptor[key]):
            return descriptor[key]
    return None


def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes)):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def check_manifest_integrity(ctx: Context) -> CheckResult:
    """The manifest must describe the files that are actually on disk."""
    failures: list[str] = []
    path = ctx.benchmarks / "manifest.json"
    if not path.exists():
        return _result("manifest-integrity", "manifest.json missing", ["manifest.json not found"])

    try:
        manifest = _read_json(path)
    except json.JSONDecodeError as exc:
        return _result("manifest-integrity", "manifest.json unparseable", [f"manifest.json: {exc.msg}"])
    if not isinstance(manifest, Mapping):
        return _result(
            "manifest-integrity", "manifest.json is not an object", ["manifest.json: top level is not an object"]
        )

    if not _non_empty(manifest.get("populationBias")):
        failures.append("manifest.json: top-level populationBias is missing or empty")

    descriptors = _manifest_descriptors(manifest)
    if not descriptors:
        failures.append("manifest.json: no per-set descriptors found")

    verified = 0
    for name in ALL_SETS:
        descriptor = descriptors.get(name)
        if descriptor is None:
            failures.append(f"manifest.json: no descriptor for set {name!r}")
            continue

        file = ctx.files.get(name)
        declared_rows = _first_value(descriptor, _ROW_KEYS, lambda v: _as_int(v) is not None)
        if declared_rows is None:
            failures.append(f"manifest.json[{name}]: no declared row count")
        elif file is None or not file.exists:
            failures.append(f"manifest.json[{name}]: declares {_as_int(declared_rows)} rows but the file is missing")
        elif _as_int(declared_rows) != file.line_count:
            failures.append(
                f"manifest.json[{name}]: declares {_as_int(declared_rows)} rows, file holds {file.line_count}"
            )

        declared_digest = _first_value(descriptor, _DIGEST_KEYS, lambda v: isinstance(v, str) and v.strip())
        if declared_digest is None:
            failures.append(f"manifest.json[{name}]: no declared sha256")
        elif file is None or not file.exists:
            failures.append(f"manifest.json[{name}]: declares a sha256 but the file is missing")
        else:
            actual = _sha256(file.path)
            if _normalise_digest(declared_digest) != actual:
                failures.append(
                    f"manifest.json[{name}]: declares sha256 {_normalise_digest(declared_digest)}, file digests {actual}"
                )
            else:
                verified += 1

        if not _non_empty(descriptor.get("usableFor")):
            failures.append(f"manifest.json[{name}]: usableFor is missing or empty")
        if not _non_empty(descriptor.get("notUsableFor")):
            failures.append(f"manifest.json[{name}]: notUsableFor is missing or empty")

    summary = f"{verified}/{len(ALL_SETS)} declared digests reproduced; populationBias present={_non_empty(manifest.get('populationBias'))}"
    return _result("manifest-integrity", summary, failures)


# --------------------------------------------------------------------------- #
# check 10 -- determinism
# --------------------------------------------------------------------------- #


def _crosswalk_ranks() -> tuple[Callable[[Any], Any], ...]:
    declaration = {name: index for index, name in enumerate(CROSSWALKS)}
    return (
        lambda value: str(value),
        lambda value: (declaration.get(str(value), len(declaration)), str(value)),
    )


def check_determinism(ctx: Context) -> CheckResult:
    """Rows must be stably ordered and written in a canonical, byte-stable form."""
    failures: list[str] = []
    canonical_lines = 0
    total_lines = 0

    for name in ALL_SETS:
        file = ctx.files.get(name)
        if file is None or not file.exists:
            failures.append(f"{name}.jsonl: file missing")
            continue

        failures.extend(file.parse_errors)
        for line_no in file.blank_lines:
            failures.append(f"{name}.jsonl:{line_no}: blank line")
        if not file.trailing_newline:
            failures.append(f"{name}.jsonl: file does not end with a newline")

        observed = [(str(row.crosswalk), row.row_number) for row in file.rows]
        if any(number is None for _, number in observed):
            failures.append(f"{name}.jsonl: at least one row has a missing or non-integer row number")
        else:
            ordered = False
            for rank in _crosswalk_ranks():
                if observed == sorted(observed, key=lambda pair: (rank(pair[0]), pair[1])):
                    ordered = True
                    break
            if not ordered:
                first_bad = next(
                    (index for index in range(1, len(observed)) if observed[index - 1] > observed[index]),
                    None,
                )
                where = f" (first break at line {file.rows[first_bad].line_no})" if first_bad is not None else ""
                failures.append(f"{name}.jsonl: rows are not sorted by (crosswalk, row){where}")
            if len(set(observed)) != len(observed):
                failures.append(f"{name}.jsonl: duplicate (crosswalk, row) keys")

        for row in file.rows:
            total_lines += 1
            if row.raw in _canonical_forms(row.data):
                canonical_lines += 1
            else:
                failures.append(f"{name}.jsonl:{row.line_no}: line is not canonical JSON (key order or spacing)")

    summary = f"{canonical_lines}/{total_lines} lines canonical; ordering checked for {len(ALL_SETS)} sets"
    return _result("determinism", summary, _limited(failures, MAX_DETAIL * 2))


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #

_CHECKS: tuple[Callable[[Context], CheckResult], ...] = (
    check_partition,
    check_counts,
    check_positives_admitted,
    check_controls_never_admitted,
    check_disputed_are_disputed,
    check_hard_negatives_rejected,
    check_labels_match_source,
    check_independent_verdicts,
    check_manifest_integrity,
    check_determinism,
)


def build_context(
    benchmarks: Path,
    archive: Path,
    review: Path,
    expectations: Expectations | None = None,
    crosswalks: Sequence[str] = CROSSWALKS,
) -> Context:
    """Read everything once: emitted files, primary archive, blind review."""
    return Context(
        benchmarks=benchmarks,
        files={name: load_benchmark_file(benchmarks, name) for name in ALL_SETS},
        archive=load_archive(archive, crosswalks),
        independent=load_independent(review, crosswalks),
        blind=load_blind(review, crosswalks),
        expectations=expectations or Expectations(),
    )


def verify(
    benchmarks: Path,
    archive: Path,
    review: Path,
    expectations: Expectations | None = None,
    crosswalks: Sequence[str] = CROSSWALKS,
) -> list[CheckResult]:
    """Run every named check and return the results in declaration order."""
    ctx = build_context(benchmarks, archive, review, expectations, crosswalks)
    return [check(ctx) for check in _CHECKS]


def render(results: Sequence[CheckResult]) -> str:
    """Render the compact pass/fail table plus specifics for every failure."""
    width = max((len(result.name) for result in results), default=10)
    lines = [f"{'check'.ljust(width)}  result  detail", f"{'-' * width}  ------  {'-' * 48}"]
    for result in results:
        lines.append(f"{result.name.ljust(width)}  {'PASS' if result.passed else 'FAIL':<6}  {result.summary}")
    passed = sum(1 for result in results if result.passed)
    lines.append(f"{'-' * width}  ------  {'-' * 48}")
    lines.append(f"{passed}/{len(results)} checks passed")

    failed = [result for result in results if not result.passed]
    if failed:
        lines.append("")
        lines.append("FAILURES")
        for result in failed:
            lines.append(f"  {result.name}:")
            for detail in _limited(result.failures):
                lines.append(f"    - {detail}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Independently verify the Atlas crosswalk benchmark suite against its source archive.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--benchmarks", type=Path, default=DEFAULT_BENCHMARKS, help="emitted benchmark directory")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE, help="atlas-3 mapping evidence archive")
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW, help="blind review directory")
    parser.add_argument("--output", type=Path, default=None, help="write the results as JSON")
    args = parser.parse_args(argv)

    if not args.benchmarks.exists():
        print(f"benchmark directory not found: {args.benchmarks}")
        return 2
    if not args.archive.exists():
        print(f"archive directory not found: {args.archive}")
        return 2

    results = verify(args.benchmarks, args.archive, args.review)

    print(f"benchmarks : {args.benchmarks}")
    print(f"archive    : {args.archive}")
    print(f"review     : {args.review}")
    print()
    print(render(results))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {"results": [result.as_dict() for result in results]}
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\nwrote {args.output}")

    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
