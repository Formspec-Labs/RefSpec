.PHONY: generate check-generated lint test test-package test-json-binding test-atlas-v3 \
	audit-atlas-v3-source-fidelity audit-registry-inventory audit-registry-real-data \
	release-atlas-federal-register-thesaurus verify-atlas-federal-register-thesaurus

ATLAS_V3_AUDIT_ROOT ?= output/atlas-3.0-full-2026-08-07-ring-audit
ATLAS_V3_AUDIT_SOURCE_ROOT ?= output/registry-real-data-sources
# Beside the distribution, never inside it. A distribution validates its own
# membership as a closed set, so a receipt written into that directory makes
# the audited artifact fail its own walk -- which is exactly what happened.
ATLAS_V3_AUDIT_RECEIPT ?= $(ATLAS_V3_AUDIT_ROOT)-source-fidelity-receipt.json

generate:
	python3 tools/generate_model.py
	uv run python tools/generate_crs_source_concept_releases.py --write
	uv run python tools/generate_resource_catalog.py --write
	uv run python tools/generate_atlas_index.py --write
	uv run python tools/generate_atlas_v3_registry_coverage.py --write
	uv run python tools/generate_atlas_v3_registry_descriptors.py --write
	uv run --no-project --with-requirements bindings/atlas/3.0/requirements.txt \
		python bindings/atlas/3.0/tools/build_fixtures.py

check-generated:
	python3 tools/generate_model.py --check
	uv run python tools/generate_crs_source_concept_releases.py --check
	uv run python tools/generate_resource_catalog.py --check
	uv run python tools/generate_atlas_index.py --check
	uv run python tools/generate_atlas_v3_registry_coverage.py --check
	uv run python tools/generate_atlas_v3_registry_descriptors.py --check
	uv run python tools/build_registry_source_manifest.py --check
	uv run --no-project --with-requirements bindings/atlas/3.0/requirements.txt \
		python bindings/atlas/3.0/tools/build_fixtures.py --check

# `test-atlas-v3` is deliberately absent. `test-package` already runs the
# identical command inside
# tests/test_atlas_v3_binding.py::test_atlas_v3_binding_and_sealed_corpus_pass,
# which additionally pins the exact case, schema and descriptor counts the
# bare target only exit-codes. Listing both ran the 110-case corpus twice for
# ~205s each -- a third of the whole suite spent proving the same thing twice.
# Keep the standalone target for binding work; do not re-add it here.
test: lint check-generated audit-registry-inventory test-json-binding test-package

# First, because it is the cheapest gate in the pipeline (~1s against ~1.7min).
# The rule set is stated in pyproject.toml and the ruff version is pinned there.
#
# `ruff format --check` is deliberately not wired: 144 of 438 files disagree with
# its style today, so adding it would reformat a third of the tree in exchange
# for no failure class this gate does not already catch. Adopting it later is a
# one-shot reformat commit plus one line here, not a decision to defer forever.
lint:
	uv run ruff check .

# Fast drift check: does the committed registry manifest still describe the code?
# This is the failure class that silently accumulates as registry modules are added.
audit-registry-inventory:
	uv run python tools/verify_registry_audit.py

# The real-data gate. It runs the suite with the claim-export real-data tests
# enabled and rejects any registry module whose publisher evidence is unproven,
# so it must set REFSPEC_REGISTRY_CLAIM_REAL_DATA rather than rely on the caller.
audit-registry-real-data:
	REFSPEC_REGISTRY_CLAIM_REAL_DATA=1 uv run python tools/verify_registry_audit.py \
		--run-tests --run-all-tests --require-real-data \
		--output research/evidence/registry-real-data-audit-2026-08-03/summary.json

# `-n auto` fans the suite across every core. Verified to produce the exact
# same pass/fail/skip set as a serial run, test id for test id; no test needed
# a serial exemption. Drop the flag to debug -- bare `uv run pytest -q` still
# works and is easier to read when something breaks.
test-package:
	uv run pytest -q -n auto

test-json-binding:
	uv run --no-project --with-requirements bindings/json/1.0/requirements.txt \
		python bindings/json/1.0/tools/validate.py

test-atlas-v3:
	uv run --no-project --with-requirements bindings/atlas/3.0/requirements.txt \
		python bindings/atlas/3.0/tools/validate.py

audit-atlas-v3-source-fidelity:
	@audit_distribution="$(ATLAS_V3_AUDIT_ROOT)"; \
	if [ ! -f "$$audit_distribution/atlas-manifest.json" ]; then \
		audit_distribution="$$audit_distribution/distribution"; \
	fi; \
	uv run --with-requirements bindings/atlas/3.0/requirements.txt \
		python tools/verify_atlas_source_fidelity.py \
		--distribution "$$audit_distribution" \
		--source-root "$(ATLAS_V3_AUDIT_SOURCE_ROOT)" \
		--output "$(ATLAS_V3_AUDIT_RECEIPT)"

# ---------------------------------------------------------------------------
# Release job. Not `test`, not `check-generated`, not continuous integration:
# every target below reads a gitignored capture and writes a distribution.
# ---------------------------------------------------------------------------

# One bounded Atlas 3.0 distribution carrying one governed scheme. The build is
# always cold -- neither reuse path may compare a bounded distribution against
# the whole code-declared topology -- and the identity is derived from the
# source accounting, so the same source bytes rebuild the same tree byte for
# byte and the manifest digest below stays an external pin rather than a
# reading of whatever happens to be on disk.
ATLAS_FR_RELEASE_KEY ?= federal-register-thesaurus-2025
ATLAS_FR_RELEASE_ROOT ?= output/atlas-3.0-federal-register-thesaurus-2025-04-01
ATLAS_FR_RELEASE_SOURCE_ROOT ?= output/registry-real-data-sources
ATLAS_FR_RELEASE_MANIFEST_SHA256 ?= fb76eb08bea4a94c6286810c14a8e1062c2f21655b9fc656f2fe2557278d6060
# Beside the distribution, never inside it, for the reason stated above the
# source-fidelity receipt.
ATLAS_FR_RELEASE_RECEIPT ?= $(ATLAS_FR_RELEASE_ROOT)-verification-receipt.json

release-atlas-federal-register-thesaurus:
	uv run --with-requirements bindings/atlas/3.0/requirements.txt \
		python tools/generate_atlas_v3_full.py \
		--only-release "$(ATLAS_FR_RELEASE_KEY)" \
		--output "$(ATLAS_FR_RELEASE_ROOT)/distribution"

# Reads both ends and compares them: the exact publisher PDF, whose occurrence
# ledger is the only place the source-side count exists, and the published
# bytes, counted from authenticated compact packs rather than from the
# producer's own receipt inside the artifact.
verify-atlas-federal-register-thesaurus:
	uv run --with-requirements bindings/atlas/3.0/requirements.txt \
		python tools/verify_federal_register_thesaurus_distribution.py \
		--distribution "$(ATLAS_FR_RELEASE_ROOT)/distribution" \
		--expected-manifest-sha256 "$(ATLAS_FR_RELEASE_MANIFEST_SHA256)" \
		--source-root "$(ATLAS_FR_RELEASE_SOURCE_ROOT)" \
		--output "$(ATLAS_FR_RELEASE_RECEIPT)"
