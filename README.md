# WorkCore engineering CAD baseline

This repository converts the v30 and v37 WorkCore HTML concepts into a
parametric B-Rep CAD and system-engineering baseline. The generated STEP files
are intended for prototype engineering review and supplier discussion. They are
**not release-to-tool** drawings until the open assumptions, load cases,
tolerances, electrical architecture and safety analyses are signed off.

## Coordinate system

- Units: millimetres
- X: front/rear; negative X is the front/foot side
- Y: left/right; positive Y is the right side
- Z: height; Z=0 is the floor plane
- Assembly origin: floor projection of the chassis datum centre

## Build

```powershell
.\build.ps1 -Stage model
```

The wrapper requires Python 3.12, checks the CAD/runtime imports, rebuilds the
artifact set, then verifies its hashes and the requested gate. Use `-Stage evt0`,
`human`, `dvt`, `pvt` or `mp` only when intentionally testing that gate; a
non-zero result is expected while its evidence remains open.

Each build uses an empty `.build-staging/<run_id>/build` tree, so an old file
cannot satisfy a missing output. Publication is a journaled logical transaction:
the public status stays `PUBLISHING` while managed files are atomically replaced,
the manifest and hash-bound `COMPLETE` status are committed last, and a dead
publisher is rolled back before a later run proceeds. Unknown files under
`build/` are never deleted or packaged; the verifier reports them recursively.

Outputs are written to `build/`:

- `workcore_stowed.step` — transport configuration
- `workcore_follow_closed.step` — empty folded restricted-follow configuration with the restored v37 base sensor suite
- `workcore_obstacle_assist.step` — v37-derived rear pull handle extended with the unoccupied chassis pitched 8°
- `workcore_seat_ready.step` — occupied-ready seat and deployed footrest
- `workcore_cafe.step` — parked social configuration with one desk half deployed and the opposite side open
- `workcore_internal_layout.step` — shells removed for battery/data/compute/drawer review
- `workcore_transfer_ready.step` — right-side swing-away transfer configuration
- `workcore_desk.step` — forward-deploying dual-panel desk configuration with armrest lids closed
- `workcore_canopy_deployed.step` — canopy configuration
- `workcore_*.glb` — lightweight visual review models
- `workcore_desk_occupied_review.glb` — product plus clothed human keep-out model
- `workcore_e6_review.html` — single-file interactive four-state product and engineering review page
- `workcore_e4_review.html` — compatibility copy for existing bookmarks, presenting the same E6 review
- `workcore_e4_review_offline.html` — cache-busting, fully offline copy with embedded Three.js runtime
- `workcore_storage_review.glb` — dedicated shell-free equipment-bay review scene
- `workcore_storage_wheel_review.glb` — equipment-bay and wheel/suspension clearance context
- `workcore_electrical_thermal_review.glb` — electrical modules, PDU partitions, harness zones and heat-rejection context
- `parts/*.step` — supplier-facing individual solids
- `bom.csv` — material/process/mass estimate
- `production_bom.csv` — candidate configuration-union catalogue; not a released EBOM, purchasing list or unit-mass source
- `cots_interface_register.csv` — candidate supplier parts and controlled envelopes
- `tolerance_register.csv` — production-critical clearances and adjustment margins
- `validation.json` — geometry and clearance checks
- `engineering_report.json` — stability, wind, structure, actuator and load checks
- `mobility_report.json` — zero-turn, obstacle, access, elevator and trunk analysis
- `power_thermal_report.json` — traction/device power, energy, runtime, harness voltage-drop and airflow checks
- `production_readiness_report.json` — design-freeze evidence index, P0 gates and stage decisions
- `requirements_traceability.csv` — product, safety, usability and production requirements with evidence status
- `risk_register.csv` — system hazard register and required control verification
- `dvpr.csv` — EVT/DVT/PVT design-verification plan and acceptance intent
- `supplier_release_register.csv` — critical commodity selection and supplier-quality gates
- `production_gate_checklist.csv` — G0 through mass-production release checklist
- `access_scenarios.csv` — door and vehicle-template fit matrix
- `build_status.json` — generation state; interrupted/failed output is never packageable
- `release_manifest.json` — source/environment/artifact hashes, check split and stage decisions
- `preview_*.png` — rendered review images

## Engineering status

E6R2 is the current product-definition and CAD baseline. It restores the original
v37 folded follow-perception architecture as production-aware internal modules,
optical/RF/acoustic interfaces and real shell apertures. The user product has
four states: Follow, Ride, Café and Focus. Core width is now approximately
720 mm; the canopy is a detachable outdoor package; satellite communications
and onboard AC are removed; the four drawers are replaced by one 16-inch main
computer bay, one universal flat-device bay and an independent approximately
4.9 L daily-items caddy. E6R2 removes the false full-size travel cap so the
folded trapezoidal back itself becomes the weather cover, and turns the standard
right Café panel 90 degrees into a 430 x 270 mm transverse surface after the
drive pod is parked. Restricted following remains an empty, folded,
whitelisted-route Beta and is not a public-space autonomous-driving claim.

