# WorkCore E6 V11 — V8 Blender exterior restart

V11 is an isolated exterior-design restart.  The four released V8 clean GLBs
are immutable spatial references; V9 and V10 visual geometry is not imported.

The workflow is deliberately split:

1. validate and import the V8 four-state references;
2. lock wheels, controls, contact surfaces and motion envelopes;
3. replace the visible body skin with one shared Blender design system;
4. review Follow closure and the lower-body mother surface before detailing;
5. render four-state review images;
6. only after visual approval, rebuild the accepted surfaces in canonical
   STEP/B-Rep and rerun the engineering gates.

Nothing below this directory is allowed to overwrite V8, V9, V10 or
`step_anchored_v2`.

