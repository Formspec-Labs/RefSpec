"""Find exact complete-recall frontiers across candidate-discovery arms.

The optimizer consumes a compact ``.npz`` bundle.  Every row in ``ranks`` is
one retrieval arm and every column is one canonical ``case/source/target``
pair.  Zero means that the arm did not retain the pair at its largest measured
depth; positive values are minimum bidirectional ranks.  Fixed candidate sets
use rank one.

The search minimizes the *set union* of selected candidates.  It does not add
per-arm candidate counts, which would double count overlap.  Pairs with the
same arm/depth membership are compressed into one weighted signature before an
exact mixed-integer solve.  A small exhaustive solver is also provided for
tests and independently checking small bundles.

Example::

    python tools/optimize_relation_candidate_pareto.py \
      --bundle /tmp/conference-pareto.npz \
      --output /tmp/conference-pareto-result.json \
      --deterministic-repeats 2
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

BUNDLE_TYPE = "RelationCandidateParetoBundle"
BUNDLE_VERSION = "1.0"
RESULT_TYPE = "RelationCandidateParetoFrontier"
RESULT_VERSION = "1.0"
PROVIDER_KIND = "provider-embedding"
RERANKER_KIND = "reranker"
GRAPH_KIND = "graph"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _array_digest(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    header = _canonical_json({"dtype": array.dtype.str, "shape": list(array.shape)}).encode()
    return _sha256_bytes(header + b"\n" + array.tobytes(order="C"))


@dataclass(frozen=True, slots=True)
class CaseLayout:
    """Canonical pair layout for one independently compared vocabulary pair."""

    name: str
    sources: tuple[str, ...]
    targets: tuple[str, ...]
    gold_flat_indexes: tuple[int, ...]
    offset: int = 0

    @property
    def pair_count(self) -> int:
        return len(self.sources) * len(self.targets)


@dataclass(frozen=True, slots=True)
class Arm:
    """Metadata for one independently selectable retrieval arm."""

    identifier: str
    family: str
    kind: str
    depths: tuple[int, ...]
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Bundle:
    """Validated compact candidate-rank evidence."""

    path: Path
    metadata: Mapping[str, Any]
    layouts: tuple[CaseLayout, ...]
    arms: tuple[Arm, ...]
    ranks: np.ndarray
    reservoirs: Mapping[str, np.ndarray]
    gold_indexes: tuple[int, ...]
    challenges: Mapping[int, tuple[str, ...]]

    @property
    def pair_count(self) -> int:
        return self.ranks.shape[1]


@dataclass(frozen=True, slots=True)
class Option:
    """One measured depth choice for an arm."""

    index: int
    arm_index: int
    arm_id: str
    depth: int
    kind: str


@dataclass(slots=True)
class SignatureModel:
    """Weighted pair-membership signatures used by both exact solvers."""

    bundle: Bundle
    options: tuple[Option, ...]
    pair_signatures: tuple[int, ...]
    signatures: tuple[int, ...]
    signature_weights: tuple[int, ...]
    gold_signatures: tuple[int, ...]
    arm_option_indexes: tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class _BitsetOption:
    """One option represented as exact Python-integer candidate and gold sets."""

    option: Option
    candidate_bits: int
    gold_bits: int
    candidate_count: int


def _metadata_bytes(metadata: Mapping[str, Any]) -> np.ndarray:
    return np.frombuffer(_canonical_json(metadata).encode("utf-8"), dtype=np.uint8)


def write_bundle(
    path: Path,
    *,
    layouts: Sequence[Mapping[str, Any]],
    arms: Sequence[Mapping[str, Any]],
    ranks: np.ndarray,
    reservoirs: Mapping[str, np.ndarray] | None = None,
    challenges: Mapping[str, Sequence[str]] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> None:
    """Write a deterministic compact bundle and immediately validate it.

    ``layouts`` contain ``name``, sorted ``sources`` and ``targets``, and
    ``goldFlatIndexes``.  Challenge keys are global decimal pair indexes.
    Reservoir masks are boolean arrays over the same global pair universe.
    """

    path = Path(path)
    ranks = np.asarray(ranks)
    reservoir_values = reservoirs or {}
    metadata: dict[str, Any] = {
        "type": BUNDLE_TYPE,
        "schemaVersion": BUNDLE_VERSION,
        "layouts": list(layouts),
        "arms": list(arms),
        "challenges": dict(challenges or {}),
        "provenance": dict(provenance or {}),
        "rankArrayDigest": _array_digest(ranks),
        "reservoirs": {},
    }
    arrays: dict[str, np.ndarray] = {"ranks": ranks}
    for index, (identifier, values) in enumerate(sorted(reservoir_values.items())):
        key = f"reservoir_{index}"
        mask = np.asarray(values, dtype=np.bool_)
        arrays[key] = mask
        metadata["reservoirs"][identifier] = {
            "arrayKey": key,
            "pairCount": int(np.count_nonzero(mask)),
            "maskDigest": _array_digest(mask),
        }
    metadata_without_digest = dict(metadata)
    metadata["metadataDigest"] = _sha256_bytes(_canonical_json(metadata_without_digest).encode())
    arrays["metadata"] = _metadata_bytes(metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **arrays)
    load_bundle(path)


def _parse_layouts(raw_layouts: Sequence[Mapping[str, Any]]) -> tuple[CaseLayout, ...]:
    result = []
    offset = 0
    previous_name: str | None = None
    for raw in raw_layouts:
        name = str(raw["name"])
        sources = tuple(str(value) for value in raw["sources"])
        targets = tuple(str(value) for value in raw["targets"])
        gold = tuple(int(value) for value in raw.get("goldFlatIndexes", ()))
        if previous_name is not None and name <= previous_name:
            raise ValueError("case layouts must use unique ascending names")
        if sources != tuple(sorted(set(sources))) or targets != tuple(sorted(set(targets))):
            raise ValueError(f"layout {name!r} must use unique sorted endpoint identifiers")
        pair_count = len(sources) * len(targets)
        if any(value < 0 or value >= pair_count for value in gold):
            raise ValueError(f"layout {name!r} has an out-of-range gold index")
        if gold != tuple(sorted(set(gold))):
            raise ValueError(f"layout {name!r} gold indexes must be unique and sorted")
        result.append(CaseLayout(name, sources, targets, gold, offset))
        offset += pair_count
        previous_name = name
    if not result:
        raise ValueError("bundle must contain at least one case layout")
    return tuple(result)


def _parse_arms(raw_arms: Sequence[Mapping[str, Any]]) -> tuple[Arm, ...]:
    result = []
    identifiers: set[str] = set()
    for raw in raw_arms:
        identifier = str(raw["id"])
        family = str(raw.get("family") or identifier)
        kind = str(raw.get("kind") or "deterministic")
        depths = tuple(int(value) for value in raw["depths"])
        if not identifier or identifier in identifiers:
            raise ValueError("arm identifiers must be non-empty and unique")
        if depths != tuple(sorted(set(depths))) or not depths or depths[0] < 1:
            raise ValueError(f"arm {identifier!r} depths must be unique ascending positive integers")
        metadata = {key: value for key, value in raw.items() if key not in {"id", "family", "kind", "depths"}}
        if kind == GRAPH_KIND:
            policy = metadata.get("anchorPolicy")
            digest = metadata.get("anchorPolicyDigest")
            if not isinstance(policy, str) or not policy:
                raise ValueError(f"graph arm {identifier!r} must declare anchorPolicy")
            if not isinstance(digest, str) or not digest.startswith("sha256:"):
                raise ValueError(f"graph arm {identifier!r} must declare anchorPolicyDigest")
        if kind == RERANKER_KIND and not isinstance(metadata.get("reservoirId"), str):
            raise ValueError(f"reranker arm {identifier!r} must declare reservoirId")
        result.append(Arm(identifier, family, kind, depths, metadata))
        identifiers.add(identifier)
    if not result:
        raise ValueError("bundle must contain at least one arm")
    return tuple(result)


def load_bundle(path: Path) -> Bundle:
    """Load and fully validate a compact evidence bundle."""

    path = Path(path)
    with np.load(path, allow_pickle=False) as archive:
        metadata = json.loads(bytes(np.asarray(archive["metadata"], dtype=np.uint8)).decode("utf-8"))
        ranks = np.asarray(archive["ranks"])
        reservoir_metadata = metadata.get("reservoirs", {})
        reservoirs = {
            identifier: np.asarray(archive[value["arrayKey"]], dtype=np.bool_)
            for identifier, value in reservoir_metadata.items()
        }
    if metadata.get("type") != BUNDLE_TYPE or metadata.get("schemaVersion") != BUNDLE_VERSION:
        raise ValueError("unsupported relation candidate Pareto bundle")
    claimed_metadata_digest = metadata.get("metadataDigest")
    metadata_without_digest = dict(metadata)
    metadata_without_digest.pop("metadataDigest", None)
    if claimed_metadata_digest != _sha256_bytes(_canonical_json(metadata_without_digest).encode()):
        raise ValueError("bundle metadata digest does not match")
    layouts = _parse_layouts(metadata["layouts"])
    arms = _parse_arms(metadata["arms"])
    pair_count = sum(layout.pair_count for layout in layouts)
    if ranks.ndim != 2 or ranks.shape != (len(arms), pair_count):
        raise ValueError("rank matrix shape does not match arm and pair metadata")
    if ranks.dtype.kind != "u":
        raise ValueError("rank matrix must use an unsigned integer type")
    if metadata.get("rankArrayDigest") != _array_digest(ranks):
        raise ValueError("rank array digest does not match")
    for arm_index, arm in enumerate(arms):
        row = ranks[arm_index]
        maximum = arm.depths[-1]
        if np.any(row > maximum):
            raise ValueError(f"arm {arm.identifier!r} has ranks above its largest measured depth")
    for identifier, mask in reservoirs.items():
        receipt = metadata["reservoirs"][identifier]
        if mask.shape != (pair_count,):
            raise ValueError(f"reservoir {identifier!r} shape does not match the pair universe")
        if int(np.count_nonzero(mask)) != int(receipt["pairCount"]):
            raise ValueError(f"reservoir {identifier!r} pair count does not match")
        if _array_digest(mask) != receipt["maskDigest"]:
            raise ValueError(f"reservoir {identifier!r} digest does not match")
    for arm_index, arm in enumerate(arms):
        if arm.kind != RERANKER_KIND:
            continue
        reservoir_id = str(arm.metadata["reservoirId"])
        if reservoir_id not in reservoirs:
            raise ValueError(f"reranker arm {arm.identifier!r} references an unknown reservoir")
        outside = (ranks[arm_index] > 0) & ~reservoirs[reservoir_id]
        if np.any(outside):
            raise ValueError(f"reranker arm {arm.identifier!r} ranks candidates outside its reservoir")
    gold_indexes = tuple(layout.offset + value for layout in layouts for value in layout.gold_flat_indexes)
    challenge_rows: dict[int, tuple[str, ...]] = {}
    for raw_index, raw_values in metadata.get("challenges", {}).items():
        index = int(raw_index)
        if index not in gold_indexes:
            raise ValueError("challenge metadata may only identify a gold pair")
        challenge_rows[index] = tuple(sorted({str(value) for value in raw_values}))
    return Bundle(
        path=path,
        metadata=metadata,
        layouts=layouts,
        arms=arms,
        ranks=ranks,
        reservoirs=reservoirs,
        gold_indexes=gold_indexes,
        challenges=challenge_rows,
    )


def build_signature_model(bundle: Bundle) -> SignatureModel:
    """Compress all pair memberships without losing any union information."""

    options = []
    arm_option_indexes = []
    for arm_index, arm in enumerate(bundle.arms):
        indexes = []
        for depth in arm.depths:
            option_index = len(options)
            options.append(Option(option_index, arm_index, arm.identifier, depth, arm.kind))
            indexes.append(option_index)
        arm_option_indexes.append(tuple(indexes))

    pair_signatures = [0] * bundle.pair_count
    for arm_index, arm in enumerate(bundle.arms):
        option_indexes = arm_option_indexes[arm_index]
        suffix_masks = []
        current = 0
        for option_index in reversed(option_indexes):
            current |= 1 << option_index
            suffix_masks.append(current)
        suffix_masks.reverse()
        lookup = {
            rank: suffix_masks[next(index for index, depth in enumerate(arm.depths) if rank <= depth)]
            for rank in sorted({int(value) for value in bundle.ranks[arm_index] if value > 0})
        }
        for pair_index in np.flatnonzero(bundle.ranks[arm_index]).tolist():
            rank = int(bundle.ranks[arm_index, pair_index])
            pair_signatures[pair_index] |= lookup[rank]

    weights: dict[int, int] = {}
    for signature in pair_signatures:
        if signature:
            weights[signature] = weights.get(signature, 0) + 1
    signatures = tuple(sorted(weights))
    gold_signatures = tuple(sorted({pair_signatures[index] for index in bundle.gold_indexes}))
    if not gold_signatures or 0 in gold_signatures:
        raise ValueError("at least one gold pair is absent from every measured arm depth")
    return SignatureModel(
        bundle=bundle,
        options=tuple(options),
        pair_signatures=tuple(pair_signatures),
        signatures=signatures,
        signature_weights=tuple(weights[value] for value in signatures),
        gold_signatures=gold_signatures,
        arm_option_indexes=tuple(arm_option_indexes),
    )


def _iter_set_bits(value: int) -> Iterable[int]:
    while value:
        low = value & -value
        yield low.bit_length() - 1
        value ^= low


def _eligible_option_mask(
    model: SignatureModel,
    *,
    allow_provider: bool,
    allow_reranker: bool,
) -> int:
    result = 0
    for option in model.options:
        if option.kind == PROVIDER_KIND and not allow_provider:
            continue
        if option.kind == RERANKER_KIND and not allow_reranker:
            continue
        result |= 1 << option.index
    return result


def _selection_key(model: SignatureModel, selected_mask: int, candidate_count: int) -> tuple[Any, ...]:
    selected = [model.options[index] for index in _iter_set_bits(selected_mask)]
    return (
        candidate_count,
        len(selected),
        sum(option.kind == PROVIDER_KIND for option in selected),
        sum(option.kind == RERANKER_KIND for option in selected),
        tuple((option.arm_id, option.depth) for option in selected),
    )


def _selected_candidate_count(model: SignatureModel, selected_mask: int) -> int:
    return sum(
        weight
        for signature, weight in zip(model.signatures, model.signature_weights, strict=True)
        if signature & selected_mask
    )


def _covers_gold(model: SignatureModel, selected_mask: int) -> bool:
    return all(signature & selected_mask for signature in model.gold_signatures)


def solve_brute_force(
    model: SignatureModel,
    *,
    allow_provider: bool,
    allow_reranker: bool,
    active_cap: int | None,
) -> tuple[int, int] | None:
    """Solve a small model exactly by exhaustive arm choices."""

    choices = []
    total = 1
    eligible = _eligible_option_mask(
        model,
        allow_provider=allow_provider,
        allow_reranker=allow_reranker,
    )
    for indexes in model.arm_option_indexes:
        arm_choices = (None, *(index for index in indexes if eligible & (1 << index)))
        choices.append(arm_choices)
        total *= len(arm_choices)
    if total > 5_000_000:
        raise ValueError("brute-force solver is limited to 5,000,000 arm-depth configurations")
    best: tuple[tuple[Any, ...], int] | None = None
    for selected_values in itertools.product(*choices):
        selected_indexes = tuple(value for value in selected_values if value is not None)
        if active_cap is not None and len(selected_indexes) > active_cap:
            continue
        selected_mask = sum(1 << value for value in selected_indexes)
        if not _covers_gold(model, selected_mask):
            continue
        candidate_count = _selected_candidate_count(model, selected_mask)
        key = _selection_key(model, selected_mask, candidate_count)
        if best is None or key < best[0]:
            best = (key, selected_mask)
    return None if best is None else (best[1], int(best[0][0]))


def _bitset_options(model: SignatureModel) -> tuple[_BitsetOption, ...]:
    """Build exact option bitsets and drop only safe same-arm plateaus."""

    gold_positions = {pair_index: index for index, pair_index in enumerate(model.bundle.gold_indexes)}
    result = []
    previous_gold_by_arm: dict[int, int] = {}
    for option in model.options:
        row = model.bundle.ranks[option.arm_index]
        selected = (row > 0) & (row <= option.depth)
        candidate_bits = int.from_bytes(np.packbits(selected, bitorder="little").tobytes(), "little")
        gold_bits = 0
        for pair_index, gold_position in gold_positions.items():
            if selected[pair_index]:
                gold_bits |= 1 << gold_position
        # A deeper option with unchanged gold is a strict candidate superset
        # of the preceding option from the same nested rank arm.  It cannot
        # improve a complete-recall union.
        if previous_gold_by_arm.get(option.arm_index) == gold_bits:
            continue
        previous_gold_by_arm[option.arm_index] = gold_bits
        result.append(_BitsetOption(option, candidate_bits, gold_bits, candidate_bits.bit_count()))
    return tuple(result)


def _better_selection(
    model: SignatureModel,
    selected_mask: int,
    candidate_count: int,
    incumbent: tuple[int, int] | None,
) -> bool:
    if incumbent is None:
        return True
    return _selection_key(model, selected_mask, candidate_count) < _selection_key(
        model,
        incumbent[0],
        incumbent[1],
    )


def _initial_branch_incumbent(
    model: SignatureModel,
    options: Sequence[_BitsetOption],
    *,
    active_cap: int | None,
) -> tuple[int, int] | None:
    """Find a deterministic complete upper bound before exhaustive search."""

    all_gold = (1 << len(model.bundle.gold_indexes)) - 1
    best: tuple[int, int] | None = None

    def consider(selected: Sequence[_BitsetOption]) -> None:
        nonlocal best
        if active_cap is not None and len(selected) > active_cap:
            return
        coverage = 0
        candidates = 0
        selected_mask = 0
        for value in selected:
            coverage |= value.gold_bits
            candidates |= value.candidate_bits
            selected_mask |= 1 << value.option.index
        if coverage != all_gold:
            return
        candidate_count = candidates.bit_count()
        if _better_selection(model, selected_mask, candidate_count, best):
            best = selected_mask, candidate_count

    # Complete single arms and pairs are cheap to enumerate and give a strong
    # bound for the provider-free and reranker-free scenarios.
    for index, left in enumerate(options):
        consider((left,))
        if active_cap == 1:
            continue
        for right in options[index + 1 :]:
            if right.option.arm_index != left.option.arm_index:
                consider((left, right))

    if active_cap is not None and active_cap <= 2:
        return best

    coverers = [
        tuple(value for value in options if value.gold_bits & (1 << gold_index))
        for gold_index in range(len(model.bundle.gold_indexes))
    ]
    hardest = min(range(len(coverers)), key=lambda index: (len(coverers[index]), index))
    # Seed greedy completion from every way to cover the hardest gold pair and
    # several fixed cost/gain trade-offs.  Greedy affects speed only; the
    # branch below still proves the optimum.
    for first in coverers[hardest]:
        for exponent in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0):
            selected = [first]
            used_arms = {first.option.arm_index}
            coverage = first.gold_bits
            candidates = first.candidate_bits
            while coverage != all_gold and (active_cap is None or len(selected) < active_cap):
                choices = []
                for value in options:
                    if value.option.arm_index in used_arms:
                        continue
                    gain = (value.gold_bits & ~coverage).bit_count()
                    if not gain:
                        continue
                    marginal = (value.candidate_bits & ~candidates).bit_count()
                    choices.append(
                        (
                            (marginal + 1) / (gain**exponent),
                            marginal,
                            -gain,
                            value.candidate_count,
                            value.option.arm_id,
                            value.option.depth,
                            value,
                        )
                    )
                if not choices:
                    break
                value = min(choices)[-1]
                selected.append(value)
                used_arms.add(value.option.arm_index)
                coverage |= value.gold_bits
                candidates |= value.candidate_bits
            consider(selected)
    return best


def solve_branch_and_bound(
    model: SignatureModel,
    *,
    allow_provider: bool,
    allow_reranker: bool,
    active_cap: int | None,
) -> tuple[int, int] | None:
    """Prove an exact optimum by branching on the rarest uncovered gold pair.

    Candidate sets are Python integer bitsets over the full pair universe.
    The search therefore measures every overlap exactly while keeping the
    branch state compact.  At each node, branches partition solutions by the
    first selected option that covers one required uncovered pair.
    """

    values = tuple(
        value
        for value in _bitset_options(model)
        if (allow_provider or value.option.kind != PROVIDER_KIND)
        and (allow_reranker or value.option.kind != RERANKER_KIND)
    )
    if not values:
        return None
    all_gold = (1 << len(model.bundle.gold_indexes)) - 1
    best = _initial_branch_incumbent(model, values, active_cap=active_cap)
    if best is None:
        # The complete maximum-depth union is a quick infeasibility check.
        maximum_by_arm: dict[int, _BitsetOption] = {}
        for value in values:
            maximum_by_arm[value.option.arm_index] = value
        if active_cap is None or len(maximum_by_arm) <= active_cap:
            coverage = 0
            for value in maximum_by_arm.values():
                coverage |= value.gold_bits
            if coverage != all_gold:
                return None

    option_count = len(values)
    all_option_mask = (1 << option_count) - 1
    options_by_arm: dict[int, int] = {}
    coverers: list[int] = [0] * len(model.bundle.gold_indexes)
    for value_index, value in enumerate(values):
        bit = 1 << value_index
        options_by_arm[value.option.arm_index] = options_by_arm.get(value.option.arm_index, 0) | bit
        for gold_index in _iter_set_bits(value.gold_bits):
            coverers[gold_index] |= bit

    def search(
        coverage: int,
        candidates: int,
        selected_original_mask: int,
        selected_count: int,
        unavailable: int,
    ) -> None:
        nonlocal best
        candidate_count = candidates.bit_count()
        if coverage == all_gold:
            if _better_selection(model, selected_original_mask, candidate_count, best):
                best = selected_original_mask, candidate_count
            return
        if best is not None and candidate_count >= best[1]:
            return
        if active_cap is not None and selected_count >= active_cap:
            return
        available = all_option_mask & ~unavailable
        uncovered = all_gold & ~coverage
        chosen_options = 0
        chosen_key: tuple[int, int, int] | None = None
        maximum_gain = 0
        for gold_index in _iter_set_bits(uncovered):
            possible = coverers[gold_index] & available
            if not possible:
                return
            count = possible.bit_count()
            minimum_new_count = min(
                (candidates | values[index].candidate_bits).bit_count() for index in _iter_set_bits(possible)
            )
            key = (count, -minimum_new_count, gold_index)
            if chosen_key is None or key < chosen_key:
                chosen_key = key
                chosen_options = possible
        for value_index in _iter_set_bits(available):
            gain = (values[value_index].gold_bits & uncovered).bit_count()
            maximum_gain = max(maximum_gain, gain)
        if maximum_gain == 0:
            return
        if active_cap is not None:
            minimum_more = math.ceil(uncovered.bit_count() / maximum_gain)
            if selected_count + minimum_more > active_cap:
                return

        branches = []
        for value_index in _iter_set_bits(chosen_options):
            value = values[value_index]
            combined = candidates | value.candidate_bits
            new_count = combined.bit_count()
            if best is not None and new_count >= best[1]:
                continue
            gain = (value.gold_bits & uncovered).bit_count()
            branches.append((new_count, -gain, value.option.arm_id, value.option.depth, value_index, combined))
        branches.sort()
        # Excluding earlier alternatives partitions complete solutions by the
        # first chosen option (in this deterministic branch order) that covers
        # the selected gold requirement.
        earlier = 0
        for _new_count, _negative_gain, _arm_id, _depth, value_index, combined in branches:
            value = values[value_index]
            search(
                coverage | value.gold_bits,
                combined,
                selected_original_mask | (1 << value.option.index),
                selected_count + 1,
                unavailable | earlier | options_by_arm[value.option.arm_index],
            )
            earlier |= 1 << value_index

    search(0, 0, 0, 0, 0)
    return best


def _secondary_objective(model: SignatureModel) -> np.ndarray:
    option_count = len(model.options)
    arm_count = len(model.bundle.arms)
    maximum_index_sum = option_count * max(arm_count, 1)
    reranker_weight = maximum_index_sum + 1
    provider_weight = (arm_count + 1) * reranker_weight
    active_weight = (arm_count + 1) * provider_weight
    result = np.zeros(option_count + len(model.signatures), dtype=np.float64)
    for option in model.options:
        result[option.index] = (
            active_weight
            + (provider_weight if option.kind == PROVIDER_KIND else 0)
            + (reranker_weight if option.kind == RERANKER_KIND else 0)
            + option.index
            + 1
        )
    return result


def solve_milp(
    model: SignatureModel,
    *,
    allow_provider: bool,
    allow_reranker: bool,
    active_cap: int | None,
) -> tuple[int, int] | None:
    """Solve one complete-recall union exactly with SciPy's HiGHS MILP."""

    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix, vstack
    except ImportError as error:  # pragma: no cover - exercised only in minimal tool environments.
        raise RuntimeError("the exact large-bundle solver needs scipy") from error

    option_count = len(model.options)
    signature_count = len(model.signatures)
    variable_count = option_count + signature_count
    rows: list[int] = []
    columns: list[int] = []
    values: list[float] = []
    lower: list[float] = []
    upper: list[float] = []

    # If any selected option contains a signature, its positive-cost union
    # variable must be one.  One aggregate inequality is enough because all
    # decision variables are binary.
    for signature_index, signature in enumerate(model.signatures):
        row = len(lower)
        bits = tuple(_iter_set_bits(signature))
        rows.extend([row] * (len(bits) + 1))
        columns.extend((*bits, option_count + signature_index))
        values.extend((*([1.0] * len(bits)), -float(len(bits))))
        lower.append(-math.inf)
        upper.append(0.0)

    # Every distinct gold membership signature must be reached.
    for signature in model.gold_signatures:
        row = len(lower)
        bits = tuple(_iter_set_bits(signature))
        rows.extend([row] * len(bits))
        columns.extend(bits)
        values.extend([-1.0] * len(bits))
        lower.append(-math.inf)
        upper.append(-1.0)

    # One measured depth at most for each retrieval arm.
    for indexes in model.arm_option_indexes:
        row = len(lower)
        rows.extend([row] * len(indexes))
        columns.extend(indexes)
        values.extend([1.0] * len(indexes))
        lower.append(-math.inf)
        upper.append(1.0)

    if active_cap is not None:
        row = len(lower)
        rows.extend([row] * option_count)
        columns.extend(range(option_count))
        values.extend([1.0] * option_count)
        lower.append(-math.inf)
        upper.append(float(active_cap))

    static = coo_matrix((values, (rows, columns)), shape=(len(lower), variable_count)).tocsr()
    objective = np.zeros(variable_count, dtype=np.float64)
    objective[option_count:] = np.asarray(model.signature_weights, dtype=np.float64)
    eligible = _eligible_option_mask(
        model,
        allow_provider=allow_provider,
        allow_reranker=allow_reranker,
    )
    upper_bounds = np.ones(variable_count, dtype=np.float64)
    for option in model.options:
        if not eligible & (1 << option.index):
            upper_bounds[option.index] = 0.0
    bounds = Bounds(np.zeros(variable_count), upper_bounds)
    integrality = np.ones(variable_count, dtype=np.uint8)
    options = {"mip_rel_gap": 0.0, "presolve": True}
    primary = milp(
        objective,
        integrality=integrality,
        bounds=bounds,
        constraints=LinearConstraint(static, np.asarray(lower), np.asarray(upper)),
        options=options,
    )
    if primary.status == 2:
        return None
    if primary.status != 0 or primary.x is None:
        raise RuntimeError(f"MILP did not prove an optimum: {primary.message}")
    candidate_optimum = round(float(primary.fun))

    # Pick a stable, operationally smaller solution from the candidate-optimal
    # face: fewer active arms, then fewer provider and reranker arms, followed
    # by stable option order.  This does not change the union optimum.
    candidate_row = coo_matrix(
        (
            np.asarray(model.signature_weights, dtype=np.float64),
            (
                np.zeros(signature_count, dtype=np.intp),
                np.arange(option_count, variable_count, dtype=np.intp),
            ),
        ),
        shape=(1, variable_count),
    ).tocsr()
    combined = vstack((static, candidate_row), format="csr")
    secondary = milp(
        _secondary_objective(model),
        integrality=integrality,
        bounds=bounds,
        constraints=LinearConstraint(
            combined,
            np.asarray((*lower, -math.inf)),
            np.asarray((*upper, float(candidate_optimum))),
        ),
        options=options,
    )
    if secondary.status != 0 or secondary.x is None:
        raise RuntimeError(f"MILP tie-break did not prove an optimum: {secondary.message}")
    selected_mask = 0
    for option in model.options:
        if secondary.x[option.index] > 0.5:
            selected_mask |= 1 << option.index
    verified_count = _selected_candidate_count(model, selected_mask)
    if verified_count != candidate_optimum or not _covers_gold(model, selected_mask):
        raise RuntimeError("solver selection failed exact post-solve verification")
    return selected_mask, candidate_optimum


