"""The Rulespec pin in the profile names the version the project installs.

`profiles/rulespec-dependency.json` declares `rulespecVersion`, and
`pyproject.toml` declares the dependency actually resolved. Nothing compared
them, so they drifted nine pre-releases apart: the profile said `0.2.0-pre.9`
while the project had depended on `0.2.0rc18` since the rc16 -> rc18 vendor
bump. Closed 2026-09-04 in the seal that re-vendored from tag
`v0.2.0-pre.18`; this file is now the guard that stops it recurring.

Why it went unnoticed is the part worth keeping. The profile was never
unverified: `generated_rulespec_dependency.py` embeds it and carries
`RULESPEC_DEPENDENCY_SHA256` over those bytes, so the pin was tamper-evident
throughout. But that digest is computed over the pin file itself. It proved
nobody had edited the claim and never asked whether the claim was true -- a
check reporting agreement with itself, which reads exactly like a passing
check.

This file was committed in `f75b4c86` as a STRICT xfail rather than a red
test, because the fix was a sealed move that had to ride the next seal. That
worked as designed: when the pin moved, the xfail failed "unexpectedly
passing" and forced the marker's deletion in the same commit that fixed it,
so the record and the code could not drift apart. The marker is gone; the
assertion it guarded is now simply true.
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
    """The third place the version is written, and the one that drifted silently.

    `validator.identity` names `rkaf-validate@<version>` twice. `release_graph`
    validates its SHAPE -- that the three component names are present -- and
    never its version, so it held `0.2.0-pre.9` for nine pre-releases beside a
    `rulespecVersion` that was equally stale. Two wrong fields agreeing is not
    corroboration.
    """

    profile = _profile()
    version = profile["rulespecVersion"]
    identity = profile["validator"]["identity"]
    assert f"rkaf-validate@{version}" in identity
    assert f"rkaf-behavior-validate@{version}" in identity


def test_the_vendored_wheel_is_the_version_the_pin_names() -> None:
    """The pin, the vendored bytes, and the uv source path are one version.

    The wheel is vendored by path, so a pin naming a version that is not in
    `vendor/` resolves to whatever file the path points at rather than failing.
    This is the assertion that would catch that.
    """

    version = _declared_dependency("rulespec-conformance")
    wheel = ROOT / "vendor" / f"rulespec_conformance-{version}-py3-none-any.whl"
    assert wheel.is_file(), f"vendor/ has no wheel for the pinned {version}"
    assert f'path = "vendor/{wheel.name}"' in PYPROJECT.read_text(encoding="utf-8")


def test_the_artifacts_floor_is_satisfied_by_the_vendored_wheel() -> None:
    """rc18 moved `rulespec-artifacts` from `==1.0.9` to `>=1.0.11`.

    A floor is satisfiable by a range, but this tree resolves from one vendored
    file, so the exact pin must name bytes that exist and clear the floor.
    """

    version = _declared_dependency("rulespec-artifacts")
    assert tuple(int(p) for p in version.split(".")) >= (1, 0, 11)
    assert (ROOT / "vendor" / f"rulespec_artifacts-{version}-py3-none-any.whl").is_file()


def test_the_profile_still_states_what_it_does_not_claim() -> None:
    """`localUnpublished` outlived the tag on purpose, and this pins that.

    rulespec published `v0.2.0-pre.18` on 2026-09-04, so a release now exists.
    These two fields were NOT moved in that seal: `releaseAvailability` flows
    into published release-graph and managed-release artifacts, and
    `productionConformanceEligible` is a claim about RefSpec's conformance
    posture rather than a fact about which version is installed. Moving them is
    a separate decision with an owner, and this assertion fails if someone
    makes it silently as part of a version bump.
    """

    profile = _profile()
    assert profile["releaseAvailability"] == "localUnpublished"
    assert profile["productionConformanceEligible"] is False


def test_the_vendor_readme_names_the_bytes_that_are_actually_vendored() -> None:
    """`vendor/README.md` documents each wheel by digest, so it can go stale.

    It did. The 2026-09-04 seal rebuilt rc18 from tag `v0.2.0-pre.18` and
    replaced `rulespec-artifacts` 1.0.9 with 1.0.11, and left the README
    describing the superseded build: a branch and worktree that no longer
    exist, and two digests belonging to bytes no longer in the tree. Nothing
    compared prose to bytes, so it read as current for a day.

    The comparison runs in the direction that catches that -- every wheel
    present must be named by its real digest -- rather than the reverse, so
    the README may still discuss a SUPERSEDED digest in prose, and does.
    """

    readme = (ROOT / "vendor" / "README.md").read_text(encoding="utf-8")
    wheels = sorted((ROOT / "vendor").glob("*.whl"))
    assert wheels, "vendor/ has no wheels; this test is measuring nothing"
    for wheel in wheels:
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        assert digest in readme, f"vendor/README.md does not name the sha256 of {wheel.name}"


def test_the_vendor_readme_names_no_wheel_that_is_gone() -> None:
    """The other half: a filename the README documents must still be there.

    This is the assertion that would have caught the 1.0.9 paragraph, which
    survived the bump to 1.0.11 describing a file that had been deleted. It
    means prose about a superseded wheel refers to it by PACKAGE and VERSION
    (`rulespec-artifacts` 1.0.9) rather than by filename.
    """

    readme = (ROOT / "vendor" / "README.md").read_text(encoding="utf-8")
    for name in set(re.findall(r"rulespec_\w+-[\w.]+-py3-none-any\.whl", readme)):
        assert (ROOT / "vendor" / name).is_file(), f"vendor/README.md documents {name}, which is not vendored"


def test_the_vendor_readme_and_the_profile_name_one_source_revision() -> None:
    """Two documents record where the wheel came from; they must agree.

    `profiles/rulespec-dependency.json` carries `validator.sourceRevision` and
    the README carries the same commit in prose. A re-vendor that updates the
    sealed profile and forgets the README leaves the two disagreeing about
    provenance, which is the drift this whole module exists for.
    """

    readme = (ROOT / "vendor" / "README.md").read_text(encoding="utf-8")
    revision = _profile()["validator"]["sourceRevision"]
    assert revision[:7] in readme, f"vendor/README.md does not name the profile's source revision {revision}"
