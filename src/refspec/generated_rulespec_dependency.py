"""Generated embedded Rulespec dependency pin. Do not edit by hand."""

from __future__ import annotations

import base64
import json
from typing import Any

RULESPEC_DEPENDENCY_SHA256 = "sha256:6e3e7b2fff7fb3c99d3498c23ace9301d3a17b3228567549692eb6a58b07d8bf"

_ENCODED_RULESPEC_DEPENDENCY = (
    "ewogICJzY2hlbWFWZXJzaW9uIjogIjEuMCIsCiAgInJ1bGVzcGVjVmVyc2lvbiI6ICIwLjIuMC1wcmUuOSIsCiAgInJlbGVhc2VB"
    "dmFpbGFiaWxpdHkiOiAibG9jYWxVbnB1Ymxpc2hlZCIsCiAgInByb2R1Y3Rpb25Db25mb3JtYW5jZUVsaWdpYmxlIjogZmFsc2Us"
    "CiAgImNvbnN0cmFpbnREaWdlc3RTY29wZSI6ICJnbG9iYWxSdWxlc3BlY0NvbnRyYWN0IiwKICAiYWRvcHRlZENvbnN0cmFpbnRT"
    "b3VyY2VzIjogWwogICAgImNvbnN0cmFpbnRzL2NvcmUiLAogICAgImNvbnN0cmFpbnRzL3Byb2ZpbGVzL3JlZnNwZWMvb3Blbi1s"
    "YWJlbC5jdWUiCiAgXSwKICAidmFsaWRhdG9yIjogewogICAgImlkZW50aXR5IjogInJrYWYtdmFsaWRhdGVAMC4yLjAtcHJlLjkg"
    "KyB0b29scy9jaV92YWxpZGF0ZS5weSArIHJrYWYtYmVoYXZpb3ItdmFsaWRhdGVAMC4yLjAtcHJlLjkiLAogICAgInNvdXJjZVJl"
    "dmlzaW9uIjogIjc5MTY3MGU3YzVlYzRjYmNkMzZjZDljZDdlZmQ0Y2UwMTQzYmMwOTQiLAogICAgImNvbXBsZXRlR2F0ZUNvbW1h"
    "bmQiOiAibWFrZSB0ZXN0IiwKICAgICJjbGFpbWVkTGV2ZWxzIjogWwogICAgICAiTDEiLAogICAgICAiTDIiLAogICAgICAiTDMi"
    "LAogICAgICAiTDQiCiAgICBdLAogICAgInNlbGZDZXJ0aWZpY2F0aW9uUGF0aCI6ICJjb25mb3JtYW5jZS9wYXJ0bmVycy9ydWxl"
    "c3BlYy1yZWZlcmVuY2UueWFtbCIsCiAgICAic2VsZkNlcnRpZmljYXRpb25TaGEyNTYiOiAiM2VlM2VkNGI2N2ZhODdiY2RiMDdm"
    "YzdhMDI3N2I2YzhhNTRkZDM0NzdiZTg5ZjRkNzc2NTJjOGMzZjcwYTcxMCIKICB9Cn0K"
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