def solve_configuration(
    model: SignatureModel,
    *,
    allow_provider: bool,
    allow_reranker: bool,
    active_cap: int | None = None,
    solver: str = "auto",
) -> tuple[int, int] | None:
    """Dispatch to the requested exact solver."""

    if solver not in {"auto", "milp", "brute-force", "branch-and-bound"}:
        raise ValueError(f"unsupported solver {solver!r}")
    if solver == "brute-force":
        return solve_brute_force(
            model,
            allow_provider=allow_provider,
            allow_reranker=allow_reranker,
            active_cap=active_cap,
        )
    if solver == "branch-and-bound":
        return solve_branch_and_bound(
            model,
            allow_provider=allow_provider,
            allow_reranker=allow_reranker,
            active_cap=active_cap,
        )
    if solver == "auto":
        total = math.prod(len(indexes) + 1 for indexes in model.arm_option_indexes)
        if total <= 1_000_000:
            return solve_brute_force(
                model,
                allow_provider=allow_provider,
                allow_reranker=allow_reranker,
                active_cap=active_cap,
            )
        return solve_branch_and_bound(
            model,
            allow_provider=allow_provider,
            allow_reranker=allow_reranker,
            active_cap=active_cap,
        )
    return solve_milp(
        model,
        allow_provider=allow_provider,
        allow_reranker=allow_reranker,
        active_cap=active_cap,
    )


