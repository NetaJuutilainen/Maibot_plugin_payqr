# 更新日志

本文件记录各版本显著变更（WebUI 插件详情页按根目录固定文件名 `CHANGELOG.md` 读取）。
版本号遵循语义化版本；按版本的详细说明另见各 [GitHub Release](https://github.com/NetaJuutilainen/Maibot_plugin_payqr/releases)。

## [1.3.1] — 2026-10-06

### 加固（AI 评审建议落实）

- 工具失败文案不再携带宿主绝对路径，只保留文件名与错误类型（防止被 LLM 复述进群）
- 默认触发提示词收敛：去掉"没有任何风险，大胆使用"，改为要求按聊天氛围判断、场合不合适时不要调用
- README：「安全与使用须知」前置到安装之前，标注默认 `list_mode=off` 为最宽松档并建议公开群使用者收紧
- `maisaka.planner.before_request` Hook 注释标注为 MaiBot 1.2.x 经验行为（非官方接口承诺）

**Full Changelog**: https://github.com/NetaJuutilainen/Maibot_plugin_payqr/compare/v1.3.0...v1.3.1

## [1.3.0] — 2026-09-19

### Features

- 统一会话黑白名单：`list_mode`（off / blacklist / whitelist）三档切换，`chat_list` 名单中**群号与 QQ 号共用**——群聊按群号匹配，私聊按对方 QQ 号匹配
- 白名单模式对无法识别身份的会话按拒绝处理（fail closed）；黑名单模式未命中即放行
- 取代 v1.2.0 的 `group_whitelist`（配置由 Runner 自动迁移）

**Full Changelog**: https://github.com/NetaJuutilainen/Maibot_plugin_payqr/compare/v1.2.0...v1.3.0

## [1.2.0] — 2026-09-19

### 加固（AI 评审建议落实）

- `qr_filename` 只允许插件数据目录/临时目录内的相对路径（`resolve()` + `relative_to()` 双重校验），绝对路径、`..` 穿越、盘符一律拒绝
- README 新增「安全与使用须知」；公开群启用前确认人设与触发提示词

### Features

- 新增 `group_whitelist` 群聊白名单（为空不限制，非空仅名单内群可触发，私聊不受影响）

**Full Changelog**: https://github.com/NetaJuutilainen/Maibot_plugin_payqr/compare/v1.1.0...v1.2.0

## [1.1.0] — 2026-09-12

### Features

- 触发提示词可在 WebUI 插件配置中自定义（`prompt.tool_description`），保存即时生效，清空恢复内置默认

### 修复

- 根因修复：宿主构建 Planner 工具列表只取注册时的简短描述，`detailed_description` 里的长提示词从未到达 LLM——新增 `maisaka.planner.before_request` Hook 在每轮请求前按配置覆盖工具描述

**Full Changelog**: https://github.com/NetaJuutilainen/Maibot_plugin_payqr/compare/v1.0.0...v1.1.0

## [1.0.0] — 2026-09-12

### Features

- 首个正式版：LLM 工具 `send_payment_qr` 常驻 Planner 工具列表（`core_tool=True` + `visibility="visible"`），话题涉及没钱/打钱/转账/赞助/红包时自主调用
- `send.hybrid` 图文合发，适配器不支持时自动回退"文本 + 图片"分开发送
- 会话级冷却防刷屏（默认 60 秒，可配置）
- 收款码图片热替换，无需重启；配置版本化（`config_version`）

## [0.1.1] — 2026-09-12

- 插件 ID 由 `github.luori7hao.payqr` 改为 `github.netajuutilainen.payqr`（提交插件市场），数据目录随之迁移

## [0.1.0] — 2026-09-12

- 初版：移植自 AstrBot 插件 [astrbot_plugin_payqr](https://github.com/luori7hao/astrbot_plugin_payqr)（MIT）