Revision E4 is a retained occupied-system geometry and safety input for East
Asian adults, not the current product baseline. E5 narrowed the launch market to
high-value knowledge workers in managed environments; its controlled B2B2C wedge
is retained by E6 while E5 product language remains design history. E4 adds closed armrest lids
in desk mode, a right swing-away transfer state, pelvic restraint, battery fire
isolation, 250 mm wheels, articulated side rockers, four-hub differential
zero-turn analysis, a 50 mm rated obstacle boundary, and door/elevator/vehicle
fit reports. Compact stow dimensions are recorded but do not override occupied
space or emergency egress.

E4-PWR1 adds a 51.2 V/30 Ah LiFePO4 design envelope, a 120 A continuous / 200 A
short-peak battery interface, separate traction and auxiliary contactors, dual
140 W USB-C PD, parked-only 600 W AC, a 90 W mast-device branch, zoned harness
routing and independent battery/electronics/laptop-bay thermal paths. All cell,
BMS, converter and fan part numbers remain supplier and prototype validation
gates.

E4-DFR1 adds physical package envelopes for the removable right-armrest drive control,
independent emergency stop, guarded charge/service-disconnect/manual-brake-release
interfaces, and an explicit production-readiness layer. The automated CAD checks
are intentionally reported separately from open regulatory, physical-test,
supplier and manufacturing gates.

E4-V37R restores three controlled features from the original v37 baseline:
the rear dual-tube obstacle-assist pull handle, the right-armrest removable
joystick/authorization pod, and the left-armrest status display plus 15 W Qi2
tray with FOD/temperature sensing. These are now CAD/BOM/validation items, not
render-only styling cues.

E5 is retained as design history but its managed-enterprise launch assumption is
superseded by E6. E5 had frozen the launch product thesis without replacing the E4 geometry baseline:
WorkCore is a personal embodied-AI work body for high-value knowledge work in
managed environments. The seat/chassis, hidden desk, asymmetric armrest HMI and
intelligence mast remain core; canopy, satellite communications, parked AC,
care claims and broad autonomy move to separately validated option packages.

The governing documents are:

- `docs/e6_product_definition_and_strategy.md` — current product constitution, four states, v37 follow-sensor restoration, storage decision, supply architecture and IP plan
- `docs/e6_launch_ecology_and_scenario_validation.md` — controlled launch wedge, real journeys, service/rescue model and pre-registered product evidence gates
- `docs/e6_object_character_and_mystery_brief.md` — new-object grammar, four-state expression, scenario behavior and falsifiable mystery/legibility gates
- `docs/configuration_control.md` — current-document precedence, evidence vocabulary and baseline rules
- `docs/configuration_mass_reconciliation.md` — pose-invariance audit, option deltas and EBOM identity closure criteria
- `docs/context_continuity_architecture.md` — measurable Context Continuity protocol, privacy boundary and EVT evidence plan
- `docs/e5_product_thesis_and_production_strategy.md` — frozen product thesis, launch scope, simplification rules, moat/IP plan and production convergence roadmap
- `docs/e4_product_definition.md` — target population, UX priorities and frozen E4 dimensions
- `docs/e4_p0_closure.md` — P0 design closures and mandatory physical release gates
- `docs/e4_access_transport_analysis.md` — elevator, shop, door and vehicle feasibility
- `docs/e4_internal_packaging_cmf.md` — laptop bay, internal modules, shells and finish maturity
- `docs/e4_power_energy_thermal_architecture.md` — complete power, energy, harness and thermal design envelope
- `docs/e4_design_freeze_readiness_review.md` — full industrial-design/NPD audit and production release sequence
- `docs/e3_human_centered_audit.md` — historical occupant-first audit and E3 findings
- `docs/v30_table_occupant_review.md` — coordinate-level review of the v30 desk
- `docs/e2_system_engineering.md` — historical E2 load boundary and prototype gates
- `docs/interface_control.md` — datums, supplier envelopes and rework controls
- `docs/safety_state_machine.md` — safe states and preliminary FMEA
- `docs/benchmark_matrix.md` — mature-product references and adoption limits

## Automated policy tests

```powershell
python -m unittest discover -s tests -v
```

These tests cover analytical units, quantity-aware mass, fail-safe motion
authority, Context Continuity privacy/safety policy, occurrence-identity rules,
controlled-overlap mutations, manifest integrity, concurrent publication,
failure rollback and dead-publisher recovery. They remain software and model
evidence only; they do not replace physical, supplier, regulatory or
manufacturing validation.
