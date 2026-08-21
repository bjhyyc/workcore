# WorkCore E6 最终外观功能门 V3 只读审查

Status: **FAIL — 当前 CAD 不能作为量产外观功能接口放行依据。**

本审查按 `e6_object_character_and_mystery_brief.md` 的原则执行：神秘感只能来自能力的克制收纳，不能来自隐藏运动意图、传感、故障、锁止、救援或服务路径。审查对象为四个受控状态 `Follow / Ride / Café / Focus`，以及当前 `skin_common.py`、`skin_lower.py`、`skin_upper.py`、`build_class_a_skin.py`、`validate_class_a.py`。未改动上述代码或任何受控 STEP。

本文件是功能接口/包覆责任审查，不是 Class-A、结构、功能安全、RF、声学、泄压或热管理试验放行。

## 1. 审查口径

状态缩写：`F=Follow`、`R=Ride`、`C=Café`、`X=Focus`、`ALL=F/R/C/X`。

外观中的功能对象必须属于以下四种之一，并在 manifest 中逐个绑定受控 occurrence：

1. `retain_exposed`：轮胎、座垫、天气密封等本身就是最终接触/运动/密封面，保留受控源件；
2. `replace_surface`：最终窗、膜、踏面、按钮或桌面皮替代样机外表面，但硬点和功能轴不变；
3. `conceal_behind_access`：充电、断电、制动释放等平时隐藏，但必须有明确的门、无电开启件和可达路径；
4. `internal_enclosed`：模块、线束、支架、导轨等完全退出正常视野，并由具体外壳承担包覆责任。

不能接受第五种状态：builder 仅从 final GLB 隐去源件，却没有与其硬点相连的最终代理或服务链。

受控功能件清单以四个实际状态 GLB/STEP 为准，而不是以 `build/parts` 目录中所有历史/备用零件为准。例如 `footrest_stowed.step`、下层抽屉和非 Focus 的 fill-light STEP 没有出现在四个受控状态 GLB 中，本轮不据此制造伪失败。

## 2. 立即阻断放行的 P0

