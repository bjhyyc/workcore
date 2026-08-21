# STEP Anchored 图像提示词原则

## 模式

- 正式工具链：受控 STEP/GLB → 参数化 Class-A CAD → VTK 物理渲染；32 张发布图必须直接来自同一次受控几何构建。
- ImageGen 仅可用于不进入发布包的早期语义探索，不得重画、替换或“美化修复”正式产品几何，也不得作为 STEP 一致性的证据。
- 每张正式图的几何来源：对应状态的 E6-DFR5-A07-SHARED-HINGE STEP/GLB 与其同构 Class-A 外覆，不以截图近似或文字提示猜测硬点。
- 最高优先级：轮心、总包络、硬点、扫掠、左右接口与状态拓扑；允许在这些边界内新增/替换独立 Class-A cosmetic skin。

## 四态共用不变量

```text
Image 1 is a controlled E6-DFR5 engineering underlay derived from the exact same physical occurrence list as the STEP assembly. Preserve its exact camera, wheel centers and diameters, axle spacing, ground contact, chassis/occupant envelope, functional hardpoints, motion-state topology, long fixed armrests, flat seat, the same hollow trapezoidal folding backrest, A08 footrest, right control pod, left display/Qi/emergency-stop zone, rear-center A07 axis, crowned sensor beam, desk leaves and all required service/sensor openings. A07 is the same fixed sleeve, one-piece moving spine and crowned beam in every state: Ride/Café are low, Follow co-folds on the A06 hinge, and Focus raises only the moving member and beam by 420 mm; never invent stage 2 or stage 3 and never make the mast appear only in Focus. A08 is one invariant six-occurrence physical assembly with one 210 × 500 × 10 mm platform and 1.890987 kg analytical mass; pose may change transforms only, never identity, definition, material, volume or mass. Treat exposed rails, brackets, carriers, actuators, supports and part clutter as inner engineering—not final visible surfaces. Design a small number of removable Class-A exterior shells around them, staying inside controlled overall envelopes and outside all motion, body, view, cooling, drainage and service keep-outs. Enclose every differential wheel with a two-zone C-wrap: the broad outboard side exposes only z=0–32 mm (open at z=20, opaque at z=55), while only the narrow front/rear longitudinal returns retain a local z=0–70 mm motion/drainage relief (open at z=55, opaque at z=90). Each of the four end returns needs a separate 1.0 mm lunar-stone body-colour outer impact skin, dry-gapped 0.1 mm from the dark structural return and spanning Y=88.6 mm and Z=71–314 mm; a dark structural return alone must fail because it reads as a tall exposed wheel in exact front/rear views. Never read either the end relief or the 110 mm service aperture as permission to expose a half or whole wheel.
```

## 外观变更

```text
Develop the final production-intent “Quiet Orbit” appearance on that underlay: fully wrap the lower chassis/frame, long-armrest mechanisms/table bundles, trapezoidal backrest carrier, footrest supports, mast drive and desk under-mechanisms with coherent manufacturable removable outer shells. Retro-futurist through late-1960s precision-instrument restraint; minimal, smooth, premium and mysterious without hiding intent. Warm lunar-stone fine-matte cosmetic shells, deep graphite-brown lower enclosure and functional hardware, smoked-umber real sensor windows only at existing apertures, sparse satin champagne anodized reveals, charcoal removable 3D-knit contact surfaces and espresso anti-fingerprint desk/foot surfaces. Use controlled real seams, TPE seals and replaceable scuff edges. No brand text.
```

## 共同否决项

```text
Do not turn it into a car, capsule, cockpit, wheelchair, mobility scooter, delivery robot, luggage, office chair or a different product. No automotive nose, grille or fenders; no full-width fake black glass; no new wheel arches; no steering wheels; no bucket seat; no short floating arm pods; no shrunken bumper-like footrest; no invented side service door; no moved privacy shutter; no fake side camera; no robot eyes; no RGB; no giant screen; no fins, portholes, decorative vents, exposed cables or impossible floating parts; no text, logo or watermark.
```

## 状态专用锁定

- Follow：同一空心梯形靠背后壳继续作为唯一天气盖；同一低态 A07 与 A06 共铰折叠；A08 脚踏为 `STOWED`；前部凹入踏阶、四轮和现有传感/服务开口保持；不得另造整体车罩。
- Ride：同一 `210 × 500 × 10 mm` A08 平台为 `DEPLOYED_LOCKED`；两条约 `520 mm` 固定长扶手、梯形靠背、右摇杆、左显示/Qi/急停与同一低位 A07 智能梁保持。
- Café：A08 主态为 `STOWED`，双脚可落地；只保留源图中的右桌部署，左侧开放；同一摇杆、pod 与授权键固定外露于右扶手前端且桌板不得遮挡，只撤销牵引授权；桅杆低位；不得改成另一种桌轨迹。显式脚踏展开属于单独可选子态。
- Focus：A08 主态为 `STOWED`，双脚可落地；源图中的同一双桌叶、中心缝保持；A07 仅让 Ride/Café 已存在的同一移动脊柱与冠梁升高 `420 mm`，固定套筒不动；隐私片只在智能梁前脸。显式脚踏展开属于单独可选子态。

正式四主态渲染范围固定为 Follow、Ride、Café、Focus 各 8 张，共 32 张；Café/Focus 的可选脚踏展开子态不得混入或替换这 32 张主态图。
