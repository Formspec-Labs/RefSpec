"""Validate a combined REF and Rulespec release graph.

The bundle is deliberately not a substitute for either validator. REF records
are passed to :mod:`refspec.binding`, and the Rulespec graph is written
unchanged to a temporary JSON-LD file for the pinned Rulespec validators.
This module checks only the boundary between those independently validated
parts: graph digest, validator receipt, covered identifiers, and cross-links.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from refspec import binding
from refspec.generated_rulespec_dependency import (
    RULESPEC_DEPENDENCY_BYTES,
)

REFSPEC_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEPENDENCY_MANIFEST = REFSPEC_ROOT / "profiles" / "rulespec-dependency.json"
GRAPH_DIGEST_ALGORITHM = binding.CANONICALIZATION_ALGORITHM
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
GRAPH_PLACEHOLDER = "{graph}"
BEHAVIOR_PLACEHOLDER = "{behavior}"
DEPENDENCY_MANIFEST_ID = "https://refspec.org/profiles/rulespec-dependency.json"
RULESPEC_VALIDATOR_COMPONENT_ID = "urn:rulespec:validator:rkaf-validate-and-ci-validate"
RULESPEC_BEHAVIOR_RUNTIME_COMPONENT_ID = "urn:rulespec:runtime:rkaf-behavior-validate"
RELEASE_GRAPH_GATE_COMPONENT_ID = "https://refspec.org/reference-runtime/release-graph-gate"
RELEASE_GRAPH_GATE_VERSION = "0.1.0.dev0"

RKAF_NAMESPACE = "https://rulespec.org/ns/v1#"
PROV_NAMESPACE = "http://www.w3.org/ns/prov#"
SKOS_NAMESPACE = "http://www.w3.org/2004/02/skos/core#"

RULESPEC_ARTIFACT = f"{RKAF_NAMESPACE}Artifact"
RULESPEC_SOURCE_FRAGMENT = f"{RKAF_NAMESPACE}SourceFragment"
RULESPEC_EVIDENCE_BINDING = f"{RKAF_NAMESPACE}EvidenceBinding"
RULESPEC_ACCESS_SCOPE = f"{RKAF_NAMESPACE}AccessScope"
RULESPEC_RETENTION_POLICY = f"{RKAF_NAMESPACE}RetentionPolicy"
RULESPEC_EXTRACTION_ACTIVITY = f"{RKAF_NAMESPACE}ExtractionActivity"
PROV_ACTIVITY = f"{PROV_NAMESPACE}Activity"
RULESPEC_REFERENCE_RESOURCE_RELEASE = f"{RKAF_NAMESPACE}ReferenceResourceRelease"
RULESPEC_CONCEPT_SCHEME = f"{RKAF_NAMESPACE}ConceptScheme"
RULESPEC_REGISTERED_CONCEPT = f"{RKAF_NAMESPACE}RegisteredConcept"
RULESPEC_LOCAL_CONCEPT = f"{RKAF_NAMESPACE}LocalConcept"
SKOS_CONCEPT_SCHEME = f"{SKOS_NAMESPACE}ConceptScheme"
SKOS_CONCEPT = f"{SKOS_NAMESPACE}Concept"
RULESPEC_CONCEPT_MAPPING = f"{RKAF_NAMESPACE}ConceptMapping"
RULESPEC_AUTHORITY = f"{RKAF_NAMESPACE}Authority"
RULESPEC_ATTESTATION = f"{RKAF_NAMESPACE}Attestation"
RULESPEC_LOCAL_ADOPTION = f"{RKAF_NAMESPACE}LocalAdoption"
RULESPEC_ASSERTION = f"{RKAF_NAMESPACE}Assertion"
RULESPEC_VALUE_ASSERTION = f"{RKAF_NAMESPACE}ValueAssertion"
RULESPEC_RELATIONSHIP_ASSERTION = f"{RKAF_NAMESPACE}RelationshipAssertion"
RULESPEC_CONCEPT_ASSIGNMENT = f"{RKAF_NAMESPACE}ConceptAssignment"
RULESPEC_BRIDGE_CONSUMER_REGISTRATION = f"{RKAF_NAMESPACE}BridgeConsumerRegistration"
RULESPEC_EFFECTIVE_PERIOD = f"{RKAF_NAMESPACE}EffectivePeriod"

ACTIVITY_TYPES = frozenset({PROV_ACTIVITY, RULESPEC_EXTRACTION_ACTIVITY})
CONCEPT_SCHEME_TYPES = frozenset(
    {
        RULESPEC_CONCEPT_SCHEME,
        SKOS_CONCEPT_SCHEME,
    }
)
CONCEPT_TYPES = frozenset(
    {
        RULESPEC_REGISTERED_CONCEPT,
        RULESPEC_LOCAL_CONCEPT,
        SKOS_CONCEPT,
    }
)
EVIDENCE_TYPES = frozenset({RULESPEC_SOURCE_FRAGMENT, RULESPEC_EVIDENCE_BINDING})
ASSERTION_TYPES = frozenset(
    {
        RULESPEC_ASSERTION,
        RULESPEC_VALUE_ASSERTION,
        RULESPEC_RELATIONSHIP_ASSERTION,
        RULESPEC_CONCEPT_ASSIGNMENT,
    }
)
AUTHORIZATION_MINIMUM = "rkaf:localOperationalUse"
AUTHORIZED_LEVELS = (
    "rkaf:localOperationalUse",
    "rkaf:publicationAllowed",
    "rkaf:officialUse",
)
APPROVING_ATTESTATION_DECISIONS = frozenset({"rkaf:approved"})
SELECTED_DEPLOYMENT_TYPES = frozenset(
    {
        "urn:ref:type:RegistryDeploymentDecision",
        "urn:ref:type:EnrichmentDeploymentDecision",
    }
)


@dataclass(frozen=True)
class RulespecReferenceRule:
    """One REF field path whose value must resolve in the Rulespec graph."""

    path: tuple[str, ...]
    expected_types: frozenset[str] | None


@dataclass(frozen=True)
class RulespecReferenceRequirement:
    """One concrete Rulespec identifier extracted from an REF record."""

    identifier: str
    path: str
    expected_types: frozenset[str] | None


def _rule(
    path: str,
    *expected_types: str,
) -> RulespecReferenceRule:
    return RulespecReferenceRule(
        path=tuple(path.split("/")),
        expected_types=(frozenset(expected_types) if expected_types else None),
    )


# These paths are deliberately narrower than "every IRI in an REF record".
# Component pins, actor identifiers, ontology terms, REF records, and external
# policy documents remain external unless a field explicitly promises a
# Rulespec semantic record.
RULESPEC_REFERENCE_RULES: Mapping[str, tuple[RulespecReferenceRule, ...]] = {
    "urn:ref:type:Capture": (
        _rule("acquisitionActivity", *ACTIVITY_TYPES),
        _rule("accessScopeRefs/*", RULESPEC_ACCESS_SCOPE),
        _rule("retentionPolicyRefs/*", RULESPEC_RETENTION_POLICY),
    ),
    "urn:ref:type:RightsAssessment": (
        _rule(
            "observedTerms/*/sourceFragment",
            RULESPEC_SOURCE_FRAGMENT,
        ),
        _rule(
            "supportingSourceFragments/*",
            RULESPEC_SOURCE_FRAGMENT,
        ),
        # The profile permits several Rulespec or adopted policy shapes. The
        # graph must define the record, but RefSpec must not invent its range.
        _rule("rulespecPolicyRefs/*"),
        _rule("attestationRefs/*", RULESPEC_ATTESTATION),
        _rule("localAdoptionRefs/*", RULESPEC_LOCAL_ADOPTION),
    ),
    "urn:ref:type:RunReceipt": (
        _rule(
            "rulespecReleases/*/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule("rulespecActivityRefs/*", *ACTIVITY_TYPES),
        _rule("rulespecOutputRefs/*"),
    ),
    "urn:ref:type:RegistryImportSnapshot": (
        _rule(
            "referenceResourceRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule("distributionArtifacts/*/id", RULESPEC_ARTIFACT),
        _rule("rulespecValidationResult/id"),
        _rule("activity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:RegistryImportCoverageReport": (
        _rule(
            "referenceResourceRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule("distributionArtifacts/*/id", RULESPEC_ARTIFACT),
        _rule("activity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:IndexedVocabularyExpression": (
        _rule(
            "referenceResourceRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule("distributionArtifact/id", RULESPEC_ARTIFACT),
        _rule("scheme", *CONCEPT_SCHEME_TYPES),
        _rule("member", *CONCEPT_TYPES),
        _rule("activity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:RegistryReconciliationReport": (
        _rule(
            "inputs/*/referenceResourceRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule(
            "inputs/*/distributionArtifacts/*/id",
            RULESPEC_ARTIFACT,
        ),
        _rule("conceptMappings/*", RULESPEC_CONCEPT_MAPPING),
        _rule("rulespecAuthorityRefs/*", RULESPEC_AUTHORITY),
        _rule("attestationRefs/*", RULESPEC_ATTESTATION),
        _rule("localAdoptionRefs/*", RULESPEC_LOCAL_ADOPTION),
        _rule(
            "selectedInputRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule(
            "reconciledRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule("activity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:RegistryDeploymentDecision": (
        _rule(
            "referenceResourceRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule("rulespecAttestationRefs/*", RULESPEC_ATTESTATION),
        _rule("localAdoptionRefs/*", RULESPEC_LOCAL_ADOPTION),
        _rule("activity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:ConceptProposal": (
        _rule("placement/targetConcept", *CONCEPT_TYPES),
        _rule("activity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:OutputProfile": (
        _rule(
            "releasePermissions/*/referenceResourceRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule(
            "mappingPermissions/*/sourceRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule(
            "mappingPermissions/*/targetRelease/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
    ),
    "urn:ref:type:SealedGoldManifest": (
        _rule("items/*/renditionArtifact/id", RULESPEC_ARTIFACT),
        _rule("items/*/sourceFragment", RULESPEC_SOURCE_FRAGMENT),
        _rule(
            "vocabularyUniverse/referenceResourceReleases/*/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule(
            "vocabularyUniverse/mappingReleases/*/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule(
            "expectations/*/registeredTargets/*/release/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule(
            "expectations/*/registeredTargets/*/target",
            *CONCEPT_TYPES,
        ),
        _rule("expectations/*/forbiddenResults/*", *CONCEPT_TYPES),
        _rule("expectations/*/evidenceRefs/*", *EVIDENCE_TYPES),
        _rule(
            "expectations/*/reviewerJudgments/*/judgment",
            RULESPEC_ATTESTATION,
        ),
        _rule(
            "expectations/*/adjudication/judgment",
            RULESPEC_ATTESTATION,
        ),
        _rule("independentJudgmentRefs/*", RULESPEC_ATTESTATION),
        _rule("disagreementRefs/*", RULESPEC_ATTESTATION),
        _rule("adjudicationRefs/*", RULESPEC_ATTESTATION),
        _rule("sealingActivity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:EnrichmentConfiguration": (
        _rule(
            "vocabulary/referenceResourceReleases/*/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
        _rule(
            "vocabulary/mappingReleases/*/id",
            RULESPEC_REFERENCE_RESOURCE_RELEASE,
        ),
    ),
    "urn:ref:type:EnrichmentEvaluationResult": (_rule("activity", *ACTIVITY_TYPES),),
    "urn:ref:type:EnrichmentDeploymentDecision": (
        _rule("rulespecAttestationRefs/*", RULESPEC_ATTESTATION),
        _rule("localAdoptionRefs/*", RULESPEC_LOCAL_ADOPTION),
        _rule("activity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:PublicationReleaseManifest": (
        _rule("rulespecDependency/conformanceResult/id"),
        _rule("rulespecReleaseGraph/id", RULESPEC_ARTIFACT),
        _rule("activity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:ReleaseGraphValidationReceipt": (
        _rule("rulespecGraph/id", RULESPEC_ARTIFACT),
        _rule(
            "authorizationEvaluations/*/subjectAssertion",
            *ASSERTION_TYPES,
        ),
        _rule("activity", *ACTIVITY_TYPES),
    ),
    "urn:ref:type:EnrichmentProfile": (),
}


@dataclass(frozen=True)
class ValidatorCommand:
    """One command in the trusted, pinned Rulespec validation sequence."""

    name: str
    argv: tuple[str, ...]

    def for_graph(self, graph_path: Path) -> list[str]:
        graph = str(graph_path)
        return [argument.replace(GRAPH_PLACEHOLDER, graph) for argument in self.argv]

    def for_behavior(self, behavior_path: Path) -> list[str]:
        behavior = str(behavior_path)
        return [argument.replace(BEHAVIOR_PLACEHOLDER, behavior) for argument in self.argv]


@dataclass(frozen=True)
class RulespecValidatorPin:
    """Trusted local configuration for the exact Rulespec validator."""

    identity: str
    source_revision: str
    evidence_revision: str
    working_directory: Path
    commands: tuple[ValidatorCommand, ...]
    behavior_command: ValidatorCommand | None = None
    component_id: str = RULESPEC_VALIDATOR_COMPONENT_ID
    component_digest: str = ""
    behavior_component_id: str = RULESPEC_BEHAVIOR_RUNTIME_COMPONENT_ID
    behavior_component_digest: str = ""
    dependency_manifest_id: str = DEPENDENCY_MANIFEST_ID
    dependency_manifest_digest: str = ""
    dependency_manifest: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ReleaseGraphGateReport:
    """Independent verdicts for the two specifications and their boundary."""

    ref_failures: tuple[str, ...] = ()
    rulespec_failures: tuple[str, ...] = ()
    cross_boundary_failures: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return not (self.ref_failures or self.rulespec_failures or self.cross_boundary_failures)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "refFailures": list(self.ref_failures),
            "rulespecFailures": list(self.rulespec_failures),
            "crossBoundaryFailures": list(self.cross_boundary_failures),
        }


def rulespec_graph_digest(graph: Any) -> str:
    """Return the exact canonical-JSON digest used to bind a bundle graph."""

    binding.validate_canonical_value(graph)
    payload = json.dumps(
        graph,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def canonical_value_digest(value: Any) -> str:
    """Return RefSpec canonical-JSON SHA-256 for a non-record value."""

    binding.validate_canonical_value(value)
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def compute_reference_resource_release_digest(
    graph: Any,
    *,
    release_iri: str,
    validator: RulespecValidatorPin,
) -> str:
    """Compute one Rulespec release digest with the exact pinned RDFC-1.0 tool.

    This is the shared boundary for import adapters that need to construct a
    portable ``rkaf:ReferenceResourceRelease``.  The external distribution
    remains canonical; this helper only seals the Rulespec semantic manifest.
    """

    if not isinstance(release_iri, str) or not release_iri.strip():
        raise ValueError("release_iri must be a non-empty absolute IRI")
    with tempfile.TemporaryDirectory(prefix="refspec-reference-release-digest-") as temporary:
        graph_path = Path(temporary) / "release.jsonld"
        graph_path.write_text(
            json.dumps(
                graph,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        command = [
            "uv",
            "run",
            "--python",
            "3.12",
            "--with-requirements",
            "requirements.txt",
            "python",
            "tools/reference_release_digest.py",
            str(graph_path),
            "--release",
            release_iri,
            "--json",
        ]
        try:
            result = subprocess.run(
                command,
                cwd=validator.working_directory,
                check=False,
                text=True,
                capture_output=True,
            )
        except OSError as error:
            raise ValueError(f"cannot execute pinned Rulespec release-digest tool: {error}") from error
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"pinned Rulespec release-digest tool returned unreadable output: {detail}") from error
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or rows[0].get("release") != release_iri
    ):
        raise ValueError("pinned Rulespec release-digest tool did not report the selected release")
    computed = rows[0].get("computed")
    if not isinstance(computed, str) or DIGEST_PATTERN.fullmatch(computed) is None:
        raise ValueError("pinned Rulespec release-digest tool returned an invalid digest")
    declared = rows[0].get("declared")
    if declared is not None and declared != computed:
        raise ValueError(f"declared release digest for {release_iri!r} does not match the pinned Rulespec computation")
    # Exit 1 is expected when the selected release has no declared digest yet.
    # Higher exit codes indicate tool or graph failures.
    if result.returncode not in {0, 1}:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"pinned Rulespec release-digest tool failed: {detail}")
    return computed


def _expanded_rulespec_type(value: str) -> str:
    """Expand the prefixes whose classes this boundary validates."""

    if value.startswith("rkaf:"):
        return RKAF_NAMESPACE + value.removeprefix("rkaf:")
    if value.startswith("prov:"):
        return PROV_NAMESPACE + value.removeprefix("prov:")
    if value.startswith("skos:"):
        return SKOS_NAMESPACE + value.removeprefix("skos:")
    return value


def _rulespec_node_types(graph: Any) -> dict[str, frozenset[str]]:
    """Index defining JSON-LD nodes and their normalized asserted types."""

    indexed: dict[str, set[str]] = {}

    def visit(value: Any, *, context: bool = False) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, context=context)
            return
        if not isinstance(value, dict) or context:
            return

        identifier = value.get("@id")
        defining_keys = {key for key in value if key not in {"@id", "@context", "@graph"}}
        if isinstance(identifier, str) and defining_keys:
            asserted = value.get("@type")
            asserted_values = asserted if isinstance(asserted, list) else [asserted]
            types = indexed.setdefault(identifier, set())
            types.update(_expanded_rulespec_type(item) for item in asserted_values if isinstance(item, str))

        for key, item in value.items():
            visit(item, context=key == "@context")

    visit(graph)
    return {identifier: frozenset(types) for identifier, types in indexed.items()}


def defined_rulespec_identifiers(graph: Any) -> frozenset[str]:
    """Find named JSON-LD nodes defined by the supplied graph."""

    return frozenset(_rulespec_node_types(graph))


def _values_at_rule_path(
    value: Any,
    path: tuple[str, ...],
    *,
    pointer: str = "",
) -> tuple[tuple[str, Any], ...]:
    if not path:
        return ((pointer or "/", value),)

    head, *tail = path
    if head == "*":
        if not isinstance(value, list):
            return ()
        results: list[tuple[str, Any]] = []
        for index, item in enumerate(value):
            results.extend(
                _values_at_rule_path(
                    item,
                    tuple(tail),
                    pointer=f"{pointer}/{index}",
                )
            )
        return tuple(results)

    if not isinstance(value, Mapping) or head not in value:
        return ()
    return _values_at_rule_path(
        value[head],
        tuple(tail),
        pointer=f"{pointer}/{head}",
    )


def _rulespec_reference_requirements(
    record: Mapping[str, Any],
) -> tuple[RulespecReferenceRequirement, ...]:
    record_type = record.get("type")
    if not isinstance(record_type, str):
        return ()
    rules = RULESPEC_REFERENCE_RULES.get(record_type)
    if rules is None:
        return ()

    requirements: list[RulespecReferenceRequirement] = []
    for rule in rules:
        for path, value in _values_at_rule_path(record, rule.path):
            if isinstance(value, str):
                requirements.append(
                    RulespecReferenceRequirement(
                        identifier=value,
                        path=path,
                        expected_types=rule.expected_types,
                    )
                )

    return tuple(requirements)


def referenced_rulespec_identifiers(
    record: Mapping[str, Any],
    graph_identifiers: frozenset[str],
) -> frozenset[str]:
    """Find the Rulespec identifiers promised by one REF record.

    Known REF record types use the normative field map, so a missing graph node
    cannot conceal a promised link. Unknown extension types retain the original
    intersection behavior for compatibility.
    """

    record_type = record.get("type")
    if isinstance(record_type, str) and record_type in RULESPEC_REFERENCE_RULES:
        return frozenset(requirement.identifier for requirement in _rulespec_reference_requirements(record))

    identifiers: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, str):
            if value in graph_identifiers:
                identifiers.add(value)
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if isinstance(value, Mapping):
            for item in value.values():
                visit(item)

    visit(record)
    return frozenset(identifiers)


def rulespec_dependency_bytes(path: Path | None = None) -> bytes:
    """Read an explicit dependency pin or use the generated installed copy."""

    path = DEFAULT_DEPENDENCY_MANIFEST if path is None else path
    if path.is_file():
        return path.read_bytes()
    if path == DEFAULT_DEPENDENCY_MANIFEST:
        return RULESPEC_DEPENDENCY_BYTES
    raise ValueError(f"Rulespec dependency manifest does not exist: {path}")


def load_rulespec_dependency_manifest(
    path: Path | None = None,
) -> dict[str, Any]:
    """Load the exact dependency manifest without requiring checkout assets."""

    try:
        manifest = json.loads(
            rulespec_dependency_bytes(path),
            object_pairs_hook=binding.reject_duplicate_keys,
            parse_constant=binding.reject_nonfinite_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"cannot read Rulespec dependency manifest: {error}") from error
    if not isinstance(manifest, dict):
        raise TypeError("Rulespec dependency manifest must be an object")
    return manifest


def load_pinned_rulespec_validator(
    rulespec_dir: Path,
    dependency_manifest: Path | None = None,
) -> RulespecValidatorPin:
    """Resolve the trusted Rulespec validator commands from RefSpec's dependency manifest.

    This builds the validator description RefSpec actually runs against a
    working Rulespec checkout at ``rulespec_dir``: the L1-L3 JSON Schema,
    SHACL, and ``ci_validate.py`` commands, and the L4 behavior runtime. It
    validates the manifest's own shape (identity, revisions), not that the
    checkout is byte-identical to any previously recorded commit or digest --
    RefSpec never re-derives a Rulespec artifact from the checkout, so there
    is nothing here for a checkout-fidelity check to protect. Re-pinning is a
    manifest edit, not a re-verification of the working tree.
    """

    rulespec_dir = rulespec_dir.resolve()
    manifest = load_rulespec_dependency_manifest(dependency_manifest)
    dependency_payload = rulespec_dependency_bytes(dependency_manifest)
    dependency_digest = "sha256:" + hashlib.sha256(dependency_payload).hexdigest()
    validator = manifest.get("validator")
    if not isinstance(validator, dict):
        raise TypeError("Rulespec dependency manifest has no validator pin")

    identity = validator.get("identity")
    source_revision = validator.get("sourceRevision")
    evidence_revision = manifest.get("evidenceRevision")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError("Rulespec validator identity is missing")
    if (
        "rkaf-validate" not in identity
        or "tools/ci_validate.py" not in identity
        or "rkaf-behavior-validate" not in identity
    ):
        raise ValueError(
            "Rulespec validator identity must pin rkaf-validate, tools/ci_validate.py, and rkaf-behavior-validate"
        )
    if not isinstance(source_revision, str) or not REVISION_PATTERN.fullmatch(source_revision):
        raise ValueError("Rulespec validator source revision is not an exact Git revision")
    if not isinstance(evidence_revision, str) or not REVISION_PATTERN.fullmatch(evidence_revision):
        raise ValueError("Rulespec evidence revision is not an exact Git revision")
    if not rulespec_dir.is_dir():
        raise ValueError(f"Rulespec checkout does not exist: {rulespec_dir}")

    certification_digest = validator.get("selfCertificationSha256")
    if not isinstance(certification_digest, str) or not certification_digest:
        raise TypeError("Rulespec validator self-certification pin is incomplete")

    commands = (
        ValidatorCommand(
            "rkaf-validate JSON Schema",
            (
                "cargo",
                "run",
                "--quiet",
                "--manifest-path",
                "crates/Cargo.toml",
                "-p",
                "rkaf-validate-cli",
                "--",
                "--json",
                GRAPH_PLACEHOLDER,
            ),
        ),
        ValidatorCommand(
            "Rulespec SHACL",
            (
                "uv",
                "run",
                "--python",
                "3.12",
                "--with-requirements",
                "requirements.txt",
                "python",
                "tools/ci_validate.py",
                "--json",
                GRAPH_PLACEHOLDER,
            ),
        ),
    )
    behavior_command = ValidatorCommand(
        "Rulespec L4 behavior",
        (
            "cargo",
            "run",
            "--quiet",
            "--manifest-path",
            "crates/Cargo.toml",
            "-p",
            "rkaf-runtime-cli",
            "--",
            "--json",
            BEHAVIOR_PLACEHOLDER,
        ),
    )
    component_digest = canonical_value_digest(
        {
            "identity": identity,
            "sourceRevision": source_revision,
            "selfCertificationSha256": certification_digest,
        }
    )
    behavior_component_digest = canonical_value_digest(
        {
            "identity": "rkaf-behavior-validate",
            "sourceRevision": source_revision,
            "evidenceRevision": evidence_revision,
            "sourcePaths": [
                "crates/rkaf-runtime",
                "crates/rkaf-runtime-cli",
            ],
        }
    )
    return RulespecValidatorPin(
        identity=identity,
        source_revision=source_revision,
        evidence_revision=evidence_revision,
        working_directory=rulespec_dir,
        commands=commands,
        behavior_command=behavior_command,
        component_digest=component_digest,
        behavior_component_digest=behavior_component_digest,
        dependency_manifest_digest=dependency_digest,
        dependency_manifest=dict(manifest),
    )


def _render_ref_diagnostic(diagnostic: Any) -> str:
    render = getattr(diagnostic, "render", None)
    return str(render()) if callable(render) else str(diagnostic)


def _string_set(
    value: Any,
    *,
    field: str,
    failures: list[str],
) -> frozenset[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        failures.append(f"{field} must be an array of identifiers")
        return frozenset()
    if len(value) != len(set(value)):
        failures.append(f"{field} must not repeat an identifier")
    return frozenset(value)


def _output_excerpt(result: subprocess.CompletedProcess[str]) -> str:
    output = (result.stderr or result.stdout or "").strip()
    if not output:
        return "no validator output"
    lines = output.splitlines()
    return " | ".join(lines[-3:])


def _run_rulespec_validator(
    graph: Any,
    digest: str,
    validator: RulespecValidatorPin,
) -> list[str]:
    failures: list[str] = []
    if not validator.commands:
        return ["pinned Rulespec validator defines no graph-validation command"]
    with tempfile.TemporaryDirectory(prefix="refspec-release-graph-") as temporary:
        graph_path = Path(temporary) / f"{digest.removeprefix('sha256:')}.jsonld"
        graph_path.write_text(
            json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for command in validator.commands:
            if not command.argv or not any(GRAPH_PLACEHOLDER in argument for argument in command.argv):
                failures.append(f"{command.name}: pinned command does not receive the exact graph")
                continue
            try:
                result = subprocess.run(
                    command.for_graph(graph_path),
                    cwd=validator.working_directory,
                    check=False,
                    text=True,
                    capture_output=True,
                )
            except OSError as error:
                failures.append(f"{command.name}: could not execute validator: {error}")
                continue
            if result.returncode:
                failures.append(
                    f"{command.name}: rejected graph with exit code {result.returncode}: {_output_excerpt(result)}"
                )
    return failures


def validate_rulespec_graph(
    graph: Any,
    *,
    validator: RulespecValidatorPin,
) -> tuple[str, ...]:
    """Run the exact pinned Rulespec JSON Schema and SHACL graph gates."""

    try:
        digest = rulespec_graph_digest(graph)
    except (TypeError, ValueError) as error:
        return (f"rulespecGraph cannot be canonicalized: {error}",)
    return tuple(_run_rulespec_validator(graph, digest, validator))


def _rulespec_nodes(graph: Any) -> dict[str, Mapping[str, Any]]:
    """Return the last defining object for each named JSON-LD node."""

    nodes: dict[str, Mapping[str, Any]] = {}

    def visit(value: Any, *, context: bool = False) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item, context=context)
            return
        if not isinstance(value, Mapping) or context:
            return
        identifier = value.get("@id")
        defining_keys = {key for key in value if key not in {"@id", "@context", "@graph"}}
        if isinstance(identifier, str) and defining_keys:
            nodes[identifier] = value
        for key, item in value.items():
            visit(item, context=key == "@context")

    visit(graph)
    return nodes


def _timestamp(value: Any, *, field: str) -> dt.datetime:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be an RFC 3339 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _string_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return ()


def _attestation_is_effective(
    attestation: Mapping[str, Any],
    *,
    evaluation_time: dt.datetime,
    nodes: Mapping[str, Mapping[str, Any]],
    node_types: Mapping[str, frozenset[str]],
    label: str,
) -> str | None:
    """Return a precise failure when an attestation is not in force."""

    if attestation.get("rkaf:decision") not in APPROVING_ATTESTATION_DECISIONS:
        return f"{label} does not carry an approving Rulespec decision"
    try:
        attested_at = _timestamp(
            attestation.get("rkaf:attestedAt"),
            field=f"{label}.rkaf:attestedAt",
        )
    except (TypeError, ValueError) as error:
        return str(error)
    if attested_at > evaluation_time:
        return f"{label} was recorded after the deployment evaluation time"

    revoked_at = attestation.get("rkaf:revokedAt")
    if revoked_at is not None:
        try:
            revoked = _timestamp(
                revoked_at,
                field=f"{label}.rkaf:revokedAt",
            )
        except (TypeError, ValueError) as error:
            return str(error)
        if revoked <= evaluation_time:
            return f"{label} was revoked at or before the deployment evaluation time"

    period_id = attestation.get("rkaf:hasEffectivePeriod")
    if period_id is None:
        return None
    if not isinstance(period_id, str):
        return f"{label}.rkaf:hasEffectivePeriod must be an identifier"
    period = nodes.get(period_id)
    if period is None:
        return f"{label} names missing effective period {period_id!r}"
    if RULESPEC_EFFECTIVE_PERIOD not in node_types.get(period_id, frozenset()):
        return f"{label} effective period {period_id!r} has the wrong Rulespec type"
    try:
        start = _timestamp(
            period.get("rkaf:effectivePeriodStart"),
            field=f"{period_id}.rkaf:effectivePeriodStart",
        )
        end_value = period.get("rkaf:effectivePeriodEnd")
        end = (
            _timestamp(
                end_value,
                field=f"{period_id}.rkaf:effectivePeriodEnd",
            )
            if end_value is not None
            else None
        )
    except (TypeError, ValueError) as error:
        return str(error)
    if evaluation_time < start or (end is not None and evaluation_time > end):
        return f"{label} is outside its Rulespec effective period"
    return None


def _behavior_test_identifier(governance_record_id: str) -> str:
    suffix = hashlib.sha256(governance_record_id.encode("utf-8")).hexdigest()
    return f"urn:ref:behavior-test:governance-authorization:{suffix}"


def _authorization_behavior_test(
    *,
    governance_record_id: str,
    graph: Mapping[str, Any],
    subject_assertion: str,
    evaluation_scope: str,
    evaluation_time: str,
    expected_level: str,
    evaluation_consumer: str | None,
) -> dict[str, Any]:
    test_case: dict[str, Any] = {
        "@context": {"rkaf": RKAF_NAMESPACE},
        "@id": _behavior_test_identifier(governance_record_id),
        "@type": "rkaf:BehaviorTestCase",
        "rkaf:behaviorContract": "rkaf:UsageEligibilityReducer",
        "rkaf:subjectAssertion": subject_assertion,
        "rkaf:evaluationScopes": [evaluation_scope],
        "rkaf:evaluationTime": evaluation_time,
        "rkaf:input": graph,
        "rkaf:expectedOutput": {"byScope": {evaluation_scope: expected_level}},
    }
    if evaluation_consumer is not None:
        test_case["rkaf:evaluationConsumer"] = evaluation_consumer
    return test_case


def _run_behavior_test(
    test_case: Mapping[str, Any],
    *,
    validator: RulespecValidatorPin,
) -> tuple[str, str]:
    """Return ``(result, diagnostic)`` for one gate-owned L4 test."""

    command = validator.behavior_command
    if command is None:
        return "error", "pinned Rulespec validator defines no L4 behavior command"
    if not command.argv or not any(BEHAVIOR_PLACEHOLDER in argument for argument in command.argv):
        return "error", (f"{command.name}: pinned command does not receive the exact BehaviorTestCase")
    with tempfile.TemporaryDirectory(prefix="refspec-rulespec-behavior-") as temporary:
        test_identifier = test_case.get("@id")
        if not isinstance(test_identifier, str):
            return "error", "gate-owned BehaviorTestCase has no identifier"
        expected_name = "deployment-authorization-" + canonical_value_digest(test_case).removeprefix("sha256:")
        path = Path(temporary) / f"{expected_name}.jsonld"
        path.write_text(
            json.dumps(test_case, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                command.for_behavior(path),
                cwd=validator.working_directory,
                check=False,
                text=True,
                capture_output=True,
            )
        except OSError as error:
            return "error", f"{command.name}: could not execute runtime: {error}"

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "error", (f"{command.name}: runtime did not emit its required JSON verdict: {_output_excerpt(result)}")
    fixtures = payload.get("fixtures") if isinstance(payload, Mapping) else None
    if not isinstance(fixtures, list) or len(fixtures) != 1:
        return "error", f"{command.name}: runtime did not report exactly one behavior test"
    fixture = fixtures[0]
    if not isinstance(fixture, Mapping):
        return "error", f"{command.name}: runtime emitted a malformed behavior verdict"
    if fixture.get("name") != expected_name:
        return "error", (
            f"{command.name}: runtime verdict names {fixture.get('name')!r}, "
            f"not the exact gate-owned behavior test {expected_name!r}"
        )
    fixture_result = fixture.get("result")
    diagnostic = fixture.get("diagnostic")
    detail = diagnostic if isinstance(diagnostic, str) else ""
    if result.returncode == 0 and fixture_result == "pass":
        return "pass", detail
    if result.returncode == 1 and fixture_result == "fail":
        return "mismatch", detail
    return "error", (
        f"{command.name}: runtime returned exit code {result.returncode} "
        f"with result {fixture_result!r}: {detail or _output_excerpt(result)}"
    )


def _governance_authorization_evaluations(
    *,
    records: Sequence[Mapping[str, Any]],
    graph: Any,
    graph_id: str | None,
    graph_digest: str | None,
    node_types: Mapping[str, frozenset[str]],
    validator: RulespecValidatorPin,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Run gate-owned L4 evaluations for every authorizing REF record."""

    failures: list[str] = []
    evaluations: list[dict[str, Any]] = []
    governed_records = [
        record
        for record in records
        if (record.get("type") in SELECTED_DEPLOYMENT_TYPES and record.get("selectionState") == "selected")
        or (
            record.get("type") == "urn:ref:type:RegistryReconciliationReport"
            and record.get("outcome") in {"selectedInput", "reconciledReleaseAuthorized"}
        )
    ]
    if not governed_records:
        return failures, evaluations
    if not isinstance(graph, Mapping):
        return ["governance authorization requires an object-form Rulespec graph"], []
    if not isinstance(graph_id, str) or graph_digest is None:
        return ["governance authorization requires the exact graph identifier and digest"], []

    nodes = _rulespec_nodes(graph)
    consumers = [
        identifier for identifier, types in node_types.items() if RULESPEC_BRIDGE_CONSUMER_REGISTRATION in types
    ]
    runtime_pin = {
        "id": validator.behavior_component_id,
        "revision": validator.source_revision,
        "digest": (
            validator.behavior_component_digest
            or canonical_value_digest(
                {
                    "identity": validator.behavior_component_id,
                    "sourceRevision": validator.source_revision,
                }
            )
        ),
    }

    for governance_record in governed_records:
        governance_record_id = governance_record.get("id")
        if not isinstance(governance_record_id, str):
            failures.append("authorizing REF record has no stable identifier")
            continue
        record_type = governance_record.get("type")
        is_reconciliation = record_type == ("urn:ref:type:RegistryReconciliationReport")
        label = f"{governance_record_id}: governance authorization"
        decision_failures: list[str] = []
        scope_source = governance_record.get("precedencePolicy" if is_reconciliation else "environment")
        scope = scope_source.get("id") if isinstance(scope_source, Mapping) else None
        effective_at = governance_record.get("recordedAt" if is_reconciliation else "effectiveAt")
        if not isinstance(scope, str):
            decision_failures.append(f"{label} has no derived scope identifier")
        try:
            evaluation_time = _timestamp(
                effective_at,
                field=f"{label}.effectiveAt",
            )
        except (TypeError, ValueError) as error:
            decision_failures.append(str(error))
            evaluation_time = None

        attestation_refs = _string_values(
            governance_record.get("attestationRefs" if is_reconciliation else "rulespecAttestationRefs")
        )
        adoption_refs = _string_values(governance_record.get("localAdoptionRefs"))
        authority_refs = _string_values(governance_record.get("rulespecAuthorityRefs")) if is_reconciliation else ()
        if not attestation_refs:
            decision_failures.append(f"{label} names no Rulespec attestation")
        if not adoption_refs:
            decision_failures.append(f"{label} names no Rulespec local adoption")

        adoption_targets: set[str] = set()
        for adoption_id in adoption_refs:
            adoption = nodes.get(adoption_id)
            adoption_label = f"{label} local adoption {adoption_id!r}"
            if adoption is None:
                decision_failures.append(f"{adoption_label} is missing")
                continue
            target = adoption.get("rkaf:targetAssertion")
            if isinstance(target, str):
                adoption_targets.add(target)
            else:
                decision_failures.append(f"{adoption_label} has no target assertion")
            if adoption.get("rkaf:adoptionStatus") != "rkaf:active":
                decision_failures.append(f"{adoption_label} is not active")
            if scope is not None and adoption.get("rkaf:adoptionScope") != scope:
                decision_failures.append(f"{adoption_label} does not use deployment scope {scope!r}")
            if adoption.get("rkaf:usageEligibility") not in AUTHORIZED_LEVELS:
                decision_failures.append(f"{adoption_label} grants less than {AUTHORIZATION_MINIMUM}")
            based_on = adoption.get("rkaf:basedOnAttestation")
            if based_on not in attestation_refs:
                decision_failures.append(f"{adoption_label} is not based on a named attestation")
            if evaluation_time is not None:
                try:
                    adopted_at = _timestamp(
                        adoption.get("rkaf:adoptedAt"),
                        field=f"{adoption_label}.rkaf:adoptedAt",
                    )
                except (TypeError, ValueError) as error:
                    decision_failures.append(str(error))
                else:
                    if adopted_at > evaluation_time:
                        decision_failures.append(f"{adoption_label} was recorded after the deployment evaluation time")

        subject = next(iter(adoption_targets)) if len(adoption_targets) == 1 else None
        if subject is None:
            decision_failures.append(f"{label} local adoptions do not target exactly one assertion")
        elif node_types.get(subject, frozenset()).isdisjoint(ASSERTION_TYPES):
            decision_failures.append(f"{label} target {subject!r} is not a Rulespec assertion")
        if subject is not None and authority_refs:
            assertion = nodes.get(subject)
            asserted_authorities = (
                set(_string_values(assertion.get("rkaf:hasAuthority"))) if assertion is not None else set()
            )
            missing_authorities = set(authority_refs) - asserted_authorities
            if missing_authorities:
                decision_failures.append(
                    f"{label} assertion does not name declared authorities {sorted(missing_authorities)!r}"
                )

        for attestation_id in attestation_refs:
            attestation = nodes.get(attestation_id)
            attestation_label = f"{label} attestation {attestation_id!r}"
            if attestation is None:
                decision_failures.append(f"{attestation_label} is missing")
                continue
            if subject is not None and subject not in _string_values(attestation.get("rkaf:targets")):
                decision_failures.append(f"{attestation_label} does not target {subject!r}")
            if evaluation_time is not None:
                failure = _attestation_is_effective(
                    attestation,
                    evaluation_time=evaluation_time,
                    nodes=nodes,
                    node_types=node_types,
                    label=attestation_label,
                )
                if failure is not None:
                    decision_failures.append(failure)

        evaluation_consumer: str | None = None
        if len(consumers) == 1:
            evaluation_consumer = consumers[0]
        elif len(consumers) > 1 and scope is not None:
            matching = [identifier for identifier in consumers if nodes[identifier].get("rkaf:consumer") == scope]
            if len(matching) == 1:
                evaluation_consumer = matching[0]
            else:
                decision_failures.append(
                    f"{label} cannot select one Rulespec consumer registration for scope {scope!r}"
                )

        if decision_failures:
            failures.extend(decision_failures)
            continue
        assert subject is not None
        assert scope is not None
        assert isinstance(effective_at, str)

        passing_test: dict[str, Any] | None = None
        effective_level: str | None = None
        runtime_error: str | None = None
        for candidate_level in AUTHORIZED_LEVELS:
            test_case = _authorization_behavior_test(
                governance_record_id=governance_record_id,
                graph=graph,
                subject_assertion=subject,
                evaluation_scope=scope,
                evaluation_time=effective_at,
                expected_level=candidate_level,
                evaluation_consumer=evaluation_consumer,
            )
            result, diagnostic = _run_behavior_test(
                test_case,
                validator=validator,
            )
            if result == "pass":
                passing_test = test_case
                effective_level = candidate_level
                break
            if result == "error":
                runtime_error = diagnostic
                break
        if passing_test is None or effective_level is None:
            failures.append(
                f"{label} did not pass the pinned Rulespec L4 runtime at or "
                f"above {AUTHORIZATION_MINIMUM}: "
                f"{runtime_error or 'computed usage was below the minimum'}"
            )
            continue

        digest_key = binding.digest_field(governance_record)
        governance_record_digest = governance_record.get(digest_key)
        if governance_record_digest != binding.canonical_payload_digest(governance_record):
            failures.append(f"{label} does not carry its exact canonical digest")
            continue
        output = {"byScope": {scope: effective_level}}
        evaluations.append(
            {
                "governanceRecord": {
                    "id": governance_record_id,
                    "digest": governance_record_digest,
                },
                "behaviorTest": {
                    "id": passing_test["@id"],
                    "digest": canonical_value_digest(passing_test),
                },
                "inputGraph": {"id": graph_id, "digest": graph_digest},
                "behaviorContract": "rkaf:UsageEligibilityReducer",
                "subjectAssertion": subject,
                "evaluationScope": scope,
                "evaluationTime": effective_at,
                "minimumUsageEligibility": AUTHORIZATION_MINIMUM,
                "effectiveUsageEligibility": effective_level,
                "outputDigest": canonical_value_digest(output),
                "runtime": runtime_pin,
                "result": "pass",
            }
        )

    return failures, evaluations