| ID | 受控硬点/源件 | 当前最终代理 | 结论与建议几何修正 | 可直接实现的 hard check |
|---|---|---|---|---|
| P0-01 Focus 隐私片硬点漂移 | `mast_privacy_shutter_parked_focus`: X `[262.5,266.5]`, Y `[65,191]`, Z `[1443,1477]` | `A07_physical_privacy_shutter`: X `[262.5,266.5]`, Y `[32,158]`, Z `[1443,1477]` | 整件沿 Y 错移 `-33 mm`；这是为了把外观塞回 320 mm beam 而移动受控机构，不是包覆。恢复源中心 `Y=128`，为 Y=160..191 的 parked 部分增加真实端袋/外罩和装配隙。 | `function.focus.privacy_shutter.source_datum`: proxy/source 三轴中心和尺寸差均 `<=0.5 mm`；`function.focus.privacy_shutter.parked_pocket`: pocket 对源 shutter 全包络且最小隙 `>=2 mm`，不得移动源件来通过。 |
| P0-02 后 UWB 被金属门皮遮蔽 | `follow_uwb_rear_radome`: X `[327,330]`, Y `[-40,40]`, Z `[258,282]` | `A10_rear_uwb_radome`: X `[331,333]`, Y `[-40,40]`, Z `[258,282]`; 其后是镁门皮 `A10_rear_flush_service_door_skin`: X `[327.5,330.5]`, Y `[-153,153]`, Z `[246,414]` | 最终 radome 只是贴在实心导电门皮外；RF 路径仍被镁完全截断。门皮必须切贯穿孔，建议不小于源 80×24 mm 投影加每边 2 mm 密封/装配余量，再装独立非导电 radome。 | `function.all.rear_uwb.clear_rf_corridor`: 从源 radome +X 外表面到最终 radome 的 corridor 与任何 conductive/opaque part 交体积为 0；门孔 YZ 投影覆盖源件 `>=100%` 且每边余量 `>=2 mm`；材质必须声明 `rf_transparent=True`。 |
| P0-03 电池泄压喉口被缩小 | `battery_pressure_vent_duct`: X `[200,330]`, Y `[-21,21]`, Z `[157,199]`，+X 出口包络截面 42×42=`1764 mm²` | `A10_pressure_relief_vent_bezel` 最小开口 50×12=`600 mm²`；A10 tunnel 虽为 78×38，最终喉口仍控制流量 | 自由截面仅源出口包络的约 34%，缩小约 66%；`pressure_vent_unobstructed=True` 不能替代几何。扩大最终最小自由截面至经泄压工程签核的值，当前至少不得小于源出口有效面积，并保持朝后、远离乘员。 | `function.all.pressure_relief.minimum_free_area`: 沿 X 对完整通道分段求自由截面，`min_area >= signed_required_area`，在未签核前 `>= source_mouth_area`；`function.all.pressure_relief.no_skin_intrusion`: skin 与源 duct 交体积为 0。 |
| P0-04 后喇叭没有声学通路 | `service_rear_horn_behind_door`: X `[319,325]`, Y `[-30,30]`, Z `[386,414]` | 无 horn outlet；同一实心镁门皮覆盖整个 YZ 投影 | “门后可维修”不等于声音能到外界。门皮应有独立疏水声学膜/微孔格栅，或经验证的导声道；不能依赖普通门缝。 | `function.all.rear_horn.outlet_present`: 每态恰有一个 `rear_horn_acoustic_outlet`；`clear_acoustic_corridor` 不穿过实心镁/PC-ABS；必须有 `minimum_open_area_mm2`、膜材、IP 目标和声压证据引用。 |
| P0-05 四个下视 IR 最终面在错误一侧 | 四个 `follow_cliff_ir_window_*`: Z `[96,99]`，出射轴 `-Z` | 四个 `A02_cliff_ir_window_*`: Z `[99,102]`，X/Y 对齐但被放在源窗上方 | 代理位于内部一侧，无法成为最低外表面；builder 又把真实源窗从 final GLB 隐去。二选一：把源窗列入 `retain_exposed` 并加周边 bezel；或把最终窗置于源窗外侧/同一最终面并建立密封光筒。 | 每态按四角逐名检查；retain 路径要求源名出现在 `_source_keep`；replace 路径要求 `proxy.zmax <= source.zmin + 0.5`、XY 投影覆盖 `>=95%`、沿 -Z corridor 与不透明 skin 交体积为 0。 |
| P0-06 Ride/Focus 驾驶控件偏离 STEP | 受控 Ride/Focus pod X `[-305,-195]`, Y `[307,359]`, Z `[681,699]`; joystick Z `[699,727]`; authorisation Z `[699,707]` | `A05_right_removable_drive_pod` Z `[673,691]`，下降 8 mm；`A05_right_joystick` / `A05_right_authorisation_key` 均下降 11 mm | “下沉”是移动硬点，不是包覆，且会让最终图与 STEP 不对应。应围绕受控 pod 做 gasket landing，不改变按钮/摇杆的轴线和操作高度。 | `function.ride.drive_controls.source_datum` 与 `function.focus.drive_controls.source_datum`: pod/joystick/key 逐件 proxy/source 中心和功能轴差 `<=0.5 mm`；允许仅扩大外壳，不允许平移控制件。 |
| P0-07 右移乘扶手机构和正锁没有完整最终责任件 | `armrest_transfer_hinge_shroud_right`: X `[186,234]`, Y `[326,374]`, Z `[500,680]`; `link_shroud_right`: X `[124,226]`, Y `[326,368]`, Z `[477,503]`; `positive_lock_right`: X `[18,62]`, Y `[306,330]`, Z `[643,661]` | `A05_armrest_table_bay_shell_right` 只到 X=140、Y=367.5、Z=675；无 transfer-lock release/witness part | 源铰根/连杆有 X=140..234、Y=367.5..374、Z=675..680 超出 A05，且正锁被壳体语义吞没。增加独立 rear transfer-root fairing（围绕完整 sweep），并在源锁硬点提供机械释放/锁位 witness；不能显示裸 shroud。 | `function.all.right_transfer_mechanism.enclosed`: 源 hinge/link shroud 对应 `internal_enclosed` 且其 sweep 外包络由指定 proxy 全覆盖，运动隙 `>=3 mm`；`right_transfer_lock.interface`: 源 lock 必须绑定 release+witness，中心公差 `<=2 mm`，Ride 时锁止可读，Transfer 时无电可解。 |
| P0-08 Focus fill light 被无依据地删除 | 受控 Focus 左灯 X `[262,270]`, Y `[-151,-109]`, Z `[1449,1471]`; 右灯 Y `[109,151]` | 无 `A07_fill_light_*`；现有 smoked window 只到 Y `[-140,140]`，且 builder 隐去源灯 | 每侧有 11 mm 超出 smoked window，材料也没有可见光透过定义。增加两个与源光轴一致的最终灯窗/端袋，或把经过光学验证的组合窗口扩到完整源投影。 | `function.focus.fill_light.windows_bilateral`: 恰好左右两件或一个明确声明组合窗口；源投影覆盖 `>=100%`，光轴偏差 `<=0.5°`，opaque corridor 交体积 0，材质含可见光透过率证据。 |
| P0-09 后服务门缺少外部无电开启链 | `service_rear_flush_door` 后含 charge / disconnect / brake release；STRANDED_SAFE 要求无电制动释放 | `A10_rear_flush_service_door_skin` 只有 `quarter_turn_internal_release=True`，无外部 latch/handhold part | 内部 release 无法证明用户能从关门状态进入；充电和救援都依赖此门。增加防误触、可戴手套、无电的外部 quarter-turn/两动作释放和拉手凹区。 | `function.all.rear_service_door.access_chain`: `door -> external_release -> open_state -> charge/disconnect/brake` 链完整；release 必须 `manual_no_power=True`、bounds 位于门外表面、不得被门自身遮蔽；三个内部接口分别检查，不能由门的聚合 token 一次代替。 |
| P0-10 热排出接口没有受控外观边界 | 热架构仅声明 sealed cassette / underbody conduction / internal mixing，现有受控外观中无签核 heat-rejection surface、外部风道或不可涂覆区 | 当前 A01-A10 没有 `thermal_keepout` / `heat_rejection_surface` 责任件；validator 也不检查 | 泄压口不是日常散热口。没有热工程输入前不能声称外观未牺牲 thermal。必须由热团队冻结导热底板/换热器外表面、面积、涂层、周边间隙和清洁路径，再由皮肤让位。 | `function.all.thermal_interface.evidence`: 缺少受控 interface 或 signed evidence 即 hard fail；有接口后检查 skin 与 thermal keep-out 交体积=0、有效面积不减、无回流到乘员区、涂层/污染限制已绑定。 |
| P0-11 final GLB 的隐藏策略没有逐源件证明 | `_source_keep` 只保留 tyre/hub/seat cushion 和 Follow weather seals，其余源 geometry 一律从 final 隐去 | 只有部分新件（如 table top）声明 `final_presentation_proxy_for`；多数靠名称猜测 | 当前 final GLB 可以在没有真正包覆/通路时看起来“干净”。必须建立逐 state、逐 source occurrence 的 disposition ledger。 | `presentation.<state>.source_disposition_complete`: controlled GLB 中每个 geometry 恰有一种 disposition；`replace_surface` 必须绑定具体 proxy；`conceal_behind_access` 必须绑定 door+release；`retain_exposed` 必须进入 allowlist；未知/重复 disposition 直接 fail。 |

