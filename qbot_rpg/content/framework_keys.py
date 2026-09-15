"""框架侧「键全集」来源注册表（编辑器批19 #4 · 通用机制）。

编辑器一号原则（`docs/编辑器修改意见0915_台账与方案.md` §〇·补）：
**框架登记/实现的东西必须显示**。对 map 形态模块，框架自身的「键全集」也是一份
能力登记——例如消息模板的全量表 `core/templates/template_table.json`（键 = 模板名）
就是框架实现、任何包都可覆盖的能力。

机制（**不写死模块名 / 模板键名**）：
  · 模块元数据 `ModuleMeta.key_source` 声明来源名（如 ``"templates"``）→ 编辑器把该来源
    的键并入条目列表；
  · 包数据里已有的键 = 「已覆盖（包）」；来源里有、包数据没有的键 = 「默认（框架）」，
    可直接编辑并在保存时写入包覆盖（走既有校验 / 原子备份 / 原子写 / 回退链路）；
  · 来源表由框架提供，来源名 → 提供器在 `FRAMEWORK_KEY_SOURCES` 注册；换模块只改
    `key_source` 声明，编辑器读取层零改动。

本模块只做「来源查询」纯逻辑；`content` 层不静态依赖 `core` 层（提供器内**延迟导入**）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Tuple

# 提供器签名：() -> (键 → 值, 键 → 框架侧说明/help)
KeyProvider = Callable[[], Tuple[Mapping[str, Any], Mapping[str, str]]]


def _templates_provider() -> Tuple[Mapping[str, Any], Mapping[str, str]]:
    """消息模板全量表（唯一存储）→ (键→文案, 键→框架侧说明)。

    说明来自表顶层 `meta.prose_keys`（整条豁免排版约束的 key → 理由），是框架侧已有的
    人类可读信息；没有说明的键由编辑器回落到「键 = 模板名」提示。延迟导入 `core`，
    避免 content 层静态依赖 core 层。
    """
    from qbot_rpg.core.templates import TABLE_META, TABLE_TEMPLATES

    raw_notes = TABLE_META.get("prose_keys") if isinstance(TABLE_META, Mapping) else None
    notes: Dict[str, str] = {}
    if isinstance(raw_notes, Mapping):
        for key, val in raw_notes.items():
            if isinstance(val, str) and val:
                notes[str(key)] = val
    return TABLE_TEMPLATES, notes


# 框架内置来源注册表（来源名 → 提供器）。新增来源只在此登记，不许在编辑器读取层写死。
FRAMEWORK_KEY_SOURCES: Dict[str, KeyProvider] = {
    "templates": _templates_provider,
}


def register_key_source(name: str, provider: KeyProvider) -> None:
    """注册一个框架侧键全集来源（同名覆盖；供框架扩展 / 测试注入）。"""
    if not isinstance(name, str) or not name:
        raise ValueError("来源名必须是非空字符串")
    FRAMEWORK_KEY_SOURCES[name] = provider


def framework_key_source(name: object) -> Mapping[str, Any]:
    """按来源名取框架键全集（未声明 / 未注册 / 提供器异常 → 空表，绝不抛）。"""
    if not isinstance(name, str) or not name:
        return {}
    provider = FRAMEWORK_KEY_SOURCES.get(name)
    if provider is None:
        return {}
    try:
        keys, _notes = provider()
    except Exception:  # noqa: BLE001 —— 来源坏了也不让编辑器崩（回落「无来源」）
        return {}
    return dict(keys) if isinstance(keys, Mapping) else {}


def framework_key_notes(name: object) -> Mapping[str, str]:
    """按来源名取「键 → 框架侧说明」（未声明 / 未注册 / 异常 → 空表）。"""
    if not isinstance(name, str) or not name:
        return {}
    provider = FRAMEWORK_KEY_SOURCES.get(name)
    if provider is None:
        return {}
    try:
        _keys, notes = provider()
    except Exception:  # noqa: BLE001
        return {}
    return dict(notes) if isinstance(notes, Mapping) else {}


__all__ = [
    "FRAMEWORK_KEY_SOURCES",
    "framework_key_notes",
    "framework_key_source",
    "register_key_source",
]
