.PHONY: generate check-generated test test-package test-json-binding test-atlas-v3 audit-atlas-v3-source-fidelity

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

test: check-generated test-json-binding test-atlas-v3 test-package

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
