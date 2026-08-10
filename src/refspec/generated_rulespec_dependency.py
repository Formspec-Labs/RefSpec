"""Generated embedded Rulespec dependency pin. Do not edit by hand."""

from __future__ import annotations

import base64
import json
from typing import Any

RULESPEC_DEPENDENCY_SHA256 = "sha256:4b2772300cbfb0154cc96fc23d43f1659c2704adbc07bc2b3893e3b73a8742b9"

_ENCODED_RULESPEC_DEPENDENCY = (
    "ewogICJzY2hlbWFWZXJzaW9uIjogIjEuMCIsCiAgInJ1bGVzcGVjVmVyc2lvbiI6ICIwLjIuMC1wcmUuOSIsCiAgInJlbGVhc2VB"
    "dmFpbGFiaWxpdHkiOiAibG9jYWxVbnB1Ymxpc2hlZCIsCiAgInByb2R1Y3Rpb25Db25mb3JtYW5jZUVsaWdpYmxlIjogZmFsc2Us"
    "CiAgImNvbnN0cmFpbnREaWdlc3RTY29wZSI6ICJnbG9iYWxSdWxlc3BlY0NvbnRyYWN0IiwKICAiYWRvcHRlZENvbnN0cmFpbnRT"
    "b3VyY2VzIjogWwogICAgImNvbnN0cmFpbnRzL2FuYWx5c2lzIiwKICAgICJjb25zdHJhaW50cy9jb3JlIiwKICAgICJjb25zdHJh"
    "aW50cy9wcm9maWxlcy9yZWZzcGVjL29wZW4tbGFiZWwuY3VlIgogIF0sCiAgInZhbGlkYXRvciI6IHsKICAgICJpZGVudGl0eSI6"
    "ICJya2FmLXZhbGlkYXRlQDAuMi4wLXByZS45ICsgdG9vbHMvY2lfdmFsaWRhdGUucHkgKyBya2FmLWJlaGF2aW9yLXZhbGlkYXRl"
    "QDAuMi4wLXByZS45IiwKICAgICJzb3VyY2VSZXZpc2lvbiI6ICI3OTE2NzBlN2M1ZWM0Y2JjZDM2Y2Q5Y2Q3ZWZkNGNlMDE0M2Jj"
    "MDk0IiwKICAgICJjb21wbGV0ZUdhdGVDb21tYW5kIjogIm1ha2UgdGVzdCIsCiAgICAiY2xhaW1lZExldmVscyI6IFsKICAgICAg"
    "IkwxIiwKICAgICAgIkwyIiwKICAgICAgIkwzIiwKICAgICAgIkw0IgogICAgXSwKICAgICJzZWxmQ2VydGlmaWNhdGlvblBhdGgi"
    "OiAiY29uZm9ybWFuY2UvcGFydG5lcnMvcnVsZXNwZWMtcmVmZXJlbmNlLnlhbWwiLAogICAgInNlbGZDZXJ0aWZpY2F0aW9uU2hh"
    "MjU2IjogIjNlZTNlZDRiNjdmYTg3YmNkYjA3ZmM3YTAyNzdiNmM4YTU0ZGQzNDc3YmU4OWY0ZDc3NjUyYzhjM2Y3MGE3MTAiCiAg"
    "fQp9Cg=="
)

RULESPEC_DEPENDENCY_BYTES = base64.b64decode(
    _ENCODED_RULESPEC_DEPENDENCY
)


def load_rulespec_dependency() -> dict[str, Any]:
    """Return a new copy of the embedded dependency manifest."""

    value = json.loads(RULESPEC_DEPENDENCY_BYTES)
    assert isinstance(value, dict)
    return value


__all__ = [
    "RULESPEC_DEPENDENCY_BYTES",
    "RULESPEC_DEPENDENCY_SHA256",
    "load_rulespec_dependency",
]
