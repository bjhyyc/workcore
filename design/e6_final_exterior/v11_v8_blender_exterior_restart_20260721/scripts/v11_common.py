"""Shared contracts for the isolated WorkCore E6 V11 Blender restart."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
V11_ROOT = SCRIPT_DIR.parent
WORKSPACE = SCRIPT_DIR.parents[3]
CONFIG_PATH = V11_ROOT / "config" / "v8_locked_sources.json"
STATES = ("follow", "ride", "cafe", "focus")
PIPELINE_ID = "WORKCORE_E6_V11_V8_RESTART"

REFERENCE_BLEND = V11_ROOT / "blender" / "e6_v11_v8_locked_reference_master.blend"
REFERENCE_REPORT = V11_ROOT / "qa" / "v11_v8_locked_reference_report.json"
GEOMETRY_REPORT = V11_ROOT / "qa" / "v11_v8_geometry_inventory.json"
REFERENCE_LIBRARY_ROOT = V11_ROOT / "libraries" / "v8_clean_references"
STATE_BLEND_ROOT = V11_ROOT / "blender" / "states"
PREVIEW_ROOT = V11_ROOT / "renders" / "preview"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object: {path}")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def config() -> dict[str, Any]:
    payload = read_json(CONFIG_PATH)
    if payload.get("status") != "LOCKED_V8_REFERENCE_ONLY":
        raise RuntimeError(f"Unexpected V8 lock status: {CONFIG_PATH}")
    return payload


def validate_state(state: str) -> str:
    value = str(state).strip().lower()
    if value not in STATES:
        raise ValueError(f"Unsupported state {state!r}; expected {STATES}")
    return value


def validate_source(state: str) -> tuple[Path, str]:
    state = validate_state(state)
    entry = config()["states"][state]
    path = WORKSPACE / str(entry["clean_glb"])
    if not path.is_file():
        raise FileNotFoundError(path)
    actual_hash = sha256(path)
    actual_bytes = path.stat().st_size
    if actual_bytes != int(entry["bytes"]) or actual_hash != str(entry["sha256"]):
        raise RuntimeError(
            f"{state}: immutable V8 GLB drifted; bytes={actual_bytes}/{entry['bytes']} "
            f"sha256={actual_hash}/{entry['sha256']}"
        )
    return path, actual_hash


def reference_library_path(state: str) -> Path:
    return REFERENCE_LIBRARY_ROOT / f"workcore_e6_v11_v8_{validate_state(state)}_reference.blend"


def reference_library_report_path(state: str) -> Path:
    return V11_ROOT / "qa" / f"v11_v8_{validate_state(state)}_reference_library.json"


def state_blend_path(state: str, revision: str = "r01") -> Path:
    return STATE_BLEND_ROOT / revision / f"workcore_e6_v11_{validate_state(state)}_{revision}.blend"


LOCKED_EXACT = {
    "A05_right_joystick",
    "A05_right_authorisation_key",
    "A05_left_status_display_window",
    "A05_left_mechanical_emergency_stop",
    "A05_follow_external_mechanical_emergency_stop",
    "A05_follow_neutral_status_witness",
}

FUNCTION_PREFIXES = ("A06_", "A07_", "A08_", "A09_")
FUNCTION_TOKENS = (
    "seat_cushion_contact_island",
    "armrest_touch_lid",
    "armrest_top_lid_hinge_reveal",
    "armrest_top_lid_release",
    "right_removable_drive_pod",
    "left_hmi_precision_bezel",
    "left_qi_",
    "emergency_stop_guard",
    "rear_service_",
    "rear_flush_service_door_skin",
)


def reference_role(original_name: str) -> str:
    if original_name.startswith("source_tyre_") or original_name in LOCKED_EXACT:
        return "LOCKED_HARDPOINT"
    if original_name.startswith(FUNCTION_PREFIXES) or any(
        token in original_name for token in FUNCTION_TOKENS
    ):
        return "FUNCTIONAL_REFERENCE"
    return "REPLACEABLE_V8_SKIN_REFERENCE"
