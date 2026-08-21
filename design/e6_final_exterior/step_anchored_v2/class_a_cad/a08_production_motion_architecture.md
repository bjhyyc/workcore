# A08 production-motion architecture — release blocker and replacement datum

Status: **P0 / NOT RELEASED / not a production certification**

This note replaces the non-physical interpretation of the current A08 motion.
It does not authorise a render or STEP release by itself.  The geometry, locks,
tolerance stack, proof load and safety circuit still have to pass the gates at
the end of this document.

## Why the current mechanism is blocked

- At 101 equally spaced samples, the current platform and moving supports have
  hard common volume from progress `0.81` onward.  The largest measured
  platform-to-one-boot common volume is `17,272.5 mm3` at progress `0.84`.
- The stowed straight support ends are `(x=-400, z=152.5/287.5) mm`; its
  deployed ends are `(x=-605/-470, z=110) mm`.  The closest endpoint moves
  `82.5 mm` including the released lateral shift.  It is therefore not a rigid
  arm rotating about a fixed hinge.
- No captured guide, carriage or four-bar occurrence exists to carry that
  moving support.  The current interpolation is a floating body, not a load
  path.
- The final `A08_footrest_root_monocoque` and two
  `A08_footrest_support_monocoque_*` occurrences exist only in Ride.  Hidden
  stowage may change a transform or visibility, but may not delete physical
  parts.
- A Café/Focus user's normal floor-position shins enter the current deployment
  sweep from progress `0.12`; one shin reaches `216,984.51 mm3` common volume.
  The seat occupancy mat cannot prove that the foot zone is clear.

## Selected replacement architecture

Use a twin captured telescopic drawer with a paired over-centre drop link on
each side.  It preserves the existing horizontal platform endpoints without a
free-flying support:

| Datum | Stowed | Deployed and positively locked |
|---|---:|---:|
| platform centre X | `-360.000 mm` | `-605.000 mm` |
| platform centre Z | `147.000 mm` | `95.000 mm` |
| platform pitch | `0 deg` | `0 deg` |
| platform outer size | `210 x 500 x 10 mm` | same physical occurrence |
| lower carriage pivot Z | `80.000 mm` | `80.000 mm` |
| drop-link pin length | `62.000 mm` | same physical occurrence |

The two body-fixed rail housings capture a primary moving cartridge and an
inner carriage.  The cartridge and inner carriage may translate only along X;
they cannot translate freely in Y/Z or rotate.  Two identical drop links on
each side form a parallelogram, so the platform stays horizontal.  A cross-shaft
synchronises left and right links.

The exact one-degree-of-freedom law is:

1. **Tactile-edge clearance, 0–10 %:** each `62 mm` drop link rotates from
   `0 deg` to `44.791325 deg` from vertical while the captured inner carriage
   retracts `43.680659 mm` into the body.  Those two X motions cancel, so the
   platform stays at `X=-360.000000 mm` and descends `18 mm` to `Z=129 mm`.
   The final tread's highest point is then `Z=143 mm`, a real `5 mm` dry gap
   below the tactile bumper's `Z=148 mm` lower datum.
2. **Captured drawer extension, 10–70 %:** hold the link angle.  From its fully
   retracted clearance position, the primary cartridge travels `144.000000 mm`
   and the captured inner carriage travels a further `83.492425 mm`.  The
   platform reaches `X=-587.492425 mm`, `Z=129 mm`.  Every rail stage retains
   at least `25 mm` overlap at maximum extension.
3. **Over-centre drop and lock, 70–100 %:** the links rotate to
   `80.718201 deg` from vertical.  Their horizontal component becomes
   `61.188234 mm` and their vertical component becomes `10.000000 mm`, placing
   the platform exactly at `X=-605.000000 mm`, `Z=95.000000 mm`.

The reverse path is mandatory for stowage.  The initial inward carriage motion
is not optional: omitting it makes the raised final tread swing through the
tactile bumper even though the older flat structural proxy appears clear.  No phase may be skipped, blended
through another part, or replaced by endpoint interpolation.

## Physical occurrences that must never disappear

- platform top, tread and perimeter occurrences;
- fixed root monocoque/housing;
- left and right primary support monocoques/cartridges;
- left and right captured inner rail stages;
- four drop links, eight replaceable plain bearings and their guarded pins;
- left/right deployed rail lock pins and independent lock witnesses;
- synchronising cross-shaft, counterbalance spring and manual release cable;
- body-side manual release paddle.

The fixed root monocoque remains attached to A01 in all states.  The two smooth
support monocoques translate through dry apertures into the body when stowed;
they do not rotate upright or vanish.  Internal load rails sit at `Y=+/-220 mm`
and below the platform.  Cosmetic support monocoques sit outboard of the
platform edge with a minimum `4 mm` dry split during the final drop, so an
unseen Boolean pocket is not used as a collision allowance.

## Preliminary load-path sizing (design input, not certification)

- analytical vertical proof-load input: `1.5 kN` distributed, `0.75 kN` per
  side;
- approximate per-side cantilever moment at the existing endpoint:
  `101.25 N m`;
- candidate nested 6061-T6 rail sections, outer to inner:
  `30 x 40 x 3`, `26 x 34 x 3`, `22 x 28 x 3`, `18 x 22 x 3 mm`;
- corresponding simple elastic bending stresses under the full per-side moment
  are approximately `24.9`, `35.4`, `54.4`, and `93.8 MPa` before joint,
  impact, fatigue or stress-concentration factors;
- minimum deployed stage overlap: `25 mm`; minimum dry running gap: `3 mm`;
- the endpoint load bypasses the actuator through two mechanical rail pins and
  two over-centre link locks.  The actuator/counterbalance may not be the sole
  occupant-load path.

FEA, pin bearing, tube crippling, link buckling, fatigue, abuse load, corrosion,
contamination and physical proof tests remain open.

## Required safety sequence

Optional Café/Focus opening is permitted only after all of the following are
true: speed zero, park brake proved, traction STO proved, table sweep clear,
two-channel foot-zone clear proved, user makes a deliberate request, and the
manual release is held.  Drive remains inhibited until both deployed lock
witnesses agree.  A seat mat alone is explicitly insufficient.  Loss or
disagreement of either foot-zone channel prevents powered release and leaves
the mechanism in its last mechanically locked state.

## Gates required before final renders

1. Same complete occurrence inventory at all 101 poses and both endpoints.
2. Inverse-transform B-Rep identity for every rigid occurrence; no volume-only
   substitute test.
3. Moving-vs-fixed, moving-vs-moving, human foot/shin and ground swept-volume
   checks at 1 % increments plus adaptive subdivision below `5 mm` clearance.
4. Zero hard common volume, except pins/bearings represented as explicit joint
   interfaces; no allow-list for platform/support overlap.
5. Minimum `3 mm` dry clearance through the complete tolerance stack and at
   least `25 mm` rail-stage overlap at maximum extension.
6. Independent proof of the two deployed rail pins, two over-centre locks,
   stowed lock, manual no-power recovery and two-channel lock sensing.
7. Physical instrumented proof-load, abuse, contamination, pinch, wet, drain,
   fatigue and emergency-recovery tests.

Until all seven gates pass on the final V8 B-Reps, A08 remains a release
blocker and must not appear in a claimed final 32-image series.
