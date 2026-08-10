"""Generated embedded Rulespec dependency pin. Do not edit by hand."""

from __future__ import annotations

import base64
import json
from typing import Any

RULESPEC_DEPENDENCY_SHA256 = "sha256:0146b316902c08a96dac51b01a5cde82b282c57028517a86108f991d62d659bb"

_ENCODED_RULESPEC_DEPENDENCY = (
    "ewogICJzY2hlbWFWZXJzaW9uIjogIjEuMCIsCiAgInJ1bGVzcGVjVmVyc2lvbiI6ICIwLjIuMC1wcmUuOSIsCiAgInJlbGVhc2VB"
    "dmFpbGFiaWxpdHkiOiAibG9jYWxVbnB1Ymxpc2hlZCIsCiAgInByb2R1Y3Rpb25Db25mb3JtYW5jZUVsaWdpYmxlIjogZmFsc2Us"
    "CiAgImNvbnRyYWN0UmV2aXNpb24iOiAiNzkxNjcwZTdjNWVjNGNiY2QzNmNkOWNkN2VmZDRjZTAxNDNiYzA5NCIsCiAgImV2aWRl"
    "bmNlUmV2aXNpb24iOiAiOWQyNDUxYjIxM2JlYjk2ODhmYTllMzEyOGFiYzAyNDVhYTMwNDkwMSIsCiAgImNvbnN0cmFpbnREaWdl"
    "c3QiOiAic2hhMjU2OmViNTE4YzZiMjA1OTNhMTA5MmNkZTg4ZjBjYmIwZDRlMmI2Mjg1MmVjN2QzZWJjNzgzOTcwYmU4NWU4MWZk"
    "NmIiLAogICJjb25zdHJhaW50RGlnZXN0U2NvcGUiOiAiZ2xvYmFsUnVsZXNwZWNDb250cmFjdCIsCiAgImNvbmZvcm1hbmNlQ29y"
    "cHVzRGlnZXN0IjogInNoYTI1NjowZGI1NjcwNjNhZTY3MmZlNGQ0ZDIzMjU4NWEzNjZkYTc1ZWQ5YjcwNThkZGRkNjUzMTM0ZWUx"
    "MzEwNGZkYjBiIiwKICAiYWRvcHRlZENvbnN0cmFpbnRTb3VyY2VzIjogWwogICAgImNvbnN0cmFpbnRzL2NvcmUiLAogICAgImNv"
    "bnN0cmFpbnRzL3Byb2ZpbGVzL3JlZnNwZWMvb3Blbi1sYWJlbC5jdWUiCiAgXSwKICAidmFsaWRhdG9yIjogewogICAgImlkZW50"
    "aXR5IjogInJrYWYtdmFsaWRhdGVAMC4yLjAtcHJlLjkgKyB0b29scy9jaV92YWxpZGF0ZS5weSArIHJrYWYtYmVoYXZpb3ItdmFs"
    "aWRhdGVAMC4yLjAtcHJlLjkiLAogICAgInNvdXJjZVJldmlzaW9uIjogIjc5MTY3MGU3YzVlYzRjYmNkMzZjZDljZDdlZmQ0Y2Uw"
    "MTQzYmMwOTQiLAogICAgImNvbXBsZXRlR2F0ZUNvbW1hbmQiOiAibWFrZSB0ZXN0IiwKICAgICJjbGFpbWVkTGV2ZWxzIjogWwog"
    "ICAgICAiTDEiLAogICAgICAiTDIiLAogICAgICAiTDMiLAogICAgICAiTDQiCiAgICBdLAogICAgInNlbGZDZXJ0aWZpY2F0aW9u"
    "UGF0aCI6ICJjb25mb3JtYW5jZS9wYXJ0bmVycy9ydWxlc3BlYy1yZWZlcmVuY2UueWFtbCIsCiAgICAic2VsZkNlcnRpZmljYXRp"
    "b25TaGEyNTYiOiAiM2VlM2VkNGI2N2ZhODdiY2RiMDdmYzdhMDI3N2I2YzhhNTRkZDM0NzdiZTg5ZjRkNzc2NTJjOGMzZjcwYTcx"
    "MCIKICB9Cn0K"
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
