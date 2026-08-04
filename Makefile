.PHONY: generate check-generated test test-package test-json-binding

generate:
	python3 tools/generate_model.py
	uv run python tools/generate_crs_source_concept_releases.py --write
	uv run python tools/generate_resource_catalog.py --write
	uv run python tools/generate_atlas_index.py --write

check-generated:
	python3 tools/generate_model.py --check
	uv run python tools/generate_crs_source_concept_releases.py --check
	uv run python tools/generate_resource_catalog.py --check
	uv run python tools/generate_atlas_index.py --check

test: check-generated test-json-binding test-package

test-package:
	uv run pytest -q

test-json-binding:
	uv run --no-project --with-requirements bindings/json/1.0/requirements.txt \
		python bindings/json/1.0/tools/validate.py
