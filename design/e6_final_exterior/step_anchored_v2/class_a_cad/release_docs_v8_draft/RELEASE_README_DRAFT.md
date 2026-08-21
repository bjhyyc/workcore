# WorkCore E6 V8 最终外观候选发布说明（草案）

文档状态：`V8 数字 CAD 候选发布说明源；正式发布状态以 release_candidate_v8/class_a_skin_manifest.json 与 BUILD_INCOMPLETE 是否存在为准`

量产认证状态：`NOT CERTIFIED（当前禁止用于 Class-A、开模、法规或量产放行）`

数字几何门结论用语：仅当正式 manifest 引用的全部数字报告为 `PASS` 且 `BUILD_INCOMPLETE` 不存在时，方可使用 `GEOMETRY_GATE_PASS_NOT_PRODUCTION_CERTIFICATION`

## 1. 本草案的用途

本目录记录 WorkCore E6 V8 最终外观候选的设计边界、已有数字证据和进入工程样机前必须补齐的验证。它不是销售材料，也不是 Class-A 曲面放行、模具放行、安全认证或量产批准。

V8 是受控 `E6-DFR5-A07-SHARED-HINGE` 四主态 STEP 的独立外观层。DFR5 只把 Follow 的完整 A07 发生项修正到与 A06 共用的 `(160, 0, 515) mm` 铰链；Ride、Café、Focus 及两个可选脚踏子态与 DFR4 字节一致。受控 STEP 仅作为只读架构底图；V8 不以替换、缩放或移动受控架构来换取外观成立。E6-DFR3 与父版本 DFR4 保留为历史追溯输入，不得再作为当前发布基线。

## 2. 产品定义：一个物品的四种状态

Follow、Ride、Café、Focus 不是四个产品，也不是在同一底盘上临时堆出的四套附件。它们是同一件“个人场域载体”在不同物理前提下的状态转化：能力在闭合时被收住，在人进入、驻车、授权和隐私条件成立后按顺序显露。

| 状态 | 物理前提 | 当前外观表达 | 不得被误读为 | 正式用户验证 |
|---|---|---|---|---|
| Follow | 空载、允许伴随移动 | 同一梯形靠背折叠后形成唯一上表面；A08 为 `STOWED`；低位感知地平线；工作脊柱在其内部净空中被遮蔽；仅保留必要的机械急停与克制状态见证 | 行李箱、宠物机器人、裸露折叠车、额外箱盖 | `TBD` |
| Ride | 乘员进入并取得控制 | 同一 A08 为 `DEPLOYED_LOCKED`；脚踏、扶手、座背围绕人建立边界；桌面保持收纳；控制与急停可读 | 医疗椅、办公椅、外壳压过乘员主体 | `TBD` |
| Café | 已驻车、单侧桌面允许展开 | A08 主态为 `STOWED`、双脚可落地；当前 CAD 仅右侧桌面展开；另一侧保持开放；控制语义退居次位 | 坏掉的半张桌、仍可牵引移动的驾驶舱 | `TBD` |
| Focus | 已驻车、双桌与隐私前提成立 | A08 主态为 `STOWED`、双脚可落地；双桌形成工作边界；同一单一移动脊柱与冠梁从低态上移 420 mm，固定套筒不动；同一右侧 pod/摇杆/授权键保持扶手前端固定外露但牵引禁用；物理隐私件与光学窗分离 | “大桌版 Ride”、仍在等待驾驶的座椅、先亮屏后确认身份、静默开启相机 | `TBD` |

神秘感只来自“能力按条件出现”，不来自隐藏危险或制造意图不明。移动方向、驻车、故障、隐私关闭、接近侧和接管需求仍必须可读。该可读性的实体测试结果为 `TBD`。

Café/Focus 可在驻车、脚部路径和前方净空成立后显式进入 A08 `DEPLOYED_LOCKED` 可选子态；它们仍分别属于 Café/Focus，不新增主态，也不进入四主态 32 图。四主态及两个可选子态始终引用同一套 47 个 A08 生产意图 occurrence，只有受控刚体变换与端点锁销状态不同。旧六发生项和 `1.890987 kg` 分析质量已经失效，当前机构质量必须由 47 件 EBOM 与首件重新闭环。

