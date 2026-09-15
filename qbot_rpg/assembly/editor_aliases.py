"""编辑器批19 #7：指令别名视图（框架内置 ∪ 包声明）——装配层实现。

**为什么在装配层**：框架内置别名来自各指令注册时自带的 `CommandSpec.aliases`，读取它需要
import `qbot_rpg.commands`；而编辑器读取层（`qbot_rpg/web`）按架构矩阵**不得**依赖
commands / assembly（`scripts/check_architecture.py` §1.4：web 允许 {content, core, storage,
data}）。装配层允许 commands + content，故别名视图在此组装，由宿主
（`scripts/editor_host.py`）注入 HTTP 响应。

只读：不写任何文件、不改路由与校验语义。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from qbot_rpg.assembly.router_setup import framework_builtin_aliases
from qbot_rpg.commands.router import AliasTable
from qbot_rpg.content.field_meta import ALIAS_CONFIG_KEY, ALIAS_CONFIG_MODULE

# 框架侧现状说明（实测：框架没有独立的静态别名表，内置别名来自 CommandSpec.aliases）。
FRAMEWORK_ALIAS_NOTE = (
    "框架侧没有独立的静态别名表：内置别名来自各指令注册时自带的 CommandSpec.aliases"
    "（本视图标「框架内置」）；包 settings.command_aliases 由装配层 AliasTable.from_config "
    "装载（本视图标「包覆盖」）。运行时两处都生效（路由先查包别名表，再查指令自带别名）；"
    "同一别名键以包声明为准。"
)


def _read_settings(pack_dir: Path) -> Mapping[str, Any]:
    try:
        doc = json.loads((pack_dir / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, Mapping) else {}


def _pack_alias_rows(pack_dir: Path) -> Tuple[List[Dict[str, Any]], str]:
    """读包 settings.command_aliases → 归一化行（复用既有 AliasTable.from_config）。"""
    raw = _read_settings(pack_dir).get(ALIAS_CONFIG_KEY)
    if not isinstance(raw, Mapping) or not raw:
        return [], ""
    try:
        table = AliasTable.from_config(raw)
    except Exception as exc:  # noqa: BLE001 —— 形态非法只提示，不让编辑器崩
        return [], f"包指令别名配置无法解析（{type(exc).__name__}）：{exc}"
    rows: List[Dict[str, Any]] = []
    for alias in sorted(table.alias_names()):
        entry = table.alias_for(alias)
        if entry is None:
            continue
        rows.append({
            "alias": str(alias),
            "command": str(getattr(entry, "command", "") or ""),
            "keep_original": bool(getattr(entry, "keep_original", True)),
            "source": "pack",
        })
    return rows, ""


def list_aliases(pack_dir: Path) -> Dict[str, Any]:
    """指令别名视图：框架内置 ∪ 包声明，两类来源分别列出（只读）。

    出参：framework / pack_declared / merged（同键以包声明为准）/ sources / framework_note / note。
    """
    pack_dir = Path(pack_dir)
    fw = dict(framework_builtin_aliases())
    pack_rows, parse_note = _pack_alias_rows(pack_dir)
    fw_rows = [{"alias": a, "command": c, "keep_original": True, "source": "framework"}
               for a, c in sorted(fw.items())]
    fw_alias = set(fw)
    for row in pack_rows:
        row["overrides_framework"] = row["alias"] in fw_alias
    merged: Dict[str, Dict[str, Any]] = {r["alias"]: dict(r) for r in fw_rows}
    for row in pack_rows:
        merged[row["alias"]] = dict(row)
    return {
        "pack": pack_dir.name,
        "module": ALIAS_CONFIG_MODULE,
        "entry_id": ALIAS_CONFIG_KEY,
        "framework": fw_rows,
        "pack_declared": pack_rows,
        "merged": [merged[k] for k in sorted(merged)],
        "sources": ["framework", "pack"],
        "framework_note": FRAMEWORK_ALIAS_NOTE,
        "note": parse_note,
    }


__all__ = ["FRAMEWORK_ALIAS_NOTE", "list_aliases"]
