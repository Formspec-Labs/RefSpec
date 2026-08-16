.PHONY: seal-distribution verify-distribution-seal generate check-generated lint lint-rdf-strict test test-package test-json-binding test-atlas-v3 \
	atlas-v3-fixtures contract-dev \
	audit-atlas-v3-source-fidelity audit-registry-inventory audit-registry-real-data \
	release-atlas-federal-register-thesaurus verify-atlas-federal-register-thesaurus \
	determinism-atlas-federal-register-thesaurus benchmark-atlas-shacl-scale \
	stage-atlas-mapping-topology

# No default. The prior default (output/atlas-3.0-full-2026-08-07-ring-audit)
# is retired: HEAD's binding refuses that distribution's constructorProfile
# (see plans/validation-cost-reset-plan.md). Callers must name a distribution
# that validates under HEAD.
ATLAS_V3_AUDIT_ROOT ?=
ATLAS_V3_AUDIT_SOURCE_ROOT ?= output/registry-real-data-sources
# Space-separated comparison names. Empty means the whole registry. A scoped run
# reports the construction units it left out as not evaluated (scoped out); it
# never counts them covered, and it never marks them failed.
ATLAS_V3_AUDIT_ONLY ?=
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
# Position mirrors the `--check` line in check-generated. This builder has no
# `--write` flag: writing is what it does unless `--check` is passed.
	uv run python tools/build_registry_source_manifest.py
	uv run --no-project --with-requirements bindings/atlas/3.1/requirements.txt \
		python bindings/atlas/3.1/tools/build_fixtures.py

# The last step here also MATERIALIZES the Atlas 3.0 case tree. Those 8,339
# files are generated and gitignored, so on a cold checkout that rebuild writes
# them and proves them against the committed `fixtures-receipt.json`; on a warm
# one the receipt answers in ~1.5s. `test` lists this target before
# `test-package` for exactly that reason -- four test modules read case
# directories directly.
check-generated:
	python3 tools/generate_model.py --check
	uv run python tools/generate_crs_source_concept_releases.py --check
	uv run python tools/generate_resource_catalog.py --check
	uv run python tools/generate_atlas_index.py --check
	uv run python tools/generate_atlas_v3_registry_coverage.py --check
	uv run python tools/generate_atlas_v3_registry_descriptors.py --check
	uv run python tools/build_registry_source_manifest.py --check
	uv run --no-project --with-requirements bindings/atlas/3.1/requirements.txt \
		python bindings/atlas/3.1/tools/build_fixtures.py --check

# `test-atlas-v3` is deliberately absent. `test-package` already runs the
# identical command inside
# tests/test_atlas_v3_binding.py::test_atlas_v3_binding_and_sealed_corpus_pass,
# which additionally pins the exact case, schema and descriptor counts the
# bare target only exit-codes. Listing both ran the 110-case corpus twice for
# ~205s each -- a third of the whole suite spent proving the same thing twice.
# Keep the standalone target for binding work; do not re-add it here.
# Order matters here beyond taste: `check-generated` materializes the
# gitignored Atlas 3.0 case tree (see that rule), and `test-package` reads it.
# Make runs these left to right, so a cold checkout is healed before pytest
# collects. The targets that can be run on their own take `atlas-v3-fixtures`
# as a prerequisite so they do not depend on that ordering.
test: lint lint-rdf-strict check-generated audit-registry-inventory test-json-binding test-package

# Build the Atlas 3.0 case tree if, and only if, it is not there. `--check`
# both builds and proves (against `fixtures-receipt.json`), so the cold path
# gets its ~9s build and the warm path pays one directory test. Anything that
# reads `bindings/atlas/3.1/fixtures/valid|invalid` should depend on this.
atlas-v3-fixtures:
	@if [ ! -d bindings/atlas/3.1/fixtures/valid ]; then \
		echo "Atlas 3.0 fixtures absent (generated, gitignored); building once"; \
		uv run --no-project --with-requirements bindings/atlas/3.1/requirements.txt \
			python bindings/atlas/3.1/tools/build_fixtures.py --check; \
	fi