## 3. V8 数字 CAD 证据边界

本节定义正式数字候选必须证明的内容，不在文档源中预先硬编码会随几何变化的零件数或检查数。正式数量、状态、时间戳和 SHA-256 只读取本次 `class_a_skin_manifest.json` 及其引用的 pre-export、post-export、post-STEP 与 QA 报告；旧轮次数字不得沿用。

只有下列责任全部由同一次正式构建报告证明为 `PASS`，且 `BUILD_INCOMPLETE` 不存在，V8 才能标记为数字 CAD 门通过：

- 四个状态均由相同基础外观链重建，并依次应用 V8 外观收敛、真实功能开口、A07 同一固定套筒＋单一移动脊柱＋同一冠梁和刚性件分区；
- A08 在 Follow/Café/Focus 主态为 `STOWED`、在 Ride 主态为 `DEPLOYED_LOCKED`；Café/Focus 的显式展开仅作为独立验证子态，不得混入四主态图像或用第二套脚踏几何替代；
- 受控四态 STEP 在构建前后字节数与 SHA-256 均匹配冻结基线；
- manifest 同时记录完整生成器、参数、设计简报、冻结约束与发布文档源的构建前后 SHA-256，构建期间任何源漂移均使发布失败；
- manifest 记录的全部最终 `SkinPart` 均为单一、有效、正体积 B-Rep 实体；
- pre-export、post-export 以及 post-STEP 检查均无硬失败，每个检查 ID 唯一并记录 `evidence_kind`；
- A01 前鼻壳在四态中均熔接同一永久 brow-and-crown 天气面：它从正常前视、站立俯视和斜上视角闭合脚舱内部，同时保持感知硬点、A04 干缝与乘员侧脚部通道；不得以状态盖板或相机规避替代；
- Follow 只有同一块 4 mm 空心梯形 A06 靠背折叠并直接形成唯一上表面，不叠加盖板；完整 A07 低态与 A06 共用同一铰链。Ride/Café 已能读到同一低位冠梁，Focus 只把单一移动脊柱、冠梁和功能嵌件上移 420 mm；
- 两件低矮空心 A04 靠背根肩固定在车身上并存在于全部四态，以至少 4 mm 全折叠行程间隙承接 A06 下方视觉体量；不得恢复仅在非 Follow 出现的 A06 根部 cheek 碎片；
- A03 以覆盖完整胎宽上冠的连续 C-wrap 轮罩、前后轴平面端回和内侧下翻吸收轮胎上部及传动区；轮端与 rocker 维修盖后的深色实体背衬阻止缝隙透出背景。外侧主皮只允许 `z=0–32 mm` 低位接地条外露并通过侧面 `z=20/55 mm` 开放/闭合探针；仅前后端回保留局部 `z=0–70 mm` 运动/排水让位并通过端部 `z=55/90 mm` 开放/闭合探针及跨轮胎宽度和上半部的 3×3 实体覆盖网格。四个端回还必须分别使用一件 `1.0 mm` 月岩体色可换冲击皮，与深色结构端回保持 `0.1 mm` 干隙并覆盖 `Y=88.6 mm、Z=71–314 mm`；深色结构端回自身通过 3×3 探针不构成视觉通过，正/后视不得读取为竖向半轮或整轮外露。四轮在 `-10/-5/0/+5/+10°` 的名义扫掠净距均不得低于 `15.5 mm`，轮罩名义外宽 `750.8 mm`；近齐平轮端盖使局部成品宽度为 `751.0 mm`，仍低于 `752 mm` 量产设计上限，随盖拆卸的 EPDM 背衬最小扫掠净距为 `15.6 mm`；
- 外包络同时执行逐面和总尺寸双锁：相对哈希绑定 DFR5 STEP 的纵向 `xmin/xmax` 各自最多增长 `25 mm`、横向 `ymin/ymax` 各自最多增长 `17 mm`，任何单面超限不得以另一侧余量抵消；Follow/Ride/Café/Focus 总长还分别受 `885/1111/906/1021 mm` 上限约束，成品总宽继续受 `752 mm` 上限约束；
- 左右 A05 扶手均为固定连续壳体，外观中不存在侧开铰链、连杆、释放拨片或相应运动分缝；A05 收纳面保持为低填充率精密周界揭缝，而非大面积假屏；
- A07 在四态中使用同一固定套筒、一件完成态移动脊柱与同一冠梁；`stage_2`、`stage_3` 属于被禁止的旧行李箱拉杆架构。正式报告记录固定/移动件径向间隙、Focus 末端至少 150 mm 轴向捕获、420 mm 单一位移、共铰链和跨态 B-Rep 一致性；脊柱以 16 mm 隐藏空心榫插入终端套口，保留 3 mm 径向装配间隙、2 mm 端余隙和 4 mm 外观干缝；下置声学网位于结构榫外侧且干隙不低于 1.5 mm，不得退回零距离面接触或嵌件穿模；
- Follow 折叠 A06 与 A04 座垫之间唯一允许的非零 common volume 是对明确非刚性泡棉的无乘员名义预压：深度不得超过 `22 mm`、公共体积不得超过 `70,000 mm³`，Ride/Café/Focus 必须为零；该例外必须同时通过专用几何门，且不替代占用互锁、供应商压缩永久变形曲线和实体循环试验；
- A08 的 47 个生产意图 occurrence 在四主态和 Café/Focus 可选展开子态中保持相同物理身份与刚性 B-Rep；平台、双固定导轨、双主卡匣、双捕获内轨、四连杆/轴承/护销、端点锁、同步轴、配重、手动释放和双通道脚区互锁均不得因收纳而删除。Ride 展开态与 Follow/Café/Focus 收纳态只改变受控变换和锁销啮合。旧六发生项与 `1.890987 kg` 已被替代，当前 EBOM、材料、紧固件、线束和首件质量仍为开放量产证据；
- Café 右侧及 Focus 两侧 A09 使用独立嵌套的直壁定向 squircle 桌腿，外截面 `72×70 / 60×58 / 48×46 mm`，相邻径向干隙 `3.0 mm`，最内机构通道 `40 mm`，且轴线与 Z 硬点不变；每个活动桌叶只保留一件连续收腰空心桌腹，旧 bridge、root fairing、saddle、方盒 belly 及其布尔残段全部退休。底部 base socket 对第一级实际干隙不少于 `2.4 mm`，Focus 顶部 root crown 收住上口，固定 A05 内缘以受控退让保持 `1.5 mm` 动静干隙，中央膝部净通道为 `250 mm`；Café 桌腹至固定 A05 保留 1.1 mm 干缝，中央接缝、锁止和维修边界仍有明确责任；
- 四态始终保留同一物理右侧 pod、joystick 与授权键，并以完全相同的 B-Rep 和世界坐标固定外露于右扶手前端；仅 Ride 允许牵引，Café/Focus 展开桌板及其真实手部操作包络都不得遮挡或迫使控制件移位；
- A10 后服务门的无电释放轴孔与拉手腔为真实减材开口；
- “最终 V8 外皮＋仅 `retain_exposed` 的受控保留件”满足正式生产边界锁；完整原型 STEP 仅作为哈希锁定的只读追溯底图，不冒充当前量产 BOM；
- 32 张正式图通过同一次 raster gate；该集合严格为 Follow、Ride、Café、Focus 四主态各 8 张，Café/Focus 可选脚踏展开子态不在其中；导出 STEP 回读、GLB 米制单位与节点清单、四主态以及两个可选脚踏展开子态的 pre/post-STEP 刚性碰撞矩阵、源 CAD 21 点运动扫掠及封闭制品集检查全部通过。

