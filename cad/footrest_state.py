"""Authoritative E6 footrest-pose contract.

The product mode and the A08 footrest pose are orthogonal.  The four primary
presentation states use the defaults below, while Cafe and Focus may request
the same physical assembly in ``DEPLOYED_LOCKED`` as a validation-only
substate.  Keeping this dependency-free prevents source CAD, Class-A skins,
human envelopes and release gates from each inventing their own state test.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class FootrestPose(str, Enum):
    STOWED = "stowed"
    DEPLOYED_LOCKED = "deployed_locked"


CONTRACT_VERSION: Final[str] = "E6-A08-POSE-1"

# ``desk`` is the controlled-source name for the user-facing Focus mode.
DEFAULT_FOOTREST_POSE: Final[dict[str, FootrestPose]] = {
    "stowed": FootrestPose.STOWED,
    "follow": FootrestPose.STOWED,
    "obstacle": FootrestPose.STOWED,
    "internal": FootrestPose.STOWED,
    "seat": FootrestPose.DEPLOYED_LOCKED,
    "ride": FootrestPose.DEPLOYED_LOCKED,
    "transfer": FootrestPose.DEPLOYED_LOCKED,
    "deployed": FootrestPose.DEPLOYED_LOCKED,
    "cafe": FootrestPose.STOWED,
    "desk": FootrestPose.STOWED,
    "focus": FootrestPose.STOWED,
}

OPTIONAL_DEPLOYMENT_MODES: Final[frozenset[str]] = frozenset(
    {"cafe", "desk", "focus"}
)


def normalise_footrest_pose(value: FootrestPose | str) -> FootrestPose:
    if isinstance(value, FootrestPose):
        return value
    # ``cad.build`` is also executable as a script and historically adds the
    # cad directory to ``sys.path``.  Accept an equivalent Enum loaded through
    # either module path instead of turning it into ``FootrestPose.X`` text.
    raw = getattr(value, "value", value)
    key = str(raw).strip().lower().replace("-", "_")
    aliases = {
        "closed": FootrestPose.STOWED,
        "retracted": FootrestPose.STOWED,
        "open": FootrestPose.DEPLOYED_LOCKED,
        "deployed": FootrestPose.DEPLOYED_LOCKED,
        "locked": FootrestPose.DEPLOYED_LOCKED,
    }
    if key in aliases:
        return aliases[key]
    try:
        return FootrestPose(key)
    except ValueError as exc:
        raise ValueError(
            f"Unknown A08 footrest pose {value!r}; expected "
            f"{[pose.value for pose in FootrestPose]}"
        ) from exc


def default_footrest_pose(configuration: str) -> FootrestPose:
    key = str(configuration).strip().lower().replace("-", "_")
    try:
        return DEFAULT_FOOTREST_POSE[key]
    except KeyError as exc:
        raise ValueError(
            f"No A08 footrest default for configuration {configuration!r}"
        ) from exc


def resolve_footrest_pose(
    configuration: str,
    requested: FootrestPose | str | None = None,
) -> FootrestPose:
    """Resolve a pose and reject unauthorised product-mode combinations."""

    key = str(configuration).strip().lower().replace("-", "_")
    default = default_footrest_pose(key)
    if requested is None:
        return default
    pose = normalise_footrest_pose(requested)
    if pose == default:
        return pose
    if key in OPTIONAL_DEPLOYMENT_MODES and pose == FootrestPose.DEPLOYED_LOCKED:
        return pose
    raise ValueError(
        f"A08 pose {pose.value!r} is not authorised for {configuration!r}; "
        f"default={default.value!r}, optional deployment is limited to Cafe/Focus"
    )


def optional_footrest_open_available(configuration: str) -> bool:
    key = str(configuration).strip().lower().replace("-", "_")
    # Validate unknown modes instead of silently returning False.
    default_footrest_pose(key)
    return key in OPTIONAL_DEPLOYMENT_MODES


__all__ = [
    "CONTRACT_VERSION",
    "DEFAULT_FOOTREST_POSE",
    "FootrestPose",
    "OPTIONAL_DEPLOYMENT_MODES",
    "default_footrest_pose",
    "normalise_footrest_pose",
    "optional_footrest_open_available",
    "resolve_footrest_pose",
]
