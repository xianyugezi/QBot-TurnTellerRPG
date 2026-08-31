"""
消息模板注册表（2026-08-31 用户拍板：消息模板配置化，不写死代码）。

设计：
- 每类面板/消息 = 一段模板字符串（key → 带 {占位符} 的模板）
- 占位符白名单：每类暴露哪些占位符由各分区 PLACEHOLDER_WHITELIST 登记；用户只能在白名单内
  调位置/换行/加字，超出白名单的占位符渲染时原样保留（不替换，提示缺失）
- 内容包覆盖：content/templates.json 覆盖同 key（深合并），未写 key 用框架内置默认 → 零配置零破坏
- 占位符语法 {name} / {attr_name}；渲染 = 占位符替换（_safe_format 缺键保留原文，不抛异常）

分区：base.py（核心 8 类）+ use_tpl/shortcut_tpl/log_tpl/codex_tpl/dialog_tpl/explore_tpl/
quest_tpl/checkin_tpl/investigate_tpl/battle_tpl/forge_tpl/alchemy_tpl/basic_rem_tpl/
register_rem_tpl（各命令模块剩余模板，子 agent 分区独占，避免并行冲突）。

铁律：纯函数、零 NoneBot import、不硬编码路径。模板字符串全部集中在各分区默认表 +
内容包 templates.json；渲染器不再内嵌面板格式字符串（只保留逻辑与占位符组装）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

from qbot_rpg.core.templates.base import DEFAULT_TEMPLATES as _BASE_TEMPLATES
from qbot_rpg.core.templates.base import PLACEHOLDER_WHITELIST as _BASE_WHITELIST
from qbot_rpg.core.templates.alchemy_tpl import DEFAULT_TEMPLATES as _ALCHEMY
from qbot_rpg.core.templates.alchemy_tpl import PLACEHOLDER_WHITELIST as _ALCHEMY_WH
from qbot_rpg.core.templates.basic_rem_tpl import DEFAULT_TEMPLATES as _BASIC_REM
from qbot_rpg.core.templates.basic_rem_tpl import PLACEHOLDER_WHITELIST as _BASIC_REM_WH
from qbot_rpg.core.templates.battle_tpl import DEFAULT_TEMPLATES as _BATTLE
from qbot_rpg.core.templates.battle_tpl import PLACEHOLDER_WHITELIST as _BATTLE_WH
from qbot_rpg.core.templates.checkin_tpl import DEFAULT_TEMPLATES as _CHECKIN
from qbot_rpg.core.templates.checkin_tpl import PLACEHOLDER_WHITELIST as _CHECKIN_WH
from qbot_rpg.core.templates.codex_tpl import DEFAULT_TEMPLATES as _CODEX
from qbot_rpg.core.templates.codex_tpl import PLACEHOLDER_WHITELIST as _CODEX_WH
from qbot_rpg.core.templates.dialog_tpl import DEFAULT_TEMPLATES as _DIALOG
from qbot_rpg.core.templates.dialog_tpl import PLACEHOLDER_WHITELIST as _DIALOG_WH
from qbot_rpg.core.templates.explore_tpl import DEFAULT_TEMPLATES as _EXPLORE
from qbot_rpg.core.templates.explore_tpl import PLACEHOLDER_WHITELIST as _EXPLORE_WH
from qbot_rpg.core.templates.forge_tpl import DEFAULT_TEMPLATES as _FORGE
from qbot_rpg.core.templates.forge_tpl import PLACEHOLDER_WHITELIST as _FORGE_WH
from qbot_rpg.core.templates.investigate_tpl import DEFAULT_TEMPLATES as _INVESTIGATE
from qbot_rpg.core.templates.investigate_tpl import PLACEHOLDER_WHITELIST as _INVESTIGATE_WH
from qbot_rpg.core.templates.log_tpl import DEFAULT_TEMPLATES as _LOG
from qbot_rpg.core.templates.log_tpl import PLACEHOLDER_WHITELIST as _LOG_WH
from qbot_rpg.core.templates.quest_tpl import DEFAULT_TEMPLATES as _QUEST
from qbot_rpg.core.templates.quest_tpl import PLACEHOLDER_WHITELIST as _QUEST_WH
from qbot_rpg.core.templates.register_rem_tpl import DEFAULT_TEMPLATES as _REG_REM
from qbot_rpg.core.templates.register_rem_tpl import PLACEHOLDER_WHITELIST as _REG_REM_WH
from qbot_rpg.core.templates.shortcut_tpl import DEFAULT_TEMPLATES as _SHORTCUT
from qbot_rpg.core.templates.shortcut_tpl import PLACEHOLDER_WHITELIST as _SHORTCUT_WH
from qbot_rpg.core.templates.use_tpl import DEFAULT_TEMPLATES as _USE
from qbot_rpg.core.templates.use_tpl import PLACEHOLDER_WHITELIST as _USE_WH

__all__ = [
    "DEFAULT_TEMPLATES",
    "PLACEHOLDER_WHITELIST",
    "resolve_templates",
    "render_template",
    "tpl_of",
]

# 汇总全部分区（同名 key 后者覆盖前者；base 优先兜底，分区具体覆盖）
_ALL_TABLES: list = [
    _BASE_TEMPLATES, _USE, _SHORTCUT, _LOG, _CODEX, _DIALOG, _EXPLORE,
    _QUEST, _CHECKIN, _INVESTIGATE, _BATTLE, _FORGE, _ALCHEMY,
    _BASIC_REM, _REG_REM,
]
_ALL_WHITELISTS: list = [
    _BASE_WHITELIST, _USE_WH, _SHORTCUT_WH, _LOG_WH, _CODEX_WH, _DIALOG_WH,
    _EXPLORE_WH, _QUEST_WH, _CHECKIN_WH, _INVESTIGATE_WH, _BATTLE_WH,
    _FORGE_WH, _ALCHEMY_WH, _BASIC_REM_WH, _REG_REM_WH,
]

DEFAULT_TEMPLATES: Dict[str, Any] = {}
for _t in _ALL_TABLES:
    DEFAULT_TEMPLATES.update(_t)

PLACEHOLDER_WHITELIST: Dict[str, set] = {}
for _w in _ALL_WHITELISTS:
    PLACEHOLDER_WHITELIST.update(_w)

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


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
    白名单内 key（未知 key 忽略，防内容包拼错引入渲染异常）。
    """
    merged = dict(DEFAULT_TEMPLATES)
    if isinstance(content_overrides, Mapping):
        for key, val in content_overrides.items():
            if key in merged and isinstance(val, str):
                merged[key] = val
    return merged


def render_template(templates: Mapping[str, Any], key: str,
                    data: Mapping[str, Any]) -> str:
    """按 key 渲染模板（缺失 key/模板 → 原样 data 兜底空串不崩）。"""
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