本轮数字摘要统一写作：`4 states / exact part and check counts recorded by the formal manifest / 0 hard failures required`。这只是数字 CAD 完整性结论，不构成动态安全、可制造性、Class-A、法规或量产认证。

### 3.1 受控 STEP 基线

| 状态 | 只读文件 | SHA-256 |
|---|---|---|
| Follow | `controlled_source_e6_dfr5/workcore_e6_dfr5_follow.step` | `f925527ce086f2b18b0c53312733aadd6fa69aebb541d158f260d9c33b1a88fc` |
| Ride | `controlled_source_e6_dfr5/workcore_e6_dfr5_ride.step` | `3bf21b0811845c0d0fc10fbd116c96fc2188cc6e7a54956cd5e383c6a48fbb89` |
| Café | `controlled_source_e6_dfr5/workcore_e6_dfr5_cafe.step` | `8118b34c83bde30f316717e028279de656db4640d1c1f74e2c7fb6c96ecddd88` |
| Focus | `controlled_source_e6_dfr5/workcore_e6_dfr5_focus.step` | `598ad5a8686989be548140c5629a1b996b85bc833f1672850c98da400626ed4c` |

任何一个哈希或字节数不一致，都必须把 V8 证据判为失效并重新审查；不得以更新基线值掩盖受控文件变化。

