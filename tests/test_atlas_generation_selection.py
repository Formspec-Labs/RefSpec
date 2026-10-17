"""Synthetic fault probes for selection, independent of Atlas semantic gates."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from refspec.atlas.generation import generation_store, require_selection_output, select_atlas_generation, selection_path
from tools import compare_build_trees, seal_distribution
from tools import generate_atlas_v3_full as generator


@pytest.fixture
def writer(monkeypatch):
    """Use marker artifacts to isolate publication; do not assert conformance."""
    def candidate(output, streamed, *args, parquet_tables=None, **kwargs):
        marker = streamed.accounting["id"]
        output.mkdir()
        (output / "atlas-manifest.json").write_text(marker)
        (output / "marker").write_text(marker)
        if parquet_tables is not None:
            parquet_tables.mkdir()
            (parquet_tables / "marker").write_text(marker)
        return {"status": "passed"}, {"distributionId": marker}

    def view(candidate, tables, output, **kwargs):
        output.mkdir()
        (output / "marker").write_text((tables / "marker").read_text())
        (output / "view-manifest.json").write_text("synthetic view")

    monkeypatch.setattr(generator, "_STATUS", SimpleNamespace(phase=lambda *a: None, memory_profile=dict))
    monkeypatch.setattr(generator, "_write_streamed_candidate_distribution", candidate)
    monkeypatch.setattr(generator, "seal_atlas_parquet_view", view)
    monkeypatch.setattr(generator, "_distribution_id", lambda accounting: accounting["id"])
    monkeypatch.setattr(generator, "_production_relation_scope_from_counts", lambda counts: {})

    def write(output, marker="old", *, parquet_view=True):
        streamed = SimpleNamespace(compiled_validation={"counts": {}}, accounting={"id": marker}, derived_rows=[])
        return generator._write_streamed_distribution(
            output, streamed, releases=[], construction_seeds=[],
            generation_report={"createdAt": "synthetic", "marker": marker}, parquet_view=parquet_view,
        )
    return write


def markers(selected):
    # Deliberately allow a pointer replacement between reads of sibling files.
    distribution = (selected.distribution / "marker").read_text()
    time.sleep(0.001)
    view = (selected.parquet_view / "marker").read_text()
    report = json.loads(selected.report.read_bytes())["marker"]
    return distribution, view, report


@pytest.mark.parametrize("fault", ["view", "report", "retain", "pointer"])
@pytest.mark.parametrize("has_previous", [False, True])
def test_preselection_failures_preserve_previous_generation(tmp_path, monkeypatch, writer, fault, has_previous):
    output = tmp_path / "chosen"
    previous = None
    if has_previous:
        writer(output)
        previous = select_atlas_generation(output)
        previous.seal.write_text("retained seal")
    original_write, original_rename, original_replace = Path.write_bytes, Path.rename, os.replace

    def write(path, data):
        if fault == "report" and path.name == "generation-report.json":
            raise OSError("injected report")
        return original_write(path, data)

    def rename(path, target):
        if fault == "retain" and Path(target).parent == generation_store(output):
            raise OSError("injected retain")
        return original_rename(path, target)

    def replace(source, target):
        if fault == "pointer" and target == output:
            raise OSError("injected pointer")
        return original_replace(source, target)

    if fault == "view":
        def fail_view(*args, **kwargs):
            raise OSError("injected view")
        monkeypatch.setattr(generator, "seal_atlas_parquet_view", fail_view)
    monkeypatch.setattr(Path, "write_bytes", write)
    monkeypatch.setattr(Path, "rename", rename)
    monkeypatch.setattr(generator.os, "replace", replace)
    with pytest.raises(OSError, match=f"injected {fault}"):
        writer(output, "new")
    if previous:
        assert select_atlas_generation(output) == previous
        assert markers(previous) == ("old",) * 3
        assert previous.seal.read_text() == "retained seal"
    else:
        assert not output.exists() and not output.is_symlink()
    assert not list(tmp_path.glob("*.selecting"))
    if fault == "pointer":
        # Completed but unselected data is retained, not deleted as rollback.
        complete = [p for p in generation_store(output).iterdir() if not p.name.startswith(".")]
        assert len(complete) == (2 if previous else 1)


def test_success_keeps_old_artifacts_and_reader_pins_once(tmp_path, monkeypatch, writer):
    output = tmp_path / "chosen"
    writer(output)
    old = select_atlas_generation(output)
    old.seal.write_text("old seal")
    calls = []
    original = os.readlink
    monkeypatch.setattr(os, "readlink", lambda path: (calls.append(path), original(path))[1])
    pinned = select_atlas_generation(output)
    assert calls == [output]
    writer(output, "new")
    assert selection_path(output) == output  # Never resolves into the old distribution.
    assert markers(pinned) == ("old",) * 3
    assert markers(select_atlas_generation(output)) == ("new",) * 3
    assert old.seal.read_text() == "old seal"
    assert not (output.parent / "parquet-view").exists()
    assert not (output.parent / "generation-report.json").exists()


def test_measurement_error_reports_selected_generation_without_rollback(tmp_path, monkeypatch, capsys, writer):
    output = tmp_path / "chosen"
    original = Path.write_bytes
    def write(path, data):
        if path.name == generator.GENERATION_MEASUREMENTS_FILE:
            raise OSError("diagnostic disk error")
        return original(path, data)
    monkeypatch.setattr(Path, "write_bytes", write)
    assert writer(output, "new")["status"] == "passed"
    assert markers(select_atlas_generation(output)) == ("new",) * 3
    assert "selected at" in capsys.readouterr().err


def test_sibling_selectors_and_no_view_are_isolated(tmp_path, writer):
    first, second = tmp_path / "one", tmp_path / "two"
    writer(first, "one")
    writer(second, "two", parquet_view=False)
    a, b = select_atlas_generation(first), select_atlas_generation(second)
    assert a.root.parent != b.root.parent
    assert markers(a) == ("one",) * 3
    assert not b.parquet_view.exists()
    assert json.loads(b.report.read_bytes())["distribution"]["path"] == "distribution"
    assert (b.distribution / "marker").read_text() == "two"


def test_existing_real_output_is_preserved_and_refused_before_loading(tmp_path, monkeypatch, writer):
    output = tmp_path / "distribution"
    output.mkdir()
    (output / "evidence").write_text("original")
    with pytest.raises(FileExistsError, match="existing real output"):
        writer(output)
    monkeypatch.setattr(generator, "load_releases", lambda **kw: pytest.fail("must refuse before loading"))
    with pytest.raises(FileExistsError, match="existing real output"):
        generator.build_distribution(output)
    assert (output / "evidence").read_text() == "original"
    assert not generation_store(output).exists()


def test_existing_invalid_selection_is_refused_before_loading(tmp_path, monkeypatch, writer):
    output = tmp_path / "chosen"
    output.symlink_to("/tmp/foreign")
    monkeypatch.setattr(generator, "load_releases", lambda **kw: pytest.fail("must refuse before loading"))
    with pytest.raises(ValueError, match="invalid generation target"):
        generator.build_distribution(output)
    real = tmp_path / "real"
    real.mkdir()
    with pytest.raises(FileExistsError, match="existing real output"):
        require_selection_output(real)
    missing = tmp_path / "missing"
    assert require_selection_output(missing) == tmp_path.resolve() / "missing"
    assert not missing.exists()
    valid = tmp_path / "valid"
    writer(valid)
    assert require_selection_output(valid) == tmp_path.resolve() / "valid"


@pytest.mark.parametrize("target", ["/tmp/foreign", "other/" + "a" * 32 + "/distribution", ".chosen.generations/../distribution", ".chosen.generations/wrong/distribution"])
def test_selection_refuses_foreign_targets(tmp_path, target):
    output = tmp_path / "chosen"
    output.symlink_to(target)
    with pytest.raises(ValueError, match="invalid generation target"):
        select_atlas_generation(output)


@pytest.mark.parametrize("artifact", ["store", "generation", "distribution", "report", "manifest", "view", "view-manifest"])
def test_selection_refuses_missing_or_symlinked_artifacts(tmp_path, writer, artifact):
    output = tmp_path / "chosen"
    writer(output)
    selected = select_atlas_generation(output)
    path = {"store": selected.root.parent, "generation": selected.root, "distribution": selected.distribution,
            "report": selected.report, "manifest": selected.distribution / "atlas-manifest.json",
            "view": selected.parquet_view, "view-manifest": selected.parquet_view / "view-manifest.json"}[artifact]
    moved = tmp_path / "moved"
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(ValueError, match="real directory|regular artifact|regular view manifest"):
        select_atlas_generation(output)


def _kill_probe_child(output, transition):
    """Run in a fresh interpreter so parser/native-library threads are not forked."""
    write_fixture = writer.__wrapped__(pytest.MonkeyPatch())
    def stop(stage):
        if stage == transition:
            print(stage, flush=True)
            signal.pause()
    candidate = generator._write_streamed_candidate_distribution
    seal = generator.seal_atlas_parquet_view
    write, rename, replace = Path.write_bytes, Path.rename, os.replace
    def wrapped_candidate(*args, **kw):
        result = candidate(*args, **kw)
        stop("distribution")
        return result
    def wrapped_seal(*args, **kw):
        result = seal(*args, **kw)
        stop("view")
        return result
    def wrapped_write(path, data):
        result = write(path, data)
        if path.name == "generation-report.json":
            stop("report")
        return result
    def wrapped_rename(path, target):
        stop("before-retain")
        result = rename(path, target)
        stop("after-retain")
        return result
    def wrapped_replace(source, target):
        stop("before-pointer")
        result = replace(source, target)
        stop("after-pointer")
        return result
    generator._write_streamed_candidate_distribution = wrapped_candidate
    generator.seal_atlas_parquet_view = wrapped_seal
    Path.write_bytes, Path.rename, os.replace = wrapped_write, wrapped_rename, wrapped_replace
    write_fixture(Path(output), "killed")


@pytest.mark.parametrize("transition", ["distribution", "view", "report", "before-retain", "after-retain", "before-pointer", "after-pointer"])
def test_killed_writer_and_restart_keep_complete_selection(tmp_path, writer, transition):
    output = tmp_path / "chosen"
    writer(output)
    old = select_atlas_generation(output)
    script = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from test_atlas_generation_selection import _kill_probe_child; "
        "_kill_probe_child(sys.argv[2], sys.argv[3])"
    )
    with subprocess.Popen(
        [sys.executable, "-c", script, str(Path(__file__).parent), str(output), transition],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) as process:
        try:
            assert select.select([process.stdout], [], [], 15)[0], "writer failed to reach transition"
            assert process.stdout.readline().strip() == transition
            process.kill()
            process.wait(timeout=5)
            assert process.returncode == -signal.SIGKILL
            expected = "killed" if transition == "after-pointer" else "old"
            assert markers(select_atlas_generation(output)) == (expected,) * 3
            orphan_files = {p: p.read_bytes() for p in generation_store(output).rglob("*") if p.is_file()}
            writer(output, "restart")
            assert markers(select_atlas_generation(output)) == ("restart",) * 3
            assert markers(old) == ("old",) * 3
            assert all(path.read_bytes() == data for path, data in orphan_files.items())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_concurrent_writers_and_readers_never_mix_generations(tmp_path, writer):
    output = tmp_path / "chosen"
    writer(output)
    def produce(prefix):
        for index in range(8):
            writer(output, f"{prefix}-{index}")
    observed = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(produce, prefix) for prefix in ("a", "b")]
        while not all(f.done() for f in futures):
            observed.append(markers(select_atlas_generation(output)))
        for future in futures:
            future.result()
    observed.append(markers(select_atlas_generation(output)))
    assert observed
    assert all(len(set(values)) == 1 for values in observed)
    assert len(list(generation_store(output).iterdir())) == 17


def test_comparison_pins_only_selected_generation_and_covers_report_and_view(tmp_path, writer):
    first, second = tmp_path / "one", tmp_path / "two"
    writer(first, "ignored-prior")
    writer(first, "same")
    writer(second, "same")
    assert compare_build_trees.main([str(first), str(second)]) == 0
    selected = select_atlas_generation(second)
    selected.report.write_text("different")
    assert compare_build_trees.main([str(first), str(second)]) == 1
    selected.report.write_bytes(select_atlas_generation(first).report.read_bytes())
    (selected.parquet_view / "marker").write_text("different")
    assert compare_build_trees.main([str(first), str(second)]) == 1


@pytest.mark.parametrize("command", ["mint", "verify"])
def test_seal_cli_selects_once_and_passes_concrete_siblings(tmp_path, monkeypatch, writer, command):
    output = tmp_path / "chosen"
    writer(output)
    old = select_atlas_generation(output)
    original = seal_distribution.select_atlas_generation
    def select(path):
        result = original(path)
        writer(output, "new")
        return result
    def consume(args, generation):
        assert generation == old
        assert generation.distribution == old.distribution
        assert generation.parquet_view == old.parquet_view
        assert generation.seal == old.seal
        return 0
    monkeypatch.setattr(seal_distribution, "select_atlas_generation", select)
    monkeypatch.setattr(seal_distribution, "_mint" if command == "mint" else "_verify", consume)
    args = ["tool", command, "--selection", str(output)]
    if command == "mint":
        args += ["--private-key", "fixture-key", "--signer-identity", "fixture"]
    monkeypatch.setattr(sys, "argv", args)
    assert seal_distribution.main() == 0


def test_cli_rebuild_preserves_selector_name(tmp_path, monkeypatch, writer):
    output = tmp_path / "chosen"
    writer(output)
    previous = select_atlas_generation(output)
    called = []
    def build(path, **kwargs):
        called.append(path)
        writer(path, "rebuilt")
    monkeypatch.setattr(generator, "build_distribution", build)
    monkeypatch.setattr(sys, "argv", ["build", "--output", str(output), "--quiet"])
    assert generator.main() == 0
    assert called == [output]
    assert markers(previous) == ("old",) * 3
    assert markers(select_atlas_generation(output)) == ("rebuilt",) * 3


def test_selection_reads_no_artifact_bytes(tmp_path, monkeypatch, writer):
    output = tmp_path / "chosen"
    writer(output)
    def unexpected_open(*args, **kwargs):
        pytest.fail("selection must not parse reports or scan artifact bytes")
    monkeypatch.setattr(Path, "open", unexpected_open)
    assert select_atlas_generation(output).distribution.is_dir()


def _generation_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "refspec.atlas.generation", *map(str, args)], capture_output=True, text=True,
    )


def test_generation_cli_prints_pinned_paths(tmp_path, writer):
    output = tmp_path / "chosen"
    writer(output)
    # Derived from the raw link, not from the code under test.
    distribution = output.parent.resolve() / os.readlink(output)
    assert _generation_cli(output).stdout.strip() == str(distribution.parent)
    assert _generation_cli(output, "--artifact", "distribution").stdout.strip() == str(distribution)
    assert _generation_cli(output, "--artifact", "parquet_view").stdout.strip() == str(distribution.parent / "parquet-view")
    real = tmp_path / "real"
    real.mkdir()
    refused = _generation_cli(real)
    assert refused.returncode == 2 and "must be a builder generation symlink" in refused.stderr


# A recording `uv`: selection calls run the real CLI (so a recipe that drops
# `--artifact` gets the wrong path), then the selector moves to a different
# generation, which a consumer re-reading it would pick up.
FAKE_UV = f"""#!{sys.executable}
import json, os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["UV_CALLS"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
if "refspec.atlas.generation" in args:
    cli = args[args.index("refspec.atlas.generation") + 1:]
    done = subprocess.run([sys.executable, "-m", "refspec.atlas.generation", *cli], capture_output=True, text=True)
    sys.stdout.write(done.stdout)
    sys.stderr.write(done.stderr)
    if done.returncode == 0:
        pointer = Path(cli[0])
        switch = pointer.with_name(".switch")
        switch.symlink_to(os.environ["NEXT_POINTER"])
        os.replace(switch, pointer)
    sys.exit(done.returncode)
"""


def _run_make(tmp_path, *arguments, next_pointer=""):
    """Run make with the recording `uv` first on PATH; return (process, recorded uv argv lists)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(FAKE_UV)
    fake_uv.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    completed = subprocess.run(
        ["make", "--no-print-directory", "-s", *arguments],
        cwd=Path(__file__).parents[1], capture_output=True, text=True,
        env={**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
             "UV_CALLS": str(calls), "NEXT_POINTER": next_pointer},
    )
    recorded = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    return completed, recorded


@pytest.mark.parametrize("target,variable,tool,release_root", [
    ("audit-atlas-v3-source-fidelity", "ATLAS_V3_AUDIT_ROOT", "tools/verify_atlas_source_fidelity.py", False),
    ("benchmark-atlas-shacl-scale", "ATLAS_SHACL_BENCH_ROOT", "tools/benchmark_atlas_shacl_scale.py", False),
    ("verify-atlas-federal-register-thesaurus", "ATLAS_FR_RELEASE_ROOT",
     "tools/verify_federal_register_thesaurus_distribution.py", True),
])
def test_make_consumers_pin_selection_once(tmp_path, writer, target, variable, tool, release_root):
    output = tmp_path / "release" / "distribution"
    output.parent.mkdir()
    writer(output)
    expected = select_atlas_generation(output)
    previous_target = os.readlink(output)
    writer(output, "replacement")
    next_target = os.readlink(output)
    output.unlink()
    output.symlink_to(previous_target)
    completed, commands = _run_make(
        tmp_path, target, f"{variable}={output.parent if release_root else output}", next_pointer=next_target,
    )
    assert completed.returncode == 0, completed.stderr
    assert len([args for args in commands if "refspec.atlas.generation" in args]) == 1
    consumer = next(args for args in commands if tool in args)
    assert consumer[consumer.index("--distribution") + 1] == str(expected.distribution)
    if release_root:
        assert consumer[consumer.index("--parquet-view") + 1] == str(expected.parquet_view)
    assert select_atlas_generation(output).distribution != expected.distribution


def test_audit_receipt_stays_beside_a_slash_terminated_selector(tmp_path, writer):
    output = tmp_path / "release" / "distribution"
    output.parent.mkdir()
    writer(output)
    completed, commands = _run_make(
        tmp_path, "audit-atlas-v3-source-fidelity", f"ATLAS_V3_AUDIT_ROOT={output}/", next_pointer=os.readlink(output),
    )
    assert completed.returncode == 0, completed.stderr
    consumer = next(args for args in commands if "tools/verify_atlas_source_fidelity.py" in args)
    assert consumer[consumer.index("--output") + 1] == f"{output}-source-fidelity-receipt.json"


GATE_ROOTS = [
    ("release-atlas-federal-register-thesaurus", "ATLAS_FR_RELEASE_ROOT"),
    ("build-atlas-umthes", "ATLAS_UMTHES_ROOT"),
    ("build-atlas-agency", "ATLAS_AGENCY_ROOT"),
]


@pytest.mark.parametrize("target,variable", GATE_ROOTS)
def test_gate_targets_clear_only_the_builder_owned_selection(tmp_path, writer, target, variable):
    root = tmp_path / "gate"
    root.mkdir()
    writer(root / "distribution")
    (root / ".distribution.deadbeef.selecting").symlink_to("nowhere")
    (root / "keep.txt").write_text("unrelated")
    completed, commands = _run_make(tmp_path, target, f"{variable}={root}")
    assert completed.returncode == 0, completed.stderr
    assert sorted(path.name for path in root.iterdir()) == ["keep.txt"]
    assert (root / "keep.txt").read_text() == "unrelated"
    builds = [args for args in commands if "tools/generate_atlas_v3_full.py" in args]
    assert len(builds) == 1 and builds[0][builds[0].index("--output") + 1] == f"{root}/distribution"


@pytest.mark.parametrize("target,variable", GATE_ROOTS)
def test_gate_targets_leave_a_real_directory_root_for_the_builder_to_refuse(tmp_path, target, variable):
    root = tmp_path / "gate"
    (root / "distribution").mkdir(parents=True)
    (root / "distribution" / "marker").write_text("original")
    (root / "keep.txt").write_text("unrelated")
    completed, commands = _run_make(tmp_path, target, f"{variable}={root}")
    assert completed.returncode == 0, completed.stderr
    assert (root / "distribution" / "marker").read_text() == "original"
    assert (root / "keep.txt").read_text() == "unrelated"
    assert len([args for args in commands if "tools/generate_atlas_v3_full.py" in args]) == 1  # The builder's refusal decides.


@pytest.mark.parametrize("target,variable", [
    ("audit-atlas-v3-source-fidelity", "ATLAS_V3_AUDIT_ROOT"),
    ("benchmark-atlas-shacl-scale", "ATLAS_SHACL_BENCH_ROOT"),
])
@pytest.mark.parametrize("input_form", ["parent", "direct-distribution"])
def test_make_consumers_refuse_unsupported_path_forms(tmp_path, writer, target, variable, input_form):
    output = tmp_path / "release" / "distribution"
    output.parent.mkdir()
    writer(output)
    argument = output.parent if input_form == "parent" else select_atlas_generation(output).distribution
    completed = subprocess.run(
        ["make", "--no-print-directory", "-s", target, f"{variable}={argument}"],
        cwd=Path(__file__).parents[1], capture_output=True, text=True,
    )
    assert completed.returncode != 0
    assert "must be a builder generation symlink" in completed.stderr


def _seal_argv(command, selection, *extra):
    key = ["--private-key", "x", "--signer-identity", "y"] if command == "mint" else []
    return ["seal", command, "--selection", str(selection), *key, *extra]


@pytest.mark.parametrize("command", ["mint", "verify"])
@pytest.mark.parametrize("flag", ["--distribution", "--parquet-view", "--seal", "--output"])
def test_seal_cli_refuses_unsupported_artifact_arguments(monkeypatch, command, flag):
    monkeypatch.setattr(sys, "argv", _seal_argv(command, "unused", flag, "unused"))
    with pytest.raises(SystemExit) as refusal:
        seal_distribution.main()
    assert refusal.value.code == 2


@pytest.mark.parametrize("command", ["mint", "verify"])
def test_seal_cli_refuses_a_non_selector(tmp_path, monkeypatch, capsys, command):
    legacy = tmp_path / "legacy" / "distribution"  # A pre-selection release: a real directory.
    legacy.mkdir(parents=True)
    (legacy / "atlas-manifest.json").write_text("{}")
    monkeypatch.setattr(sys, "argv", _seal_argv(command, legacy))
    assert seal_distribution.main() == 1
    assert "must be a builder generation symlink" in capsys.readouterr().err
    assert not list(tmp_path.rglob("*seal*.json"))


@pytest.mark.parametrize("target,variables,message", [
    ("audit-atlas-v3-source-fidelity", ["ATLAS_V3_AUDIT_ROOT="], "ATLAS_V3_AUDIT_ROOT must name"),
    ("verify-distribution-seal", ["SEAL_ROOT="], "SEAL_ROOT must name"),
    ("seal-distribution", ["SEAL_ROOT=", "SEAL_KEY=k"], "SEAL_ROOT must name"),
])
def test_make_targets_require_their_selector_variable(tmp_path, target, variables, message):
    completed, commands = _run_make(tmp_path, target, *variables)
    assert completed.returncode == 2 and message in completed.stderr
    assert commands == []


def test_comparator_refuses_unselected_tree(tmp_path, capsys):
    direct = tmp_path / "distribution"
    direct.mkdir()
    assert compare_build_trees.main([str(direct), str(direct)]) == 1
    assert "must be a builder generation symlink" in capsys.readouterr().out


def test_benchmark_requires_concrete_selected_distribution(tmp_path, monkeypatch, writer):
    from tools import benchmark_atlas_shacl_scale as benchmark
    output = tmp_path / "distribution"
    writer(output)
    selected = select_atlas_generation(output)
    calls = []
    def measure(path):
        calls.append(path)
        return {"scaleClass": "fixture", "mode": "default", "shaclSeconds": 1,
                "quadCount": 1, "packCount": 1, "parseSeconds": 0}
    monkeypatch.setattr(benchmark, "measure", measure)
    assert benchmark.main(["--distribution", str(selected.distribution), "--baseline", str(tmp_path / "absent.json")]) == 0
    for unsupported in (output, output.parent):
        assert benchmark.main(["--distribution", str(unsupported)]) == 1
    assert calls == [selected.distribution]
