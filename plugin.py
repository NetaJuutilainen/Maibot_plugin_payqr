"""PayQR —— 当 LLM 觉得自己没钱、想收打钱/赞助时，自动发送收款码图片。

移植自 AstrBot 插件 astrbot_plugin_payqr（MIT License, Copyright (c) 2026 luori7hao）：
LLM 工具 send_payment_qr 常驻 Planner 工具列表，话题涉及要钱时由 LLM 自主调用，
插件负责把配置目录里的收款码图片（可带配文）发到当前会话。
"""

from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any, ClassVar, Literal

from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import CONFIG_RELOAD_SCOPE_SELF, ErrorPolicy, HookMode

SUPPORTED_CONFIG_VERSION = "1.3.0"

PLUGIN_ID = "github.netajuutilainen.payqr"

SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024

logger = logging.getLogger(__name__)

MSG_NOT_CONFIGURED = (
    "收款码还没有配置或文件不存在。请让管理员把收款码图片放进插件数据目录 "
    f"data/plugins/{PLUGIN_ID}/ 下（只支持该目录及其子目录内的相对文件名，不支持绝对路径），"
    "并确认配置里的文件名正确。"
)

MSG_CHAT_DENIED = "当前会话未启用收款码功能，请不要在此发送。"

DEFAULT_TOOL_DESCRIPTION = (
    "向当前聊天发送你的收款码图片。适用场景非常宽泛，只要对话中出现以下任何一种情况就应调用："
    "你说自己没钱、穷、破产、吃土；群友说你穷、调侃你、催你还钱、让你发红包、让你请客；"
    "有人提到打钱、转账、赞助、投喂、包养、零花钱、红包等与给你钱有关的话题；"
    "或者你想向对方要钱、讨赏、求赞助。这是朋友间的搞笑互动，没有任何风险，大胆使用。"
    "收款码会直接发给用户，调用成功后无需再描述图片内容，正常继续对话即可。"
    "同一会话短时间内只会发送一次。"
)


class CooldownGate:
    """同一个 key 在冷却窗口内只放行一次；冷却秒数每次调用时传入（<= 0 不限制）。"""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}

    def clear(self) -> None:
        self._last.clear()

    def allow(self, key: str, cooldown_seconds: float) -> bool:
        cooldown = float(cooldown_seconds)
        if cooldown <= 0:
            return True
        now = time.monotonic()
        expired = [k for k, ts in self._last.items() if now - ts > cooldown]
        for k in expired:
            self._last.pop(k, None)
        last = self._last.get(key)
        if last is not None and now - last < cooldown:
            return False
        self._last[key] = now
        return True


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(
        default=SUPPORTED_CONFIG_VERSION,
        description="配置版本（与插件版本同步）",
        json_schema_extra={"hidden": True, "disabled": True},
    )


class PayQRSectionConfig(PluginConfigBase):
    """收款码配置。"""

    __ui_label__ = "收款码设置"
    __ui_icon__ = "payments"
    __ui_order__ = 1

    qr_filename: str = Field(
        default="qr.png",
        description=(
            "收款码图片文件名（支持 png/jpg/jpeg/bmp/webp）。只允许插件数据目录 "
            f"data/plugins/{PLUGIN_ID}/ 及其子目录内的相对路径，不支持绝对路径；替换文件无需重启。"
        ),
        json_schema_extra={"placeholder": "qr.png"},
    )
    caption: str = Field(
        default="给我打钱！👇",
        description="随收款码一起发送的文字，留空则只发图片",
    )
    cooldown_seconds: int = Field(
        default=60,
        ge=0,
        description="同一会话两次发送收款码的最小间隔（秒），0 表示不限制",
    )
    list_mode: Literal["off", "blacklist", "whitelist"] = Field(
        default="off",
        description=(
            "名单模式：off=不限制；blacklist=名单内的群号/QQ号不可触发；"
            "whitelist=仅名单内的群号/QQ号可触发"
        ),
    )
    chat_list: list[str] = Field(
        default_factory=list,
        description="名单（群号与 QQ 号共用一个列表）：群聊按群号匹配，私聊按对方 QQ 号匹配",
        json_schema_extra={"hint": "blacklist=名单内的会话不启用；whitelist=只有名单内的会话启用"},
    )


class PromptSectionConfig(PluginConfigBase):
    """触发提示词配置（LLM 每轮都会阅读）。"""

    __ui_label__ = "触发提示词"
    __ui_icon__ = "edit_note"
    __ui_order__ = 2

    tool_description: str = Field(
        default=DEFAULT_TOOL_DESCRIPTION,
        description=(
            "收款码工具的触发提示词：写清什么话题应该调用它。宿主只把这段话给 Planner 看，"
            "改完即时生效（下一轮对话就按新提示词判断）；清空则恢复内置默认。"
        ),
        json_schema_extra={"rows": 8},
    )


