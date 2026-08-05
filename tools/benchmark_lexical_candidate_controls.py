"""Benchmark deterministic lexical controls for Atlas relation discovery.

This tool measures candidate discovery only. It keeps mapping-relation
semantics separate from the surface-text challenges that retrieval must solve.
It reuses the OAEI and Atlas input adapters from the broader candidate
benchmark without changing that shared tool.

Run the complete Conference matrix with a pinned optional dependency:

    uv run --with 'rapidfuzz==3.14.3' \
      tools/benchmark_lexical_candidate_controls.py \
      --root /tmp/refspec-candidate-benchmark.ANhNrc \
      --suite conference --output /tmp/lexical-conference.json \
      --labeled-pool-output /tmp/candidate-kind-pool.json

Anatomy and Atlas default to a practical subset. Pass ``--profile full`` to
run every arm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from refspec.atlas.qualification import AtlasConcept
from refspec.storage import canonical_json

try:
    from tools import benchmark_atlas_candidate_retrieval as shared_benchmark
except ImportError:  # Direct execution places tools/ on sys.path.
    import benchmark_atlas_candidate_retrieval as shared_benchmark


DEFAULT_TOP_K = (1, 2, 3, 5, 10, 20, 50, 100)
SCORE_MULTIPLIER = 1_000_000
PAIR_SOURCE_BITS = 24
PAIR_CASE_BITS = 16
PAIR_TARGET_MASK = (1 << PAIR_SOURCE_BITS) - 1
PAIR_SOURCE_MASK = (1 << PAIR_SOURCE_BITS) - 1


@dataclass(frozen=True, slots=True)
class ScorerSpec:
    """One scorer and the exact text representation supplied to it."""

    name: str
    metric: str
    representation: str
    family: str
    higher_is_better: bool = True


SCORER_SPECS = (
    ScorerSpec("levenshtein-distance", "levenshtein-distance", "raw-label", "edit", False),
    ScorerSpec("normalized-levenshtein", "normalized-levenshtein", "normalized-label", "edit"),
    ScorerSpec("rapidfuzz-ratio", "ratio", "normalized-label", "rapidfuzz-label"),
    ScorerSpec("rapidfuzz-partial-ratio", "partial-ratio", "normalized-label", "rapidfuzz-label"),
    ScorerSpec("rapidfuzz-token-sort-ratio", "token-sort-ratio", "normalized-label", "rapidfuzz-label"),
    ScorerSpec("rapidfuzz-token-set-ratio", "token-set-ratio", "normalized-label", "rapidfuzz-label"),
    ScorerSpec("rapidfuzz-wratio", "wratio", "normalized-label", "rapidfuzz-label"),
    ScorerSpec("rapidfuzz-qratio", "qratio", "normalized-label", "rapidfuzz-label"),
    ScorerSpec("jaro", "jaro", "normalized-label", "edit"),
    ScorerSpec("jaro-winkler", "jaro-winkler", "normalized-label", "edit"),
    ScorerSpec("compact-jaro-winkler", "jaro-winkler", "compact-label", "edit"),
    ScorerSpec("token-sorted-qratio", "qratio", "token-sorted-label", "token-variant"),
    ScorerSpec("alias-token-set-ratio", "token-set-ratio", "alias-bag", "field-variant"),
    ScorerSpec("alias-wratio", "wratio", "alias-bag", "field-variant"),
    ScorerSpec("identifier-qratio", "qratio", "identifier", "field-variant"),
    ScorerSpec("acronym-token-set-ratio", "token-set-ratio", "acronym", "field-variant"),
    ScorerSpec("character-trigram-token-set", "token-set-ratio", "character-trigrams", "character"),
)
SCORER_BY_NAME = {spec.name: spec for spec in SCORER_SPECS}
PRACTICAL_ARM_NAMES = frozenset(
    {
        "levenshtein-distance",
        "normalized-levenshtein",
        "rapidfuzz-token-set-ratio",
        "rapidfuzz-wratio",
        "compact-jaro-winkler",
        "alias-wratio",
        "identifier-qratio",
    }
)
UNION_MEMBERS = {
    "edit-control-union": frozenset(
        {
            "levenshtein-distance",
            "normalized-levenshtein",
            "jaro",
            "jaro-winkler",
            "compact-jaro-winkler",
        }
    ),
    "rapidfuzz-label-union": frozenset(
        {
            "rapidfuzz-ratio",
            "rapidfuzz-partial-ratio",
            "rapidfuzz-token-sort-ratio",
            "rapidfuzz-token-set-ratio",
            "rapidfuzz-wratio",
            "rapidfuzz-qratio",
            "token-sorted-qratio",
        }
    ),
    "field-variant-union": frozenset(
        {
            "alias-token-set-ratio",
            "alias-wratio",
            "identifier-qratio",
            "acronym-token-set-ratio",
            "character-trigram-token-set",
        }
    ),
    "lexical-control-union": frozenset(spec.name for spec in SCORER_SPECS),
}

REPRESENTATION_DESCRIPTIONS = {
    "raw-label": "NFKC and case-folded preferred label; punctuation and spacing remain significant",
    "normalized-label": "diacritic-folded, camel-case-split, lowercase alphanumeric preferred-label tokens",
    "compact-label": "normalized preferred label with token boundaries removed",
    "token-sorted-label": "normalized preferred-label tokens in lexical order",
    "alias-bag": "sorted unique preferred and alternate labels after normalization",
    "identifier": "normalized local IRI identifier",
    "acronym": "sorted acronym, initial-subsequence, and explicit abbreviation keys",
    "character-trigrams": "sorted unique boundary-padded trigrams from the compact normalized label",
}

CHALLENGE_TAXONOMY = {
    "lexical-exact": "Preferred labels become equal after declared normalization.",
    "lexical-near": "Preferred labels differ but retain strong edit or Jaro-Winkler similarity.",
    "alias-synonym": "An alternate label supplies a stronger cross-vocabulary match than the preferred labels.",
    "identifier-code": "Local identifiers or code-like strings supply material matching evidence.",
    "abbreviation": "An acronym or abbreviation bridges the two labels.",
    "definition-semantic": "Definitions share material content when labels provide weak evidence.",
    "hierarchy-graph": "Parent or child labels provide material cross-vocabulary evidence.",
    "broader-narrower-granularity": "One label adds or removes substantive tokens, creating a granularity gap.",
    "inverse-directional-property": "Property labels express related roles from opposite directions.",
    "compound-compositional": "A multi-token concept is composed from a shorter concept phrase.",
    "token-reordered": "The same main tokens occur in a materially different order.",
    "substring-fragment": "One surface form appears as a strong substring of the other.",
    "semantic-gap": "Expert alignment bridges labels without a strong declared lexical or structural signal.",
}

MAPPING_RELATION_SEMANTICS = {
    "exact": "The mapping asserts equivalence or exact matching.",
    "close": "The mapping asserts a close but non-identical meaning.",
    "broad": "The target is broader than the source.",
    "narrow": "The target is narrower than the source.",
    "related": "The mapping asserts an associative relation.",
}
ALIGNMENT_RELATION_TO_SEMANTIC = {
    "=": "exact",
    "~": "close",
    ">": "broad",
    "<": "narrow",
    "related": "related",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _normalized_tokens(value: str) -> tuple[str, ...]:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", unicodedata.normalize("NFKC", value))
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(character for character in folded if not unicodedata.combining(character))
    return tuple(token for token in re.split(r"[^0-9a-z]+", folded) if token)


def _normalized_label(value: str) -> str:
    return " ".join(_normalized_tokens(value))


def _raw_label(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _identifier(value: str) -> str:
    parsed = urlparse(value)
    tail = parsed.fragment or parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if parsed.scheme == "urn":
        tail = value.rsplit(":", 1)[-1]
    return _normalized_label(unquote(tail))


def _acronym(value: str) -> str:
    tokens = _normalized_tokens(value)
    return "".join(token[0] for token in tokens) if len(tokens) > 1 else "".join(tokens)


def _abbreviation_keys(value: str) -> tuple[str, ...]:
    tokens = _normalized_tokens(value)
    keys: set[str] = set()
    if len(tokens) > 1:
        initials = "".join(token[0] for token in tokens)
        for start in range(len(initials)):
            for end in range(start + 2, len(initials) + 1):
                keys.add(initials[start:end])
    for raw_token in re.findall(r"[A-Za-z0-9]+", value):
        normalized = _normalized_label(raw_token).replace(" ", "")
        if 2 <= len(normalized) <= 8 and (raw_token.isupper() or not set(normalized) & set("aeiou")):
            keys.add(normalized)
    if len(tokens) == 1 and 2 <= len(tokens[0]) <= 8:
        keys.add(tokens[0])
    return tuple(sorted(keys))


def _character_trigrams(value: str) -> str:
    compact = "".join(_normalized_tokens(value))
    if not compact:
        return ""
    padded = f"^^{compact}$$"
    return " ".join(sorted({padded[index : index + 3] for index in range(len(padded) - 2)}))


def representation_text(concept: AtlasConcept, representation: str) -> str:
    """Return the declared deterministic string for one scorer arm."""

    if representation == "raw-label":
        return _raw_label(concept.pref_label)
    normalized = _normalized_label(concept.pref_label)
    if representation == "normalized-label":
        return normalized
    if representation == "compact-label":
        return normalized.replace(" ", "")
    if representation == "token-sorted-label":
        return " ".join(sorted(normalized.split()))
    if representation == "alias-bag":
        labels = {_normalized_label(value) for value in (concept.pref_label, *concept.alt_labels)}
        return " ; ".join(sorted(value for value in labels if value))
    if representation == "identifier":
        return _identifier(concept.member)
    if representation == "acronym":
        return " ".join(_abbreviation_keys(concept.pref_label))
    if representation == "character-trigrams":
        return _character_trigrams(concept.pref_label)
    raise ValueError(f"unsupported representation {representation!r}")


def _rapidfuzz_components() -> tuple[Any, Any, Any, Any, Any, Any]:
    try:
        import numpy as np
        import rapidfuzz
        from rapidfuzz import fuzz, process
        from rapidfuzz.distance import Jaro, JaroWinkler, Levenshtein
    except ImportError as error:
        raise RuntimeError("RapidFuzz is required; run with uv run --with 'rapidfuzz==3.14.3'") from error
    return np, rapidfuzz, fuzz, process, (Levenshtein, Jaro, JaroWinkler), np.int32


def _scorer(spec: ScorerSpec) -> tuple[Callable[..., Any], int]:
    _np, _rapidfuzz, fuzz, _process, distances, _dtype = _rapidfuzz_components()
    levenshtein, jaro, jaro_winkler = distances
    scorers: dict[str, tuple[Callable[..., Any], int]] = {
        "levenshtein-distance": (levenshtein.distance, 1),
        "normalized-levenshtein": (levenshtein.normalized_similarity, SCORE_MULTIPLIER),
        "ratio": (fuzz.ratio, SCORE_MULTIPLIER),
        "partial-ratio": (fuzz.partial_ratio, SCORE_MULTIPLIER),
        "token-sort-ratio": (fuzz.token_sort_ratio, SCORE_MULTIPLIER),
        "token-set-ratio": (fuzz.token_set_ratio, SCORE_MULTIPLIER),
        "wratio": (fuzz.WRatio, SCORE_MULTIPLIER),
        "qratio": (fuzz.QRatio, SCORE_MULTIPLIER),
        "jaro": (jaro.similarity, SCORE_MULTIPLIER),
        "jaro-winkler": (jaro_winkler.similarity, SCORE_MULTIPLIER),
    }
    return scorers[spec.metric]


def score_matrix(
    queries: Sequence[str],
    choices: Sequence[str],
    *,
    spec: ScorerSpec,
    workers: int,
) -> Any:
    """Return an integer score matrix with the arm's declared direction."""

    _np, _rapidfuzz, _fuzz, process, _distances, dtype = _rapidfuzz_components()
    scorer, multiplier = _scorer(spec)
    return process.cdist(
        list(queries),
        list(choices),
        scorer=scorer,
        score_multiplier=multiplier,
        dtype=dtype,
        workers=workers,
    )


