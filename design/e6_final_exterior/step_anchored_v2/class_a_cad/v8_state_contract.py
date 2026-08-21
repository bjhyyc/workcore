"""Authoritative primary-state semantics for the WorkCore E6 V8 candidate.

The four release renders are primary states, not an exhaustive list of every
user-selectable substate.  In particular, Cafe and Focus default to a stowed
footrest so the occupant can place both feet on the floor; the same physical
footrest may still be deployed on request as an optional substate.  Keeping
that distinction in one dependency-free module prevents geometry, ledgers,
validators and render inventory from silently drifting apart.
"""

from __future__ import annotations

from typing import Final

from cad.footrest_state import (
    CONTRACT_VERSION as FOOTREST_CONTRACT_VERSION,
    FootrestPose,
    default_footrest_pose,
    optional_footrest_open_available as _source_optional_open,
)


PRIMARY_STATES: Final[tuple[str, ...]] = ("follow", "ride", "cafe", "focus")

STATE_ALIASES: Final[dict[str, str]] = {
    "follow": "follow",
    "follow_closed": "follow",
    "follow-closed": "follow",
    "obstacle": "follow",
    "ride": "ride",
    "seat": "ride",
    "seat_ready": "ride",
    "seat-ready": "ride",
    "transfer": "ride",
    "cafe": "cafe",
    "café": "cafe",
    "focus": "focus",
    "desk": "focus",
    "deployed_desk": "focus",
}

SOURCE_CONFIGURATION: Final[dict[str, str]] = {
    "follow": "follow",
    "ride": "seat",
    "cafe": "cafe",
    "focus": "desk",
}

DEFAULT_FOOTREST_STATE: Final[dict[str, str]] = {
    state: default_footrest_pose(source).value
    for state, source in SOURCE_CONFIGURATION.items()
}

OPTIONAL_FOOTREST_OPEN_STATES: Final[frozenset[str]] = frozenset(
    {"cafe", "focus"}
)


def canonical_v8_state(value: str) -> str:
    """Return one canonical primary state or raise on an unknown label."""

    key = str(value).strip().lower()
    try:
        return STATE_ALIASES[key]
    except KeyError as exc:
        raise ValueError(
            f"Unknown WorkCore E6 V8 state {value!r}; expected one of "
            f"{sorted(STATE_ALIASES)}"
        ) from exc


def default_footrest_is_deployed(state: str) -> bool:
    """Whether the four-state release presentation deploys the footrest."""

    canonical = canonical_v8_state(state)
    return DEFAULT_FOOTREST_STATE[canonical] == FootrestPose.DEPLOYED_LOCKED.value


def optional_footrest_open_available(state: str) -> bool:
    """Whether a non-primary, user-selected footrest-open substate is valid."""

    canonical = canonical_v8_state(state)
    return _source_optional_open(SOURCE_CONFIGURATION[canonical])


def footrest_state_evidence(state: str) -> dict[str, object]:
    """Serializable evidence used by manifests, gates and per-part metadata."""

    canonical = canonical_v8_state(state)
    return {
        "primary_state": canonical,
        "footrest_pose": DEFAULT_FOOTREST_STATE[canonical],
        "default_footrest_state": DEFAULT_FOOTREST_STATE[canonical],
        "optional_footrest_open_available": (
            canonical in OPTIONAL_FOOTREST_OPEN_STATES
        ),
        "optional_substate_in_primary_render_set": False,
        "footrest_contract_version": FOOTREST_CONTRACT_VERSION,
        "physical_assembly_id": "WC-A08",
    }


__all__ = [
    "DEFAULT_FOOTREST_STATE",
    "FOOTREST_CONTRACT_VERSION",
    "OPTIONAL_FOOTREST_OPEN_STATES",
    "PRIMARY_STATES",
    "STATE_ALIASES",
    "SOURCE_CONFIGURATION",
    "canonical_v8_state",
    "default_footrest_is_deployed",
    "footrest_state_evidence",
    "optional_footrest_open_available",
]
