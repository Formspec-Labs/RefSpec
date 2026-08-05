"""Focused checks for the experiment-only ICPSR endpoint projection."""

from __future__ import annotations

import pytest

from refspec.atlas.qualification import AtlasConcept, AtlasConceptContext
from tools import benchmark_atlas_candidate_retrieval as shared
from tools import benchmark_icpsr_endpoint_alias_projection as experiment


def _row(
    member: str,
    label: str,
    role: str,
    *uses: str,
) -> dict[str, object]:
    return {
        "conceptIri": member,
        "officialLabel": label,
        "officialLabelRole": role,
        "relations": [
            {
                "relation": "use",
                "resolutionStatus": "uriVerified",
                "targetConceptIri": target,
                "targetLabel": {
                    "urn:test:middle": "Middle alias",
                    "urn:test:start": "Starting alias",
                    "urn:test:preferred": "Preferred concept",
                    "urn:test:other": "Other concept",
                }[target],
            }
            for target in uses
        ],
    }


def test_projection_follows_access_term_chains_to_preferred_sink() -> None:
    rows = [
        _row("urn:test:preferred", "Preferred concept", "preferred"),
        _row("urn:test:middle", "Middle alias", "alternate", "urn:test:preferred"),
        _row("urn:test:start", "Starting alias", "alternate", "urn:test:middle"),
        _row("urn:test:unresolved", "Unresolved alias", "alternate"),
    ]

    projection = experiment.build_endpoint_projection(rows)

    assert projection.preferred_members == frozenset({"urn:test:preferred"})
    assert projection.aliases_by_preferred == {"urn:test:preferred": ("Middle alias", "Starting alias")}
    assert [row["hops"] for row in projection.access_paths] == [1, 2]
    assert projection.unresolved_alternates[0]["member"] == "urn:test:unresolved"
    assert projection.digest.startswith("sha256:")


def test_projection_refuses_branching_cycle_and_label_ambiguity() -> None:
    preferred = _row("urn:test:preferred", "Preferred concept", "preferred")
    other = _row("urn:test:other", "Other concept", "preferred")
    with pytest.raises(ValueError, match="ambiguous use targets"):
        experiment.build_endpoint_projection(
            [preferred, other, _row("urn:test:branch", "Branch", "alternate", "urn:test:preferred", "urn:test:other")]
        )

    cycle = [
        _row("urn:test:middle", "Middle alias", "alternate", "urn:test:start"),
        _row("urn:test:start", "Starting alias", "alternate", "urn:test:middle"),
    ]
    with pytest.raises(ValueError, match="cycle"):
        experiment.build_endpoint_projection(cycle)

    duplicate = [
        preferred,
        other,
        _row("urn:test:alias-one", "Same alias", "alternate", "urn:test:preferred"),
        _row("urn:test:alias-two", "same alias", "alternate", "urn:test:other"),
    ]
    with pytest.raises(ValueError, match="label reaches two"):
        experiment.build_endpoint_projection(duplicate)


def test_case_projection_keeps_preferred_endpoints_and_enriches_hierarchy_context() -> None:
    projection = experiment.build_endpoint_projection(
        [
            _row("urn:test:preferred", "Preferred concept", "preferred"),
            _row("urn:test:access", "Access label", "alternate", "urn:test:preferred"),
        ]
    )
    source = AtlasConcept("urn:source", "urn:source-release", "Source")
    preferred = AtlasConcept(
        "urn:test:preferred",
        "urn:icpsr-release",
        "Preferred concept",
        parents=(AtlasConceptContext("urn:test:preferred", "Preferred concept"),),
    )
    alternate = AtlasConcept("urn:test:access", "urn:icpsr-release", "Access label")
    case = shared.AlignmentCase(
        "example",
        (source,),
        (preferred, alternate),
        frozenset({(source.member, preferred.member)}),
    )

    projected = experiment.project_alignment_cases((case,), projection)[0]

    assert [concept.member for concept in projected.targets] == ["urn:test:preferred"]
    assert projected.targets[0].alt_labels == ("Access label",)
    assert projected.targets[0].parents[0].alt_labels == ("Access label",)
