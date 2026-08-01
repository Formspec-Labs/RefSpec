from __future__ import annotations

from types import MappingProxyType
from typing import Any

from refspec import (
    ManagedReleaseIdentityLink,
    ManagedReleaseMember,
    ManagedReleaseView,
)

IS_VERSION_OF = "http://purl.org/dc/terms/isVersionOf"
PRIOR_VERSION = "http://www.w3.org/2002/07/owl#priorVersion"
IS_REPLACED_BY = "http://purl.org/dc/terms/isReplacedBy"
REPLACES = "http://purl.org/dc/terms/replaces"

R5_RELEASE = "https://elsst.cessda.eu/id/5/"
R6_RELEASE = "https://elsst.cessda.eu/id/6/"
R5_RETIRED = "https://elsst.cessda.eu/id/5/retired"
R6_RETIRED = "https://elsst.cessda.eu/id/6/retired"
R6_SUCCESSOR = "https://elsst.cessda.eu/id/6/successor"
STABLE_RETIRED = "https://elsst.cessda.eu/id/retired"


def _frozen_record(values: dict[str, Any]) -> MappingProxyType[str, Any]:
    return MappingProxyType(values)


def _view() -> ManagedReleaseView:
    members = {
        R5_RETIRED: ManagedReleaseMember(
            member_iri=R5_RETIRED,
            release_iri=R5_RELEASE,
            scheme_iri=R5_RELEASE,
            record=_frozen_record(
                {
                    "@id": R5_RETIRED,
                    "dcterms:isVersionOf": STABLE_RETIRED,
                }
            ),
        ),
        R6_RETIRED: ManagedReleaseMember(
            member_iri=R6_RETIRED,
            release_iri=R6_RELEASE,
            scheme_iri=R6_RELEASE,
            record=_frozen_record(
                {
                    "@id": R6_RETIRED,
                    "dcterms:isVersionOf": {"@id": STABLE_RETIRED},
                    "owl:priorVersion": (R5_RETIRED,),
                    "dcterms:isReplacedBy": (R6_SUCCESSOR,),
                }
            ),
        ),
        R6_SUCCESSOR: ManagedReleaseMember(
            member_iri=R6_SUCCESSOR,
            release_iri=R6_RELEASE,
            scheme_iri=R6_RELEASE,
            record=_frozen_record(
                {
                    "@id": R6_SUCCESSOR,
                    REPLACES: ({"@id": R6_RETIRED},),
                }
            ),
        ),
    }
    return ManagedReleaseView(
        _release_id="urn:test:managed-release:elsst",
        _rulespec_graph_id="urn:test:rulespec-graph:elsst",
        _rulespec_graph=MappingProxyType(
            {
                "@graph": tuple(member.record for member in members.values()),
            }
        ),
        _expression_corpus_snapshot=MappingProxyType(
            {
                "id": "urn:test:expression-corpus",
                "digest": "sha256:" + ("0" * 64),
            }
        ),
        _members=MappingProxyType(members),
        _expressions=(),
        _relations=(),
        _lifecycle_participants=(),
        _concept_mappings=(),
        _release_graph_validation_receipt=MappingProxyType({}),
    )


def test_identity_links_preserve_native_iris_and_resolve_packaged_releases() -> None:
    links = list(_view().iter_identity_links(member_iri=R6_RETIRED))

    assert links == [
        ManagedReleaseIdentityLink(
            subject_member_iri=R6_RETIRED,
            predicate_iri=IS_VERSION_OF,
            object_iri=STABLE_RETIRED,
            subject_release_iri=R6_RELEASE,
            object_release_iri=None,
        ),
        ManagedReleaseIdentityLink(
            subject_member_iri=R6_RETIRED,
            predicate_iri=PRIOR_VERSION,
            object_iri=R5_RETIRED,
            subject_release_iri=R6_RELEASE,
            object_release_iri=R5_RELEASE,
        ),
        ManagedReleaseIdentityLink(
            subject_member_iri=R6_RETIRED,
            predicate_iri=IS_REPLACED_BY,
            object_iri=R6_SUCCESSOR,
            subject_release_iri=R6_RELEASE,
            object_release_iri=R6_RELEASE,
        ),
    ]


def test_identity_link_filters_use_exact_subject_and_predicate_iris() -> None:
    view = _view()

    assert list(
        view.iter_identity_links(
            member_iri=R6_SUCCESSOR,
            predicate_iri=REPLACES,
        )
    ) == [
        ManagedReleaseIdentityLink(
            subject_member_iri=R6_SUCCESSOR,
            predicate_iri=REPLACES,
            object_iri=R6_RETIRED,
            subject_release_iri=R6_RELEASE,
            object_release_iri=R6_RELEASE,
        )
    ]
    assert list(view.iter_identity_links(predicate_iri="dcterms:replaces")) == []
