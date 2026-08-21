# WorkCore E6 · R14 Interactive Review

R14 外观、四种产品状态、开合结构与内部布局的 Three.js 交互评审页。项目独立位于 `interactive/r14_threejs_review`，没有修改原有 STEP 文件。

## 启动

需要 Node.js 22.13 或更高版本。

### 完全离线查看（推荐）

双击项目根目录的 `OPEN_R14_OFFLINE.cmd`。它只启动 `127.0.0.1:4173` 本机服务并打开默认浏览器，不访问在线 Site，也不会从网络下载模型、脚本、字体或材质。已经生成的 `dist/`、五个 GLB 和浏览器资源全部保存在本文件夹内。

也可以手动运行：

```powershell
npm start
```

然后打开 `http://127.0.0.1:4173/`。

### 开发与重新构建

```powershell
npm install
npm run dev
```

浏览器打开终端给出的本地地址。生产构建：

```powershell
npm run build
npm start
```

`npm start -- --hostname 127.0.0.1 --port 4173` 可显式指定本地监听地址。项目内的生产服务器会正确处理 Windows 静态资源路径。

## 交互

- 拖动旋转，滚轮缩放，点击模型结构查看或操作。
- 底部切换 Follow / Ride / Café / Focus；键盘快捷键为 `1`–`4`。
- 右上切换 Object / Internal / Exploded；快捷键为 `E` / `I` / `X`。
- `Review items` 列出靠背、桅杆、脚踏、桌板、扶手盖、设备仓、后服务门、前部感知带和固定摇杆。
- Internal 模式可按 Power / Drive / Control / Sense 筛选，并用 Section 滑块剖切外壳。

## 事实边界

- `ENDPOINT`：R14 存在源外观端点或定义铰点，可用于外观与布局评审，不等于机构成立。
- `PREVIEW`：仅为运动方向/维护空间预览，不能视作 STEP、碰撞、导轨、铰链或量产机构验证。
- `INSPECT`：仅定位固定结构，不执行运动。
- 内部模型 `workcore_internal_layout.glb` 是 E6-DFR3 历史包装子集，不是完整内部总成，也不是 R14 / DFR4 / DFR5 量产冻结真值。页面固定显示其来源、缺项和非量产边界。
- R14 QA 中的 `PASS` 只代表 Blender 外观保存文件检查通过，不代表机构运动、STEP 或量产结构验证通过。

## 已冻结的页面约束

- 摇杆始终固定外露在右扶手顶端，不随扶手盖或桌板移动。
- 左侧 Qi 区随左扶手盖运动；小屏幕固定在母表面，保持前高后低。
- Follow 为靠背折叠后的闭合表面意图，桅杆仍存在但处于低位；桌板不能从 Follow 直接弹出。
- Ride 默认展开脚踏；Café / Focus 默认收纳但允许手动打开。
- 差速轮维持半包覆，设备仓与后服务门在 R14 外观层只表现为齐平门缝。

## 模型资产

`public/` 内包含生产服务所需的扁平化模型资产：

- `workcore_r14_follow.glb`
- `workcore_r14_ride.glb`
- `workcore_r14_cafe.glb`
- `workcore_r14_focus.glb`
- `workcore_internal_layout.glb`
- `asset_manifest.json`（文件大小、来源修订与 SHA-256）

前三态/Focus GLB 来自 R14 Blender 四态文件；内部 GLB 保留 DFR3 历史基线身份，页面不会用它覆盖当前 R14 的 HMI、摇杆、靠背或桅杆设计。