## 3. 必须保留或受控表达的完整接口清单

下表中的“当前状态”只说明 CAD 中是否有一个代理，不代表功能已验证。

### 3.1 低位感知、状态与 RF

| Gate ID | 状态 | 受控对象 | 当前最终 part | 当前风险/缺口 | Validator 谓词 |
|---|---|---|---|---|---|
| `FG3.sensor.front_tof.left/right` | ALL | `follow_front_tof_left/right_window` | `A01_front_left/right_tof_window` + `A01_perception_horizon_carrier` | 约 89 mm 前投影依赖三条光筒；现有 gate 只数窗口，不证明筒内无挡、无串扰、可排水 | Y/Z 中心差 `<=0.5 mm`；最终窗覆盖源投影 `>=100%`；沿 -X 光筒 corridor 与所有 opaque part 交体积=0；左右必须各一件 |
| `FG3.sensor.leg_scanner` | ALL | `follow_leg_scanner_window` | `A01_front_leg_scanner_window` + carrier | 与 ToF 同类；还需避免脚井/污水遮挡 | 中心/投影/corridor 同上；独立窗口恰好一件；最低排水口低于光筒最低点 |
| `FG3.sensor.tactile_bumper` | ALL | `follow_front_tactile_bumper_membrane` | `A01_front_tactile_bumper_skin` | 当前位置基本连续，但未验证源压力边覆盖、壳间缝和更换路径 | Y/Z 投影重叠 `>=95%`；最终膜位于最前外表面；源膜到代理间隙 `0..2 mm`；不得被 A01 nose 覆盖 |
| `FG3.sensor.side_ultrasonic.four_corners` | ALL | front/rear × left/right 四个 face | 四个 `A02_side_ultrasonic_face_*` | 当前 geometry 有四个，但现有 coverage 只要求 `minimum_count=2 + bilateral`，可少掉前/后各一件仍通过 | 按 `{front_left,front_right,rear_left,rear_right}` 精确集合检查；中心差 `<=1 mm`；外法线一致；每件 corridor 无不透明 skin |
| `FG3.sensor.cliff_ir.four_corners` | ALL | 四个下视窗 | 四个 `A02_cliff_ir_window_*` | **P0-05**，最终面在源窗上方 | 采用 P0-05 的 egress-axis/retain-or-replace 检查 |
| `FG3.rf.side_uwb.left/right` | ALL | `follow_uwb_side_radome_left/right` | `A04_side_uwb_radome_left/right` | 位置有代理，但未检查 paint/镁门/紧固件造成的 RF shadow | 左右各一；中心差 `<=8 mm` 仅在有明确 RF corridor 时允许；corridor 内不得有 conductive part；材质/涂层介电证据必填 |
| `FG3.rf.rear_uwb` | ALL | `follow_uwb_rear_radome` | `A10_rear_uwb_radome` | **P0-02**，镁门皮阻断 | 采用 P0-02 |
| `FG3.sensor.rear_tof` | ALL | `follow_rear_tof_window` | `A10_rear_tof_window` + A10 through-tunnel | 当前 A10 已切 tunnel，但未把源窗、tunnel、最终窗作为同一光路验证 | Y/Z 中心差 `<=0.5 mm`；+X corridor 无挡；tunnel 最小截面覆盖源窗 `>=100%`；最终窗可从外部清洁/更换 |
| `FG3.status.rear` | ALL | `hmi_rear_status_light` | `A10_rear_status_lens` | 存在，但“2 m 可读、非颜色冗余”只能由体验样机证明 | CAD 检查位置/外露/不被门遮；evidence 检查 2 m、5 秒、色觉/听力差异和移动/停稳/故障语义不复用 |
| `FG3.rf.hidden_antennas` | ALL | `follow_hidden_backrest_antenna_left/right` | 无独立 radome；依赖 A04/A06 非导电皮肤 | 隐藏天线可以不显露，但必须有 RF keep-out；当前没有 proxy binding/涂层/金属禁区 | 左右 antenna occurrence 均绑定 `internal_enclosed` 和 `rf_keepout`; keep-out 与 conductive skin/fastener 交体积=0；皮厚、涂层、介电与 OTA evidence 必填 |

