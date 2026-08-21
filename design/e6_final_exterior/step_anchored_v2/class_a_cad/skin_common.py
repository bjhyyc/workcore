"""Shared primitives for the independent WorkCore E6 exterior-skin study.

This module intentionally has no dependency on ``cad.build`` and never writes to
``build/``.  Coordinates follow the controlled E6 convention: -X front, +X
rear, +Y right, -Y left, +Z up; all dimensions are millimetres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import cadquery as cq


Color = tuple[float, float, float, float]


LUNAR_STONE: Color = (0.58, 0.55, 0.50, 1.0)
GRAPHITE_BROWN: Color = (0.10, 0.09, 0.08, 1.0)
SMOKED_UMBER: Color = (0.12, 0.09, 0.07, 0.88)
CHAMPAGNE: Color = (0.55, 0.49, 0.39, 1.0)
CHARCOAL_KNIT: Color = (0.12, 0.115, 0.105, 1.0)
ESPRESSO: Color = (0.20, 0.15, 0.12, 1.0)
SATIN_STAINLESS: Color = (0.54, 0.53, 0.50, 1.0)
SMOKED_WALNUT: Color = (0.255, 0.155, 0.095, 1.0)
OXBLOOD_LEATHER: Color = (0.17, 0.075, 0.055, 1.0)
TPE_DARK: Color = (0.055, 0.05, 0.045, 1.0)
SAFETY_RED: Color = (0.72, 0.035, 0.025, 1.0)


@dataclass(frozen=True)
class SkinPart:
    """One independently serviceable exterior-study solid."""

    name: str
    shape: cq.Shape
    color: Color
    material: str
    module: str
    configuration: str
    intent: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def bounds(self) -> dict[str, float]:
        box = self.shape.BoundingBox()
        return {
            "xmin": box.xmin,
            "xmax": box.xmax,
            "ymin": box.ymin,
            "ymax": box.ymax,
            "zmin": box.zmin,
            "zmax": box.zmax,
            "xlen": box.xlen,
            "ylen": box.ylen,
            "zlen": box.zlen,
        }


def _shape(value: cq.Workplane | cq.Shape) -> cq.Shape:
    if isinstance(value, cq.Shape):
        return value
    found = value.val()
    if not isinstance(found, cq.Shape):
        raise TypeError(f"Expected a CadQuery shape, received {type(found)!r}")
    return found


def rounded_box(
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    radius: float,
    *,
    fillet_all: bool = True,
) -> cq.Shape:
    """Return a centred closed rounded box, reducing radius if OCC rejects it."""

    sx, sy, sz = size
    if min(sx, sy, sz) <= 0:
        raise ValueError(f"Invalid box size: {size}")
    body = cq.Workplane("XY").box(sx, sy, sz)
    selectors = body.edges() if fillet_all else body.edges("|Z")
    safe = min(radius, min(sx, sy, sz) * 0.45)
    for candidate in (safe, safe * 0.75, safe * 0.5, safe * 0.25, 0.0):
        try:
            result = body if candidate <= 0 else selectors.fillet(candidate)
            return _shape(result.translate(center))
        except Exception:
            continue
    raise RuntimeError(f"Unable to build rounded box {size} at {center}")


def rounded_rect_prism(
    size_xy: tuple[float, float],
    height: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    """A 2.5D rounded rectangle with flat top/bottom for clean panel interfaces."""

    sx, sy = size_xy
    body = cq.Workplane("XY").box(sx, sy, height).edges("|Z")
    safe = min(radius, sx * 0.45, sy * 0.45)
    result = body if safe <= 0 else body.fillet(safe)
    return _shape(result.translate(center))


def rounded_frame(
    outer_xy: tuple[float, float],
    inner_xy: tuple[float, float],
    height: float,
    center: tuple[float, float, float],
    radius: float,
) -> cq.Shape:
    """Closed U/O-frame proxy formed by subtracting an inner rounded prism."""

    outer = rounded_rect_prism(outer_xy, height, center, radius)
    inner = rounded_rect_prism(
        inner_xy,
        height + 4.0,
        center,
        max(1.0, radius * 0.6),
    )
    return outer.cut(inner)


def tapered_loft(
    lower_xy: tuple[float, float],
    upper_xy: tuple[float, float],
    z0: float,
    z1: float,
    center_xy: tuple[float, float],
) -> cq.Shape:
    """Simple closed tapered solid used for back/mast cosmetic envelopes."""

    cx, cy = center_xy
    wp = (
        cq.Workplane("XY", origin=(cx, cy, z0))
        .rect(*lower_xy)
        .workplane(offset=z1 - z0)
        .rect(*upper_xy)
        .loft(combine=True)
    )
    return _shape(wp)


def cut_many(base: cq.Shape, cutters: Iterable[cq.Shape]) -> cq.Shape:
    result = base
    for cutter in cutters:
        result = result.cut(cutter)
    return result


def union_many(shapes: Iterable[cq.Shape]) -> cq.Shape:
    values = list(shapes)
    if not values:
        raise ValueError("union_many requires at least one shape")
    result = values[0]
    for item in values[1:]:
        result = result.fuse(item)
    return result


def validate_parts(parts: Iterable[SkinPart]) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    for part in parts:
        if part.name in names:
            errors.append(f"duplicate name: {part.name}")
        names.add(part.name)
        if part.shape.isNull():
            errors.append(f"null shape: {part.name}")
        elif not part.shape.isValid():
            errors.append(f"invalid shape: {part.name}")
        elif part.shape.Volume() <= 0:
            errors.append(f"non-positive volume: {part.name}")
    return errors


def export_parts(parts: Iterable[SkinPart], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for part in parts:
        cq.exporters.export(part.shape, str(directory / f"{part.name}.step"))
