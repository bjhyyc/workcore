# WorkCore configuration-control index

Status: E6R2 working design-history index. This file identifies which inputs are current and which files are historical. It does not close `G-006`: the workspace still needs an immutable source-control baseline, change authority, approvals, deviation control and a released document-management process.

## 1. Current baseline and precedence

| Layer | Current authority | Precedence rule |
|---|---|---|
| Product north star and four-state constitution | `docs/e6_product_definition_and_strategy.md` | Governs product meaning and core/option boundaries; does not override a safety restriction |
| Launch niche, ODD and scenario evidence | `docs/e6_launch_ecology_and_scenario_validation.md` | Governs the first controlled deployment wedge; narrower than the long-term E6 vision |
| Safety states and preliminary hazards | `docs/safety_state_machine.md` | A restrictive safety condition wins over a marketing or experience statement |
| Geometry and numerical design inputs | `cad/parameters.py` and current `cad/*.py` | Generated JSON/CSV is evidence of the exact code run; prose numbers are explanatory only |
| Pose identity and mass reconciliation | `docs/configuration_mass_reconciliation.md` | Any unresolved pose-dependent mass or same-name definition conflict blocks a base-SKU mass claim |
| Structural datums and interfaces | `docs/interface_control.md` plus `build/cots_interface_register.csv` | Supplier drawings and signed ICDs must eventually supersede provisional envelopes |
| Verification and production evidence | `build/production_readiness_report.json`, `build/requirements_traceability.csv`, `build/risk_register.csv`, `build/dvpr.csv` | An unexecuted plan or nominal calculation cannot be promoted to physical evidence |
| Build provenance | `build/release_manifest.json` for preserved E6-DFR3 trace inputs; `design/e6_final_exterior/step_anchored_v2/class_a_cad/controlled_source_e6_dfr4/e6_dfr4_a08_manifest.json` for the E6-DFR4-A08 primary exterior underlay | Only files whose hashes appear in the matching revision manifest belong to that generated baseline; the manifests are not interchangeable |

If two current sources disagree, the product is not allowed to choose the more convenient claim. Record an issue, apply the safer/narrower boundary, and resolve it through an approved change before release.

## 2. Revision families

| Family | Status | Permitted use |
|---|---|---|
| E6R2 / E6-DFR4-A08 | Current working exterior-source correction | Four primary exterior underlays plus Café/Focus optional-open validation states; engineering review only, not production release |
| E6R2 / E6-DFR3 | Preserved predecessor and auxiliary trace input | Historical comparison and unchanged auxiliary interfaces only; it is not the current four-state A08 publication baseline |
| E5 | Superseded product thesis; retained design history | Rationale, launch-wedge and moat history; not current geometry |
| E4 | Inherited occupied geometry, power and interface history | Input provenance only where E6 explicitly retains it; stale counts and masses are not current |
| E3/E2/E0 and v30/v37 | Historical concepts and rejected/learned alternatives | Design-history evidence only; never a release source |

All historical documents should be read as snapshots even where their original prose says “current”. The current generated report and this index take precedence for status and counts.

## 3. Evidence vocabulary

| Term | Meaning |
|---|---|
| `PASS` for an automated check | The encoded nominal rule passed for the generated model |
| `analysis_complete` | A calculation or model has been reviewed as an input; supplier, tolerance and physical evidence may remain open |
| `partial` | Some traceable input exists, but the gate's complete exit criterion is not met |
| `closed` | The controlled deliverable, objective evidence, required reviews and approval signatures all exist for the defined scope |
| `NO-GO` | The next stage is prohibited until the named prerequisites close |

The count of automated checks must always be split into solid-validity checks and semantic/analytical checks. Neither category is a substitute for tolerance analysis, physical tests, regulatory review, supplier release or manufacturing capability.

## 4. Baseline rules

1. A release candidate must reference one product revision, one CAD/code commit, one EBOM revision, one firmware/software set, one risk file, one DVP&R revision and one approved intended-use/ODD statement.
2. Part identity is pose-independent. Stowed, open, rotated or extended geometry is an occurrence transform, not a new procurement item. Options and left/right variants require explicit effectivity.
3. EBOM, MBOM, service BOM and visualization-state parts are separate structures. The current `production_bom.csv` remains a generated union/canonicalization aid until a pose-invariant EBOM reconciliation passes; it must not be used alone for purchasing, cost or unit mass.
4. `build_status.json` distinguishes generation from publication and from a product release decision. Each run generates into an empty `.build-staging/<run_id>/build`, validates the complete expected artifact set, binds it to a manifest, then publishes under an exclusive lock. Public status is `PUBLISHING` throughout the multi-file transaction; the manifest is committed immediately before the hash-bound `COMPLETE` status. A write-ahead journal and rollback copies recover an interrupted publisher, and the verifier double-reads status to reject a concurrent switch. This logical transaction does not make the product releasable: the requested stage gate must still pass.
5. Requirements, hazards, controls, design outputs, tests, reports, deviations and gates use stable IDs and explicit links. Free-text similarity is not traceability.
6. A result is not current merely because a file exists in `build/`. Package and review only artifacts listed in the matching `release_manifest.json`. Unknown or retired files are preserved to avoid destroying user data, recursively reported as unmanaged, and excluded from the release package.
7. Any change to a safety limit, structural hardpoint, supplier envelope, material, firmware, calibration, privacy behavior, ODD or public claim triggers impact analysis and regression selection.
8. A failed or conditional test remains failed/conditional. Waivers require scope, rationale, risk review, expiry, approver and affected serial/configuration range.

## 5. Current configuration-control blockers

- The Git branch has no initial immutable commit, so generated artifacts cannot yet be tied to a released source revision.
- Owners, approvers and signed evidence are missing from the development gates.
- The A08 footrest pose identity is reconciled in E6-DFR4-A08, but the remaining physical product BOM still contains other pose-state identity ambiguity and option mixing.
- E6 Core, Outdoor Pack, Dock, mirrored Café and any later care/accessibility package do not yet have independent effectivity and safety cases.
- No physical EVT, DVT or PVT report is registered; all such claims remain open.

These are release blockers, not documentation polish items.