def validate_release_graph_bundle(
    bundle: Mapping[str, Any],
    *,
    validator: RulespecValidatorPin,
    _authorization_evaluations: list[dict[str, Any]] | None = None,
) -> ReleaseGraphGateReport:
    """Validate both specifications and the explicit boundary between them."""

    ref_failures: list[str] = []
    rulespec_failures: list[str] = []
    cross_failures: list[str] = []

    if bundle.get("bundleVersion") != "1.0":
        cross_failures.append("bundleVersion must be '1.0'")

    records_value = bundle.get("refRecords")
    records: list[dict[str, Any]] = []
    if not isinstance(records_value, list) or any(not isinstance(record, dict) for record in records_value):
        ref_failures.append("refRecords must be an array of REF record objects")
    else:
        records = records_value
        try:
            ref_failures.extend(_render_ref_diagnostic(diagnostic) for diagnostic in binding.validate(records))
        except (OSError, TypeError, ValueError) as error:
            ref_failures.append(f"REF validator could not validate records: {error}")

    graph = bundle.get("rulespecGraph")
    computed_digest: str | None = None
    graph_identifiers: frozenset[str] = frozenset()
    graph_node_types: dict[str, frozenset[str]] = {}
    if not isinstance(graph, (dict, list)):
        rulespec_failures.append("rulespecGraph must be a JSON-LD object or array")
    else:
        try:
            computed_digest = rulespec_graph_digest(graph)
            graph_node_types = _rulespec_node_types(graph)
            graph_identifiers = frozenset(graph_node_types)
        except (TypeError, ValueError) as error:
            rulespec_failures.append(f"rulespecGraph cannot be canonicalized: {error}")
        if not graph_identifiers:
            rulespec_failures.append("rulespecGraph does not define any named Rulespec identifier")
        if computed_digest is not None:
            rulespec_failures.extend(_run_rulespec_validator(graph, computed_digest, validator))

    declared_digest = bundle.get("rulespecGraphDigest")
    graph_identifier = bundle.get("rulespecGraphId")
    if not isinstance(graph_identifier, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]+", graph_identifier):
        cross_failures.append("rulespecGraphId must be an absolute IRI")
    if bundle.get("graphDigestAlgorithm") != GRAPH_DIGEST_ALGORITHM:
        cross_failures.append(f"graphDigestAlgorithm must be {GRAPH_DIGEST_ALGORITHM!r}")
    if not isinstance(declared_digest, str) or not DIGEST_PATTERN.fullmatch(declared_digest):
        cross_failures.append("rulespecGraphDigest must be a lowercase SHA-256 digest")
    elif computed_digest is not None and declared_digest != computed_digest:
        cross_failures.append(
            f"rulespecGraphDigest {declared_digest!r} does not match exact graph digest {computed_digest!r}"
        )

    receipt = bundle.get("validatorReceipt")
    if not isinstance(receipt, dict):
        cross_failures.append("validatorReceipt must be an object")
    else:
        if receipt.get("result") != "pass":
            cross_failures.append("validatorReceipt.result must be 'pass'")
        if receipt.get("validatorIdentity") != validator.identity:
            cross_failures.append("validatorReceipt.validatorIdentity does not match the pinned validator")
        if receipt.get("validatorSourceRevision") != validator.source_revision:
            cross_failures.append(
                "validatorReceipt.validatorSourceRevision does not match the pinned validator revision"
            )
        receipt_digest = receipt.get("graphDigest")
        if receipt.get("graphId") != graph_identifier:
            cross_failures.append("validatorReceipt.graphId does not match rulespecGraphId")
        if receipt_digest != declared_digest:
            cross_failures.append("validatorReceipt.graphDigest does not match rulespecGraphDigest")
        if computed_digest is not None and receipt_digest != computed_digest:
            cross_failures.append("validatorReceipt.graphDigest does not bind the exact Rulespec graph")
        covered = _string_set(
            receipt.get("coveredIdentifiers"),
            field="validatorReceipt.coveredIdentifiers",
            failures=cross_failures,
        )
        if covered != graph_identifiers:
            missing = sorted(graph_identifiers - covered)
            unexpected = sorted(covered - graph_identifiers)
            cross_failures.append(
                "validatorReceipt.coveredIdentifiers does not exactly cover the "
                f"Rulespec graph; missing={missing!r}, unexpected={unexpected!r}"
            )

    ref_identifiers = {record.get("id") for record in records if isinstance(record.get("id"), str)}
    for record in records:
        record_identifier = record.get("id")
        if not isinstance(record_identifier, str):
            continue
        for requirement in _rulespec_reference_requirements(record):
            asserted_types = graph_node_types.get(requirement.identifier)
            if asserted_types is None:
                cross_failures.append(
                    f"{record_identifier}{requirement.path} cannot resolve "
                    f"Rulespec identifier {requirement.identifier!r}: the "
                    "validated graph does not define it"
                )
                continue
            if not asserted_types:
                cross_failures.append(
                    f"{record_identifier}{requirement.path} resolves "
                    f"{requirement.identifier!r}, but its defining Rulespec "
                    "node has no @type"
                )
                continue
            if requirement.expected_types is not None and asserted_types.isdisjoint(requirement.expected_types):
                cross_failures.append(
                    f"{record_identifier}{requirement.path} requires "
                    f"{requirement.identifier!r} to have one of "
                    f"{sorted(requirement.expected_types)!r}, but the "
                    f"Rulespec graph asserts {sorted(asserted_types)!r}"
                )

    expected_cross_references = {
        (record["id"], rulespec_identifier)
        for record in records
        if isinstance(record.get("id"), str)
        for rulespec_identifier in referenced_rulespec_identifiers(
            record,
            graph_identifiers,
        )
    }
    cross_references = bundle.get("crossReferences")
    if not isinstance(cross_references, list) or not cross_references:
        cross_failures.append("crossReferences must be a non-empty array")
    else:
        seen: set[tuple[str, str]] = set()
        for index, cross_reference in enumerate(cross_references):
            if not isinstance(cross_reference, dict):
                cross_failures.append(f"crossReferences[{index}] must be an object")
                continue
            ref_identifier = cross_reference.get("refRecordId")
            rulespec_identifier = cross_reference.get("rulespecIdentifier")
            if not isinstance(ref_identifier, str) or not isinstance(rulespec_identifier, str):
                cross_failures.append(f"crossReferences[{index}] must name a REF record and Rulespec identifier")
                continue
            pair = (ref_identifier, rulespec_identifier)
            if pair in seen:
                cross_failures.append(f"crossReferences[{index}] repeats cross-reference {pair!r}")
            seen.add(pair)
            if ref_identifier not in ref_identifiers:
                cross_failures.append(f"crossReferences[{index}] cannot resolve REF record {ref_identifier!r}")
            if rulespec_identifier not in graph_identifiers:
                cross_failures.append(
                    f"crossReferences[{index}] cannot resolve Rulespec identifier {rulespec_identifier!r}"
                )
        if seen != expected_cross_references:
            missing = sorted(expected_cross_references - seen)
            unexpected = sorted(seen - expected_cross_references)
            cross_failures.append(
                "crossReferences do not exactly enumerate Rulespec graph "
                f"identifiers present in REF records; missing={missing!r}, "
                f"unexpected={unexpected!r}"
            )

    dependency = validator.dependency_manifest
    if dependency is not None:
        for record in records:
            if record.get("type") != ("urn:ref:type:PublicationReleaseManifest"):
                continue
            declared = record.get("rulespecDependency")
            if not isinstance(declared, Mapping):
                cross_failures.append(
                    f"{record.get('id')}: PublicationReleaseManifest has no Rulespec dependency object"
                )
                continue
            expected_fields = {
                "version": dependency.get("rulespecVersion"),
                "contractRevision": dependency.get("contractRevision"),
                "evidenceRevision": dependency.get("evidenceRevision"),
                "constraintDigest": dependency.get("constraintDigest"),
                "conformanceCorpusDigest": dependency.get("conformanceCorpusDigest"),
                "releaseAvailability": dependency.get("releaseAvailability"),
            }
            for field_name, expected in expected_fields.items():
                if declared.get(field_name) != expected:
                    cross_failures.append(
                        f"{record.get('id')}: rulespecDependency."
                        f"{field_name} does not match the gate dependency "
                        "manifest"
                    )
            declared_validator = declared.get("validator")
            expected_validator = {
                "id": validator.component_id,
                "revision": validator.source_revision,
                "digest": validator.component_digest,
            }
            if declared_validator != expected_validator:
                cross_failures.append(
                    f"{record.get('id')}: rulespecDependency.validator does not match the exact gate validator"
                )

    behavior_failures, behavior_evaluations = _governance_authorization_evaluations(
        records=records,
        graph=graph,
        graph_id=(graph_identifier if isinstance(graph_identifier, str) else None),
        graph_digest=computed_digest,
        node_types=graph_node_types,
        validator=validator,
    )
    cross_failures.extend(behavior_failures)
    if _authorization_evaluations is not None:
        _authorization_evaluations.extend(behavior_evaluations)

    return ReleaseGraphGateReport(
        ref_failures=tuple(ref_failures),
        rulespec_failures=tuple(rulespec_failures),
        cross_boundary_failures=tuple(cross_failures),
    )