上述四态及两个可选脚踏子态共同受 `controlled_source_e6_dfr5/e6_dfr5_a07_hinge_manifest.json` 约束；该受控源 manifest 的冻结 SHA-256 为 `dc27774b66320f8580c7bcd7d23a5c0f97e8e2187a808809f8116e811bc601a4`。正式构建必须同时核对 manifest 与其列出的 STEP/GLB，不能只核对表中的四个 STEP。

## 4. 当前数字 CAD 没有证明什么

下列项目均未被静态几何门证明，结果统一为 `TBD`，并阻塞量产放行：

- Class-A 曲面：曲率连续性、斑马纹、反射线、面间高光流动、A 面公差和手工补面结果；
- 动态机构：全行程扫掠、变形件、线束/软管、密封压缩、轴承间隙、污染后运动、夹剪点与故障回收；
- 结构：乘员、桌面、脚踏、扶手、救援点、搬运点、跌落、冲击、疲劳、倾覆和寿命；
- 热：电池、驱动、充电、计算平台、日照、堵风道、热表面、低温启动与热失控隔离；
- RF/EMC：UWB、ToF、雷达/超声、Wi-Fi/蓝牙/蜂窝等天线的透过、去谐、互扰、线束辐射和法规测试；
- 防护与环境：IP 等级、雨淋、排水、冷凝、盐雾、灰尘、泥沙、清洁剂、消毒剂、UV、温湿循环；
- 材料与 CMF：真实色差、光泽、纹理、皮脂、刮擦、耐磨、阻燃、气味、老化和批次稳定性；
- 制造：材料牌号、壁厚、筋位、柱位、拔模、分型、滑块、缩水、翘曲、浇口、顶出、装配路径和模具寿命；
- 公差：GD&T、装配基准、间隙面差、密封压缩、机构累计误差、热胀冷缩、供应商工艺能力和量产 Cpk；
- 人因：5 秒无讲解识别、2 m/5 m 状态可读性、戴手套操作、色觉/听力差异、儿童/宠物/软包/污渍误用和应急救援；
- 软件与生态：身份、权限、隐私、部分恢复、离线、低电、错误设备、任务恢复 P95、数据清除和转售交接；
- 法规：产品分类、目标销售地区、适用标准、第三方实验室方案、认证样机和型式试验；
- 知识产权：正式先前技术检索、FTO、外观/发明专利范围与规避方案；
- 成本与供应链：目标 BOM、模具投资、工装、良率、维修件、备件年限、供应商能力和停产替代。

## 5. 当前发布状态