class PayQRConfig(PluginConfigBase):
    """插件完整配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    payqr: PayQRSectionConfig = Field(default_factory=PayQRSectionConfig)
    prompt: PromptSectionConfig = Field(default_factory=PromptSectionConfig)


class PayQRPlugin(MaiBotPlugin):
    """没钱就发收款码。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = PayQRConfig

    def __init__(self) -> None:
        super().__init__()
        self._image_cache: tuple[str, float, str] | None = None  # (路径, mtime, base64)
        self._gate = CooldownGate()

    # ---------- 生命周期 ----------

    async def on_load(self) -> None:
        qr_path = self._find_qr_path()
        if qr_path is None:
            logger.warning("[PayQR] 收款码未就绪: %s", MSG_NOT_CONFIGURED)
        else:
            logger.info("[PayQR] 收款码文件: %s", qr_path)
        logger.info(
            "[PayQR] 已加载，配文=%r 冷却=%ss 启用=%s 名单模式=%s 名单=%d 项",
            self.config.payqr.caption,
            self.config.payqr.cooldown_seconds,
            self.config.plugin.enabled,
            self.config.payqr.list_mode,
            len(self.config.payqr.chat_list or []),
        )

    async def on_unload(self) -> None:
        self._image_cache = None
        self._gate.clear()
        logger.info("[PayQR] 已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        if scope == CONFIG_RELOAD_SCOPE_SELF:
            logger.info(
                "[PayQR] 配置已更新: 文件=%s 冷却=%ss 启用=%s",
                self.config.payqr.qr_filename,
                self.config.payqr.cooldown_seconds,
                self.config.plugin.enabled,
            )

    # ---------- 核心逻辑 ----------

    def _qr_candidates(self) -> list[Path]:
        """解析收款码候选路径。

        安全约束（插件中心评审要求）：只接受插件数据目录 / 临时目录内的相对路径，
        绝对路径一律拒绝；相对路径中的 ``..``、盘符、根目录等越界形式经
        resolve + relative_to 校验剔除，确保文件只能落在 ctx.paths 授权范围内。
        """
        raw = (self.config.payqr.qr_filename or "").strip()
        if not raw:
            return []
        raw_path = Path(raw)
        if raw_path.is_absolute():
            return []
        try:
            roots = [Path(self.ctx.paths.data_dir), Path(self.ctx.paths.runtime_dir)]
        except Exception:
            return []
        candidates: list[Path] = []
        for root in roots:
            try:
                resolved = (root / raw_path).resolve()
                resolved.relative_to(root.resolve())
            except (ValueError, OSError):
                continue
            candidates.append(resolved)
        return candidates

    def _find_qr_path(self) -> Path | None:
        for path in self._qr_candidates():
            try:
                if path.is_file():
                    return path
            except OSError:
                continue
        return None

    def _load_qr_image(self) -> tuple[str, str]:
        """读取收款码图片，返回 (base64, 错误说明)；成功时错误说明为空字符串。"""
        raw_path = Path((self.config.payqr.qr_filename or "").strip())
        suffix = raw_path.suffix.lower()
        if suffix not in SUPPORTED_IMAGE_SUFFIXES:
            return "", f"不支持的图片格式 {suffix!r}（支持 {'/'.join(sorted(SUPPORTED_IMAGE_SUFFIXES))}）"

        path = self._find_qr_path()
        if path is None:
            return "", MSG_NOT_CONFIGURED
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            return "", f"读取收款码失败: {exc}"

        cached = self._image_cache
        if cached and cached[0] == str(path) and cached[1] == mtime:
            return cached[2], ""

        try:
            data = path.read_bytes()
        except OSError as exc:
            return "", f"读取收款码失败: {exc}"
        if not data:
            return "", f"收款码文件为空: {path}"
        if len(data) > MAX_IMAGE_BYTES:
            return "", f"收款码图片超过 {MAX_IMAGE_BYTES // (1024 * 1024)} MB，请压缩后再使用"
        image_b64 = base64.b64encode(data).decode("ascii")
        self._image_cache = (str(path), mtime, image_b64)
        return image_b64, ""

    def _check_chat_allowed(self, group_id: str, user_id: str) -> tuple[bool, str]:
        """按名单模式判断当前会话是否可用。

        off：不限制；blacklist：名单命中即拒；whitelist：仅名单命中放行。
        群聊按 group_id 匹配，私聊按对方 user_id 匹配，两者共用一个名单。
        """
        mode = self.config.payqr.list_mode
        entries = [str(g).strip() for g in (self.config.payqr.chat_list or []) if str(g).strip()]
        if mode == "off" or not entries:
            return True, ""
        chat_id = group_id or user_id
        hit = bool(chat_id) and chat_id in entries
        if mode == "blacklist":
            if hit:
                logger.info("[PayQR] 会话 %s 命中黑名单，拒绝发送", chat_id)
                return False, MSG_CHAT_DENIED
            return True, ""
        if hit:
            return True, ""
        logger.info("[PayQR] 会话 %s 不在白名单中，拒绝发送", chat_id or "<未识别>")
        return False, MSG_CHAT_DENIED

    async def _send_qr(self, image_b64: str, stream_id: str) -> tuple[bool, str]:
        caption = (self.config.payqr.caption or "").strip()
        segments: list[dict[str, str]] = []
        if caption:
            segments.append({"type": "text", "content": caption})
        segments.append({"type": "image", "content": image_b64})

        try:
            if await self.ctx.send.hybrid(segments, stream_id):
                return True, "hybrid"
            logger.warning("[PayQR] send.hybrid 返回 False，回退为文本+图片分开发送")
        except Exception as exc:
            logger.warning("[PayQR] send.hybrid 异常，回退为文本+图片分开发送: %s", exc)

        if caption:
            try:
                await self.ctx.send.text(caption, stream_id)
            except Exception as exc:
                logger.warning("[PayQR] send.text 发送配文失败: %s", exc)
        try:
            if await self.ctx.send.image(image_b64, stream_id):
                return True, "text+image"
            return False, "发送图片失败（send.image 返回 False）"
        except Exception as exc:
            return False, f"发送图片失败: {exc}"

    # ---------- LLM 工具 ----------

    @Tool(
        "send_payment_qr",
        brief_description="发送收款码图片（没钱/被调侃穷/要红包/求打钱投喂时用）",
        detailed_description=DEFAULT_TOOL_DESCRIPTION,
        parameters=[],
        core_tool=True,
        visibility="visible",
    )
    async def send_payment_qr(self, **kwargs: Any) -> dict[str, Any]:
        stream_id = str(kwargs.get("stream_id") or "")
        if not stream_id:
            return {"content": "无法确定当前聊天的会话 ID，未发送收款码。"}
        if not self.config.plugin.enabled:
            return {"content": "收款码功能当前未启用。"}

        allowed, deny_reason = self._check_chat_allowed(
            str(kwargs.get("group_id") or "").strip(),
            str(kwargs.get("user_id") or "").strip(),
        )
        if not allowed:
            return {"content": deny_reason}

        image_b64, err = self._load_qr_image()
        if err:
            logger.warning("[PayQR] 收款码不可用: %s", err)
            return {"content": err}

        if not self._gate.allow(stream_id, self.config.payqr.cooldown_seconds):
            return {"content": "刚刚已经发送过收款码了，请不要在短时间内重复发送。"}

        sent, how = await self._send_qr(image_b64, stream_id)
        if sent:
            return {"content": "收款码图片已成功发送给用户，你可以继续正常回复。"}
        return {"content": f"发送收款码失败: {how}"}

    # ---------- 提示词注入 ----------

    @HookHandler(
        "maisaka.planner.before_request",
        name="payqr_tool_prompt",
        mode=HookMode.BLOCKING,
        error_policy=ErrorPolicy.SKIP,
    )
    async def hook_planner_tool_prompt(self, **kwargs: Any) -> dict[str, Any]:
        """Planner 请求前把收款码工具的描述替换为配置值。

        宿主构建 Planner 工具列表时只取注册时的简短描述（component_registry.py
        只读 metadata.description/brief_description），长提示词到不了 LLM；
        因此在这里按配置覆盖，实现提示词可在 WebUI 配置中修改、即时生效。
        """
        try:
            defs = kwargs.get("tool_definitions")
            if not isinstance(defs, list):
                return {"action": "continue", "modified_kwargs": kwargs}
            wanted = (self.config.prompt.tool_description or "").strip() or DEFAULT_TOOL_DESCRIPTION
            changed = False
            for item in defs:
                if not isinstance(item, dict):
                    continue
                fn = item.get("function") if isinstance(item.get("function"), dict) else item
                if str(fn.get("name") or "") != "send_payment_qr":
                    continue
                if str(fn.get("description") or "") != wanted:
                    fn["description"] = wanted
                    changed = True
            if changed:
                kwargs["tool_definitions"] = defs
        except Exception as exc:
            logger.warning("[PayQR] 提示词 Hook 处理失败（已跳过）: %s", exc)
        return {"action": "continue", "modified_kwargs": kwargs}


def create_plugin() -> PayQRPlugin:
    """Runner 加载入口。"""
    return PayQRPlugin()