# First, because it is the cheapest gate in the pipeline (~1s against ~1.7min).
# The rule set is stated in pyproject.toml and the ruff version is pinned there.
#
# `ruff format --check` is deliberately not wired: 144 of 438 files disagree with
# its style today, so adding it would reformat a third of the tree in exchange
# for no failure class this gate does not already catch. Adopting it later is a
# one-shot reformat commit plus one line here, not a decision to defer forever.
lint:
	uv run ruff check .

# The wire's second reader. Every other RDF gate in this repository is rdflib
# reading what rdflib wrote, which cannot catch a defect rdflib is willing to
# round-trip -- and the oxigraph spike found two such classes in shipped bytes.
# This parses the one RDF artifact in git with pyoxigraph in strict mode, and
# sweeps any distribution named by ATLAS_RDF_STRICT_ROOTS (os.pathsep-separated
# roots, absent by default: distributions are gitignored). Kept beside `lint`
# rather than inside it so `lint` stays the ~1s ruff gate; both run in CI.
lint-rdf-strict:
	uv run python tools/lint_rdf_strict.py

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
# Wall-clock budget (plans/validation-cost-reset-plan.md check regime and its
# "Budget gate re-spec" open item): target is 60s, warn past 60s. The old
# 120s (2x margin) FAIL line was re-measured at 112-140s on identical trees
# and flipped red nondeterministically, so the hard FAIL threshold is 240s --
# a runaway guard, not a margin on the target. The 120s FAIL line re-arms
# once the suite is next measured under 60s (expected after the plan's
# deletion campaign shrinks it); until then 240s is what actually gates.
test-package: atlas-v3-fixtures
	@start=$$(date +%s); \
	uv run pytest -q -n auto; \
	status=$$?; \
	end=$$(date +%s); \
	elapsed=$$((end - start)); \
	if [ "$$status" -ne 0 ]; then exit "$$status"; fi; \
	if [ "$$elapsed" -gt 240 ]; then \
		echo "test-package budget FAIL: took $${elapsed}s, exceeds the 240s runaway-guard budget" >&2; \
		exit 1; \
	elif [ "$$elapsed" -gt 60 ]; then \
		echo "test-package budget WARN: took $${elapsed}s, over the 60s target (within the 240s fail budget)" >&2; \
	fi

test-json-binding:
	uv run --no-project --with-requirements bindings/json/1.0/requirements.txt \
		python bindings/json/1.0/tools/validate.py

test-atlas-v3: atlas-v3-fixtures
	uv run --no-project --with-requirements bindings/atlas/3.1/requirements.txt \
		python bindings/atlas/3.1/tools/validate.py

audit-atlas-v3-source-fidelity:
	@if [ -z "$(ATLAS_V3_AUDIT_ROOT)" ]; then \
		echo "error: ATLAS_V3_AUDIT_ROOT is unset. The old default" >&2; \
		echo "(output/atlas-3.0-full-2026-08-07-ring-audit) was retired:" >&2; \
		echo "HEAD's binding refuses that distribution's constructorProfile" >&2; \
		echo "(see plans/validation-cost-reset-plan.md). Name a distribution" >&2; \
		echo "that validates under HEAD, for example:" >&2; \
		echo "  make audit-atlas-v3-source-fidelity \\" >&2; \
		echo "    ATLAS_V3_AUDIT_ROOT=output/atlas-3.1-federal-register-thesaurus-2025-04-01" >&2; \
		exit 1; \
	fi
	@audit_distribution="$(ATLAS_V3_AUDIT_ROOT)"; \
	if [ ! -f "$$audit_distribution/atlas-manifest.json" ]; then \
		audit_distribution="$$audit_distribution/distribution"; \
	fi; \
	only_flags=""; \
	for comparison in $(ATLAS_V3_AUDIT_ONLY); do \
		only_flags="$$only_flags --only $$comparison"; \
	done; \
	uv run --with-requirements bindings/atlas/3.1/requirements.txt \
		python tools/verify_atlas_source_fidelity.py \
		--distribution "$$audit_distribution" \
		--source-root "$(ATLAS_V3_AUDIT_SOURCE_ROOT)" \
		$$only_flags \
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
ATLAS_FR_RELEASE_ROOT ?= output/atlas-3.1-federal-register-thesaurus-2025-04-01
ATLAS_FR_RELEASE_SOURCE_ROOT ?= output/registry-real-data-sources
ATLAS_FR_RELEASE_MANIFEST_SHA256 ?= 5af4afc8b426ca72b503621ddcbeee7cd1a8becffee5b41985986b3b9708cc9d
# The served Parquet view is a separate sealed artifact with its own external
# pin; the seal payload binds both digests, and the view manifest names this
# distribution manifest back.
ATLAS_FR_RELEASE_VIEW_SHA256 ?= ffea1b83bee61ac1ea5e2680852d5e18a409e54f4b41d3035367887b9fe36a57
# Beside the distribution, never inside it, for the reason stated above the
# source-fidelity receipt.
ATLAS_FR_RELEASE_RECEIPT ?= $(ATLAS_FR_RELEASE_ROOT)-verification-receipt.json