| 发布层级 | 证据 | 当前状态 |
|---|---|---|
| 受控输入未变 | `qa/input_pin_report.json`；manifest 中构建前后四态 STEP 哈希与字节数 | `以正式报告及 manifest 为准；必须 PASS` |
| 内存静态几何门 | `qa/v8_geometry_release_gate.json` 与 `validation_pre_export.json` | `以正式报告为准；必须 0 硬失败` |
| 导出 STEP 后静态几何门 | `qa/v8_geometry_release_post_step.json` 与 `class_a_validation.json` | `以正式报告为准；必须 0 硬失败` |
| Café/Focus 可选脚踏展开门 | `qa/rigid_pair_collision_cafe_footrest_open.json`、`qa/rigid_pair_collision_focus_footrest_open.json` 及对应 `post_step` 报告；源 manifest 同时给出各 21 点扫掠 | `以正式报告为准；四份 Class-A 静态报告及两份源扫掠均必须 PASS；不进入 32 图` |
| 完整刚性碰撞矩阵 | 四态 pre-export 与 post-STEP 报告；0.1 mm³ 硬门；无未解释白名单 | `以正式报告为准；四态均必须 PASS` |
| 导出后几何回读 | `qa/exported_part_step_reload_gate.json`；每件重新导入并比较拓扑、体积和边界签名 | `以正式报告为准；必须 PASS` |
| GLB 复核 | `qa/glb_units_inventory_gate.json`；米制单位、节点/几何清单及边界与 STEP 一致 | `以正式报告为准；必须 PASS` |
| 32 图交付门 | `qa/render_series_raster_gate.json`；四主态 4×8、1600×1200、唯一文件、构建后生成、hero 与 QA 不同；不含 Café/Focus 可选脚踏展开子态 | `以正式报告为准；必须 PASS` |
| 最终候选制品集完整性 | manifest 全部文件 SHA-256、0 缺失、0 额外、闭包 PASS 且 `BUILD_INCOMPLETE` 不存在 | `以正式 manifest 和只读复核为准；两者缺一不可` |
| 工业设计人工视觉评审 | 四态八视图、1:1 轮廓、实体 CMF、无讲解评审 | `TBD；raster PASS 不替代人工与实体评审` |
| Class-A 曲面放行 | A 面数据、曲率/高光、公差签署 | `TBD` |
| 工程样机 DVT | 结构、热、RF、环境、机构、人因 | `TBD` |
| 法规/认证 | 适用标准与第三方报告 | `TBD` |
| 模具与量产 | DFM、T0/T1、能力研究、试产审核 | `TBD` |
| 最终量产批准 | 跨职能签署 | `TBD（BLOCKED）` |

## 6. V8 候选交付物清单

正式候选使用下列固定结构；实际逐件数量、路径集合、字节数、SHA-256 和门状态以本次正式 manifest 为唯一索引：

- 四态逐件外皮 STEP：`<state>/parts/*.step`；
- 四态独立皮肤 STEP：`<state>/workcore_e6_class_a_skin_<state>.step`；
- 四态“只读受控架构＋最终皮肤”复合 STEP：`<state>/workcore_e6_class_a_<state>_with_read_only_underlay.step`；
- 四态 review GLB 与 QA overlay GLB：`<state>/workcore_e6_class_a_<state>.glb`、`<state>/workcore_e6_class_a_<state>_qa_overlay.glb`；
- 四主态 hero、QA overlay、front、rear、left、right、top、bottom 共 32 张 1600×1200 PNG；Café/Focus 可选脚踏展开子态仅属验证范围，不替换或扩充此正式图集；
- 根级导出前/导出后验证：`validation_pre_export.json`、`class_a_validation.json`；
- `qa/` 中的输入固定、pre/post-STEP 几何、pre/post-STEP 四态刚性碰撞、检查 ID、STEP 回读、GLB 清单、32 图 raster 与源处置报告；
- 源处置 JSON/Markdown、manifest 内零件/材料/metadata/路径清单与物理 occurrence 责任；
- `release_status.json`：只声明数字 CAD 状态，并保持 `production_certification_claimed=false`；
- `class_a_skin_manifest.json`：正式制品索引、逐文件 SHA-256 与 artifact closure 证据；
- `docs/`：本发布说明、工业化复测矩阵和视觉设计依据的同版副本。

存在 `BUILD_INCOMPLETE`、缺少 manifest、manifest 任一数字门非 `PASS`、制品闭包不一致或文档与 manifest 不是同版时，以上目录只能视为构建中间物，不得作为数字候选交付。

## 7. 发布纪律

1. 任一几何、材料、分件、状态姿态或受控输入变化，必须重跑全部数字门；不得只复测被修改的截图。
2. 静态 B-Rep 的 `PASS` 只能写成数字几何证据，不能扩写成动态安全、可制造或法规合格。
3. 所有豁免必须有物理界面类型、责任人、批准依据和过期条件；“视觉上看不到”不是碰撞豁免理由。
4. 未完成项目统一写 `TBD`；不得使用“基本完成”“预计无问题”“量产级”代替证据。
5. 当神秘感与安全意图冲突时，安全意图优先；当外观包覆与散热、感知、制动、维修冲突时，先解决工程路径，再冻结外观。