def _decode_pair(bundle: Bundle, pair_index: int) -> tuple[str, str, str]:
    for layout in bundle.layouts:
        if pair_index >= layout.offset + layout.pair_count:
            continue
        local = pair_index - layout.offset
        source_index, target_index = divmod(local, len(layout.targets))
        return layout.name, layout.sources[source_index], layout.targets[target_index]
    raise IndexError(pair_index)


def _pair_set_digest(bundle: Bundle, selected_pair_indexes: Iterable[int]) -> str:
    digest = hashlib.sha256()
    for pair_index in sorted(selected_pair_indexes):
        case, source, target = _decode_pair(bundle, pair_index)
        digest.update(f"{case}\t{source}\t{target}\n".encode())
    return "sha256:" + digest.hexdigest()


def _challenge_coverage(bundle: Bundle, selected_pairs: set[int]) -> dict[str, Mapping[str, Any]]:
    groups: dict[str, set[int]] = {}
    for pair_index in bundle.gold_indexes:
        for challenge in bundle.challenges.get(pair_index, ("unlabeled",)):
            groups.setdefault(challenge, set()).add(pair_index)
    return {
        challenge: {
            "relations": len(indexes),
            "found": len(indexes & selected_pairs),
            "recall": round(len(indexes & selected_pairs) / len(indexes), 9),
        }
        for challenge, indexes in sorted(groups.items())
    }


