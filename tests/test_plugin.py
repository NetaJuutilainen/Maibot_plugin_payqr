"""插件行为测试：真实 maibot_sdk 2.8.0 + 伪造 PluginContext，不依赖真实 MaiBot 宿主。"""

import asyncio
import base64
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import plugin as payqr  # noqa: E402

# 1x1 红色 PNG
PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PNG_1X1_BYTES = base64.b64decode(PNG_1X1_B64)


class FakePaths:
    def __init__(self, data_dir: Path, runtime_dir: Path):
        self.data_dir = data_dir
        self.runtime_dir = runtime_dir


class FakeSend:
    """记录 send.* 调用；可配置 hybrid 失败/异常以测试回退链路。"""

    def __init__(self):
        self.calls: list[tuple] = []
        self.hybrid_result = True
        self.hybrid_raise: Exception | None = None
        self.image_result = True

    async def hybrid(self, segments, stream_id, **kwargs):
        self.calls.append(("hybrid", segments, stream_id))
        if self.hybrid_raise:
            raise self.hybrid_raise
        return self.hybrid_result

    async def image(self, image_data, stream_id, **kwargs):
        self.calls.append(("image", image_data, stream_id))
        return self.image_result

    async def text(self, text, stream_id, **kwargs):
        self.calls.append(("text", text, stream_id))
        return True


class FakeCtx:
    def __init__(self, data_dir: Path, runtime_dir: Path):
        self.paths = FakePaths(data_dir, runtime_dir)
        self.logger = logging.getLogger("test.payqr")
        self.send = FakeSend()


def make_plugin(tmp: Path, drop_qr: bool = True, prompt: dict | None = None, **overrides) -> payqr.PayQRPlugin:
    data_dir = tmp / "data" / "plugins" / payqr.PLUGIN_ID
    runtime_dir = tmp / "runtime"
    data_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if drop_qr:
        (data_dir / "qr.png").write_bytes(PNG_1X1_BYTES)

    plugin = payqr.create_plugin()
    plugin._ctx = FakeCtx(data_dir, runtime_dir)  # 模拟 Runner 注入
    overrides = dict(overrides)
    enabled = overrides.pop("enabled", True)
    config = {
        "plugin": {"enabled": enabled, "config_version": payqr.SUPPORTED_CONFIG_VERSION},
        "payqr": {
            "qr_filename": "qr.png",
            "caption": "给我打钱！👇",
            "cooldown_seconds": 60,
            **overrides,
        },
    }
    if prompt is not None:
        config["prompt"] = dict(prompt)
    plugin.set_plugin_config(config)
    return plugin


def call_tool(plugin, **kwargs):
    return asyncio.run(plugin.send_payment_qr(**kwargs))


def test_tool_metadata():
    plugin = payqr.create_plugin()
    components = plugin.get_components()
    tools = [c for c in components if c.get("name") == "send_payment_qr"]
    assert len(tools) == 1, f"应只注册 1 个 Tool，实际: {[c.get('name') for c in components]}"
    tool = tools[0]
    assert str(tool.get("type", "")).lower() == "tool"
    meta = tool.get("metadata") or {}
    combined = " ".join(str(meta.get(k, "")) for k in ("description", "brief_description", "detailed_description"))
    assert "没钱" in combined, combined
    assert meta.get("core_tool") is True, "core_tool 元数据丢失（会掉进 deferred 池）"


def test_send_success_hybrid(tmp_path):
    plugin = make_plugin(tmp_path)
    result = call_tool(plugin, stream_id="s1")
    assert "成功" in result["content"], result
    calls = plugin._ctx.send.calls
    assert len(calls) == 1 and calls[0][0] == "hybrid", calls
    segments = calls[0][1]
    assert segments[0] == {"type": "text", "content": "给我打钱！👇"}
    assert segments[1]["type"] == "image"
    assert segments[1]["content"] == PNG_1X1_B64
    assert calls[0][2] == "s1"


def test_cooldown_blocks_second_send(tmp_path):
    plugin = make_plugin(tmp_path)
    call_tool(plugin, stream_id="s1")
    result = call_tool(plugin, stream_id="s1")
    assert "刚刚" in result["content"] or "重复" in result["content"], result
    assert len(plugin._ctx.send.calls) == 1, "冷却期内不应再次发送"


def test_cooldown_is_per_stream(tmp_path):
    plugin = make_plugin(tmp_path)
    call_tool(plugin, stream_id="s1")
    result = call_tool(plugin, stream_id="s2")
    assert "成功" in result["content"], result
    assert len(plugin._ctx.send.calls) == 2


