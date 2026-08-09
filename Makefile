.PHONY: generate check-generated test test-package test-json-binding test-atlas-v3 \
	audit-atlas-v3-source-fidelity audit-registry-inventory audit-registry-real-data

ATLAS_V3_AUDIT_ROOT ?= output/atlas-3.0-full-2026-08-07-ring-audit
ATLAS_V3_AUDIT_SOURCE_ROOT ?= output/registry-real-data-sources
ATLAS_V3_AUDIT_RECEIPT ?= $(ATLAS_V3_AUDIT_ROOT)/atlas-source-fidelity-receipt.json

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
	uv run --no-project --with-requirements bindings/atlas/3.0/requirements.txt \
		python bindings/atlas/3.0/tools/build_fixtures.py --check

test: check-generated audit-registry-inventory test-json-binding test-atlas-v3 test-package

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

test-package:
	uv run pytest -q

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
