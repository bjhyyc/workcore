# C 盘清理与可逆归档记录（2026-07-25）

## 结果

- 开始时 C 盘可用空间：约 1.153 GiB
- 完成复测后 C 盘可用空间：约 3.45 GiB（Codex 日志仍在持续写入，数值会小幅波动）
- 本轮 D 盘归档：`D:\workcore_archive\2026-07-25_c_drive_cleanup_round2`
- 归档总量：约 3.223 GiB，36,796 个文件
- 策略：只做可逆转移；未永久删除当前产品资产、任务历史或活动数据库

## 已转移

| 分类 | 大小 | 内容 |
|---|---:|---|
| `downloaded_installers_and_archives` | 1.109 GiB | Downloads 中 25 个安装包、APK 与压缩包 |
| `active_relocated` | 1.085 GiB | WorkCore `.venv`；原路径保留 Junction |
| `regenerable_caches` | 0.668 GiB | npm 可再生缓存 |
| `workcore_historical` | 0.230 GiB | V11 R01–R13 状态/预览/QA、R13 final、旧验证输出与旧 HTML |
| `codex_stale_temp` | 0.132 GiB | 可移动的旧 Codex 安装/插件临时项 |

历史 WorkCore 内容包括：

- V11 `blender\states\r01`–`r13`
- V11 `renders\preview\r01`–`r13`
- V11 `renders\final\r13`
- V11 `qa\r01`–`r13`
- `step_anchored_v2\class_a_cad\.validation_work`
- V8 两个外围视觉预检目录
- 专利图 QA 的浏览器临时 profile
- R14 Three.js 的 `.vinext`、`.wrangler` 可再生目录
- 根 `build` 中 E2、E3 和旧 E4 离线审查 HTML

## 明确保留

- 当前 V11/R14 全部正式资产
- V8 母底、四个锁定 clean GLB 与引用库
- `step_anchored_v2`、DFR4、DFR5 和正式 STEP/GLB
- 当前根 `build`
- R14 Three.js 的 `public`、`dist` 和 D 盘 `node_modules`
- `C:\Users\86135\.codex\sessions`
- `logs_2.sqlite`、WAL 和当前 Codex 缓存
- 正被 Blender MCP/Python 使用的 UV cache

## 复测

- R14 Three.js：构建成功，3/3 自动测试通过
- 受控 GLB 字节与交互/来源约束通过
- `.venv` Junction：14,216 个文件、1,165,200,542 字节，与迁移前一致
- CadQuery 2.8.0、NumPy 2.4.6 可从迁移后的环境导入
- STEP/桌板包装回归：11/11 测试通过，包含 61 帧抽取、0–105° 开盖扫掠、折叠包络、三段抽取和 STEP 往返

注：`.venv\Scripts\python.exe` 仍指向此前已不存在的本机 Python 3.12 路径，这是迁移前已有的失效启动器。工程采用受控 Codex Python 运行时加 `.venv\Lib\site-packages`，完整回归已通过。

## 当前未处理

- R14 复测后 npm/npx 活动重新产生约 852 MiB 缓存；检测到 npm/npx 进程仍在运行，因此没有强行移动。
- Codex `sessions` 约 16.4 GiB，其中当前任务文件仍在写入。
- Codex `logs_2.sqlite` 约 2.96 GiB，当前正在使用。
- UV cache 约 3.03 GiB，多项 Python/Blender MCP 进程正从中运行。

这些内容只能在完全退出 Codex、npm/npx 与相关 Blender/Python 服务后进行第二阶段清理。
