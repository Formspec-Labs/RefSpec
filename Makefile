.PHONY: generate check-generated test test-package test-json-binding test-rulespec-working-tree test-cross-repository test-real-vocabulary

RULESPEC_DIR ?= ../../rulespec

generate:
	python3 tools/generate_model.py

check-generated:
	python3 tools/generate_model.py --check

test: check-generated test-json-binding test-package

test-package:
	uv run pytest -q

test-json-binding:
	uv run --no-project --with-requirements bindings/json/1.0/requirements.txt \
		python bindings/json/1.0/tools/validate.py

test-rulespec-working-tree: test-json-binding
	python3 bindings/json/1.0/tools/validate_rulespec_gate.py \
		--rulespec-dir "$(RULESPEC_DIR)" \
		--run-rulespec-gate

test-cross-repository: test-json-binding
	python3 bindings/json/1.0/tools/validate_rulespec_gate.py \
		--rulespec-dir "$(RULESPEC_DIR)" \
		--run-rulespec-gate \
		--require-closure-pin

# Explicitly networked and intentionally absent from the offline `make test`.
test-real-vocabulary:
	uv run python -m refspec.registry.federal_register_real_test \
		--rulespec-root "$(RULESPEC_DIR)"
