"""The Rulespec pin in the profile must name the version the project installs.

`profiles/rulespec-dependency.json` declares `rulespecVersion`, and
`pyproject.toml` declares the dependency actually resolved. Nothing compared
them, so they drifted nine pre-releases apart -- the profile says
`0.2.0-pre.9` while the project has depended on `0.2.0rc18` since the rc16 ->
rc18 vendor bump.

The drift is invisible rather than unnoticed, and the reason is the point.
The profile IS verified: `generated_rulespec_dependency.py` embeds it and
carries `RULESPEC_DEPENDENCY_SHA256` over those bytes. But that digest is
computed over the pin file itself, so it proves only that nobody edited the
claim. It never asks whether the claim is true. A check that reports agreement
with itself is the defect family this repository spent 2026-09-01 through
09-04 naming, and this is its cleanest instance: every digest in the loop
derives from the thing under test.

**The fix is deliberately NOT in this commit.** The profile is digest-sealed,
so correcting `rulespecVersion` moves `RULESPEC_DEPENDENCY_SHA256` and every
consumer of the embedded copy. That is a sealed move and belongs in the next
seal, with its reason stated, rather than riding along with a test. The xfail
below therefore documents a live defect rather than a hypothetical one, and
`strict=True` means it turns into a FAILURE the moment the pin is fixed --
forcing whoever fixes it to delete this marker rather than leave a passing
xfail nobody reads.

Not left as a plain red test on purpose. A permanently red assertion is worse
than none: REF-067 records how the receipt provenance check went red for a
reason nobody could clear and buried a real drift signal underneath, and the
lesson is three days old. A strict xfail makes the defect visible without
spending the suite's own signal to do it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles" / "rulespec-dependency.json"
PYPROJECT = ROOT / "pyproject.toml"

#: rulespec spells its own version `0.2.0-pre.N`; the built wheel and every
#: dependency spelling normalise that to `0.2.0rcN` under PEP 440. Comparing
#: the two strings raw would report drift that is only spelling.
_PRE_TO_RC = ("-pre.", "rc")


def _profile_version() -> str:
    return json.loads(PROFILE.read_text(encoding="utf-8"))["rulespecVersion"]


def _declared_dependency() -> str:
    match = re.search(r'"rulespec-conformance==([^"]+)"', PYPROJECT.read_text(encoding="utf-8"))
    assert match is not None, "pyproject.toml no longer pins rulespec-conformance by exact version"
    return match.group(1)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "known drift: the profile pins 0.2.0-pre.9 while the project depends on 0.2.0rc18. "
        "Fixing it moves RULESPEC_DEPENDENCY_SHA256, so it rides the next seal. "
        "Delete this marker in the same commit that corrects the pin."
    ),
)
def test_the_profile_pin_names_the_installed_rulespec() -> None:
    """What the profile claims and what the project installs are one version."""

    assert _profile_version().replace(*_PRE_TO_RC) == _declared_dependency()


def test_the_drift_is_exactly_the_gap_recorded_above() -> None:
    """A narrower, always-green companion, so the gap is asserted not narrated.

    Pinning the two ends means the xfail above cannot quietly become stale: if
    either side moves for any reason -- someone bumps the dependency, someone
    half-fixes the profile -- this fails and the xfail's reason string has to
    be rewritten rather than left describing a drift that is no longer this
    one. It is deleted together with the marker when the pin is corrected.
    """

    assert _profile_version() == "0.2.0-pre.9"
    assert _declared_dependency() == "0.2.0rc18"


def test_the_profile_is_honest_about_what_it_cannot_verify() -> None:
    """The two fields that keep the stale pin from being a false claim.

    `localUnpublished` and `productionConformanceEligible: false` are why this
    drift is a defect rather than an incident: the profile never claimed the
    pin was externally verified. spicy-regs says the same thing by failing its
    publish gate closed while the contract is an unreleased candidate. Both
    are downstream of rulespec having published one tag, `v0.2.0-pre.7`, 114
    commits behind its own HEAD.
    """

    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert profile["releaseAvailability"] == "localUnpublished"
    assert profile["productionConformanceEligible"] is False
