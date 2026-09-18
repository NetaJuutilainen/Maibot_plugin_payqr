# 麦麦赛博讨口子（maibot_plugin_payqr）

当 MaiBot 的 LLM 在对话中觉得自己**没钱了、想收打钱/转账/赞助/红包**时，自动发送你配置的收款码图片。

移植自 AstrBot 插件 [astrbot_plugin_payqr](https://github.com/luori7hao/astrbot_plugin_payqr)（MIT），行为保持一致：收款码的触发时机完全由 LLM 自主判断。

## 效果

```
群友：麦麦你好穷啊哈哈哈
麦麦：（发送收款码图片 + "给我打钱！👇"）
麦麦：哼，扫了就是好朋友！
```

## 安装

1. 把本目录（整个 `maibot_plugin_payqr/`）放进 MaiBot 的 `plugins/` 目录；
2. 在 WebUI（默认 `http://127.0.0.1:8001`）插件管理里加载/启用插件；
3. 放入你的收款码图片（见下）。

## 配置收款码（必须做一步）

把你的收款码图片命名为 `qr.png`（或任意名字，见配置项），放到插件数据目录：

```
MaiBot/data/plugins/github.netajuutilainen.payqr/qr.png
```

- 支持 `png / jpg / jpeg / bmp / webp`，大小 ≤ 10 MB；
- **替换图片不需要重启或重载插件**，下次调用自动生效；
- `qr_filename` 只接受该数据目录（及其子目录）内的**相对文件名**，不支持绝对路径——出于安全考虑，插件不会读取 `ctx.paths` 授权范围之外的任何文件。

> 请勿把自己的收款码提交到公开仓库，本仓库的 `.gitignore` 已排除根目录下的图片文件。

## 配置项

| 配置 | 默认值 | 说明 |
|---|---|---|
| `payqr.qr_filename` | `qr.png` | 收款码图片文件名，仅支持插件数据目录/临时目录内的相对路径（含子目录） |
| `payqr.caption` | `给我打钱！👇` | 随收款码一起发送的文字，留空则只发图片 |
| `payqr.cooldown_seconds` | `60` | 同一会话两次发送的最小间隔（秒），防止被群友反复骗图；`0` 表示不限制 |
| `payqr.group_whitelist` | 空 | 群聊白名单（QQ 群号列表）。**为空不限制**；非空时仅列表中的群可触发，私聊不受影响 |
| `prompt.tool_description` | （内置默认） | 收款码工具的触发提示词，Planner 每轮都会阅读；改完即时生效，清空恢复内置默认 |

## 工作原理

- 注册一个 MaiBot LLM 工具 `send_payment_qr`（`core_tool=True` + `visibility="visible"`，常驻 Planner 工具列表，与 AstrBot 版"注册即常驻"的行为一致），由 Planner 自主决定何时调用；
- 触发提示词通过 `maisaka.planner.before_request` Hook 在每轮 Planner 请求前按配置动态注入——宿主构建工具列表时只保留注册时的简短描述，插件用配置里的完整提示词覆盖它，因此提示词可以在 WebUI 配置中随意修改、即时生效；
- 调用时优先用 `send.hybrid` 把配文和图片合成一条消息发送；适配器不支持时自动回退为"文本 + 图片"分开发送；
- 内置会话级冷却（AstrBot 原版没有，这里防刷屏用），冷却期内 LLM 再次调用只会收到"刚刚已经发过"的提示，不会重复发图。

## 安全与使用须知

- **路径受限**：插件只会读取插件数据目录（`data/plugins/github.netajuutilainen.payqr/`）和临时目录内的文件，配置里填绝对路径或 `../` 一律无效。请只放置你自己拥有的收款码图片。
- **公开群使用前请先确认人设与提示词**：LLM 自主讨钱在公开场合可能造成观感问题。启用前请确认人格设定与 `prompt.tool_description` 符合你的预期；也可以用 `payqr.group_whitelist` 把功能限制在指定群里。
- **触发提示词只影响本插件**：修改 `prompt.tool_description` 不会影响 bot 的其他行为；请勿把其他工具的名称写进提示词以免误导 Planner。

## 提高触发率：给人设加"动机"

工具提示词解决的是"怎么发码"，而触发率的上限取决于人设里有没有"想讨钱"的动机。建议在人格设定中加一句，例如：

> 你很穷，经常哭穷，喜欢开玩笑地向群友讨钱、求投喂。

人设给动机、工具提示词给方法，两边配合触发最自然。若触发仍不理想，优先调整插件配置里的 `prompt.tool_description`（写清你希望触发的具体说法），不要去改官方 planner 提示词——那是全局资产，升级会丢、影响所有行为。

## 本地测试

仓库自带不依赖真实 MaiBot 宿主的离线测试（基于真实 maibot-plugin-sdk 2.8.0 + 伪造 ctx）：

```
python tests/run_tests.py
```

覆盖：工具元数据、发送成功/回退链路、冷却、配置热更新、缺图/禁用等分支。

## 常见问题

- **一直不触发**：触发与否由 LLM 判断。话题里明确出现"穷/打钱/转账/赞助/发红包"等字眼最容易触发；可以看主程序日志里 `plugin.invoke_tool` 是否有 `send_payment_qr`。
- **发送了但群里没图**：查主进程日志 `[cap.send.*]` 与适配器日志，确认协议端支持发图。
- **`E_CAPABILITY_DENIED`**：确认 `_manifest.json` 的 `capabilities` 未被改动，修改能力声明后需要完整重启 MaiBot。

## 致谢与许可

- 原插件：[luori7hao/astrbot_plugin_payqr](https://github.com/luori7hao/astrbot_plugin_payqr)（MIT License, © 2026 luori7hao）
- 本仓库同样以 MIT 许可发布。
