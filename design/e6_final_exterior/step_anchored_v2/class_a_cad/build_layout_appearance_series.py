"""Compatibility entry point for the final WorkCore V8 render series.

The former implementation retained all four CAD states in one process and,
more importantly, mislabeled an authored-skin-only STEP as ``layout_full``.
There must be only one release implementation for this safety-critical export.
The crash-bounded builder now owns the canonical workflow: one state per child,
the complete hash-pinned DFR5 internal assembly in every full-layout STEP, an
independent fresh-process STEP re-import gate, eight GLBs and 32 renders.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from build_layout_appearance_series_low_memory import main as _bounded_main


DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent
    / "final_product_v8_layout_appearance_20260718_r2"
)


def main(output: Path = DEFAULT_OUTPUT) -> None:
    """Run the single crash-bounded, full-internal-layout release pipeline."""

    _bounded_main(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Build the WorkCore E6 V8 four-state full-layout and exterior "
            "release through the bounded canonical pipeline."
        )
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    main(arguments.output)