### 3.2 HMI、控制权与安全状态

| Gate ID | 状态 | 受控对象 | 当前最终 part | 当前风险/缺口 | Validator 谓词 |
|---|---|---|---|---|---|
| `FG3.hmi.left_display` | ALL | `hmi_status_display_left` | `A05_left_status_display_window` + bezel | 代理存在；缺少 source/proxy datum binding 和可视角/眩光证据 | 中心、倾角、有效显示开口与 source 差 `<=0.5 mm/0.5°`；无壳遮挡；材料/evidence 绑定 |
| `FG3.hmi.qi_target` | ALL | Qi coil / presence-temperature sensor | `A05_left_qi_target_ring` | 目标环存在；未检查线圈轴、金属 keep-out、FOD/热传感区域是否被最终材料改变 | 目标环/coil 同轴 `<=1 mm`；规定半径内无导电 skin；最终堆叠厚度与 Qi/FOD/温升 evidence 必填 |
| `FG3.safety.mechanical_estop` | ALL | `hmi_mechanical_emergency_stop` | `A05_left_mechanical_emergency_stop` + guard | 按钮 proxy 与源位置一致；现有 validator 主要靠名称/大范围位置 | 按钮轴/中心/直径逐件绑定；外部可达 corridor；guard 不侵入操作圆柱；按钮必须 source-linked 而非仅有红色圆柱 |
| `FG3.hmi.drive_pod` | R/X；F/C 收纳 | pod / joystick / authorisation key | 三个 A05 right parts | **P0-06**；此外状态逻辑必须明确 Focus 是停驶但 pod 是否保留 | R/X 逐件 datum check；F/C final 不得出现外部 drive pod；X 若保留需 `drive_disabled=True` 的状态证据，不能把存在等同于授权 |
| `FG3.safety.right_transfer_lock` | ALL，Transfer 时解锁 | right transfer hinge/link/positive lock | 无专门最终 release/witness | **P0-07** | 采用 P0-07，并加 Ride/Follow/Café/Focus 的 locked witness 与 Transfer 的无电 release 状态矩阵 |

