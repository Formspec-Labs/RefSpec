"""Generated REF JSON Binding record types. Do not edit by hand."""

from __future__ import annotations

from typing import Any, Literal

from typing_extensions import NotRequired, Required, TypedDict

MODEL_SHA256 = "sha256:8db9b2882256ed0f03e11b72649000ed0fb9b1f172e790c3003e364fa0165d1e"


class REFRecordData(TypedDict, total=False):
    id: Required[str]
    type: Required[str]
    recordedAt: Required[str]
    recordedBy: Required[str]
    schemaVersion: Required[str]
    operationalState: Required[str]


class CaptureData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    source: Required[Any]
    sourceLocator: Required[Any]
    requestMethod: Required[Any]
    safeRequestParameters: Required[dict[str, Any]]
    retrievalStartedAt: Required[str]
    retrievalEndedAt: Required[str]
    responseStatus: Required[Any]
    requestHeaders: Required[dict[str, Any]]
    responseHeaders: Required[dict[str, Any]]
    mediaType: NotRequired[Any]
    acquisitionStatus: Required[Literal['success', 'partial', 'failure']]
    byteDigest: NotRequired[Any]
    byteLength: NotRequired[int]
    storageReference: NotRequired[Any]
    contentPreservation: Required[Literal['exactBytes', 'canonicalResponse', 'exactApplicationPayload']]
    preservationLimit: NotRequired[Any]
    completeness: Required[dict[str, Any]]
    acquisitionActivity: Required[Any]
    runReceipt: Required[Any]
    accessScopeRefs: Required[Any]
    retentionPolicyRefs: Required[Any]
    rightsExpressionRefs: Required[Any]


class ConceptProposalData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    facet: Required[Any]
    wording: Required[dict[str, Any]]
    evidenceAddresses: Required[list[Any]]
    activity: Required[Any]
    workflowState: Required[Literal['submitted', 'underReview', 'acceptedForPromotion', 'rejected', 'withdrawn', 'superseded']]
    governanceQueue: Required[Any]
    proposedAnchors: NotRequired[Any]
    proposedMappingRefs: NotRequired[Any]
    supersessionHistory: Required[list[Any]]


class EnrichmentConfigurationData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    implementation: Required[dict[str, Any]]
    enrichmentProfile: Required[Any]
    outputProfile: Required[Any]
    acceptancePolicy: Required[Any]
    schemas: Required[list[Any]]
    inputCorpora: Required[list[Any]]
    vocabulary: Required[dict[str, Any]]
    indexes: Required[list[dict[str, Any]]]
    candidateChannels: Required[list[dict[str, Any]]]
    models: Required[list[dict[str, Any]]]
    prompts: Required[Any]
    toolPolicies: Required[Any]
    budgets: Required[list[dict[str, Any]]]
    determinism: Required[list[dict[str, Any]]]
    otherBehaviorPins: Required[Any]
    secretVersionRefs: Required[Any]


class EnrichmentDeploymentDecisionData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    environment: Required[dict[str, Any]]
    configuration: Required[Any]
    evaluationResult: Required[Any]
    outputProfile: Required[Any]
    selectionState: Required[Literal['staged', 'selected', 'deselected', 'failed']]
    effectiveAt: Required[str]
    reason: Required[Any]
    activity: Required[Any]
    predecessorDecision: NotRequired[Any]
    supersedingDecision: NotRequired[Any]
    rulespecAttestationRefs: Required[Any]
    localAdoptionRefs: Required[Any]
    authorizationValidations: NotRequired[list[dict[str, Any]]]


class EnrichmentEvaluationResultData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    configuration: Required[Any]
    sealedGoldManifest: Required[Any]
    evaluationProtocol: Required[Any]
    predeclaredMeasures: Required[list[Any]]
    thresholds: Required[list[dict[str, Any]]]
    configuredStrata: Required[list[dict[str, Any]]]
    exclusions: Required[Any]
    uncertaintyMethod: Required[Any]
    observedMeasures: Required[list[dict[str, Any]]]
    measurePopulations: Required[list[dict[str, Any]]]
    gates: Required[list[dict[str, Any]]]
    evaluator: Required[Any]
    activity: Required[Any]
    evaluatedAt: Required[str]
    outputArtifactDigests: Required[list[Any]]
    verdict: Required[Literal['pass', 'fail', 'developmentOnly']]


