# WorkCore E6 configuration-mass reconciliation

Status: P0 configuration-control finding. These values are analytical CAD mass estimates, not measured hardware, a released EBOM or a customer specification. The former E6-DFR4 six-occurrence A08 abstraction has been superseded by the E6-DFR5 captured-drawer/over-centre-link production-intent inventory. The new geometry can close pose identity only after its executable gates pass; it reopens A08 mass and EBOM reconciliation.

## Finding

The same base product cannot gain mass merely by changing pose. The legacy E6R2 analytical configurations below do, so no single mass may be released for the base SKU from that table.

| Configuration | Legacy E6R2 analytical product mass (kg) | Delta from stowed (kg) | Interpretation |
|---|---:|---:|---|
| Stowed / restricted Follow | 114.1069 | 0.0000 | Legacy transport-model estimate only |
| Obstacle-assist | 114.6871 | 0.5802 | Telescopic handle still changes physical representation |
| Ride / seat / transfer hardware closed | 115.9876 | 1.8807 | Physical occurrences remain missing or replaced across poses |
| Café | 119.3175 | 5.2106 | Dedicated transverse linkage and deployed desk geometry are not yet represented in every pose |
| Focus / desk | 119.6816 | 5.5747 | Largest legacy core four-state inconsistency |
| Outdoor deployed | 123.1972 | 9.0903 | Mixes a true option with pose inconsistencies |

The `internal` configuration is an exploded/shell-hidden review scene and is excluded from pose-mass comparison. The generated `production_bom.csv` is a candidate union catalogue; its union mass is not a product mass.

## Known reconciliation defects

- **Superseded A08 baseline:** the old six-occurrence, `1.890987 kg` DFR4 abstraction is not a valid mass claim for the current mechanism. E6-DFR5 now carries one 47-occurrence production-intent B-Rep inventory through every pose and primary state, including fixed guides, captured rails, four links, bearings, guarded pins, endpoint locks, synchroniser, counterbalance, manual release and two-channel foot-zone hardware. Follow/Café/Focus default to `STOWED`; Ride defaults to `DEPLOYED_LOCKED`; Café/Focus may enter an explicitly requested optional `DEPLOYED_LOCKED` substate. The 47 identities and rigid transforms are executable geometry gates; material assignments, fasteners, harness, supplier parts and measured assembly mass remain open.
- The obstacle handle changes by about 0.5802kg between folded and extended representations.
- The transfer hinge/link/shrouds and joystick/authorization hardware are now instantiated in every user configuration with controlled occurrence IDs. This removed false pose deltas without claiming EBOM closure.
- Approximately 0.4600kg of travel seals still appears only in closed poses; attachment ownership and open-pose transforms remain unresolved.
- The former same-name `desk_yoke_right` collision is separated into Focus and Café linkage occurrences, so supplier STEP export can no longer silently overwrite one definition with the other. Their presence across all base poses is still unresolved and remains visible in the occurrence-set delta.
- The outdoor canopy is a legitimate option delta of approximately 7.0096kg. Creator fill lights are a separate approximately 0.2000kg option. Both require explicit option effectivity and must not appear or disappear because of pose.

## Required data model

Every physical occurrence needs a stable `physical_occurrence_id`, part number, revision, quantity and option/effectivity code. Pose changes only its transform. A replacement geometry for the same occurrence must either preserve the controlled mass/identity or advance the part revision through change control. Names and regular-expression canonicalization are not identity. The current generated report measures controlled-ID coverage and lists added/missing occurrence IDs for every base pose; incomplete coverage is itself a release failure.

The released structure must separate:

- base-SKU EBOM and measured/estimated unit mass;
- option deltas such as `OPT-CANOPY` and `OPT-CREATOR-LIGHTS`;
- pose transforms;
- validation envelopes and human/equipment keep-outs;
- MBOM consumables, service parts and shipping materials.

## Closure criteria

1. For each base-SKU pose, the set of physical occurrence IDs and quantities is identical.
2. Base-SKU pose mass spread is no more than 0.001kg after deterministic rounding.
3. Same-ID definitions match controlled mass, material, volume/bounding-box or geometry hash, supplier part and revision; any mismatch fails the build.
4. Each option is tested both installed and absent; its mass delta is pose-invariant and agrees with the option EBOM.
5. CAD estimate, released EBOM roll-up and first-article measured mass have an approved reconciliation with uncertainty and deviation disposition.
6. Only after these conditions close may product, transport, stability, power/runtime or cost reports use a frozen base-SKU mass.

For A08 specifically, E6-DFR5 requires the same 47 production-intent occurrence identities and rigid B-Reps in `STOWED` and `DEPLOYED_LOCKED`; only their allowed transforms and lock-pin engagement state may change. This closes neither a 47-line EBOM nor assembly mass: both remain P0 until every occurrence has controlled material, supplier/part revision, fasteners and harness, followed by CAD roll-up and first-article reconciliation.