def stable_top_indices(row: Any, *, higher_is_better: bool, top_k: int) -> tuple[int, ...]:
    """Rank one score row with a stable index tie-break."""

    np, _rapidfuzz, _fuzz, _process, _distances, _dtype = _rapidfuzz_components()
    values = -np.asarray(row, dtype=np.int64) if higher_is_better else np.asarray(row, dtype=np.int64)
    return tuple(int(value) for value in np.argsort(values, kind="stable")[:top_k])


@dataclass(frozen=True, slots=True)
class PairCodec:
    """Compact pair identifiers tied to canonical case and member ordering."""

    case_names: tuple[str, ...]
    sources: tuple[tuple[str, ...], ...]
    targets: tuple[tuple[str, ...], ...]

    @classmethod
    def from_cases(cls, cases: Sequence[Any]) -> PairCodec:
        ordered = tuple(sorted(cases, key=lambda case: case.name))
        sources = tuple(tuple(sorted(concept.member for concept in case.sources)) for case in ordered)
        targets = tuple(tuple(sorted(concept.member for concept in case.targets)) for case in ordered)
        if len(ordered) >= 1 << PAIR_CASE_BITS:
            raise ValueError("too many cases for deterministic pair encoding")
        if any(len(values) >= 1 << PAIR_SOURCE_BITS for values in (*sources, *targets)):
            raise ValueError("too many concepts for deterministic pair encoding")
        return cls(tuple(case.name for case in ordered), sources, targets)

    def code(self, case_index: int, source_index: int, target_index: int) -> int:
        return (case_index << (PAIR_SOURCE_BITS * 2)) | (source_index << PAIR_SOURCE_BITS) | target_index

    def decode(self, code: int) -> tuple[str, str, str]:
        case_index = code >> (PAIR_SOURCE_BITS * 2)
        source_index = (code >> PAIR_SOURCE_BITS) & PAIR_SOURCE_MASK
        target_index = code & PAIR_TARGET_MASK
        return (
            self.case_names[case_index],
            self.sources[case_index][source_index],
            self.targets[case_index][target_index],
        )