def summarize_solution(model: SignatureModel, selected_mask: int, candidate_count: int) -> dict[str, Any]:
    """Recompute a selected union, its digest, challenges, and exclusive rescues."""

    selected_options = tuple(model.options[index] for index in _iter_set_bits(selected_mask))
    selected_pairs = {
        pair_index for pair_index, signature in enumerate(model.pair_signatures) if signature & selected_mask
    }
    gold = set(model.bundle.gold_indexes)
    found = selected_pairs & gold
    if len(selected_pairs) != candidate_count or found != gold:
        raise RuntimeError("reported solution is not an exact complete union")
    arms = []
    for option in selected_options:
        own_option_bit = 1 << option.index
        others = selected_mask ^ own_option_bit
        own_pairs = {
            pair_index for pair_index, signature in enumerate(model.pair_signatures) if signature & own_option_bit
        }
        other_pairs = {pair_index for pair_index, signature in enumerate(model.pair_signatures) if signature & others}
        exclusive_pairs = own_pairs - other_pairs
        exclusive_gold = exclusive_pairs & gold
        arm = model.bundle.arms[option.arm_index]
        raw_model = arm.metadata.get("model")
        if isinstance(raw_model, Mapping):
            model_evidence: object = {
                key: raw_model[key]
                for key in ("requestedName", "artifactRevision", "artifactDigest", "backend")
                if key in raw_model
            }
        else:
            model_evidence = raw_model
        arms.append(
            {
                "id": option.arm_id,
                "family": arm.family,
                "kind": option.kind,
                "depth": option.depth,
                "candidatesAtDepth": len(own_pairs),
                "goldAtDepth": len(own_pairs & gold),
                "exclusiveCandidates": len(exclusive_pairs),
                "uniqueGoldRescues": len(exclusive_gold),
                "candidatesPerUniqueRescue": (
                    round(len(exclusive_pairs) / len(exclusive_gold), 6) if exclusive_gold else None
                ),
                "uniqueGoldPairs": [
                    {"case": case, "source": source, "target": target}
                    for case, source, target in (
                        _decode_pair(model.bundle, pair_index) for pair_index in sorted(exclusive_gold)
                    )
                ],
                "evidence": {
                    key: value
                    for key, value in {
                        "model": model_evidence,
                        "provider": arm.metadata.get("provider"),
                        "mode": arm.metadata.get("mode"),
                        "rankDigest": arm.metadata.get("rankDigest"),
                        "receiptFileDigest": arm.metadata.get("receiptFileDigest"),
                        "executionCost": arm.metadata.get("executionCost"),
                        "anchorPolicy": arm.metadata.get("anchorPolicy"),
                        "anchorPolicyDigest": arm.metadata.get("anchorPolicyDigest"),
                        "reservoirId": arm.metadata.get("reservoirId"),
                    }.items()
                    if value is not None
                },
            }
        )
    reservoir_ids = sorted(
        {
            str(model.bundle.arms[option.arm_index].metadata["reservoirId"])
            for option in selected_options
            if option.kind == RERANKER_KIND
        }
    )
    return {
        "candidateCount": candidate_count,
        "goldFound": len(found),
        "goldCount": len(gold),
        "recall": 1.0,
        "activeArmCount": len(selected_options),
        "providerArmCount": sum(option.kind == PROVIDER_KIND for option in selected_options),
        "rerankerArmCount": sum(option.kind == RERANKER_KIND for option in selected_options),
        "pairSetDigest": _pair_set_digest(model.bundle, selected_pairs),
        "selectedArms": arms,
        "rerankerDependencies": [
            {
                "reservoirId": identifier,
                "scoredCandidatePairs": int(np.count_nonzero(model.bundle.reservoirs[identifier])),
                "reservoirMaskDigest": model.bundle.metadata["reservoirs"][identifier]["maskDigest"],
            }
            for identifier in reservoir_ids
        ],
        "challengeCoverage": _challenge_coverage(model.bundle, selected_pairs),
    }


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_values = (left["candidateCount"], left["activeArmCount"])
    right_values = (right["candidateCount"], right["activeArmCount"])
    return all(a <= b for a, b in zip(left_values, right_values, strict=True)) and any(
        a < b for a, b in zip(left_values, right_values, strict=True)
    )


