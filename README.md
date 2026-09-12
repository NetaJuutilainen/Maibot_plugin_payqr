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
- 也可以在插件配置里把 `qr_filename` 改成绝对路径，指向任意位置的图片。

> 请勿把自己的收款码提交到公开仓库，本仓库的 `.gitignore` 已排除根目录下的图片文件。

## 配置项

| 配置 | 默认值 | 说明 |
|---|---|---|
| `payqr.qr_filename` | `qr.png` | 收款码图片文件名，按 数据目录 → 临时目录 → 插件目录 → 工作目录 → 绝对路径 顺序查找 |
| `payqr.caption` | `给我打钱！👇` | 随收款码一起发送的文字，留空则只发图片 |
| `payqr.cooldown_seconds` | `60` | 同一会话两次发送的最小间隔（秒），防止被群友反复骗图；`0` 表示不限制 |

## 工作原理

- 注册一个 MaiBot LLM 工具 `send_payment_qr`（`core_tool=True`，常驻 Planner 工具列表，与 AstrBot 版"注册即常驻"的行为一致），工具描述里写明触发场景（没钱/转账/赞助/红包等），由 Planner 自主决定何时调用；
- 调用时优先用 `send.hybrid` 把配文和图片合成一条消息发送；适配器不支持时自动回退为"文本 + 图片"分开发送；
- 内置会话级冷却（AstrBot 原版没有，这里防刷屏用），冷却期内 LLM 再次调用只会收到"刚刚已经发过"的提示，不会重复发图。

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
