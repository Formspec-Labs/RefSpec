.PHONY: test test-json-binding test-rulespec-working-tree test-cross-repository

RULESPEC_DIR ?= ../../rulespec

test: test-json-binding

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
