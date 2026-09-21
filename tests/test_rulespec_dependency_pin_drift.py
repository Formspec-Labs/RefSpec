"""The Rulespec pin in the profile names the version the project installs.

`profiles/rulespec-dependency.json`'s `rulespecVersion` and `pyproject.toml`'s
resolved dependency went nine pre-releases apart (profile `0.2.0-pre.9` vs
installed `0.2.0rc18`) because the profile's digest is computed over the pin
file itself -- a check reporting agreement with itself. Closed 2026-09-04 in
the seal re-vendored from tag `v0.2.0-pre.18`; this module is the guard,
committed in `f75b4c86` as a strict xfail whose unexpected pass forced the
marker's deletion in the fixing commit.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles" / "rulespec-dependency.json"
PYPROJECT = ROOT / "pyproject.toml"

#: rulespec spells its own version `0.2.0-pre.N`; the built wheel and every
#: dependency spelling normalise that to `0.2.0rcN` under PEP 440. Comparing
#: the two strings raw would report drift that is only spelling.
_PRE_TO_RC = ("-pre.", "rc")


def _profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def _declared_dependency(package: str) -> str:
    match = re.search(rf'"{package}==([^"]+)"', PYPROJECT.read_text(encoding="utf-8"))
    assert match is not None, f"pyproject.toml no longer pins {package} by exact version"
    return match.group(1)


def test_the_profile_pin_names_the_installed_rulespec() -> None:
    """What the profile claims and what the project installs are one version."""

    assert _profile()["rulespecVersion"].replace(*_PRE_TO_RC) == _declared_dependency("rulespec-conformance")


def test_the_validator_identity_carries_the_same_version() -> None:
    """Pin that validator.identity names both `rkaf-validate@<version>` and `rkaf-behavior-validate@<version>` at the
    profile's version.

    `release_graph` validates only the identity's shape, never its version, so
    both fields agreed while both were stale; two wrong fields agreeing is not
    corroboration.
    """

    profile = _profile()
    version = profile["rulespecVersion"]
    identity = profile["validator"]["identity"]
    assert f"rkaf-validate@{version}" in identity
    assert f"rkaf-behavior-validate@{version}" in identity


def test_the_vendored_wheel_is_the_version_the_pin_names() -> None:
    """Pin that the pinned version, the vendored wheel file, and the uv source path agree.

    The wheel is vendored by path, so a pin naming a version absent from
    `vendor/` would resolve to whatever the path points at rather than fail.
    """

    version = _declared_dependency("rulespec-conformance")
    wheel = ROOT / "vendor" / f"rulespec_conformance-{version}-py3-none-any.whl"
    assert wheel.is_file(), f"vendor/ has no wheel for the pinned {version}"
    assert f'path = "vendor/{wheel.name}"' in PYPROJECT.read_text(encoding="utf-8")


def test_the_artifacts_floor_is_satisfied_by_the_vendored_wheel() -> None:
    """Pin that the exact `rulespec-artifacts` pin clears rc18's `>=1.0.11` floor and its wheel is vendored.

    A floor is satisfiable by a range, but this tree resolves from one vendored
    file, so the exact pin must name bytes that exist and clear the floor.
    """

    version = _declared_dependency("rulespec-artifacts")
    assert tuple(int(p) for p in version.split(".")) >= (1, 0, 11)
    assert (ROOT / "vendor" / f"rulespec_artifacts-{version}-py3-none-any.whl").is_file()


def test_the_profile_still_states_what_it_does_not_claim() -> None:
    """Pin `localUnpublished` and `productionConformanceEligible: false` as deliberate (REF-068).

    The 2026-09-04 tag moved provenance, not availability: the field means a
    consumer can obtain the dependency from a publisher, and the wheel in
    `vendor/` was built here from the tag. Moving either is a posture decision
    that must not ride a mechanical version bump.
    """

    profile = _profile()
    assert profile["releaseAvailability"] == "localUnpublished"
    assert profile["productionConformanceEligible"] is False


def test_the_vendor_readme_names_the_bytes_that_are_actually_vendored() -> None:
    """Pin that every vendored wheel's real sha256 is named in `vendor/README.md`.

    The comparison runs in one direction on purpose so the README may still
    discuss a superseded digest in prose; the 2026-09-04 seal left it describing
    deleted bytes, and nothing compared prose to bytes.
    """

    readme = (ROOT / "vendor" / "README.md").read_text(encoding="utf-8")
    wheels = sorted((ROOT / "vendor").glob("*.whl"))
    assert wheels, "vendor/ has no wheels; this test is measuring nothing"
    for wheel in wheels:
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        assert digest in readme, f"vendor/README.md does not name the sha256 of {wheel.name}"


def test_the_vendor_readme_names_no_wheel_that_is_gone() -> None:
    """Pin that every wheel filename the README documents still exists in `vendor/`.

    This is what would have caught the 1.0.9 paragraph; prose about a superseded
    wheel must name it by package and version, not filename.
    """

    readme = (ROOT / "vendor" / "README.md").read_text(encoding="utf-8")
    for name in set(re.findall(r"rulespec_\w+-[\w.]+-py3-none-any\.whl", readme)):
        assert (ROOT / "vendor" / name).is_file(), f"vendor/README.md documents {name}, which is not vendored"


def test_the_vendor_readme_and_the_profile_name_one_source_revision() -> None:
    """Pin that the profile's `validator.sourceRevision` appears in the vendor README, so a re-vendor cannot update one
    without the other.
    """

    readme = (ROOT / "vendor" / "README.md").read_text(encoding="utf-8")
    revision = _profile()["validator"]["sourceRevision"]
    assert revision[:7] in readme, f"vendor/README.md does not name the profile's source revision {revision}"