class EnrichmentProfileData(REFRecordData, total=False):
    version: Required[Any]
    contentDigest: Required[Any]
    facets: Required[list[dict[str, Any]]]


class IndexedVocabularyExpressionData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    referenceResourceRelease: Required[Any]
    registryImportSnapshot: Required[Any]
    distributionArtifact: Required[Any]
    member: Required[Any]
    scheme: Required[Any]
    sourceProperty: NotRequired[Any]
    sourcePath: NotRequired[Any]
    originalLiteral: Required[Any]
    language: NotRequired[Any]
    datatype: NotRequired[Any]
    normalizationPolicy: Required[Any]
    indexedText: Required[Any]
    indexedTextDigest: Required[Any]
    indexedRepresentationVersion: Required[Any]
    expressionCorpusSnapshot: Required[Any]
    activity: Required[Any]
    receipt: Required[Any]


class OutputProfileData(REFRecordData, total=False):
    version: Required[Any]
    contentDigest: Required[Any]
    enrichmentProfile: Required[Any]
    acceptancePolicies: Required[list[Any]]
    publicationViews: Required[list[Any]]
    releasePermissions: Required[list[dict[str, Any]]]
    mappingPermissions: Required[list[dict[str, Any]]]
    openLabelPermissions: Required[list[dict[str, Any]]]


class PublicationReleaseManifestData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    version: Required[Any]
    refspecVersion: Required[Any]
    operationalSerializationProfile: Required[Any]
    rulespecDependency: Required[dict[str, Any]]
    claimedConformanceLevels: Required[list[Any]]
    inventoryCoveragePins: Required[list[Any]]
    rulespecReleaseGraph: Required[Any]
    refOperationalRecords: Required[list[Any]]
    expressionCorpusSnapshot: Required[Any]
    runReceipt: Required[Any]
    releaseState: Required[Literal['incomplete', 'complete', 'rolledBack']]
    deploymentClass: Required[Literal['developmentOnly', 'production']]
    consumerEligible: Required[bool]
    publishedAt: Required[str]
    activity: Required[Any]
    predecessor: NotRequired[Any]
    rollbackOf: NotRequired[Any]


class ReleaseGraphValidationReceiptData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    receiptVersion: Required[Literal['1.0']]
    rulespecDependencyManifest: Required[Any]
    rulespecGraph: Required[Any]
    refRecordDigests: Required[list[Any]]
    rulespecValidator: Required[Any]
    rulespecBehaviorRuntime: Required[Any]
    gateImplementation: Required[Any]
    verdicts: Required[dict[str, Any]]
    authorizationEvaluations: Required[list[dict[str, Any]]]
    coveredRulespecIdentifiers: Required[Any]
    crossReferencesDigest: Required[Any]
    validatedAt: Required[str]
    activity: Required[Any]


class RegistryDeploymentDecisionData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    environment: Required[dict[str, Any]]
    registryImportSnapshot: Required[Any]
    referenceResourceRelease: Required[Any]
    coverageReport: Required[Any]
    reconciliationReport: NotRequired[Any]
    outputProfile: Required[Any]
    selectionState: Required[Literal['quarantined', 'staged', 'selected', 'deselected', 'failed']]
    effectiveAt: Required[str]
    reason: Required[Any]
    activity: Required[Any]
    rulespecAttestationRefs: Required[Any]
    localAdoptionRefs: Required[Any]
    authorizationValidations: NotRequired[list[dict[str, Any]]]
    predecessor: NotRequired[Any]


class RegistryImportCoverageReportData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    outputProfile: Required[Any]
    registryImportSnapshot: Required[Any]
    referenceResourceRelease: Required[Any]
    distributionArtifacts: Required[list[Any]]
    importProfile: Required[Any]
    parserVersion: Required[Any]
    expressionCorpusSnapshot: Required[Any]
    activity: Required[Any]
    receipt: Required[Any]
    reportStatus: Required[Literal['pass', 'fail']]
    features: Required[list[dict[str, Any]]]