# Bare `uv run`, i.e. the PROJECT environment -- deliberately, and it must stay
# that way. The builder imports RefSpec package code, so it is a project tool,
# not a binding consumer; `--with-requirements bindings/atlas/3.1/requirements.txt`
# used to be layered here and silently pinned a DIFFERENT rdflib (7.6.0) than
# the release workflow's bare `uv run` (7.5.0). Same tree, two entry points,
# two manifest digests. One environment is the only way the external pin below
# means anything. The validator invocations elsewhere in this file keep
# `--no-project --with-requirements` for the opposite reason: they must prove a
# consumer can verify offline with no RefSpec package code at all.
release-atlas-federal-register-thesaurus:
	uv run python tools/generate_atlas_v3_full.py \
		--only-release "$(ATLAS_FR_RELEASE_KEY)" \
		--output "$(ATLAS_FR_RELEASE_ROOT)/distribution"

# The determinism gate, in the miniature that runs in 6.4s measured (both
# builds plus the comparison, 2026-08-13): build the same bounded release twice,
# into two scratch roots, and require the two trees to be byte-identical. It is the weekly reproducible-rebuild control
# (docs/seal-design.md section 4) shrunk to a size that can run beside a commit
# instead of beside a release, and it fails on the failure it is built for --
# a builder that leaks wall-clock time, a set iteration order, an absolute path
# or a dict ordering into the bytes it signs. Whole trees, not just the manifest
# digest: the manifest covers its declared members, not the served Parquet view
# or the generation report beside it.
#
# Reads the pinned publisher captures ($(ATLAS_FR_RELEASE_SOURCE_ROOT), the
# 2025-04-01 thesaurus PDF) and the portfolio managed release beside this
# repository, so it belongs in this release section and NOT in `make test`:
# hosted CI runners have neither. ci.yml carries the same target behind a
# presence check that skips with a notice.
ATLAS_FR_DETERMINISM_ROOT ?= output/atlas-3.1-federal-register-thesaurus-determinism

determinism-atlas-federal-register-thesaurus:
	rm -rf "$(ATLAS_FR_DETERMINISM_ROOT)-a" "$(ATLAS_FR_DETERMINISM_ROOT)-b"
	$(MAKE) release-atlas-federal-register-thesaurus \
		ATLAS_FR_RELEASE_ROOT="$(ATLAS_FR_DETERMINISM_ROOT)-a"
	$(MAKE) release-atlas-federal-register-thesaurus \
		ATLAS_FR_RELEASE_ROOT="$(ATLAS_FR_DETERMINISM_ROOT)-b"
	uv run python tools/compare_build_trees.py \
		"$(ATLAS_FR_DETERMINISM_ROOT)-a" "$(ATLAS_FR_DETERMINISM_ROOT)-b"