def issue_release_graph_validation_receipt(
    bundle: Mapping[str, Any],
    *,
    validator: RulespecValidatorPin,
    dependency_manifest: Path | None = None,
    receipt_id: str,
    recorded_at: str,
    recorded_by: str,
    activity: str,
) -> dict[str, Any]:
    """Execute all gates and issue their modeled receipt only after success."""

    authorization_evaluations: list[dict[str, Any]] = []
    report = validate_release_graph_bundle(
        bundle,
        validator=validator,
        _authorization_evaluations=authorization_evaluations,
    )
    if not report.passed:
        failures = [
            *(f"REF: {value}" for value in report.ref_failures),
            *(f"RULESPEC: {value}" for value in report.rulespec_failures),
            *(f"CROSS: {value}" for value in report.cross_boundary_failures),
        ]
        raise ValueError("release-graph validation receipt was not issued: " + " | ".join(failures))

    records_value = bundle.get("refRecords")
    graph = bundle.get("rulespecGraph")
    cross_references = bundle.get("crossReferences")
    if not isinstance(records_value, list) or not isinstance(graph, dict) or not isinstance(cross_references, list):
        raise TypeError("passing release-graph bundle has an invalid shape")
    graph_id = bundle.get("rulespecGraphId")
    if not isinstance(graph_id, str) or not graph_id:
        raise ValueError("receipt issuance requires an external Rulespec graph identifier")

    record_references: list[dict[str, str]] = []
    for index, value in enumerate(records_value):
        if not isinstance(value, dict):
            raise TypeError(f"refRecords[{index}] is not an object")
        identifier = value.get("id")
        digest_key = binding.digest_field(value)
        digest = value.get(digest_key)
        expected = binding.canonical_payload_digest(value)
        if not isinstance(identifier, str) or not identifier or digest != expected:
            raise ValueError(f"refRecords[{index}] cannot be bound to an exact canonical digest")
        record_references.append({"id": identifier, "digest": expected})
    record_references.sort(key=lambda item: (item["id"], item["digest"]))
    if len({item["id"] for item in record_references}) != len(record_references):
        raise ValueError("receipt issuance requires unique REF record identifiers")

    dependency_bytes = rulespec_dependency_bytes(dependency_manifest)
    dependency_digest = "sha256:" + hashlib.sha256(dependency_bytes).hexdigest()
    if not validator.dependency_manifest_digest or validator.dependency_manifest_digest != dependency_digest:
        raise ValueError("receipt dependency manifest does not match the manifest that loaded the Rulespec validator")
    validator_digest = validator.component_digest or canonical_value_digest(
        {
            "identity": validator.identity,
            "sourceRevision": validator.source_revision,
            "evidenceRevision": validator.evidence_revision,
        }
    )
    behavior_runtime_digest = validator.behavior_component_digest or canonical_value_digest(
        {
            "identity": validator.behavior_component_id,
            "sourceRevision": validator.source_revision,
        }
    )
    gate_digest = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt = {
        "id": receipt_id,
        "type": "urn:ref:type:ReleaseGraphValidationReceipt",
        "recordedAt": recorded_at,
        "recordedBy": recorded_by,
        "schemaVersion": "1.0",
        "operationalState": "passed",
        "receiptVersion": "1.0",
        "rulespecDependencyManifest": {
            "id": validator.dependency_manifest_id,
            "digest": dependency_digest,
        },
        "rulespecGraph": {
            "id": graph_id,
            "digest": rulespec_graph_digest(graph),
        },
        "refRecordDigests": record_references,
        "rulespecValidator": {
            "id": validator.component_id,
            "revision": validator.source_revision,
            "digest": validator_digest,
        },
        "rulespecBehaviorRuntime": {
            "id": validator.behavior_component_id,
            "revision": validator.source_revision,
            "digest": behavior_runtime_digest,
        },
        "gateImplementation": {
            "id": RELEASE_GRAPH_GATE_COMPONENT_ID,
            "revision": RELEASE_GRAPH_GATE_VERSION,
            "digest": gate_digest,
        },
        "verdicts": {
            "refBinding": "pass",
            "rulespecConformance": "pass",
            "rulespecBehavior": "pass",
            "crossBoundary": "pass",
        },
        "authorizationEvaluations": authorization_evaluations,
        "coveredRulespecIdentifiers": sorted(defined_rulespec_identifiers(graph)),
        "crossReferencesDigest": canonical_value_digest(cross_references),
        "validatedAt": recorded_at,
        "activity": activity,
    }
    receipt["canonicalPayloadDigest"] = binding.canonical_payload_digest(receipt)
    diagnostics = binding.validate([receipt])
    if diagnostics:
        raise ValueError(
            "issued release-graph receipt failed REF binding: "
            + " | ".join(diagnostic.render() for diagnostic in diagnostics)
        )
    return receipt


