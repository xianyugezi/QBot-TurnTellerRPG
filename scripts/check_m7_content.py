#!/usr/bin/env python3
"""3f 内容包校验器（scripts/check_m7_content.py · M7 BCH-09 3f F-18 · R-27 可达性检查）。

校验项（对齐 docs/细化/细化_3f_单机向体验.md R-16 / R-27，提示性不阻断）：
  1) 隐藏要素可达性校验：每张地图隐藏要素（hidden BOSS window / interact_points
     lore_condition / hidden_reveal / exits hidden / environment_events condition）
     → 前置条件键全部是已注册条件键（白名单：var 键空间 [事件:*]/[图鉴完成度]/[季节]/
     [时段]/[天气]/level/物品/任务等，以条件引擎 normalize_var 权威判定）+ 引用
     （hidden_find_id / map_ref / enemy / boss_ref）在内容包 registry 可解析 →
     不可达要素报红（无发现路径=可能永不可发现，R-16 黄提示语义，本脚本 RED 提示不阻断）。
  2) 条件键白名单校验：全文扫描包内 JSON 的 condition 键（条件引擎原子 {var,...} /
     旧 event 原语 {type:event,...}）→ 未注册键报清单（黄提示）。
  3) 模板占位符校验：desc/intro/reveal/ambient 文本模板 → {季节}/{时段}/{天气}/{地图}
     占位符合法（含契约 R-14 明确允许的 {图鉴完成度}），其余 {X} 未定义占位符报提示。

退出码：0=通过（无提示）；1=有提示（提示性不阻断，可保存但建议修复，对齐
「只建议不限制」哲学 NPC 4.5 / R-16）。支持 --path 指定内容包目录；纯 Python 标准库
（仅 import 仓库内 qbot_rpg.engine.condition_engine / qbot_rpg.core.adventure_log 的
常量与 normalize_var，两者均零第三方依赖）。

用法：python scripts/check_m7_content.py [--path 内容包目录]   （缺省 content/demo_lv15）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

# 仓库根引导（使脚本可从任意 cwd 运行；qbot_rpg 仅标准库依赖）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from qbot_rpg.core.adventure_log import (  # noqa: E402
    EVENT_KEY_CODEX_NEW,
    EVENT_KEY_FIRST_CROWN,
    EVENT_KEY_FIRST_KILL,
    EVENT_KEY_HIDDEN_FIND,
    EVENT_KEY_MILESTONE,
    EVENT_KEY_STORY_NODE,
)
from qbot_rpg.engine.condition_engine import (  # noqa: E402
    EVENT_PRESETS,
    normalize_var,
)

# -------------------------------------------------------------------------------------
# 白名单（条件键 / 事件注册表 / 模板占位符）
# -------------------------------------------------------------------------------------
# 事件注册表（NPC 4.3.2 预置 + 冒险日志六类；3f 预置两行 [事件:环境事件]/[事件:隐藏发现]
# 走 _event_registered 特判——模式已注册，但具体 ID 须在包内声明（可达性，见 §七 L113）
REGISTERED_EVENT_NAMES: set = set(EVENT_PRESETS) | {
    EVENT_KEY_FIRST_KILL,
    EVENT_KEY_FIRST_CROWN,
    EVENT_KEY_STORY_NODE,
    EVENT_KEY_HIDDEN_FIND,
    EVENT_KEY_MILESTONE,
    EVENT_KEY_CODEX_NEW,
}

# 模板占位符合法集（3d 模板规范子集 + R-14 明确允许的 {图鉴完成度}）
LEGAL_PLACEHOLDERS: Tuple[str, ...] = ("季节", "时段", "天气", "地图", "图鉴完成度")

# 模板文本字段（desc/intro/reveal/ambient 及别名），递归扫描占位符
TEMPLATE_FIELDS: Tuple[str, ...] = ("desc", "intro", "reveal", "ambient", "text", "hint")

# 校验范围 JSON 文件（条件键/占位符全文扫描）
SCAN_FILES: Tuple[str, ...] = (
    "maps.json", "enemies.json", "npcs.json", "npc.json",
    "quest.json", "quests.json", "items.json", "action.json", "settings.json",
)

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


# -------------------------------------------------------------------------------------
# 通用小工具
# -------------------------------------------------------------------------------------
def _as_list(value: object) -> List[Any]:
    """list 归一：list/tuple 直通；单 dict → [dict]；其余 → []。"""
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Mapping):
        return [value]
    return []


def _load_json(pack_dir: str, name: str) -> Optional[Any]:
    """读包内 JSON（缺文件 → None；解析失败 → None 不阻断，容错）。"""
    path = os.path.join(pack_dir, name)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _add_id(index: Dict[str, Any], fname: str, eid: str) -> None:
    """按文件名把 ID 写入对应引用集合（registry 解析索引）。"""
    if fname == "enemies.json":
        index["enemy_ids"].add(eid)
    elif fname in ("items.json", "equipment.json"):
        index["item_ids"].add(eid)
    elif fname in ("npcs.json", "npc.json"):
        index["npc_ids"].add(eid)
    elif fname in ("quest.json", "quests.json"):
        index["quest_ids"].add(eid)


def _collect_ids(index: Dict[str, Any], fname: str, data: object) -> None:
    """从模块 JSON 收集 ID → 引用索引（list[dict.id] 或 {id: entry} 两形态）。"""
    if fname == "maps.json":
        for m in _as_list(data):
            if isinstance(m, Mapping) and isinstance(m.get("id"), str) and m.get("id"):
                index["maps"][m["id"]] = m
        index["map_ids"] = set(index["maps"].keys())
        return
    if isinstance(data, list):
        for e in data:
            if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e.get("id"):
                _add_id(index, fname, e["id"])
    elif isinstance(data, Mapping):
        for eid in data:
            if isinstance(eid, str):
                _add_id(index, fname, eid)


def _collect_hidden_refs(index: Dict[str, Any], map_raw: Mapping[str, Any]) -> None:
    """收集隐藏要素引用（hidden_find_id 自声明集合 / 窗口行派生 env_event_id）。"""
    for p in _as_list(map_raw.get("interact_points")):
        if isinstance(p, Mapping):
            _register_hidden_find(index, p.get("hidden_find_id"))
    for row in _as_list(map_raw.get("monsters")):
        if not isinstance(row, Mapping):
            continue
        _register_hidden_find(index, row.get("hidden_find_id"))
        ev = row.get("event_id") or row.get("env_event_id")
        if isinstance(ev, str) and ev:
            index["env_event_ids"].add(ev)
    hr = map_raw.get("hidden_reveal")
    for item in _as_list(hr):
        if isinstance(item, Mapping):
            _register_hidden_find(index, item.get("hidden_find_id"))
    for e in _as_list(map_raw.get("environment_events")):
        if isinstance(e, Mapping):
            eid = e.get("event_id") or e.get("id")
            if isinstance(eid, str) and eid:
                index["env_event_ids"].add(eid)


def _register_hidden_find(index: Dict[str, Any], hf: object) -> None:
    """hidden_find_id 自声明登记（非空 str 才收）。"""
    if isinstance(hf, str) and hf:
        index["hidden_find_ids"].add(hf)


def build_index(pack_dir: str) -> Dict[str, Any]:
    """构建引用索引：maps{id:raw} / map_ids / enemy_ids / item_ids / npc_ids /
    quest_ids / hidden_find_ids（自声明）/ env_event_ids（派生+显式）/ raw（各模块 JSON）。"""
    index: Dict[str, Any] = {
        "maps": {},
        "map_ids": set(),
        "enemy_ids": set(),
        "item_ids": set(),
        "npc_ids": set(),
        "quest_ids": set(),
        "hidden_find_ids": set(),
        "env_event_ids": set(),
        "raw": {},
    }
    for fname in SCAN_FILES:
        data = _load_json(pack_dir, fname)
        if data is None:
            continue
        index["raw"][fname] = data
        _collect_ids(index, fname, data)
    for map_raw in index["maps"].values():
        _collect_hidden_refs(index, map_raw)
    return index


# -------------------------------------------------------------------------------------
# 条件键扫描（递归遍历条件引擎原子表达式）
# -------------------------------------------------------------------------------------
def _iter_condition_exprs(obj: object) -> Iterator[Mapping[str, Any]]:
    """递归遍历 JSON 值，产出条件引擎原子表达式：含 `var` 键的 dict（四键原子）或
    旧 event 原语 {type:"event", event, target, count}。字符串值 `condition:"pv_broken"`
    （战斗行动条件，非条件引擎）不产出，防误报。"""
    if isinstance(obj, Mapping):
        if "var" in obj:
            yield obj
            return
        if (isinstance(obj.get("type"), str) and obj.get("type") == "event"
                and isinstance(obj.get("event"), str)):
            yield obj
            return
        for v in obj.values():
            yield from _iter_condition_exprs(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_condition_exprs(v)


def _condition_vars_of(cond: object) -> List[str]:
    """条件表达式 → 全部 var 键列表（递归 any/all/not 与数组；旧 event 原语 → [事件:x]）。"""
    out: List[str] = []
    for expr in _iter_condition_exprs(cond):
        var = expr.get("var")
        if isinstance(var, str) and var:
            out.append(var)
        elif (isinstance(expr.get("type"), str) and expr.get("type") == "event"
              and isinstance(expr.get("event"), str)):
            out.append("[事件:" + str(expr["event"]) + "]")
    return out


def _var_registered(var: object) -> bool:
    """条件键是否已注册（权威判定 = 条件引擎 normalize_var 非 None，涵盖 REGISTERED_VARS
    精确键 / VAR_ALIASES 中英互译含 {T} 模式 / [事件:*]/[签到:*]/x_ 前缀）。"""
    if not isinstance(var, str) or not var:
        return False
    return normalize_var(var)[0] is not None


def _event_name_of(var: str) -> Tuple[Optional[str], Optional[str]]:
    """事件 var 拆分：`[事件:环境事件:雨夜]` → (name="[事件:环境事件]", target="雨夜")；
    非事件形 → (None, None)。"""
    if not (var.startswith("[事件:") and var.endswith("]")):
        return None, None
    inner = var[len("[事件:"):-1]
    if ":" in inner:
        name, target = inner.rsplit(":", 1)
        if name and target:
            return "[事件:" + name + "]", target
    return var, None


def _event_registered(index: Mapping[str, Any], name: str, target: Optional[str]) -> bool:
    """事件名注册判定：预置/冒险日志六类 → 已注册；3f 预置两行 [事件:环境事件]/
    [事件:隐藏发现] 为模式注册——具体 ID 须在包内自声明集合（env_event_ids /
    hidden_find_ids）解析（契约 §七 L113，未声明 → 永不可达，黄提示）。"""
    if name in ("[事件:环境事件]", "[事件:隐藏发现]"):
        if not (isinstance(target, str) and target):
            return False
        if name == "[事件:环境事件]":
            return target in index["env_event_ids"]
        return target in index["hidden_find_ids"]
    return name in REGISTERED_EVENT_NAMES


# -------------------------------------------------------------------------------------
# 校验 1：隐藏要素可达性（R-16 / R-27 · 提示性不阻断）
# -------------------------------------------------------------------------------------
def _hidden_reveals(map_raw: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """隐藏地图揭示候选（对齐 investigate._hidden_reveals）：地图级 raw hidden_reveal
    （单/数组）+ exits 隐藏入口（mode=hidden）。"""
    out: List[Mapping[str, Any]] = []
    hr = map_raw.get("hidden_reveal")
    for item in _as_list(hr):
        if not isinstance(item, Mapping):
            continue
        ref = item.get("map_ref") or item.get("map_id")
        if isinstance(ref, str) and ref:
            out.append({"map_ref": ref, "lore_condition": item.get("lore_condition"),
                        "hidden_find_id": item.get("hidden_find_id")})
    ex = map_raw.get("exits")
    if isinstance(ex, Mapping):
        for entry in ex.values():
            if not isinstance(entry, Mapping):
                continue
            if (entry.get("mode") == "hidden" and isinstance(entry.get("to"), str)
                    and entry.get("to")):
                out.append({"map_ref": entry.get("to"), "lore_condition": entry.get("condition"),
                            "hidden_find_id": None})
    return out


def _cond_bad_keys(cond: object) -> List[str]:
    """条件表达式含未注册条件键清单（可达性判定：条件永假 → 无发现路径）。"""
    return [v for v in _condition_vars_of(cond) if not _var_registered(v)]


def check_hidden_reachability(index: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """隐藏要素可达性校验（R-16/R-27）：前置条件键全部已注册 + 引用可解析 →
    不可达要素报红（提示性不阻断）。"""
    issues: List[Mapping[str, Any]] = []
    for map_id, raw in sorted(index["maps"].items()):
        _check_map_window_rows(issues, index, map_id, raw)
        _check_map_interact_points(issues, index, map_id, raw)
        _check_map_hidden_reveals(issues, index, map_id, raw)
        _check_map_env_events(issues, index, map_id, raw)
    return issues


def _check_map_window_rows(issues, index, map_id, raw) -> None:
    """隐藏 BOSS 窗口行可达性：window/after 条件键注册 + enemy/boss_ref 可解析。"""
    for row in _as_list(raw.get("monsters")):
        if not isinstance(row, Mapping):
            continue
        win = row.get("window")
        if not isinstance(win, (Mapping, list, tuple)):
            continue
        enemy = row.get("enemy")
        enemy_s = str(enemy) if enemy is not None else None
        bad = _cond_bad_keys(win)
        aft = row.get("after")
        if aft is not None:
            bad += _cond_bad_keys(aft)
        if bad:
            issues.append({
                "level": "RED", "kind": "hidden_boss",
                "msg": f"map={map_id} enemy={enemy_s} 前置条件含未注册条件键 {sorted(set(bad))} "
                       f"→ 无发现路径=可能永不可发现（R-16）",
            })
            continue
        if enemy_s is not None and enemy_s not in index["enemy_ids"]:
            issues.append({
                "level": "RED", "kind": "hidden_boss",
                "msg": (f"map={map_id} 引用敌人 {enemy_s} "
                        f"在 enemies.json registry 无法解析 → 不可达"),
            })
        _register_hidden_find(index, row.get("hidden_find_id"))


def _check_map_interact_points(issues, index, map_id, raw) -> None:
    """交互点彩蛋可达性：lore_condition 条件键注册 + hidden_find_id 引用解析。"""
    for p in _as_list(raw.get("interact_points")):
        if not isinstance(p, Mapping):
            continue
        pid = p.get("id")
        pid_s = str(pid) if pid is not None else "?"
        lc = p.get("lore_condition")
        bad = _cond_bad_keys(lc) if lc is not None else []
        if bad:
            issues.append({
                "level": "RED", "kind": "interact_point",
                "msg": f"map={map_id} interact_point={pid_s} lore_condition 含未注册条件键 "
                       f"{sorted(set(bad))} → 无发现路径=可能永不可发现（R-16）",
            })


def _check_map_hidden_reveals(issues, index, map_id, raw) -> None:
    """隐藏地图揭示可达性：lore_condition 条件键注册 + map_ref 引用解析。"""
    for cand in _hidden_reveals(raw):
        ref = cand.get("map_ref")
        lc = cand.get("lore_condition")
        bad = _cond_bad_keys(lc) if lc is not None else []
        if bad:
            issues.append({
                "level": "RED", "kind": "hidden_map",
                "msg": f"map={map_id} 隐藏地图揭示 {ref} 条件含未注册条件键 {sorted(set(bad))} "
                       f"→ 无发现路径=可能永不可发现（R-16）",
            })
        elif ref is not None and ref not in index["map_ids"]:
            issues.append({
                "level": "RED", "kind": "hidden_map",
                "msg": f"map={map_id} 隐藏地图引用 {ref} 在 maps.json registry 无法解析 → 不可达",
            })


def _check_map_env_events(issues, index, map_id, raw) -> None:
    """环境事件定义可达性：condition 条件键注册 + event_id 全局唯一（重复 → 提示）。"""
    seen: set = set()
    for e in _as_list(raw.get("environment_events")):
        if not isinstance(e, Mapping):
            continue
        eid = e.get("event_id") or e.get("id")
        eid_s = str(eid) if eid is not None else "?"
        if eid_s in seen:
            issues.append({
                "level": "YELLOW", "kind": "environment_event",
                "msg": f"map={map_id} 环境事件 {eid_s} 重复定义（event_id 应全局唯一）",
            })
        seen.add(eid_s)
        cond = e.get("condition")
        bad = _cond_bad_keys(cond) if cond is not None else []
        if bad:
            issues.append({
                "level": "RED", "kind": "environment_event",
                "msg": f"map={map_id} 环境事件 {eid_s} 条件含未注册条件键 {sorted(set(bad))} "
                       f"→ 永不触发（可达性）",
            })


# -------------------------------------------------------------------------------------
# 校验 2：条件键白名单（R-27 · 未注册键报清单）
# -------------------------------------------------------------------------------------
def check_condition_whitelist(index: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """全文扫描 SCAN_FILES 的条件键 → 未注册键/未登记事件报清单（黄提示不阻断）。"""
    issues: List[Mapping[str, Any]] = []
    for fname, data in sorted(index["raw"].items()):
        for expr in _iter_condition_exprs(data):
            var = expr.get("var")
            if isinstance(var, str) and var:
                if not _var_registered(var):
                    issues.append({
                        "level": "YELLOW", "kind": "condition_key",
                        "msg": (f"{fname}: 未注册条件键 {var!r} "
                                f"（白名单 var 键空间外，条件恒不满足）"),
                    })
                    continue
                name, target = _event_name_of(var)
                if name is not None and not _event_registered(index, name, target):
                    if name in ("[事件:环境事件]", "[事件:隐藏发现]"):
                        msg = (f"{fname}: 事件 {name} 引用目标 {target!r} 未在包内声明 "
                               f"→ 永不计数（可达性，契约 §七 L113）")
                    else:
                        msg = (f"{fname}: 事件 {name} 未在事件注册表登记"
                               f"（确认拼写或先登记，NPC 4.3.2）")
                    issues.append({"level": "YELLOW", "kind": "condition_key", "msg": msg})
            else:
                ev = expr.get("event")
                name = "[事件:" + str(ev) + "]"
                if not _event_registered(index, name, expr.get("target")):
                    issues.append({
                        "level": "YELLOW", "kind": "condition_key",
                        "msg": (f"{fname}: 事件 {name} 未在事件注册表登记 "
                                f"（旧 event 原语，建议迁移四键）"),
                    })
    return issues


# -------------------------------------------------------------------------------------
# 校验 3：模板占位符（R-27 · 未定义占位符报提示）
# -------------------------------------------------------------------------------------
def _iter_templates(obj: object, field: Optional[str] = None) -> Iterator[Tuple[str, str]]:
    """递归遍历 JSON 值，产出 (字段名, 含 {X} 的模板文本)：TEMPLATE_FIELDS 键的字符串值。"""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if isinstance(k, str) and k in TEMPLATE_FIELDS and isinstance(v, str) and "{" in v:
                yield k, v
            else:
                yield from _iter_templates(v, field)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_templates(v, field)


def check_placeholders(index: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """模板占位符校验（R-27）：{季节}/{时段}/{天气}/{地图}/{图鉴完成度} 合法，其余 {X}
    未定义占位符报提示（黄）。"""
    issues: List[Mapping[str, Any]] = []
    for fname, data in sorted(index["raw"].items()):
        for field, text in _iter_templates(data):
            for ph in sorted(_PLACEHOLDER_RE.findall(text)):
                if ph not in LEGAL_PLACEHOLDERS:
                    issues.append({
                        "level": "YELLOW", "kind": "placeholder",
                        "msg": f"{fname} [{field}]: 未定义占位符 {{{ph}}}"
                               f"（合法: {'/'.join('{' + p + '}' for p in LEGAL_PLACEHOLDERS)}）",
                    })
    return issues


# -------------------------------------------------------------------------------------
# 主入口
# -------------------------------------------------------------------------------------
def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    """参数解析：--path 内容包目录（缺省仓库 content/demo_lv15）。"""
    default_pack = os.path.join(_REPO_ROOT, "content", "demo_lv15")
    ap = argparse.ArgumentParser(description="3f 内容包校验器（F-18/R-27 可达性/白名单/占位符）")
    ap.add_argument("--path", default=default_pack,
                    help="内容包目录（缺省 content/demo_lv15）")
    return ap.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """运行三项校验并打印报告。返回 exit code：0=通过（无提示）；1=有提示（提示性不阻断）；
    2=内容包目录不存在/不可读。"""
    args = _parse_args(argv)
    pack_dir = os.path.abspath(args.path)
    if not os.path.isdir(pack_dir):
        print(f"错误：内容包目录不存在或不可读: {pack_dir}")
        return 2
    print(f"== 3f 内容包校验器 (F-18/R-27) == 包: {os.path.basename(pack_dir)} @ {pack_dir}")
    index = build_index(pack_dir)
    issues: List[Mapping[str, Any]] = []
    issues += check_hidden_reachability(index)
    issues += check_condition_whitelist(index)
    issues += check_placeholders(index)
    for i in issues:
        print(f"[{i['level']}] {i['kind']}: {i['msg']}")
    red = sum(1 for i in issues if i["level"] == "RED")
    yellow = len(issues) - red
    print(f"== 摘要：RED {red} / YELLOW {yellow} / 总计 {len(issues)} ==")
    if issues:
        print("有提示（提示性不阻断：可保存但建议修复，对齐「只建议不限制」哲学）")
        return 1
    print("通过（无提示）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