# The staging gate to run BEFORE any full build. The Federal Register release is
# one source unit whose key is already a valid pack-path token, so a build
# bounded to it exercises neither cross-release ownership nor the unit-key /
# pack-token distinction -- `eurovoc-4.24` owns `packs/sources/eurovoc-4-24/`,
# and conflating the two survived a green FR staging artifact and failed the
# ~25-minute full build. These four units cost about a minute and cover what
# the single-unit artifact cannot: two dotted keys, one path-safe key, one
# mapping units and every endpoint dependency they declare.
ATLAS_MAPPING_STAGE_ROOT ?= output/atlas-3.1-mapping-topology-staging

stage-atlas-mapping-topology:
	rm -rf "$(ATLAS_MAPPING_STAGE_ROOT)"
	uv run python tools/generate_atlas_v3_full.py \
		--only-release eurovoc-4.24 \
		--only-release eurovoc-domains-4.24 \
		--only-release lcsh-eurovoc-alignment-endpoints-2026-08-06 \
		--only-release eurovoc-lcsh-alignment-20240711 \
		--only-release fast-topical-current \
		--only-release fast-lcsh-adopted-2026-08-15 \
		--only-release unified-agenda-priority-category \
		--only-release gao-cra-priority-of-regulation \
		--only-release unified-agenda-gao-cra-priority-2026-08-15 \
		--output "$(ATLAS_MAPPING_STAGE_ROOT)/distribution"
	uv run --no-project --with-requirements bindings/atlas/3.1/requirements.txt \
		python bindings/atlas/3.1/tools/validate.py \
		--distribution "$(ATLAS_MAPPING_STAGE_ROOT)/distribution"

# The contract-iteration inner loop, ~45s. Edit the ontology, the shapes, a
# schema or the conformance corpus, then run this one target: it re-derives the
# fixture corpus if the receipt says it is stale, proves the whole binding
# against it, builds one bounded real distribution, smoke-parses that, verifies
# it end to end against the publisher PDF, and prints the two digests the
# release pins carry. Four commands that were always run in this order, and one
# of them (the digests) was always read off the tree by hand afterwards.
#
# Its own scratch root, never $(ATLAS_FR_RELEASE_ROOT): this loop runs while the
# contract is in motion, so it must not overwrite the release artifact that the
# external pins and the seal describe. Its two expected digests are read off the
# tree it just built, deliberately -- mid-iteration there is no pin to check
# against yet, and surfacing the new ones is the point.
# `verify-atlas-federal-register-thesaurus` stays the gate that checks the
# release artifact against the committed pins.
ATLAS_CONTRACT_DEV_ROOT ?= output/atlas-3.1-contract-dev

contract-dev:
	uv run --no-project --with-requirements bindings/atlas/3.1/requirements.txt \
		python bindings/atlas/3.1/tools/build_fixtures.py --check
	$(MAKE) test-atlas-v3
	rm -rf "$(ATLAS_CONTRACT_DEV_ROOT)"
	$(MAKE) release-atlas-federal-register-thesaurus \
		ATLAS_FR_RELEASE_ROOT="$(ATLAS_CONTRACT_DEV_ROOT)"
	uv run --no-project --with-requirements bindings/atlas/3.1/requirements.txt \
		python bindings/atlas/3.1/tools/validate.py \
		--smoke "$(ATLAS_CONTRACT_DEV_ROOT)/distribution" --quiet
	@manifest_sha256=$$(shasum -a 256 \
		"$(ATLAS_CONTRACT_DEV_ROOT)/distribution/atlas-manifest.json" | cut -d' ' -f1); \
	view_sha256=$$(shasum -a 256 \
		"$(ATLAS_CONTRACT_DEV_ROOT)/parquet-view/view-manifest.json" | cut -d' ' -f1); \
	uv run --with-requirements bindings/atlas/3.1/requirements.txt \
		python tools/verify_federal_register_thesaurus_distribution.py \
		--distribution "$(ATLAS_CONTRACT_DEV_ROOT)/distribution" \
		--expected-manifest-sha256 "$$manifest_sha256" \
		--parquet-view "$(ATLAS_CONTRACT_DEV_ROOT)/parquet-view" \
		--expected-view-manifest-sha256 "$$view_sha256" \
		--source-root "$(ATLAS_FR_RELEASE_SOURCE_ROOT)" \
		--output "$(ATLAS_CONTRACT_DEV_ROOT)-verification-receipt.json" >/dev/null; \
	echo; \
	echo "contract-dev: bounded artifact rebuilt and verified."; \
	echo "  ATLAS_FR_RELEASE_MANIFEST_SHA256 ?= $$manifest_sha256"; \
	echo "  ATLAS_FR_RELEASE_VIEW_SHA256 ?= $$view_sha256"