def _print_failures(label: str, failures: Iterable[str]) -> None:
    for failure in failures:
        print(f"{label}: {failure}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the combined release-graph gate."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--rulespec-dir", type=Path, required=True)
    parser.add_argument(
        "--dependency-manifest",
        type=Path,
        default=DEFAULT_DEPENDENCY_MANIFEST,
    )
    parser.add_argument(
        "--issue-receipt",
        type=Path,
        help="write a modeled receipt only after the live combined gate passes",
    )
    parser.add_argument(
        "--receipt-id",
        default="urn:ref:release-graph-validation-receipt:local",
    )
    parser.add_argument(
        "--recorded-by",
        default="urn:ref:agent:release-graph-gate",
    )
    parser.add_argument(
        "--activity",
        default="urn:ref:activity:validate-release-graph",
    )
    parser.add_argument(
        "--recorded-at",
        help="RFC 3339 receipt time; defaults to the current UTC time",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        bundle = binding.load_json(args.bundle)
        if not isinstance(bundle, dict):
            raise TypeError("release-graph bundle must be an object")
        validator = load_pinned_rulespec_validator(
            args.rulespec_dir,
            args.dependency_manifest,
        )
    except (OSError, TypeError, ValueError) as error:
        report = ReleaseGraphGateReport(rulespec_failures=(str(error),))
    else:
        report = validate_release_graph_bundle(bundle, validator=validator)
        if report.passed and args.issue_receipt is not None:
            recorded_at = args.recorded_at or (
                dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            )
            try:
                receipt = issue_release_graph_validation_receipt(
                    bundle,
                    validator=validator,
                    dependency_manifest=args.dependency_manifest,
                    receipt_id=args.receipt_id,
                    recorded_at=recorded_at,
                    recorded_by=args.recorded_by,
                    activity=args.activity,
                )
                args.issue_receipt.write_text(
                    json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            except (OSError, TypeError, ValueError) as error:
                report = ReleaseGraphGateReport(
                    cross_boundary_failures=(f"could not issue validation receipt: {error}",)
                )

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        _print_failures("REF", report.ref_failures)
        _print_failures("RULESPEC", report.rulespec_failures)
        _print_failures("CROSS", report.cross_boundary_failures)
        print("RefSpec/Rulespec release graph:", "PASS" if report.passed else "FAIL")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