def _canonical_cases(cases: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(sorted(cases, key=lambda case: case.name))


def _gold_codes(cases: Sequence[Any], codec: PairCodec) -> frozenset[int]:
    result = set()
    for case_index, case in enumerate(_canonical_cases(cases)):
        source_indexes = {member: index for index, member in enumerate(codec.sources[case_index])}
        target_indexes = {member: index for index, member in enumerate(codec.targets[case_index])}
        result.update(
            codec.code(case_index, source_indexes[source], target_indexes[target]) for source, target in case.gold
        )
    return frozenset(result)


def _pair_line(codec: PairCodec, code: int) -> bytes:
    case, source, target = codec.decode(code)
    return f"{case}\t{source}\t{target}\n".encode()


def _summarize_pair_ranks(
    pair_ranks: Mapping[int, int],
    *,
    top_ks: Sequence[int],
    gold: frozenset[int],
    codec: PairCodec,
    include_misses: bool = False,
) -> tuple[list[dict[str, Any]], dict[int, frozenset[int]]]:
    hashers = {top_k: hashlib.sha256() for top_k in top_ks}
    counts = {top_k: 0 for top_k in top_ks}
    for code, rank in sorted(pair_ranks.items()):
        line = _pair_line(codec, code)
        for top_k in top_ks:
            if rank <= top_k:
                counts[top_k] += 1
                hashers[top_k].update(line)
    coverage = {
        top_k: frozenset(code for code in gold if pair_ranks.get(code, max(top_ks) + 1) <= top_k) for top_k in top_ks
    }
    results = []
    for top_k in top_ks:
        item: dict[str, Any] = {
            "topK": top_k,
            "candidates": counts[top_k],
            "found": len(coverage[top_k]),
            "recall": round(len(coverage[top_k]) / len(gold), 9) if gold else None,
            "pairSetDigest": "sha256:" + hashers[top_k].hexdigest(),
        }
        if include_misses:
            item["missedGold"] = [
                {"case": case, "source": source, "target": target}
                for case, source, target in (codec.decode(code) for code in sorted(gold - coverage[top_k]))
            ]
        results.append(item)
    return results, coverage


def run_arm(
    cases: Sequence[Any],
    *,
    spec: ScorerSpec,
    top_ks: Sequence[int],
    codec: PairCodec,
    gold: frozenset[int],
    workers: int,
    block_size: int,
) -> tuple[dict[str, Any], dict[int, int], dict[int, frozenset[int]]]:
    """Run exact bidirectional top-k for one scorer arm."""

    np, rapidfuzz, _fuzz, _process, _distances, _dtype = _rapidfuzz_components()
    maximum = max(top_ks)
    pair_ranks: dict[int, int] = {}
    feature_hasher = hashlib.sha256()
    ranking_hasher = hashlib.sha256()
    started = time.monotonic()
    for case_index, case in enumerate(_canonical_cases(cases)):
        source_by_member = {concept.member: concept for concept in case.sources}
        target_by_member = {concept.member: concept for concept in case.targets}
        sources = tuple(source_by_member[member] for member in codec.sources[case_index])
        targets = tuple(target_by_member[member] for member in codec.targets[case_index])
        source_texts = tuple(representation_text(concept, spec.representation) for concept in sources)
        target_texts = tuple(representation_text(concept, spec.representation) for concept in targets)
        for role, concepts, texts in (("source", sources, source_texts), ("target", targets, target_texts)):
            for concept, text in zip(concepts, texts, strict=True):
                feature_hasher.update(f"{case.name}\t{role}\t{concept.member}\t{text}\n".encode())

        for start in range(0, len(sources), block_size):
            source_block = source_texts[start : start + block_size]
            matrix = score_matrix(source_block, target_texts, spec=spec, workers=workers)
            ranking_values = -matrix.astype(np.int64) if spec.higher_is_better else matrix.astype(np.int64)
            orders = np.argsort(ranking_values, axis=1, kind="stable")[:, : min(maximum, len(targets))]
            for local_source_index, target_indexes in enumerate(orders):
                source_index = start + local_source_index
                for rank, target_index_value in enumerate(target_indexes, start=1):
                    target_index = int(target_index_value)
                    code = codec.code(case_index, source_index, target_index)
                    pair_ranks[code] = min(rank, pair_ranks.get(code, maximum + 1))
                    score = int(matrix[local_source_index, target_index])
                    ranking_hasher.update(
                        f"{case.name}\tforward\t{sources[source_index].member}\t"
                        f"{targets[target_index].member}\t{rank}\t{score}\n".encode()
                    )
            del orders, ranking_values, matrix

        for start in range(0, len(targets), block_size):
            target_block = target_texts[start : start + block_size]
            matrix = score_matrix(target_block, source_texts, spec=spec, workers=workers)
            ranking_values = -matrix.astype(np.int64) if spec.higher_is_better else matrix.astype(np.int64)
            orders = np.argsort(ranking_values, axis=1, kind="stable")[:, : min(maximum, len(sources))]
            for local_target_index, source_indexes in enumerate(orders):
                target_index = start + local_target_index
                for rank, source_index_value in enumerate(source_indexes, start=1):
                    source_index = int(source_index_value)
                    code = codec.code(case_index, source_index, target_index)
                    pair_ranks[code] = min(rank, pair_ranks.get(code, maximum + 1))
                    score = int(matrix[local_target_index, source_index])
                    ranking_hasher.update(
                        f"{case.name}\treverse\t{targets[target_index].member}\t"
                        f"{sources[source_index].member}\t{rank}\t{score}\n".encode()
                    )
            del orders, ranking_values, matrix

    results, coverage = _summarize_pair_ranks(
        pair_ranks,
        top_ks=top_ks,
        gold=gold,
        codec=codec,
        include_misses=True,
    )
    report = {
        "name": spec.name,
        "family": spec.family,
        "metric": spec.metric,
        "representation": spec.representation,
        "representationDefinition": REPRESENTATION_DESCRIPTIONS[spec.representation],
        "scoreDirection": "higher-first" if spec.higher_is_better else "lower-first",
        "integerScoreMultiplier": SCORE_MULTIPLIER if spec.metric != "levenshtein-distance" else 1,
        "rapidfuzzVersion": rapidfuzz.__version__,
        "execution": "exact bidirectional fixed-size score blocks",
        "scoreBlockRows": block_size,
        "featureVectorDigest": "sha256:" + feature_hasher.hexdigest(),
        "rankingDigest": "sha256:" + ranking_hasher.hexdigest(),
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "results": results,
    }
    return report, pair_ranks, coverage


def _update_union(union: dict[int, int], pairs: Mapping[int, int]) -> None:
    for code, rank in pairs.items():
        previous = union.get(code)
        if previous is None or rank < previous:
            union[code] = rank


def _unique_rescues(
    arm_coverage: Mapping[str, Mapping[int, frozenset[int]]],
    *,
    top_ks: Sequence[int],
    codec: PairCodec,
) -> list[dict[str, Any]]:
    result = []
    for top_k in top_ks:
        for name in sorted(arm_coverage):
            other = set().union(
                *(coverage[top_k] for other_name, coverage in arm_coverage.items() if other_name != name)
            )
            unique = arm_coverage[name][top_k] - other
            result.append(
                {
                    "arm": name,
                    "topK": top_k,
                    "count": len(unique),
                    "pairs": [
                        {"case": case, "source": source, "target": target}
                        for case, source, target in (codec.decode(code) for code in sorted(unique))
                    ],
                }
            )
    return result


def _mapping_relations(root: Path, cases: Sequence[Any], suite: str) -> dict[tuple[str, str, str], str]:
    if suite == "anatomy":
        return {(case.name, source, target): "exact" for case in cases for source, target in case.gold}
    if suite == "atlas":
        result: dict[tuple[str, str, str], str] = {}
        relation_names = {
            "exactMatch": "exact",
            "closeMatch": "close",
            "broadMatch": "broad",
            "narrowMatch": "narrow",
            "relatedMatch": "related",
        }
        for case in cases:
            directory = root / "qualification-baseline" / case.name
            if not directory.is_dir():
                continue
            assertion_path = directory / "relation-assertions-v2" / "relation-assertions.json"
            if not assertion_path.is_file():
                assertion_path = directory / "relation-assertions" / "relation-assertions.json"
            assertions = json.loads(assertion_path.read_text())
            for row in assertions["mappingAssertions"]:
                relation = str(row["relation"])
                local_name = relation.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                result[(case.name, str(row["sourceConcept"]), str(row["targetConcept"]))] = relation_names.get(
                    local_name, "related"
                )
        expected = {(case.name, source, target) for case in cases for source, target in case.gold}
        if set(result) != expected:
            raise ValueError("Atlas typed mapping assertions do not match the benchmark gold pairs")
        return result
    resource = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
    result: dict[tuple[str, str, str], str] = {}
    for case in cases:
        path = root / "references" / f"{case.name}.rdf"
        for cell in ET.parse(path).iter():
            if cell.tag.rsplit("}", 1)[-1] != "Cell":
                continue
            left = None
            right = None
            relation = "="
            for child in cell:
                local = child.tag.rsplit("}", 1)[-1]
                if local == "entity1":
                    left = child.get(resource)
                elif local == "entity2":
                    right = child.get(resource)
                elif local == "relation" and child.text:
                    relation = child.text.strip()
            if left and right:
                result[(case.name, left, right)] = ALIGNMENT_RELATION_TO_SEMANTIC.get(relation, "related")
    return result


def _token_jaccard(left: str | None, right: str | None) -> float:
    left_tokens = set(_normalized_tokens(left or ""))
    right_tokens = set(_normalized_tokens(right or ""))
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _best_alias_score(left: AtlasConcept, right: AtlasConcept, scorer: Callable[[str, str], float]) -> float:
    left_labels = tuple(
        (normalized, index > 0)
        for index, value in enumerate((left.pref_label, *left.alt_labels))
        if (normalized := _normalized_label(value))
    )
    right_labels = tuple(
        (normalized, index > 0)
        for index, value in enumerate((right.pref_label, *right.alt_labels))
        if (normalized := _normalized_label(value))
    )
    return max(
        (
            float(scorer(left_label, right_label))
            for left_label, left_is_alias in left_labels
            for right_label, right_is_alias in right_labels
            if left_is_alias or right_is_alias
        ),
        default=0.0,
    )


def _directional_property(left: str, right: str) -> bool:
    left_tokens = set(_normalized_tokens(left))
    right_tokens = set(_normalized_tokens(right))
    direction_markers = {"assigned", "assign", "by", "has", "is", "of", "reviewer", "reviewed", "to"}
    content_left = left_tokens - direction_markers
    content_right = right_tokens - direction_markers
    marker_pattern = bool(left_tokens & direction_markers) and bool(right_tokens & direction_markers)
    return marker_pattern and (bool(content_left & content_right) or "reviewer" in (left_tokens | right_tokens))


def classify_challenges(left: AtlasConcept, right: AtlasConcept) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Assign transparent, multi-label retrieval challenges to one gold pair."""

    _np, _rapidfuzz, fuzz, _process, distances, _dtype = _rapidfuzz_components()
    _levenshtein, _jaro, jaro_winkler = distances
    left_pref = _normalized_label(left.pref_label)
    right_pref = _normalized_label(right.pref_label)
    left_labels = {_normalized_label(value) for value in (left.pref_label, *left.alt_labels)} - {""}
    right_labels = {_normalized_label(value) for value in (right.pref_label, *right.alt_labels)} - {""}
    ratio = float(fuzz.ratio(left_pref, right_pref))
    partial = float(fuzz.partial_ratio(left_pref, right_pref))
    token_sort = float(fuzz.token_sort_ratio(left_pref, right_pref))
    token_set = float(fuzz.token_set_ratio(left_pref, right_pref))
    winkler = float(jaro_winkler.similarity(left_pref, right_pref))
    alias_score = _best_alias_score(left, right, fuzz.WRatio)
    left_identifier = _identifier(left.member)
    right_identifier = _identifier(right.member)
    identifier_score = float(fuzz.QRatio(left_identifier, right_identifier))
    left_acronym = _acronym(left.pref_label)
    right_acronym = _acronym(right.pref_label)
    left_abbreviations = set(_abbreviation_keys(left.pref_label))
    right_abbreviations = set(_abbreviation_keys(right.pref_label))
    left_tokens = set(left_pref.split())
    right_tokens = set(right_pref.split())
    strict_subset = bool(left_tokens and right_tokens) and (left_tokens < right_tokens or right_tokens < left_tokens)
    hierarchy_score = max(
        (
            float(fuzz.WRatio(_normalized_label(a.pref_label), _normalized_label(b.pref_label)))
            for a in (*left.parents, *left.children)
            for b in (*right.parents, *right.children)
        ),
        default=0.0,
    )
    definition_jaccard = _token_jaccard(left.definition, right.definition)

    challenges: set[str] = set()
    if left_pref == right_pref and left_pref:
        challenges.add("lexical-exact")
    elif ratio >= 80 or winkler >= 0.9:
        challenges.add("lexical-near")
    if (left_labels & right_labels and left_pref != right_pref) or (alias_score >= 90 and alias_score >= ratio + 8):
        challenges.add("alias-synonym")
    if (left_identifier == right_identifier and left_identifier and left_pref != right_pref) or (
        identifier_score >= 90
        and (
            any(character.isdigit() for character in left_identifier + right_identifier)
            or identifier_score >= ratio + 12
        )
    ):
        challenges.add("identifier-code")
    if left_pref != right_pref and (
        bool(left_abbreviations & right_abbreviations)
        or left_acronym == right_pref.replace(" ", "")
        or right_acronym == left_pref.replace(" ", "")
    ):
        challenges.add("abbreviation")
    if definition_jaccard >= 0.12 and ratio < 85:
        challenges.add("definition-semantic")
    if hierarchy_score >= 90 and ratio < 90:
        challenges.add("hierarchy-graph")
    if strict_subset:
        challenges.update(("broader-narrower-granularity", "compound-compositional"))
    if _directional_property(left.pref_label, right.pref_label) and ratio < 85:
        challenges.add("inverse-directional-property")
    if token_sort >= 90 and token_sort >= ratio + 10:
        challenges.add("token-reordered")
    if partial >= 90 and partial >= ratio + 12:
        challenges.add("substring-fragment")
    if not challenges or max(ratio, token_set, alias_score, identifier_score, hierarchy_score) < 70:
        challenges.add("semantic-gap")
    evidence = {
        "preferredRatio": round(ratio, 3),
        "preferredPartialRatio": round(partial, 3),
        "preferredTokenSortRatio": round(token_sort, 3),
        "preferredTokenSetRatio": round(token_set, 3),
        "preferredJaroWinkler": round(winkler, 6),
        "bestAliasWRatio": round(alias_score, 3),
        "identifierQRatio": round(identifier_score, 3),
        "definitionTokenJaccard": round(definition_jaccard, 6),
        "hierarchyWRatio": round(hierarchy_score, 3),
        "sourceAcronym": left_acronym,
        "targetAcronym": right_acronym,
    }
    return tuple(sorted(challenges)), evidence


def build_labeled_pool(
    cases: Sequence[Any],
    *,
    codec: PairCodec,
    mapping_relations: Mapping[tuple[str, str, str], str],
    gold_best_ranks: Mapping[str, Mapping[int, int]],
) -> dict[str, Any]:
    case_lookup = {case.name: case for case in cases}
    rows = []
    for code in sorted(_gold_codes(cases, codec)):
        case_name, source, target = codec.decode(code)
        case = case_lookup[case_name]
        source_concept = next(value for value in case.sources if value.member == source)
        target_concept = next(value for value in case.targets if value.member == target)
        challenges, evidence = classify_challenges(source_concept, target_concept)
        rows.append(
            {
                "case": case_name,
                "source": source,
                "sourceLabel": source_concept.pref_label,
                "target": target,
                "targetLabel": target_concept.pref_label,
                "mappingRelationSemantic": mapping_relations[(case_name, source, target)],
                "retrievalChallenges": list(challenges),
                "challengeEvidence": evidence,
                "bestRankByArm": {name: ranks.get(code) for name, ranks in sorted(gold_best_ranks.items())},
            }
        )
    payload = {
        "type": "AtlasRelationCandidateChallengePool",
        "schemaVersion": "1.0",
        "labelingMethod": "deterministic observable-feature rules over every expert gold relation",
        "challengeTaxonomy": CHALLENGE_TAXONOMY,
        "mappingRelationSemantics": MAPPING_RELATION_SEMANTICS,
        "relations": rows,
    }
    payload["poolDigest"] = "sha256:" + hashlib.sha256(canonical_json(rows).encode()).hexdigest()
    return payload


def _kind_coverage(
    pool: Mapping[str, Any],
    *,
    codec: PairCodec,
    arm_coverage: Mapping[str, Mapping[int, frozenset[int]]],
    union_coverage: Mapping[str, Mapping[int, frozenset[int]]],
    top_ks: Sequence[int],
    gold: frozenset[int],
) -> dict[str, Any]:
    code_by_key = {codec.decode(code): code for code in gold}
    kind_codes: dict[str, set[int]] = {name: set() for name in CHALLENGE_TAXONOMY}
    relation_codes: dict[str, set[int]] = {name: set() for name in MAPPING_RELATION_SEMANTICS}
    for row in pool["relations"]:
        code = code_by_key[(row["case"], row["source"], row["target"])]
        for challenge in row["retrievalChallenges"]:
            kind_codes[challenge].add(code)
        relation_codes[row["mappingRelationSemantic"]].add(code)

    def summarize(groups: Mapping[str, set[int]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for kind, codes in groups.items():
            depths = []
            for top_k in top_ks:
                arms = {
                    name: {
                        "found": len(codes & coverage[top_k]),
                        "recall": round(len(codes & coverage[top_k]) / len(codes), 9) if codes else None,
                    }
                    for name, coverage in sorted(arm_coverage.items())
                }
                unions = {
                    name: {
                        "found": len(codes & coverage[top_k]),
                        "recall": round(len(codes & coverage[top_k]) / len(codes), 9) if codes else None,
                    }
                    for name, coverage in sorted(union_coverage.items())
                }
                best = sorted(
                    ({"arm": name, **values} for name, values in {**arms, **unions}.items()),
                    key=lambda value: (-value["found"], value["arm"]),
                )[:3]
                depths.append({"topK": top_k, "arms": arms, "unions": unions, "best": best})
            result[kind] = {"relations": len(codes), "depths": depths}
        return result

    return {
        "retrievalChallenges": summarize(kind_codes),
        "mappingRelationSemantics": summarize(relation_codes),
    }


def _input_file_digests(root: Path, suite: str) -> dict[str, str]:
    if suite == "conference":
        selected = [
            path
            for path in root.rglob("*")
            if path.is_file()
            and (
                path.name in shared_benchmark.CONFERENCE_REFERENCE_NAMES
                or (
                    path.parent.name == "ontologies"
                    and path.stem.casefold() in shared_benchmark.CONFERENCE_ONTOLOGY_NAMES
                )
            )
        ]
    elif suite == "anatomy":
        selected = [path for path in root.glob("anatomy-*") if path.is_file()]
    else:
        selected = [
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.name
            in {
                "concepts-source.json",
                "concepts-target.json",
                "crosswalk-bundle.json",
                "qualification-receipt.json",
            }
        ]
    return {str(path.relative_to(root)): _sha256(path) for path in sorted(selected)}


def _deterministic_result_digest(result: Mapping[str, Any]) -> str:
    stable = json.loads(canonical_json(result))
    stable.pop("elapsedSeconds", None)
    for arm in stable.get("arms", ()):
        arm.pop("elapsedSeconds", None)
    return "sha256:" + hashlib.sha256(canonical_json(stable).encode()).hexdigest()


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--suite", choices=("conference", "anatomy", "atlas"), required=True)
    parser.add_argument("--profile", choices=("auto", "full", "practical"), default="auto")
    parser.add_argument("--arm", action="append", choices=tuple(SCORER_BY_NAME))
    parser.add_argument("--top-k", action="append", type=int, dest="top_ks")
    parser.add_argument("--workers", type=int, default=-1)
    parser.add_argument("--block-size", type=int, default=256)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--labeled-pool-output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    top_ks = tuple(sorted(set(args.top_ks or DEFAULT_TOP_K)))
    if any(value <= 0 for value in top_ks):
        raise ValueError("top-k values must be positive")
    if args.block_size <= 0:
        raise ValueError("block-size must be positive")
    profile = args.profile
    if profile == "auto":
        profile = "full" if args.suite == "conference" else "practical"
    if args.arm:
        specs = tuple(SCORER_BY_NAME[name] for name in dict.fromkeys(args.arm))
        profile = "selected"
    elif profile == "full":
        specs = SCORER_SPECS
    else:
        specs = tuple(spec for spec in SCORER_SPECS if spec.name in PRACTICAL_ARM_NAMES)

    adapter_path = Path(shared_benchmark.__file__).resolve()
    adapter_digest_before = _sha256(adapter_path)
    if args.suite == "conference":
        cases = shared_benchmark.conference_cases(args.root)
    elif args.suite == "anatomy":
        cases = shared_benchmark.anatomy_cases(args.root)
    else:
        cases = shared_benchmark.atlas_cases(args.root)
    codec = PairCodec.from_cases(cases)
    gold = _gold_codes(cases, codec)
    case_digests = shared_benchmark._case_digest(cases)
    union_ranks: dict[str, dict[int, int]] = {
        name: {} for name, members in UNION_MEMBERS.items() if members & {spec.name for spec in specs}
    }
    arm_coverage: dict[str, dict[int, frozenset[int]]] = {}
    gold_best_ranks: dict[str, dict[int, int]] = {}
    arm_reports = []
    started = time.monotonic()
    for spec in specs:
        report, pair_ranks, coverage = run_arm(
            cases,
            spec=spec,
            top_ks=top_ks,
            codec=codec,
            gold=gold,
            workers=args.workers,
            block_size=args.block_size,
        )
        arm_reports.append(report)
        arm_coverage[spec.name] = coverage
        gold_best_ranks[spec.name] = {code: rank for code, rank in pair_ranks.items() if code in gold}
        for union_name, members in UNION_MEMBERS.items():
            if union_name in union_ranks and spec.name in members:
                _update_union(union_ranks[union_name], pair_ranks)
        del pair_ranks

    union_reports = []
    union_coverage: dict[str, dict[int, frozenset[int]]] = {}
    for name, ranks in sorted(union_ranks.items()):
        results, coverage = _summarize_pair_ranks(
            ranks,
            top_ks=top_ks,
            gold=gold,
            codec=codec,
            include_misses=True,
        )
        union_reports.append(
            {
                "name": name,
                "members": sorted(UNION_MEMBERS[name] & {spec.name for spec in specs}),
                "results": results,
            }
        )
        union_coverage[name] = coverage

    mapping_relations = _mapping_relations(args.root, cases, args.suite)
    labeled_pool = None
    kind_coverage = None
    if args.suite == "conference":
        labeled_pool = build_labeled_pool(
            cases,
            codec=codec,
            mapping_relations=mapping_relations,
            gold_best_ranks=gold_best_ranks,
        )
        kind_coverage = _kind_coverage(
            labeled_pool,
            codec=codec,
            arm_coverage=arm_coverage,
            union_coverage=union_coverage,
            top_ks=top_ks,
            gold=gold,
        )
        if args.labeled_pool_output:
            args.labeled_pool_output.parent.mkdir(parents=True, exist_ok=True)
            args.labeled_pool_output.write_text(canonical_json(labeled_pool) + "\n", encoding="utf-8")

    adapter_digest_after = _sha256(adapter_path)
    if adapter_digest_after != adapter_digest_before:
        raise RuntimeError("shared input adapter changed during the benchmark; rerun from one pinned revision")
    result = {
        "type": "AtlasLexicalCandidateControlBenchmark",
        "schemaVersion": "1.0",
        "suite": args.suite,
        "profile": profile,
        "topK": list(top_ks),
        "caseCount": len(cases),
        "sourceConcepts": sum(len(case.sources) for case in cases),
        "targetConcepts": sum(len(case.targets) for case in cases),
        "goldRelations": len(gold),
        "corpusDigest": case_digests["corpus"],
        "goldDigest": case_digests["gold"],
        "inputFiles": _input_file_digests(args.root, args.suite),
        "toolDigest": _sha256(Path(__file__).resolve()),
        "sharedAdapterDigest": adapter_digest_after,
        "workers": args.workers,
        "scoreBlockRows": args.block_size,
        "arms": arm_reports,
        "unions": union_reports,
        "uniqueRescues": _unique_rescues(arm_coverage, top_ks=top_ks, codec=codec),
        "challengeTaxonomy": CHALLENGE_TAXONOMY,
        "mappingRelationSemantics": MAPPING_RELATION_SEMANTICS,
        "mappingRelationCounts": {
            semantic: sum(value == semantic for value in mapping_relations.values())
            for semantic in MAPPING_RELATION_SEMANTICS
        },
        "candidateKindCoverage": kind_coverage,
        "labeledPoolDigest": labeled_pool["poolDigest"] if labeled_pool else None,
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }
    result["deterministicResultDigest"] = _deterministic_result_digest(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(result) + "\n", encoding="utf-8")
    print(
        canonical_json(
            {
                "arms": len(arm_reports),
                "elapsedSeconds": result["elapsedSeconds"],
                "goldRelations": len(gold),
                "output": str(args.output),
                "outputDigest": _sha256(args.output),
                "suite": args.suite,
                "unions": len(union_reports),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