def solve_frontier(
    model: SignatureModel,
    *,
    name: str,
    allow_provider: bool,
    allow_reranker: bool,
    solver: str,
) -> dict[str, Any]:
    """Return the complete candidate-count/active-arm Pareto frontier."""

    global_result = solve_configuration(
        model,
        allow_provider=allow_provider,
        allow_reranker=allow_reranker,
        solver=solver,
    )
    if global_result is None:
        return {
            "name": name,
            "allowProvider": allow_provider,
            "allowReranker": allow_reranker,
            "complete": False,
            "pareto": [],
        }
    global_summary = summarize_solution(model, *global_result)
    maximum_useful_arms = int(global_summary["activeArmCount"])
    points = []
    for active_cap in range(1, maximum_useful_arms):
        result = solve_configuration(
            model,
            allow_provider=allow_provider,
            allow_reranker=allow_reranker,
            active_cap=active_cap,
            solver=solver,
        )
        if result is not None:
            points.append(summarize_solution(model, *result))
    points.append(global_summary)
    unique: dict[tuple[int, int, str], dict[str, Any]] = {}
    for point in points:
        key = (point["candidateCount"], point["activeArmCount"], point["pairSetDigest"])
        unique[key] = point
    pareto = [
        point
        for point in unique.values()
        if not any(_dominates(other, point) for other in unique.values() if other is not point)
    ]
    pareto.sort(key=lambda value: (value["activeArmCount"], value["candidateCount"], value["pairSetDigest"]))
    minimum = min(pareto, key=lambda value: (value["candidateCount"], value["activeArmCount"]))
    return {
        "name": name,
        "allowProvider": allow_provider,
        "allowReranker": allow_reranker,
        "complete": True,
        "paretoObjective": ["candidateCount", "activeArmCount"],
        "pareto": pareto,
        "minimumCandidateCompleteUnion": minimum,
    }


