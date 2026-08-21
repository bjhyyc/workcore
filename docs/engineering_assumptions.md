# WorkCore E0 engineering assumptions and gates

## Status vocabulary

- **Fixed**: inherited directly from the v30 concept or selected as the E0 datum.
- **Provisional**: adequate for packaging CAD but must be confirmed before detail design.
- **Gate**: missing information that prevents production release.

## Fixed E0 geometry

| Item | Value |
|---|---:|
| Overall body envelope | 810 x 680 mm |
| Wheel diameter / tread width | 180 / 58 mm |
| Wheel centre height | 90 mm |
| Main canopy projection | 800 mm |
| Main canopy width | 380 mm |
| Deployed canopy width | 620 mm |
| Canopy roller tube OD | 40 mm |
| Canopy deployed mast stroke | 480 mm |

The lower structural enclosure is narrowed to 552 mm in E0.1.  This preserves at
least 8 mm tyre-to-structure running clearance while the cosmetic upper deck retains
the 680 mm visual envelope.

## Provisional manufacturing architecture

| Subsystem | E0 material/process | Notes |
|---|---|---|
| Chassis | 6061-T6 rectangular tube, welded then finish-machined | 40 x 40 x 3 mm members |
| Lower body | 5052-H32 folded/welded aluminium enclosure | Packaging solid only in E0 |
| Upper deck/body panels | PC-ABS or thermoformed composite panels | Split lines and draft not designed |
| Seat/back structure | 6061-T6 frame with replaceable upholstery carrier | Foam and textile represented as envelopes |
| Mast | 6061-T6 nested rectangular extrusion | Bearing pads and anti-rotation key not designed |
| Canopy arms/front rail | 6061-T6 extrusion | Wind load and joint pins are gates |
| Canopy fabric | PU-coated polyester, 0.8 mm CAD thickness | Pattern, seams and prestress are gates |
| Wheel hubs/axles | 6061-T6 hub, stainless axle | Bearings and drive torque are gates |

## E0 clearance rules

- 0.5 mm per side: CNC-machined static fit.
- 1.0 mm per side: aligned telescoping members with bearing pads.
- 1.5 mm per side: formed or moulded adjacent panels.
- 3.0 mm minimum: exposed moving mechanism under controlled alignment.
- 8.0 mm minimum: wheel-to-fixed-body running clearance.
- 12.0 mm minimum: pinch-zone design target where fingers can enter; guarding is still required.

## Human-factors verification baseline

E0 uses an adjustable-user target rather than treating the v30 visual dimensions as sacred.
The current CAD moves the compressed seat top to 550 mm, uses a 430 mm usable seat
depth and 560 mm seat width, and raises the armrest top to 735 mm.  These values are
checked automatically against the published OSHA workstation ranges.  The fixed high
seat remains near the top of the OSHA range because the 180 mm mobility wheels package
under the body; a stable footrest is therefore a required system component, not an
optional accessory.

- Seat top target: 381-559 mm (15-22 in).
- Usable seat depth target: 381-432 mm (15-17 in).
- Seat width: at least 457 mm (18 in).
- Armrest top above compressed seat: 178-267 mm (7-10.5 in).
- Seated keyboard/work surface adjustment target: 559-762 mm (22-30 in).
- User controls: one-hand operation without tight grasp/pinch/twist; design operating
  force no more than 22.2 N (5 lbf) where accessibility is in scope.
- Leg clearance target near the user: at least 520 mm wide and 440 mm deep at knee
  level; table packaging must demonstrate this in E1.

Sources: [OSHA workstation purchasing guide](https://www.osha.gov/etools/computer-workstations/checklists/purchasing-guide),
[OSHA workspace clearance guidance](https://www.osha.gov/etools/computer-workstations/components/work-space),
and [U.S. Access Board operable-parts guidance](https://www.access-board.gov/ada/guides/chapter-3-operable-parts/).

## Tolerance and rework strategy

1. Use the chassis top plane as datum A, the longitudinal centre plane as datum B, and
   the rear crossmember machined face as datum C.  Modules locate to A|B|C; cosmetic
   skins never establish mechanism position.
2. Put slots in replaceable brackets, not in the welded frame.  After welding, machine
   the wheel/hinge/mast interfaces in one setup or use a dowelled fixture.
3. Use two round pins plus one relieved/diamond pin pattern for removable modules so
   location is deterministic without over-constraint.
4. Tolerance critical gaps from process capability: CNC interfaces ±0.10 mm, laser-cut
   features ±0.20 mm, formed panel interface features ±0.50 mm provisional.  Do not
   combine worst-case cosmetic tolerances into kinematic loops.
5. Use vendor CAD envelopes and hole patterns for purchased slides, hinges, actuators,
   bearings and latches.  Never dimension production brackets from a rendered mesh.
6. Add go/no-go gauges for mast tube fit, wheel alignment, drawer parallelism and latch
   engagement.  Every adjustment must have a measurable nominal and bounded range.
7. Freeze interface-control drawings before cosmetic surfacing so industrial-design
   changes cannot silently move hardpoints.


## Release gates

1. Rated occupant, cargo and tow/assist loads, including dynamic and misuse factors.
2. Centre-of-gravity and anti-tip limits in travel, desk and canopy states.
3. Drive topology, motor torque, brake type, tyre, bearing and axle selections.
4. Table working load, support reactions, hinge pins and latch redundancy.
5. Canopy design wind speed, rain load, drainage slope and automatic retract strategy.
6. Mast actuator, holding brake, buckling margin and ingress protection.
7. Battery cell specification, enclosure venting, thermal paths and applicable transport standard.
8. Electrical architecture, isolation, grounding, EMC and emergency-stop behaviour.
9. Anthropometric targets, seat pressure mapping and accessibility requirements.
10. Target production volume and approved processes, which determine panel/tooling design.
11. Full tolerance stack, GD&T datum scheme, fastener schedule and service access.
12. Jurisdiction-specific machinery, mobility, furniture, battery and fire compliance review.
