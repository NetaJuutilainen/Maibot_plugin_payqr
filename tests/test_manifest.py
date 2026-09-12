"""_manifest.json 静态校验（按 MaiBot 1.2.3 ManifestValidator 规则）。"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_TOP_FIELDS = {
    "manifest_version", "id", "version", "name", "description", "author", "license",
    "urls", "host_application", "sdk", "capabilities", "i18n", "dependencies",
    "plugin_type", "llm_providers", "display", "changelog",
}
ID_RE = re.compile(r"^[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)+$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def load_manifest() -> dict:
    return json.loads((REPO_ROOT / "_manifest.json").read_text(encoding="utf-8"))


def test_no_unknown_fields():
    manifest = load_manifest()
    unknown = set(manifest) - ALLOWED_TOP_FIELDS
    assert not unknown, f"schema 外多余字段（extra=forbid 会拒载）: {unknown}"


def test_required_fields_present():
    manifest = load_manifest()
    for field in ("manifest_version", "id", "version", "name", "description",
                  "author", "license", "urls", "host_application", "sdk",
                  "capabilities", "i18n"):
        assert manifest.get(field), f"缺少必填字段: {field}"
    assert manifest["manifest_version"] == 2
    assert manifest["author"].get("name")
    assert manifest["urls"].get("repository", "").startswith("https://")


def test_id_and_version_format():
    manifest = load_manifest()
    assert ID_RE.match(manifest["id"]), f"id 必须含 . 或 - 分隔符: {manifest['id']}"
    assert VERSION_RE.match(manifest["version"]), "version 必须严格三段式"
    for key in ("host_application", "sdk"):
        section = manifest[key]
        assert VERSION_RE.match(section["min_version"])
        assert VERSION_RE.match(section["max_version"])
        assert section["min_version"] <= section["max_version"]


def test_host_range_is_generic():
    manifest = load_manifest()
    host = manifest["host_application"]
    assert host["min_version"] == "1.0.0"
    assert host["max_version"] == "1.99.99", "通用插件建议放宽 max_version，避免 Host 升级后拒载"


def test_capabilities_match_code_usage():
    manifest = load_manifest()
    declared = set(manifest["capabilities"])
    code = (REPO_ROOT / "plugin.py").read_text(encoding="utf-8")
    used = set(re.findall(r"self\.ctx\.send\.(\w+)", code))
    capability_map = {"text": "send.text", "image": "send.image", "hybrid": "send.hybrid"}
    used_caps = {capability_map[name] for name in used if name in capability_map}
    assert used_caps, "代码里没有用到任何 send 能力？"
    missing = used_caps - declared
    assert not missing, f"代码用到但 manifest 未声明的能力（会 E_CAPABILITY_DENIED）: {missing}"
    extra = declared - used_caps
    assert not extra, f"声明了但代码未用的能力（能力声明应与调用一一对应）: {extra}"