def test_cooldown_disabled(tmp_path):
    plugin = make_plugin(tmp_path, cooldown_seconds=0)
    call_tool(plugin, stream_id="s1")
    call_tool(plugin, stream_id="s1")
    assert len(plugin._ctx.send.calls) == 2


def test_fallback_when_hybrid_false(tmp_path):
    plugin = make_plugin(tmp_path)
    plugin._ctx.send.hybrid_result = False
    result = call_tool(plugin, stream_id="s1")
    assert "成功" in result["content"], result
    kinds = [c[0] for c in plugin._ctx.send.calls]
    assert kinds == ["hybrid", "text", "image"], kinds


def test_fallback_when_hybrid_raises(tmp_path):
    plugin = make_plugin(tmp_path)
    plugin._ctx.send.hybrid_raise = RuntimeError("rpc boom")
    result = call_tool(plugin, stream_id="s1")
    assert "成功" in result["content"], result
    kinds = [c[0] for c in plugin._ctx.send.calls]
    assert kinds == ["hybrid", "text", "image"], kinds


def test_no_caption_single_image_segment(tmp_path):
    plugin = make_plugin(tmp_path, caption="  ")
    result = call_tool(plugin, stream_id="s1")
    assert "成功" in result["content"], result
    segments = plugin._ctx.send.calls[0][1]
    assert len(segments) == 1 and segments[0]["type"] == "image", segments


def test_missing_qr_returns_not_configured(tmp_path):
    # 用一个任何候选目录都不存在的文件名，避免被插件目录兜底路径找到
    plugin = make_plugin(tmp_path, drop_qr=False, qr_filename="no_such_qr.png")
    result = call_tool(plugin, stream_id="s1")
    assert "不存在" in result["content"], result
    assert plugin._ctx.send.calls == [], "缺图时不应发送"


def test_unsupported_suffix(tmp_path):
    plugin = make_plugin(tmp_path, qr_filename="qr.gif")
    result = call_tool(plugin, stream_id="s1")
    assert "不支持" in result["content"], result


def test_disabled_plugin(tmp_path):
    plugin = make_plugin(tmp_path, enabled=False)
    result = call_tool(plugin, stream_id="s1")
    assert "未启用" in result["content"], result
    assert plugin._ctx.send.calls == []


def test_no_stream_id(tmp_path):
    plugin = make_plugin(tmp_path)
    result = call_tool(plugin)
    assert "会话" in result["content"], result
    assert plugin._ctx.send.calls == []


def test_image_cache_invalidated_on_file_change(tmp_path):
    plugin = make_plugin(tmp_path)
    qr_path = plugin._ctx.paths.data_dir / "qr.png"
    call_tool(plugin, stream_id="s1")

    bigger = PNG_1X1_BYTES + b"\x00" * 32
    qr_path.write_bytes(bigger)
    old = qr_path.stat().st_mtime
    import os

    os.utime(qr_path, (old + 5, old + 5))  # 确保 mtime 变化
    call_tool(plugin, stream_id="s9")
    image_calls = [c for c in plugin._ctx.send.calls if c[0] == "hybrid"]
    new_b64 = image_calls[1][1][-1]["content"]
    assert new_b64 == base64.b64encode(bigger).decode("ascii"), "图片变更后应重新读取"


def test_hook_rewrites_tool_description(tmp_path):
    plugin = make_plugin(tmp_path, prompt={"tool_description": "自定义提示词ABC"})
    defs = [
        {"type": "function", "function": {"name": "send_payment_qr", "description": "旧描述", "parameters": {}}},
        {"type": "function", "function": {"name": "reply", "description": "系统工具", "parameters": {}}},
    ]
    result = asyncio.run(plugin.hook_planner_tool_prompt(tool_definitions=defs, session_id="s1"))
    assert result["action"] == "continue"
    out = result["modified_kwargs"]["tool_definitions"]
    assert out[0]["function"]["description"] == "自定义提示词ABC"
    assert out[1]["function"]["description"] == "系统工具", "不得改动其他工具的描述"


def test_hook_supports_flat_schema(tmp_path):
    plugin = make_plugin(tmp_path, prompt={"tool_description": "自定义提示词ABC"})
    defs = [{"name": "send_payment_qr", "description": "旧描述", "parameters": {}}]
    result = asyncio.run(plugin.hook_planner_tool_prompt(tool_definitions=defs))
    assert result["modified_kwargs"]["tool_definitions"][0]["description"] == "自定义提示词ABC"