# The shapes-change scale gate. Times the SHACL phase alone against a built
# distribution and fails past 3x the recorded baseline
# (tools/atlas-shacl-scale-baseline.json). It exists because constraint cost is
# emergent: the Jena spike measured each of one node shape's constraints fast at
# 29.3M quads and the shape whole at 40x that, so no reading of a shapes diff
# predicts its cost. Release tier by weight, not by principle -- the number that
# matters is measured at release scale, and the runner sized for it is where it
# belongs (release.yml's acceptance job runs it there).
ATLAS_SHACL_BENCH_ROOT ?= $(ATLAS_FR_RELEASE_ROOT)

benchmark-atlas-shacl-scale:
	REFSPEC_ATLAS_VALIDATION_MODE=audit uv run python tools/benchmark_atlas_shacl_scale.py \
		--distribution "$(ATLAS_SHACL_BENCH_ROOT)"

# Reads both ends and compares them: the exact publisher PDF, whose occurrence
# ledger is the only place the source-side count exists, and the published
# bytes, counted from the authenticated Parquet tables rather than from the
# producer's own receipt inside the artifact.
verify-atlas-federal-register-thesaurus:
	uv run --with-requirements bindings/atlas/3.1/requirements.txt \
		python tools/verify_federal_register_thesaurus_distribution.py \
		--distribution "$(ATLAS_FR_RELEASE_ROOT)/distribution" \
		--expected-manifest-sha256 "$(ATLAS_FR_RELEASE_MANIFEST_SHA256)" \
		--parquet-view "$(ATLAS_FR_RELEASE_ROOT)/parquet-view" \
		--expected-view-manifest-sha256 "$(ATLAS_FR_RELEASE_VIEW_SHA256)" \
		--source-root "$(ATLAS_FR_RELEASE_SOURCE_ROOT)" \
		--output "$(ATLAS_FR_RELEASE_RECEIPT)"

# The fourth verb. `seal-distribution` is the ceremony step and is the ONLY
# part of build -> prove -> sign -> serve that this repository cannot perform
# on its own: the signer key is deliberately offline, so SEAL_KEY must be
# supplied by whoever holds it. The tool refuses to sign a distribution that
# carries no acceptance receipt, because the seal binds the acceptance digest
# precisely so a consumer can tell "signed" from "signed AND proven".
#
#   make seal-distribution SEAL_ROOT=output/atlas-3.1-full-<date> SEAL_KEY=~/path/to/key
#
# `verify-distribution-seal` needs no key and checks the signature, all three
# bound digests, closed membership and every pinned byte against
# docs/seal-allowed-signers.
SEAL_ROOT ?= output/atlas-3.1-full-2026-08-13b
SEAL_SIGNER ?= atlas-release@refspec
SEAL_ALLOWED_SIGNERS ?= docs/seal-allowed-signers

seal-distribution:
	@test -n "$(SEAL_KEY)" || { echo "SEAL_KEY is required (the offline signing key); nothing was signed"; exit 2; }
	uv run --no-sync python tools/seal_distribution.py mint \
		--distribution "$(SEAL_ROOT)/distribution" \
		--parquet-view "$(SEAL_ROOT)/parquet-view" \
		--private-key "$(SEAL_KEY)" \
		--signer-identity "$(SEAL_SIGNER)"

verify-distribution-seal:
	uv run --no-sync python tools/seal_distribution.py verify \
		--distribution "$(SEAL_ROOT)/distribution" \
		--parquet-view "$(SEAL_ROOT)/parquet-view" \
		--seal "$(SEAL_ROOT)/distribution-seal.json" \
		--allowed-signers "$(SEAL_ALLOWED_SIGNERS)"