SCENARIOS = (
    ("unrestricted", True, True),
    ("no-provider", False, True),
    ("no-reranker", True, False),
    ("no-provider-no-reranker", False, False),
)


def optimize_bundle(bundle: Bundle, *, solver: str = "auto") -> dict[str, Any]:
    """Optimize all required operating scenarios."""

    model = build_signature_model(bundle)
    frontiers = {
        name: solve_frontier(
            model,
            name=name,
            allow_provider=allow_provider,
            allow_reranker=allow_reranker,
            solver=solver,
        )
        for name, allow_provider, allow_reranker in SCENARIOS
    }
    dependency_validation = {
        "graphArms": [
            {
                "id": arm.identifier,
                "anchorPolicy": arm.metadata["anchorPolicy"],
                "anchorPolicyDigest": arm.metadata["anchorPolicyDigest"],
                "validated": True,
            }
            for arm in bundle.arms
            if arm.kind == GRAPH_KIND
        ],
        "rerankerArms": [
            {
                "id": arm.identifier,
                "reservoirId": arm.metadata["reservoirId"],
                "reservoirPairCount": int(np.count_nonzero(bundle.reservoirs[str(arm.metadata["reservoirId"])])),
                "allRankedCandidatesInsideReservoir": True,
                "executionCost": arm.metadata.get("executionCost"),
            }
            for arm in bundle.arms
            if arm.kind == RERANKER_KIND
        ],
    }
    result: dict[str, Any] = {
        "type": RESULT_TYPE,
        "schemaVersion": RESULT_VERSION,
        "bundle": str(bundle.path),
        "bundleMetadataDigest": bundle.metadata["metadataDigest"],
        "pairCount": bundle.pair_count,
        "goldCount": len(bundle.gold_indexes),
        "armCount": len(bundle.arms),
        "optionCount": len(model.options),
        "compressedPairSignatureCount": len(model.signatures),
        "dependencyValidation": dependency_validation,
        "languageScope": bundle.metadata.get("provenance", {}).get("languageScope"),
        "excludedProductionArms": bundle.metadata.get("provenance", {}).get("excludedProductionArms", []),
        "solver": (
            "exact exhaustive"
            if solver == "brute-force"
            else "exact rarest-gold branch-and-bound"
            if solver in {"auto", "branch-and-bound"}
            else "exact MILP"
        ),
        "frontiers": frontiers,
    }
    stable = dict(result)
    result["resultDigest"] = _sha256_bytes(_canonical_json(stable).encode())
    return result


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--solver",
        choices=("auto", "milp", "brute-force", "branch-and-bound"),
        default="auto",
    )
    parser.add_argument("--deterministic-repeats", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.deterministic_repeats < 1:
        raise ValueError("deterministic repeats must be positive")
    bundle = load_bundle(args.bundle)
    results = [optimize_bundle(bundle, solver=args.solver) for _ in range(args.deterministic_repeats)]
    digests = {result["resultDigest"] for result in results}
    if len(digests) != 1:
        raise RuntimeError("deterministic repeat produced different frontier digests")
    result = results[0]
    result["deterministicRepeats"] = args.deterministic_repeats
    rendered = _canonical_json(result) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