def test_hook_falls_back_to_default_when_empty(tmp_path):
    plugin = make_plugin(tmp_path, prompt={"tool_description": "   "})
    defs = [{"type": "function", "function": {"name": "send_payment_qr", "description": "旧描述", "parameters": {}}}]
    result = asyncio.run(plugin.hook_planner_tool_prompt(tool_definitions=defs))
    assert result["modified_kwargs"]["tool_definitions"][0]["function"]["description"] == payqr.DEFAULT_TOOL_DESCRIPTION


def test_hook_tolerates_missing_payload(tmp_path):
    plugin = make_plugin(tmp_path)
    result = asyncio.run(plugin.hook_planner_tool_prompt(session_id="s1"))
    assert result["action"] == "continue"
    result = asyncio.run(plugin.hook_planner_tool_prompt(tool_definitions="bad", session_id="s1"))
    assert result["action"] == "continue"


def test_absolute_path_rejected(tmp_path):
    # 绝对路径即使真实存在也必须被拒绝（评审要求：路径限定在 ctx.paths 内）
    evil_dir = tmp_path / "evil"
    evil_dir.mkdir(parents=True, exist_ok=True)
    (evil_dir / "qr.png").write_bytes(PNG_1X1_BYTES)
    plugin = make_plugin(tmp_path, drop_qr=False, qr_filename=str(evil_dir / "qr.png"))
    result = call_tool(plugin, stream_id="s1")
    assert "不存在" in result["content"], result
    assert plugin._ctx.send.calls == [], "绝对路径必须被拒绝"


def test_traversal_rejected(tmp_path):
    # ../ 穿越到数据目录上一级（plugins 目录）的图片必须被拒绝
    plugin = make_plugin(tmp_path, drop_qr=False, qr_filename="../qr.png")
    (plugin._ctx.paths.data_dir.parent / "qr.png").write_bytes(PNG_1X1_BYTES)
    result = call_tool(plugin, stream_id="s1")
    assert "不存在" in result["content"], result
    assert plugin._ctx.send.calls == [], ".. 穿越必须被拒绝"


def test_subdir_within_data_dir_allowed(tmp_path):
    plugin = make_plugin(tmp_path, drop_qr=False, qr_filename="sub/qr.png")
    sub = plugin._ctx.paths.data_dir / "sub"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "qr.png").write_bytes(PNG_1X1_BYTES)
    result = call_tool(plugin, stream_id="s1")
    assert "成功" in result["content"], result


def test_runtime_dir_candidate(tmp_path):
    plugin = make_plugin(tmp_path, drop_qr=False)
    (plugin._ctx.paths.runtime_dir / "qr.png").write_bytes(PNG_1X1_BYTES)
    result = call_tool(plugin, stream_id="s1")
    assert "成功" in result["content"], result


def test_whitelist_blocks_unlisted_group(tmp_path):
    plugin = make_plugin(tmp_path, group_whitelist=["111"])
    result = call_tool(plugin, stream_id="s1", group_id="222")
    assert "未启用" in result["content"], result
    assert plugin._ctx.send.calls == [], "白名单之外的群不应发送"


def test_whitelist_allows_listed_group(tmp_path):
    plugin = make_plugin(tmp_path, group_whitelist=["111"])
    result = call_tool(plugin, stream_id="s1", group_id="111")
    assert "成功" in result["content"], result


def test_whitelist_private_chat_unaffected(tmp_path):
    plugin = make_plugin(tmp_path, group_whitelist=["111"])
    result = call_tool(plugin, stream_id="s1")
    assert "成功" in result["content"], result


def test_empty_whitelist_allows_any_group(tmp_path):
    plugin = make_plugin(tmp_path)
    result = call_tool(plugin, stream_id="s1", group_id="999")
    assert "成功" in result["content"], result


def test_lifecycle_roundtrip(tmp_path):
    plugin = make_plugin(tmp_path, cooldown_seconds=60)
    asyncio.run(plugin.on_load())
    # 配置热更新把冷却改为 0：同一会话应立即可重复发送
    config = plugin.get_plugin_config_data()
    config["payqr"]["cooldown_seconds"] = 0
    plugin.set_plugin_config(config)
    asyncio.run(plugin.on_config_update("self", {}, "0.1.0"))
    call_tool(plugin, stream_id="s1")
    call_tool(plugin, stream_id="s1")
    assert len(plugin._ctx.send.calls) == 2, "冷却改为 0 后不应再拦截"
    asyncio.run(plugin.on_unload())
    assert plugin._image_cache is None