### 3.3 声学、环境、泄压与热

| Gate ID | 状态 | 受控对象 | 当前最终 part | 当前风险/缺口 | Validator 谓词 |
|---|---|---|---|---|---|
| `FG3.acoustic.lower_voice.four_slots` | ALL | 左右各两个 voice acoustic slots | 四个 `A02_acoustic_mesh_*` | 当前有四个；现有 coverage 只要求两件且 bilateral | 精确要求 `left_1,left_2,right_1,right_2`；中心差 `<=1 mm`；开孔面积、膜材、IP、声衰减 evidence 必填 |
| `FG3.acoustic.mast_microphone` | ALL，隐私状态仍需语义明确 | mast microphone array | `A07_microphone_acoustic_mesh` | 有 underside mesh，但没有 array-to-mesh corridor/遮挡检查 | corridor 无挡；mesh 投影覆盖 array；水膜/风噪/声衰减 evidence；错误身份/旧会话不得自动沿用的系统证据另行检查 |
| `FG3.environment.mast_air_exchange` | ALL | mast environment sensor | `A07_environment_sensor_grille` | 有 grille；未验证空气交换路径、冷凝和 Follow 折叠态朝向 | source-to-grille corridor 无挡；最小自由面积；所有姿态不形成积水杯；疏水膜和响应时间 evidence |
| `FG3.acoustic.rear_horn` | ALL | service rear horn | 无 | **P0-04** | 采用 P0-04 |
| `FG3.pressure_relief` | ALL | battery pressure vent duct | `A10_pressure_relief_vent_bezel` | **P0-03** | 采用 P0-03 |
| `FG3.thermal.heat_rejection` | ALL | 日常热排出/导热面 | 无冻结接口 | **P0-10** | 采用 P0-10；泄压口不能代替散热证据 |

### 3.4 排水、密封与可清洁路径

| Gate ID | 状态 | 当前表达 | 当前风险/缺口 | Validator 谓词 |
|---|---|---|---|---|
| `FG3.drain.follow_weather` | F | builder 保留 `travel_front_tpe_water_lip`、`travel_hinge_local_weather_bridge`、左右 `travel_side_tpe_seal_drain_*` | 这是正确的 `retain_exposed` 思路，但 validator 不验证 final GLB 确实保留四件、A06/A07 没堵住它们 | 精确 source-name allowlist；四件均存在；skin 与排水 outlet 交体积=0；左右出口低于轨道最低点 |
| `FG3.drain.A01_optical_tunnels` | ALL | 无明确 drain part/metadata | 三条长光筒可能积水、泥浆或清洁液；“窗口存在”不足 | 每条 tunnel 有独立低点 drain/clean path；outlet bounds 低于 cavity zmin；截面和堵塞检查 evidence |
| `FG3.drain.A02_side_shells` | ALL | 每侧三个几何 drain notch，但没有独立语义记录 | 注释/boolean cutter 不会被 manifest/validator稳定识别 | 左右各三个 outlet，按位置 X≈`-300,-20,235` 检查；开口穿到最低边；不得与 cliff window corridor 相交 |
| `FG3.drain.A04_seat_ring` | ALL | `A04_open_u_seat_pan_ring` 有两条 liquid path | 仅 metadata count；未验证路径连通/不流入 caddy | 左右各一，出口低于 ring cavity；与 caddy/harness keep-out 不相交 |
| `FG3.drain.A05_table_cassettes` | ALL；展开态更关键 | cassette door/exit throat 有 seal，无 drain | 灰尘、杯液或雨水可进入 430 mm 侧舱，当前没有最低点出口 | 每个物理 cassette 在 door/exit 两种状态都有 drain；不向 HMI/Qi/乘员排液；state-conserved physical ID |
| `FG3.drain.A08_footrest` | R/C/X | tread 3 slots、两 boot drain、两 collar drain | 部件存在；现有 validator 不证明贯通且不朝轮胎/电气喷液 | 三个 tread 槽 + 左右 boot/collar 出口精确计数；所有开口贯通；排液落点避开轮胎接触和电气接口 |
| `FG3.drain.A09_focus_seam` | X | 左右 `A09_focus_centre_seam_seal`，保持 12 mm seam | 表达合理；只检查 AABB gap，不证明排水/逃生/夹指路径贯通 | gap `10..14 mm`；两 seal 不相交；沿 -Z 有连续逃生/排水 corridor；锁件不得桥接 gap |
| `FG3.drain.A10_rear_apron` | ALL | A10 三个 bottom drain breaks | 存在；generic `all.drainage` 可能被任一别处 token 误满足 | rear apron 必须恰有三处、贯通到 zmin，且避开 rear ToF/pressure vent corridor |

