# WorkCore E6 V11 V8 Blender restart — CAD and visual brief

## Classification

- Model: WorkCore E6 four-state exterior/layout assembly.
- Task type: source modification and visual surface restart from immutable V8
  state geometry; Blender is the visual decision model, not the production
  STEP release.
- Source: four clean V8 `workcore_e6_class_a_<state>.glb` files.
- Excluded sources: all V9/R09 and V10 visual meshes, proportions and probe
  geometry.
- Units: 1 Blender unit = 1 metre; engineering reports use millimetres.
- Coordinates after the single import correction: front `-X`, rear `+X`, left
  `-Y`, right `+Y`, up `+Z`.

## Design objective

Create one quiet, low, complete and mysterious new object.  It must not read as
a wheelchair, office chair, tool cart, suitcase or exposed robot chassis.
Retro-futurism comes from proportion, continuous volume, precise functional
seams and real materials, not decoration or exposed mechanisms.

## Immutable product DNA and hardpoints

- A06 retains its iconic front-view trapezoid.
- Follow uses that same A06 as its only folded upper surface; no hood, box lid,
  skirt or filler surface is permitted.
- A07 remains one externally recognisable tapered mast in every state.  Ride
  and Cafe share the low pose; Focus translates the same moving mast/head by
  `+420 mm Z`; Follow folds A07 with A06.
- Both armrests are fixed continuous bodies; there is no side-opening armrest.
- The right joystick and authorisation control remain exposed on the forward
  right armrest top in all four states.
- The display is one `124 x 49 mm` layer, tilted about world Y by `8 degrees`,
  front high and rear low.
- Cafe deploys the right table only; Focus deploys both tables.  Deployed table
  surfaces remain inboard of the armrest inner faces and never cover the
  joystick.
- Ride footrest is deployed by default; Follow, Cafe and Focus are stowed by
  default.
- Differential wheels are partially absorbed by the body mother surface.  No
  separately readable fender is allowed.
- A04 battery/equipment door remains `464 x 86 mm R18` in a
  `466 x 88 mm R19` opening, with a nominal `1 mm` seam and `300 mm` service
  travel.
- Overall finished width remains at or below `752 mm` until an engineering
  change is explicitly approved.

## P0 exterior work

1. Rebuild the lower body as one continuous mother surface joining front nose,
   belly, side shoulders, equipment door and wheel half-wrap.
2. Re-solve Follow closure using the A06/A07/seat/armrest physical pieces.  It
   may have a controlled slope; it need not be mechanically flat.
3. Rebuild armrest proportions and the top interface as one hierarchy while
   preserving the control, display, charging and table-cassette envelopes.
4. Reduce parting lines to real motion, service, sensing, drainage and safety
   boundaries.
5. Freeze a restrained CMF: dark mineral low-gloss body, real leather contact
   surfaces, natural walnut veneer and limited brushed 316 stainless detail.

## Validation targets

- Four states are generated from the same named design parameters and shared
  source functions; there are no state-specific cosmetic cover parts.
- V8 input byte counts and SHA-256 values match the locked baseline before each
  build.
- The one-time GLB axis correction is exactly `Rx(-90 degrees)` with no scale
  correction.
- Wheels, joystick, authorisation control, emergency stop, display face, seat
  contact, A06/A07, tables, footrest and service interfaces remain traceable by
  original V8 occurrence ID.
- Baseline and every accepted visible revision receive front, rear, left,
  right, top and hero visual checks; Follow receives additional high-front and
  rear-oblique closure checks.
- Blender approval does not claim Class-A, manufacturability, motion safety or
  production release.  Accepted visual geometry must be rebuilt in the
  canonical V8 STEP/B-Rep pipeline and all affected gates rerun.

## Output paths

- Reference master: `blender/e6_v11_v8_locked_reference_master.blend`
- Visual revisions: `blender/e6_v11_visual_rXX.blend`
- Source reports: `qa/`
- Preview renders: `renders/preview/`
- Formal renders after STEP round-trip: `renders/final32/`

