"""Generated embedded Rulespec dependency pin. Do not edit by hand."""

from __future__ import annotations

import base64
import json
from typing import Any

RULESPEC_DEPENDENCY_SHA256 = "sha256:e1c797e4a49651269ac404aad16c47b00fa5852d137bb80a2d9a389ba4c25c76"

_ENCODED_RULESPEC_DEPENDENCY = (
    "ewogICJzY2hlbWFWZXJzaW9uIjogIjEuMCIsCiAgInJ1bGVzcGVjVmVyc2lvbiI6ICIwLjIuMC1wcmUuMTgiLAogICJyZWxlYXNl"
    "QXZhaWxhYmlsaXR5IjogImxvY2FsVW5wdWJsaXNoZWQiLAogICJwcm9kdWN0aW9uQ29uZm9ybWFuY2VFbGlnaWJsZSI6IGZhbHNl"
    "LAogICJjb25zdHJhaW50RGlnZXN0U2NvcGUiOiAiZ2xvYmFsUnVsZXNwZWNDb250cmFjdCIsCiAgImFkb3B0ZWRDb25zdHJhaW50"
    "U291cmNlcyI6IFsKICAgICJjb25zdHJhaW50cy9hbmFseXNpcyIsCiAgICAiY29uc3RyYWludHMvY29yZSIsCiAgICAiY29uc3Ry"
    "YWludHMvcHJvZmlsZXMvcmVmc3BlYy9vcGVuLWxhYmVsLmN1ZSIKICBdLAogICJ2YWxpZGF0b3IiOiB7CiAgICAiaWRlbnRpdHki"
    "OiAicmthZi12YWxpZGF0ZUAwLjIuMC1wcmUuMTggKyB0b29scy9jaV92YWxpZGF0ZS5weSArIHJrYWYtYmVoYXZpb3ItdmFsaWRh"
    "dGVAMC4yLjAtcHJlLjE4IiwKICAgICJzb3VyY2VSZXZpc2lvbiI6ICJhNTE5ZDA2YjJjODkzMTk2NWI0Y2VkYTk0NjkyYTk2ZmU4"
    "YjViNzFlIiwKICAgICJjb21wbGV0ZUdhdGVDb21tYW5kIjogIm1ha2UgdGVzdCIsCiAgICAiY2xhaW1lZExldmVscyI6IFsKICAg"
    "ICAgIkwxIiwKICAgICAgIkwyIiwKICAgICAgIkwzIiwKICAgICAgIkw0IgogICAgXSwKICAgICJzZWxmQ2VydGlmaWNhdGlvblBh"
    "dGgiOiAiY29uZm9ybWFuY2UvcGFydG5lcnMvcnVsZXNwZWMtcmVmZXJlbmNlLnlhbWwiLAogICAgInNlbGZDZXJ0aWZpY2F0aW9u"
    "U2hhMjU2IjogIjNlZTNlZDRiNjdmYTg3YmNkYjA3ZmM3YTAyNzdiNmM4YTU0ZGQzNDc3YmU4OWY0ZDc3NjUyYzhjM2Y3MGE3MTAi"
    "CiAgfQp9Cg=="
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