### 3.5 门、人工释放、锁止和救援

| Gate ID | 状态 | 受控对象 | 当前最终 part | 当前风险/缺口 | Validator 谓词 |
|---|---|---|---|---|---|
| `FG3.service.upper_equipment_doors` | ALL | 左右 upper drawer/cots latch | `A04_upper_equipment_door_left/right` + release | 门已包住实际四态 GLB 中的上层 drawer fronts；release 与源 latch 不同硬点，需要证明机械 linkage、开门扫掠和锁位 | 左右各一门/一 release；door 对源 drawer 投影覆盖；闭态间隙、开态扫掠；release 绑定 source latch，不能只靠聚合 token |
| `FG3.service.daily_caddy` | ALL | unpowered access lid | `A04_daily_caddy_flush_hatch` | 外盖位于源 lid 上方，允许二级访问，但未证明从外盖到源 lid 的连续取出路径和无电手指入口 | `outer_hatch -> source_lid -> bin` access chain；所有中间壳不堵；`manual_no_power=True`；需要 handhold/release part 或可证明的 lift edge |
| `FG3.safety.footrest_lock_release` | R/C/X | deployed footrest / manual latch / two supports | A08 top/tread/perimeter、两 boot、两 body collar、manual release shell | 包覆方向正确；缺少锁止 mechanical witness、手套/无电操作包络和完整运动 sweep | proxy/source latch 中心差 `<=2 mm`；release corridor；`manual_no_power=True`；左右支持全 sweep clearance；锁止 witness 在 Ride 可读 |
| `FG3.rescue.recovery_handle` | ALL | stowed crossbar + left/right positive latches | `A04_recovery_handle_grip_shell` + `grip_inlay` | 新增 grip inlay 合理；但一个聚合 `positive_latches` token 不能证明左右两锁可触/已锁，也未检查拉出 sweep | source crossbar 全包覆但 grasp corridor 保留；左/右 latch 分别绑定 release/witness；开底手包络；stowed/deployed sweep 和 113 kg 级单人救援 evidence |
| `FG3.service.rear_door` | ALL | door / charge / disconnect / brake release | A10 door skin | **P0-09**；现有 `_extract_openings` 会把一个门的聚合 metadata拆成四个“已满足” opening，属于假证据 | 三个内部接口分别绑定 occurrence、位置和 door-open access；外部 release 单独 part；服务门闭态不等于内部接口可访问 |
| `FG3.service.charge_port` | ALL；Travel/charging | guarded charge port | 门后，无独立 final proxy | 平时隐藏正确，但必须能无电开门并插接，线缆不得跨救援/排水路径 | door-open state 中 connector envelope 无挡，插拔 corridor/弯曲半径/应力释放；闭态有密封和状态联锁 |
| `FG3.service.battery_disconnect` | ALL；Service | guarded disconnect | 门后 | 需要防误触、锁定/挂牌和无电进入 | access chain + two-action guard + lockout evidence；不得被 charge cable 或门铰遮蔽 |
| `FG3.service.brake_release` | ALL；STRANDED_SAFE | guarded brake release | 门后 | 必须在整机无主电时可达，且松手/复位逻辑明确 | `manual_no_power=True`；门和 release 均可无电；操作包络；释放状态必须有机械 witness，不能只靠屏幕 |

### 3.6 桅杆与工作感知

