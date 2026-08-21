# WorkCore v30 to v37 engineering design review

> 本文件记录早期架构取舍。桌板载人结论已由 `v30_table_occupant_review.md` 和 `e3_human_centered_audit.md` 替代；E2 的桌板位置已判定失败。

## Source control

- v30 source: `WorkCore-3D-v30-HiddenCanopy.html`
- v37 source: `WorkCore-3D-v37-ArmrestChamfer.html`
- v37 SHA-256: `9BF0082E69A980CFCD542B6A91E213D47E82724D179BD90BEF0155125F300877`
- Review basis: program geometry and state logic.  The HTML is a visual mechanism
  demonstrator, not a tolerance-controlled CAD definition.

## Decisions

| v37 change | Decision | Engineering reason / E2 correction |
|---|---|---|
| Fixed back hinge with armrest inner chamfer | Adopt | Fewer moving datums and no sliding hinge hardpoint. Rebuilt as B-Rep solids and checked against the folded back, instead of trusting the `8 mm` source comment. E2 实测扫掠最小间隙为 13.546 mm。 |
| Armrest integrated down to the body | Adopt architecture | Removes the v30 floating support and makes the side module a structural/service carrier.  E1 uses a hollow replaceable shell located from chassis datums. |
| Full-length armrest lid | Adopt | Better service access and enough opening to remove the stored table module.  Production version needs a positive latch, seal, open stop and drain strategy. |
| Upright-fold 430 x 260 mm side table | Adopt with changes | Packaging is better than the v30 diagonal cantilever.  E1 changes the 10 mm stainless plate to a light aluminium honeycomb sandwich panel and adds positive centre latches. |
| Fixed 805 mm table surface | Reject | Too high for the published 559-762 mm seated keyboard range.  E1 uses 750 mm as the packaging target; final production should provide adjustment or target-population evidence. |
| Armrest top at 685 mm with original 580 mm seat top | Reject | About 105 mm support height is below the 178-267 mm workstation target.  E1 uses a 550 mm seat top and 735 mm armrest top. |
| Commented `zero-interference` claim | Reject as evidence | Three.js does not run a swept-volume or tolerance check.  E1 performs solid intersection checks and will add an 8 mm clearance envelope after kinematic hardpoints are frozen. |
| Cover/table hard interlocks | Adopt | The cover must be open before table motion and cannot close until the table is stowed.  This becomes a dual-channel position/latch requirement, not only animation ordering. |
| Qi phone soft interlock | Correct | v37 opens lids in mode 8 but hides the phone only in modes 4 and 5.  Production logic must sense occupancy and either inhibit lid motion or command a user-visible removal step in every affected state. |
| `trapN` helper | Do not adopt | It is defined in v37 but the actual back still uses `trap`; it provides no production geometry in that revision. |

## E2 user-experience baseline

- Seat top: 550 mm with a mandatory integrated footrest because this remains a high seat.
- Usable seat depth: 430 mm; width: 560 mm; waterfall front edge required.
- Armrest support height: 185 mm above compressed seat.
- Desk surface: 750 mm; two 430 x 260 mm halves meet into a 430 x 520 mm surface.
- Each table half target mass: under 1.5 kg before hinges/latches.
- One-hand user effort target: no more than 22.2 N at handles; assisted motion must not
  create an uncontrolled closing load.
- No structural state may depend on a friction hinge alone.