class RegistryImportSnapshotData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    inventoryCoverageComponent: Required[Any]
    importProfile: Required[Any]
    captures: Required[list[Any]]
    externalReferences: Required[list[Any]]
    referenceResourceRelease: Required[Any]
    distributionArtifacts: Required[list[Any]]
    rightsAssessment: Required[Any]
    adoptedPolicyRefs: Required[Any]
    transformation: Required[Any]
    exclusions: Required[list[dict[str, Any]]]
    failures: Required[list[dict[str, Any]]]
    rulespecValidationResult: Required[Any]
    refValidationResult: Required[Any]
    expectedRefreshCadence: Required[Any]
    activity: Required[Any]
    receipt: Required[Any]
    predecessorImportSnapshot: NotRequired[Any]


class RegistryReconciliationReportData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    inputs: Required[list[dict[str, Any]]]
    comparedItems: Required[list[dict[str, Any]]]
    differences: Required[list[dict[str, Any]]]
    conceptMappings: Required[Any]
    precedencePolicy: Required[Any]
    rulespecAuthorityRefs: Required[Any]
    attestationRefs: Required[Any]
    localAdoptionRefs: Required[Any]
    authorizationValidations: NotRequired[list[dict[str, Any]]]
    unresolvedItems: Required[Any]
    selectedInputRelease: NotRequired[Any]
    reconciledRelease: NotRequired[Any]
    synthesizedUnionAuthorized: Required[bool]
    activity: Required[Any]
    outcome: Required[Literal['selectedInput', 'reconciledReleaseAuthorized', 'unresolved']]


class RightsAssessmentData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    target: Required[dict[str, Any]]
    observedTerms: Required[list[dict[str, Any]]]
    supportingSourceFragments: Required[list[Any]]
    permissions: Required[dict[str, Any]]
    purpose: Required[Any]
    attribution: Required[Any]
    audience: Required[Any]
    effectiveAt: Required[str]
    priorAssessment: NotRequired[Any]
    rulespecPolicyRefs: Required[Any]
    attestationRefs: Required[Any]
    localAdoptionRefs: Required[Any]


class RunReceiptData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    inputCaptures: Required[list[Any]]
    inputSnapshots: Required[list[Any]]
    rulespecReleases: Required[list[Any]]
    coverageWindow: Required[dict[str, Any]]
    rulespecActivityRefs: Required[Any]
    rulespecAgentRefs: Required[Any]
    rulespecOutputRefs: Required[Any]
    providerDetailsReference: NotRequired[Any]
    environmentLock: Required[Any]
    outputs: Required[list[Any]]
    counts: Required[dict[str, Any]]
    exclusions: Required[list[dict[str, Any]]]
    failures: Required[list[dict[str, Any]]]
    quarantinedItems: Required[list[dict[str, Any]]]
    startedAt: Required[str]
    endedAt: Required[str]
    nondeterministicStages: Required[list[Any]]
    reproducibility: Required[Literal['byteIdentical', 'deterministicFromPinnedInputs', 'replayableWithNondeterminism', 'notReplayable']]
    replayLimit: NotRequired[Any]


class SealedGoldManifestData(REFRecordData, total=False):
    canonicalPayloadDigest: Required[Any]
    evaluationGeneration: Required[Any]
    purpose: Required[Any]
    selectionProtocol: Required[Any]
    sourceDigest: Required[Any]
    corpusDigest: Required[Any]
    selectionDigest: Required[Any]
    draftingControl: Required[dict[str, Any]]
    partitions: Required[dict[str, Any]]
    items: Required[list[dict[str, Any]]]
    vocabularyUniverse: Required[dict[str, Any]]
    expectations: Required[list[dict[str, Any]]]
    reviewers: Required[Any]
    independentJudgmentRefs: Required[Any]
    disagreementRefs: Required[Any]
    adjudicationRefs: Required[Any]
    exclusions: Required[Any]
    partitionReport: Required[dict[str, Any]]
    sealingTime: Required[str]
    sealingActivity: Required[Any]


__all__ = [
    "CaptureData",
    "ConceptProposalData",
    "EnrichmentConfigurationData",
    "EnrichmentDeploymentDecisionData",
    "EnrichmentEvaluationResultData",
    "EnrichmentProfileData",
    "IndexedVocabularyExpressionData",
    "OutputProfileData",
    "PublicationReleaseManifestData",
    "REFRecordData",
    "RegistryDeploymentDecisionData",
    "RegistryImportCoverageReportData",
    "RegistryImportSnapshotData",
    "RegistryReconciliationReportData",
    "ReleaseGraphValidationReceiptData",
    "RightsAssessmentData",
    "RunReceiptData",
    "SealedGoldManifestData",
]