| Gate ID | 状态 | 受控对象 | 当前最终 part | 当前风险/缺口 | Validator 谓词 |
|---|---|---|---|---|---|
| `FG3.mast.shrouds` | ALL | outer/inner mast、guides、reeving、harness | `A07_mast_fixed_outer_sleeve`、`moving_inner_sleeve`、`root_transition_fairing`，F 另有 cassette cover | 当前有最终套件；仍需证明完整 source mechanism containment、wiper/pinch/污染界面，而不是只检查存在和 3 mm clearance | source mechanism 各 occurrence 绑定 `internal_enclosed`；外包络全覆盖；移动成员 sweep clearance；上下端 wiper/排水/pinch gap；Follow cassette 对完整折叠 sweep 检查 |
| `FG3.mast.lock_pins.bilateral` | ALL | 左右 mast lock pin | fixed sleeve 上两个 slots（同一 part metadata） | 现有 coverage 只要求一个匹配 part，无法证明两个真实孔和左右硬点 | 精确要求 source `-1/+1` 两个 station；slot 中心/尺寸与源 pin 公差；每侧独立 inspection/release corridor；一侧缺失即 fail |
| `FG3.mast.camera_depth_window` | ALL | 4K + depth/IR camera | `A07_sensor_beam_smoked_window` | 一个组合窗口可接受，但必须明确两光轴和涂层区域；不能仅凭 280×40 黑条 | 两 source camera 投影均在可透区域；各 optical corridor 无挡；可见/IR 透过、畸变、加热/结露和清洁 evidence |
| `FG3.mast.privacy_shutter` | F/R/C closed，X parked | physical shutter | `A07_physical_privacy_shutter` | **P0-01** | 采用 P0-01；另要求闭态遮住 camera active apertures，parked 态不遮 camera/fill-light，状态可在 2 m 读出 |
| `FG3.mast.fill_light` | X | left/right fill light | 无 | **P0-08** | 采用 P0-08 |
| `FG3.mast.microphone_environment` | ALL | mic array / environment sensor | acoustic mesh / grille | 代理存在；需 corridor、姿态排水和隐私状态证据 | 采用 3.3 对应检查 |

### 3.7 桌板、升降和正锁

| Gate ID | 状态 | 受控对象 | 当前最终 part | 当前风险/缺口 | Validator 谓词 |
|---|---|---|---|---|---|
| `FG3.table.cassette_state` | F/R 两门闭；C 左门闭/右 exit；X 双 exit | 同一物理左右 table cassette | `A05_table_cassette_door_*` 或 `exit_bezel/throat_seal_*` | 当前状态矩阵已表达；仍需同一 physical ID、排水、夹指和门锁证据 | 每 state/side 恰有 door XOR exit；同一 occurrence ID 守恒；deployed leaf 对应 side 必须 exit；stowed leaf 必须 door；不得生成第二套桌件 |
| `FG3.table.final_leaf_surface` | C 右；X 左右 | `desk_panel_left/right` | `A09_table_top_skin_*`、edge band、underbelly | 表面代理已新增，但 top/edge 与只读源 panel 占据同体积；必须明确是 `replace_surface` 而非另加碰撞实体 | 每叶恰有一 `final_presentation_proxy_for=desk_panel_*`; disposition=`replace_surface`；若 additive 则与 source 交体积=0；若 replacement 则需被替换层厚度/体积/装配定义 |
| `FG3.table.lift_boots` | C 右；X 左右 | lift tube/column boot | 三段 `A09_table_lift_boot_*` + root fairing/bridge | 三段视觉表达已加入；需证明全 stroke、顶部 11 mm、wiper 和夹指界面完全受控 | source tube/boot 全 sweep 包络在 final boot/root 内；最小径向隙；三段重叠不拉脱；顶部/底部 wiper 和 drain；不得只检查 bbox 高度 |
| `FG3.table.cafe_locks` | C | translation lock + rotation lock pin | root fairing openings、release paddle、positive-lock witness | part 已有；release paddle 与源 lock 之间是未定义 linkage，锁止状态不能只由装饰环暗示 | 两个 source lock 分别绑定 station；release linkage ID；source/proxy 中心容差；90°/80 mm 两终点 mechanical witness；左开放侧不得出现控制件 |
| `FG3.table.focus_two_lock_stations` | X | source lock pins/latches at X=-555/-255 | 左右各两个 `A09_focus_lock_release_paddle_*`，edge/top/underbelly openings | 源架构是两个 station，当前生成四个 leaf-local paddle；可以是双侧联动，但现有 CAD/validator直接假定“四个独立”而没有 linkage 证明 | 精确要求 station ID 集合 `{-555,-255}`；每 station 恰有一个 source lock；若双侧各一 paddle，二者必须共享同一 mechanical linkage ID、单侧释放故障策略和状态一致性，不能用 part 数量代替架构 |
| `FG3.table.focus_centre_gap` | X | 12 mm seam / two centre latches | edge/top/underbelly cutouts + two seam seals | AABB gap 当前可检查；还需保证锁/释放不桥接逃生和排水 corridor | 最终 gap `10..14 mm`；任一非允许 lock pin 对 seam corridor 的占用受控；无锋利边；无电 release 后可在 10 s 逃生的实物 evidence |
| `FG3.table.manual_no_power_release` | C/X | table locks | Café/Focus paddles | 材质和命名暗示机械件，但 metadata 没有统一 `manual_no_power=True`、操作力和手套包络 | 每个物理 lock station 有无电 release；reach cylinder 无壳/杯/桌边干涉；操作力、戴手套、5F～95M 和 10 s 逃生 evidence |

