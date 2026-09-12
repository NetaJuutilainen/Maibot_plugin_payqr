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
from typing import Any, ClassVar

from maibot_sdk import Field, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import CONFIG_RELOAD_SCOPE_SELF

SUPPORTED_CONFIG_VERSION = "0.1.1"

PLUGIN_ID = "github.netajuutilainen.payqr"

SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024

logger = logging.getLogger(__name__)

MSG_NOT_CONFIGURED = (
    "收款码还没有配置或文件不存在，请让管理员把收款码图片放进插件数据目录 "
    f"data/plugins/{PLUGIN_ID}/ 下，并确认配置里的文件名正确。"
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
            "收款码图片文件名（支持 png/jpg/jpeg/bmp/webp）。把图片放到插件数据目录 "
            f"data/plugins/{PLUGIN_ID}/ 下即可，替换文件无需重启；也支持绝对路径。"
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


class PayQRConfig(PluginConfigBase):
    """插件完整配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    payqr: PayQRSectionConfig = Field(default_factory=PayQRSectionConfig)


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
            "[PayQR] 已加载，配文=%r 冷却=%ss 启用=%s",
            self.config.payqr.caption,
            self.config.payqr.cooldown_seconds,
            self.config.plugin.enabled,
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
        raw = (self.config.payqr.qr_filename or "").strip()
        if not raw:
            return []
        raw_path = Path(raw)
        if raw_path.is_absolute():
            return [raw_path]
        candidates: list[Path] = []
        try:
            candidates.append(self.ctx.paths.data_dir / raw_path)
            candidates.append(self.ctx.paths.runtime_dir / raw_path)
        except Exception:
            pass
        candidates.append(Path(__file__).resolve().parent / raw_path)
        candidates.append(Path.cwd() / raw_path)
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
        brief_description="发送收款码图片",
        detailed_description=(
            "当你觉得自己没钱了、穷了、需要别人打钱、转账、赞助、请客、发红包等与要钱相关的话题时，"
            "调用此工具向当前聊天的用户发送收款码图片。收款码会直接发给用户，"
            "调用成功后无需再描述图片内容，正常继续对话即可。同一会话短时间内只会发送一次。"
        ),
        parameters=[],
        core_tool=True,
    )
    async def send_payment_qr(self, **kwargs: Any) -> dict[str, Any]:
        stream_id = str(kwargs.get("stream_id") or "")
        if not stream_id:
            return {"content": "无法确定当前聊天的会话 ID，未发送收款码。"}
        if not self.config.plugin.enabled:
            return {"content": "收款码功能当前未启用。"}

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


def create_plugin() -> PayQRPlugin:
    """Runner 加载入口。"""
    return PayQRPlugin()
