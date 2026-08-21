# WorkCore E6 最终外观 — STEP Anchored V2

本目录是无几何锚定概念图的纠正版。当前外观构建的受控几何基线是版本化 `E6-DFR5-A07-SHARED-HINGE`；E6-DFR4 与 E6-DFR3 仅作为只读父版追溯：

| 产品状态 | 受控 STEP | 同源 GLB | 原始预览 |
|---|---|---|---|
| Follow | `class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_follow.step` | `class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_follow.glb` | 由同版 V8 渲染构建生成 |
| Ride | `class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_ride.step` | `class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_ride.glb` | 由同版 V8 渲染构建生成 |
| Café | `class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_cafe.step` | `class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_cafe.glb` | 由同版 V8 渲染构建生成 |
| Focus | `class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_focus.step` | `class_a_cad/controlled_source_e6_dfr5/workcore_e6_dfr5_focus.glb` | 由同版 V8 渲染构建生成 |

## 方法

1. 仅读取受控 GLB，生成与 STEP 拓扑同源的统一前右高位 3/4 参考图；
2. 把每张参考图作为工程内核/硬点/扫掠 underlay，而不是把样机外露零件当最终表面；
3. 生成时锁死轮心、总包络、机构拓扑、物理件 ID、相机和状态；
4. 在不侵入运动/视场/人体/服务边界的前提下，重新建立连续 Class-A cosmetic skin，包覆外露承力架、导轨、支撑、传动与零件森林；
5. 纠正图与原始几何参考并存，不能把概念图当尺寸证据；
6. 所有现有 STEP/STP 文件生成前后复算 SHA-256 树哈希。

## 目录

- `geometry_lock.md`：不得漂移的尺寸/拓扑与可重塑区域。
- `cladding_architecture.md`：Class-A 外覆分区、包覆对象与必须留下的功能开口。
- `source_refs/`：从同源受控 GLB 离屏渲染的几何参考及渲染脚本。
- `corrected_renders/`：早期图像纠正试验，已被 V7 CAD 全部取代，不得作为当前设计结果。
- `prompt_set.md`：每张纠正图使用的精确约束提示词。
- `qa/`：关联性检查、已知偏差与完整性证据。
- `class_a_cad/controlled_source_e6_dfr5/`：当前只读受控输入与 DFR5 manifest。
- `class_a_cad/release_candidate_v8/`：V8 正式输出目标；只有同轮全部门禁、32/32 raster 和 artifact closure 通过且不存在 `BUILD_INCOMPLETE` 时才成立。目录未生成或闭包未通过时不得引用为完成制品。
- `class_a_cad/`：V8 参数化源、验证器与发布脚本；`release_candidate_v3/v6/v7`、`visual_gate_v4/v5` 均为只读过程批次，不是当前设计结果。

## 解释边界

`corrected_renders/` 和 V7 及更早候选只保留为过程证据，不是当前尺寸、包覆或外观证据。V8 只有在 `release_candidate_v8/` 的 skin-only STEP、关联 STEP、GLB、32 张正式 PNG、manifest、QA 报告与只读制品闭包同时成立后才可引用；在此之前状态必须写作 `BUILD PENDING / NOT RELEASED`。即使数字门全部通过，它仍是 Class-A 方向/包络研究，不等同量产曲面、结构、安全或法规放行。