## 4. 当前 validator 的假通过路径

1. `_proxy_parts` 只按 part 名或 `functional_opening` token 匹配，没有要求绑定具体 source occurrence；一个外形相似的假窗口也可通过。
2. `_add_proxy_gate` 多数只数件数和左右侧，不检查功能轴、外露方向、光/RF/声/气 corridor 或源硬点。
3. `coverage.*.A02.ultrasonic_faces` 最少只要两件且左右都有，四角系统可缺一半。
4. `coverage.*.A04.equipment_release` 最少只要一件，不能证明左右门各自可开。
5. `coverage.*.A07.lock_pin_access` 一个 sleeve 的 token 就能通过，不能证明左右两个 slot 与两个源 pin 对齐。
6. A09 的 lock/release token 同时写在 edge、top、underbelly、root fairing 和 paddle 上，聚合 shell 能冒充真实锁件；应按 station/source occurrence 去重。
7. `_extract_openings` 会把 `service_aperture_mm` 或一个 door 的聚合 metadata 复制成 rear door、charge、disconnect、brake 四个 opening；没有 door-open access chain。
8. `all.drainage` 只需任何一个 metadata key 含 `drain`，不能证明每个液体低点都有出口。
9. clearance validator 只检查 tyre/rocker/mast，不检查 source-proxy hardpoint 对齐、source 被皮肤遮挡或 conductive/opaque material 插入功能路径。
10. `_source_keep` 是 presentation allowlist，不是功能覆盖证明；当前 builder 在校验前就会隐藏所有未 allow 的源件，造成后 UWB、horn、fill light 等“图上干净、物理失效”。

## 5. 建议新增的 validator 数据契约

每个最终功能 proxy 至少增加以下 metadata；缺失时不得进入量产外观 PASS：

```text
source_occurrence_ids: [controlled GLB/STEP occurrence names]
disposition: retain_exposed | replace_surface | conceal_behind_access | internal_enclosed
functional_axis: +X | -X | +Y | -Y | +Z | -Z | radial
exposure_states: [follow, ride, cafe, focus]
access_via: optional final door occurrence
release_via: optional final release occurrence
manual_no_power: true|false
minimum_open_area_mm2: optional signed requirement
material_function: optical_ir | optical_visible | rf_transparent | acoustic_transparent | pressure_vent | drain | touch | structural_cover
lock_station_id / linkage_id: required for every positive lock and release
evidence_refs: RF / optical / acoustic / IP / thermal / usability / safety test identifiers
```

建议在 `validate_class_a.py` 增加以下通用 helper，而不是继续堆名称关键词：

```text
require_source_disposition_complete(state)
require_proxy_datum(source, proxy, center_tol, angle_tol)
require_projected_coverage(source, proxy_or_aperture, axis, ratio, margin)
require_clear_functional_corridor(source, exterior, axis, forbidden_materials)
require_minimum_free_area(corridor, signed_area)
require_access_chain(exterior_door, release, internal_interface, no_power)
require_lock_station(source_lock, witness, release, linkage_id, states)
require_drain_path(cavity_low_point, outlet, minimum_area)
require_source_sweep_enclosed(source_occurrences, proxy_parts, clearance)
```

## 6. 建议实现顺序

1. 先冻结 source-disposition ledger，并让 final GLB 对任何未绑定源件直接构建失败；
2. 修复 P0-01～P0-09 的几何关系，P0-10 等待热工程冻结接口；
3. 把四类 corridor（光学、RF、声学、泄压）和三类 access chain（服务门、无电释放、正锁 station）写成 B-Rep hard checks；
4. 再补逐区域排水、密封、清洁和手套可达 checks；
5. 最后运行四态 STEP 复导、source hash、运动 sweep、正投影/QA overlay 和 1:1 实物功能验证。

只有上述 hard checks 全部通过，才能说“外露部件已被真正包覆，同时功能接口没有被外观牺牲”。当前结果仍是方向 CAD，不能称为量产最终外观放行。
