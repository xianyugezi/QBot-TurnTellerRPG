"""消息模板注册表（终态：**全量表为唯一存储**）。

设计（终态 · 2026-09-12 消息模板重构收口）：
- 全部玩家可见消息模板集中在**单一全量表** `template_table.json`（key → 带 {占位符} 的模板串）。
- 占位符白名单：由表内 key 的占位符自动派生（渲染时缺键原样保留，不替换、不抛异常）。
- 内容包覆盖：`content/<pack>/templates.json` 覆盖同 key（深合并），未写 key 用表默认
  → 零配置零破坏。
- 占位符语法 {name} / {attr_name}；渲染 = 正则替换（_safe_format）。

历史：迁移期曾有 22 个 `*_tpl.py` 分区文件与本表并存（迁移期同名 key 由本表覆盖）；
2026-09-12 全部分区迁移归零后分区文件统一删除，仅保留 `base.py`（核心 8 类基础模板，
非消息面板类）与本表。

铁律：纯函数、零 NoneBot import、不硬编码路径；渲染器只做逻辑与占位符组装，不内嵌文案。
排版规范见 docs/消息模板重构/00_方案与规范_v1.md；宽度校验 scripts/check_template_width.py。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from qbot_rpg.core.templates.base import DEFAULT_TEMPLATES as _BASE_TEMPLATES
from qbot_rpg.core.templates.base import PLACEHOLDER_WHITELIST as _BASE_WHITELIST

__all__ = [
    "DEFAULT_TEMPLATES",
    "PLACEHOLDER_WHITELIST",
    "TABLE_TEMPLATES",
    "resolve_templates",
    "render_template",
    "tpl_of",
]

DEFAULT_TEMPLATES: Dict[str, Any] = dict(_BASE_TEMPLATES)
PLACEHOLDER_WHITELIST: Dict[str, set] = dict(_BASE_WHITELIST)

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")

# —— 全量模板表（唯一存储）——
_TABLE_PATH = Path(__file__).with_name("template_table.json")
TABLE_TEMPLATES: Dict[str, str] = {}
try:
    _doc = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
    _tpl_raw = _doc.get("templates") if isinstance(_doc, dict) else None
    if isinstance(_tpl_raw, dict):
        TABLE_TEMPLATES = {k: v for k, v in _tpl_raw.items() if isinstance(v, str)}
except OSError:
    # 表文件缺失（非 repo 部署的兼容路径）：表现同迁移前（全走 base 默认）。
    TABLE_TEMPLATES = {}
DEFAULT_TEMPLATES.update(TABLE_TEMPLATES)

# 表内 key 的占位符白名单自动派生（与旧分区手工登记同语义；测试锚定同款）。
for _k, _v in TABLE_TEMPLATES.items():
    PLACEHOLDER_WHITELIST.setdefault(_k, set(_PLACEHOLDER_RE.findall(_v)))


def _safe_format(template: str, data: Mapping[str, Any]) -> str:
    """占位符替换（缺键保留原文，不抛异常）。"""
    allowed = set(data)

    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key in allowed:
            return str(data[key])
        return m.group(0)

    return _PLACEHOLDER_RE.sub(_sub, template)


def resolve_templates(content_overrides: Any = None) -> Dict[str, Any]:
    """内容包 templates.json 覆盖默认模板（深合并，未写 key 用默认）。

    content_overrides: Registry templates_raw / dict / None。仅接受 dict 且仅合并
    已存在 key（未知 key 忽略，防内容包拼错引入渲染异常）。
    """
    merged = dict(DEFAULT_TEMPLATES)
    if isinstance(content_overrides, Mapping):
        for key, val in content_overrides.items():
            if key in merged and isinstance(val, str):
                merged[key] = val
    return merged


def render_template(templates: Mapping[str, Any], key: str,
                    data: Mapping[str, Any]) -> str:
    """按 key 渲染模板（缺失 key/模板 → 返回空串不崩）。"""
    tpl = templates.get(key)
    if not isinstance(tpl, str):
        return ""
    return _safe_format(tpl, data)


def tpl_of(ctx: Any, key: str, data: Optional[Mapping[str, Any]] = None) -> str:
    """渲染器统一入口：从 ctx 读模板（无 ctx/无 templates → 内置默认）。

    data: {占位符: 值}。用法：tpl_of(ctx, "role_header", {"name": "阿伟"})。
    """
    tpls = ctx.get("templates") if isinstance(ctx, Mapping) else None
    if not isinstance(tpls, Mapping):
        tpls = DEFAULT_TEMPLATES
    return render_template(tpls, key, data or {})
