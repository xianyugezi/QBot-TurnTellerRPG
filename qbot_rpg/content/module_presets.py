"""框架默认「模块推荐组合」（批65；用户 2026-09-22 诉求）。

背景
----
一号原则（`docs/深度打造_决策记录.md`）要求**编辑器显示 = 框架能力全集**：空白包也能在
左栏看到全部框架模块（「未启用」灰显）。但新作者面对 36 个模块仍会「不知道先勾哪些」。
本模块提供**框架级推荐组合**（预设）：一个组合 = 一组模块键 + 中文名 + 一句话说明 +
适用人群。编辑器在 ⚙ 模块开关面板顶部列出它们，点击 = **累加启用**（不覆盖用户已勾的）。

数据形状（与条目预设 `entry_presets.py` 同构，但作用域是**模块**而非条目）
--------------------------------------------------------------------------
每条组合 = `{id, label, help, audience, modules}`：
  · `id`       ：组合键（框架声明，包可同 id 覆盖）；
  · `label`    ：中文名；
  · `help`     ：一句话说明（面板里给非技术用户看）；
  · `audience` ：适用人群一句话；
  · `modules`  ：该组合包含的模块键（**顺序即勾选展示顺序**）。

框架默认 ∪ 包声明
-----------------
生效组合 = **框架默认 ∪ 包声明**（`merge_module_presets`）：
  1. **同 id → 包声明整体覆盖框架默认**（不是逐字段合并，避免歧义）；
  2. 包可**追加**新组合：框架没有的 id → 追加到框架默认之后，保持包声明顺序；
  3. 包可**关闭**某个组合：`manifest.json.module_presets_disable: ["<组合 id>", ...]`；
  4. **包未声明 → 框架默认组合仍在**（一号原则：不得因包没声明就消失）。

依赖闭包（关键）
----------------
组合内的模块若声明了前置模块（`module_catalog` 的 `requires`，如「派生链」依赖「技能」、
「强化」依赖「装备」），一键应用时**自动带上依赖**（`preset_modules_with_deps` 递归补全）。
依赖关系**只从 `module_catalog` 读取**，本模块**不写死任何模块名 / 依赖名**——写死的只有
"框架默认组合的内容本身"（这是框架级默认知识，与条目预设同一口径）。

通用性护栏
----------
本模块的机制代码不认任何内容包业务名；`FRAMEWORK_MODULE_PRESETS` 里出现的模块键必须
在 `module_catalog.FRAMEWORK_MODULE_CATALOG` 真实登记，由 `framework_module_preset_errors()`
自检（测试与自检共用），**不臆造模块键**。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.content.module_catalog import CATALOG_BY_MODULE, ModuleCatalogEntry

# 面板顶部「推荐组合」区的标题 / 一句话引导（框架默认；前端模板层可直接展示）。
MODULE_PRESET_TITLE = "推荐组合"
MODULE_PRESET_HINT = (
    "一键把一组常用模块累加勾上（不取消你已勾的）；缺的前置模块会自动补勾。"
)

# =====================================================================================
# 框架默认组合（顺序 = 面板展示顺序）
# =====================================================================================
# 说明：`modules` 只列**这个组合想表达的能力**；前置模块由依赖闭包在应用时自动补全
# （例如「采集」需要「地图」、「符文」需要「效果」——这里是刻意不列全，用闭包证明机制）。
FRAMEWORK_MODULE_PRESETS: Tuple[Mapping[str, Any], ...] = (
    {
        "id": "basic_rpg",
        "label": "基础 RPG 包",
        "help": "能玩起来的最小集：物品、装备、技能、怪物、地图、任务、NPC、商店。",
        "audience": "第一次做可玩内容的新作者",
        "modules": (
            "items", "equipment", "skills", "skill_chains", "effects",
            "statuses", "enemies", "maps", "quest", "npc", "shop", "stats",
        ),
    },
    {
        "id": "life_adventure",
        "label": "生活冒险包",
        "help": "生活线：炼金 / 打造（配方）、锻造、采集、钓鱼、种植——"
                "缺的依赖（如采集要的地图、符文要的效果）会自动补勾。",
        "audience": "想做采集 / 炼金 / 打造 / 钓鱼等生活线的作者",
        "modules": (
            "items", "equipment", "recipe", "forge", "fishing",
            "farming", "gathering", "proficiency", "runes",
            "assistant", "contest",
        ),
    },
    {
        "id": "story_exploration",
        "label": "故事探索包",
        "help": "叙事向：主线任务与任务链、NPC、地图、事件、副本、成就与图鉴。",
        "audience": "以主线 / 任务 / NPC / 地图叙事为主的作者",
        "modules": (
            "quest", "quest_board", "npc", "maps", "enemies", "dungeon",
            "items", "skills", "effects", "statuses", "achievements", "codex",
        ),
    },
)

def _preset_id(item: Mapping[str, Any]) -> str:
    return str(item.get("id") or "")


def _normalize_preset(item: object) -> Optional[Mapping[str, Any]]:
    """把**包声明**的一条组合归一成框架同形（非法 → None，由调用方记 note 丢弃）。

    只做形态归一，不校验模块键是否真实存在（那是解析/应用层的事）。
    """
    if not isinstance(item, Mapping):
        return None
    pid = str(item.get("id") or "").strip()
    mods = item.get("modules")
    if not pid or not isinstance(mods, (list, tuple)):
        return None
    out: Dict[str, Any] = {"id": pid}
    for key in ("label", "help", "audience"):
        val = item.get(key)
        out[key] = str(val) if isinstance(val, str) else ""
    # 模块键：只收非空字符串，去重保序（包声明里的脏值不静默变成"启用一个空模块名"）。
    seen: List[str] = []
    for m in mods:
        name = str(m or "").strip()
        if name and name not in seen:
            seen.append(name)
    if not seen:
        return None
    out["modules"] = tuple(seen)
    return out


def merge_module_presets(
        pack_presets: Sequence[Mapping[str, Any]] = (),
        disabled: Sequence[object] = ()) -> Tuple[Mapping[str, Any], ...]:
    """生效组合 = 框架默认 ∪ 包声明；返回**新元组**，不改任何入参。

    规则（与 docstring 一致，纯函数）：
      · 框架默认按声明顺序在前；包声明同 id → **整体覆盖**（位置仍是框架默认的位置）；
      · 包声明的**新 id** → 追加到末尾（保持包声明顺序）；
      · `disabled` 里的 id → 从结果移除（关闭）。
    """
    merged: List[Mapping[str, Any]] = [dict(p) for p in FRAMEWORK_MODULE_PRESETS]
    index = {_preset_id(p): i for i, p in enumerate(merged)}
    extras: List[Mapping[str, Any]] = []
    for raw in pack_presets or ():
        item = _normalize_preset(raw)
        if item is None:
            continue
        pid = _preset_id(item)
        if pid in index:
            merged[index[pid]] = item
        else:
            extras.append(item)
    merged.extend(extras)
    off = {str(x) for x in (disabled or ()) if str(x or "")}
    if off:
        merged = [p for p in merged if _preset_id(p) not in off]
    return tuple(merged)


def _entry_for(module: str, catalog: Mapping[str, ModuleCatalogEntry]
               ) -> Optional[ModuleCatalogEntry]:
    return catalog.get(module)


def preset_modules_with_deps(
        modules: Iterable[object],
        *,
        declared: Iterable[object] = (),
        catalog: Optional[Mapping[str, ModuleCatalogEntry]] = None,
        enableable: Optional[Any] = None) -> Dict[str, Any]:
    """按 `module_catalog.requires` 递归补全组合的依赖闭包（不写死模块名）。

    入参：
      · `modules`   ：组合声明的模块键（可含重复 / 脏值）；
      · `declared`  ：本包 manifest 已声明的模块（已启用的自定义模块也算可用）；
      · `catalog`   ：模块目录（缺省 = 框架目录 `CATALOG_BY_MODULE`）；
      · `enableable`：`(module) -> bool`；缺省 = 目录里存在且 `implemented`。

    出参（全部为**保序去重**的模块键列表）：
      · `ordered`   ：显式模块在前（按声明顺序）+ 自动补勾的依赖（按发现顺序）；
      · `auto_deps` ：仅由依赖闭包补进来的模块；
      · `unknown`   ：既不在目录、也未在包声明 → 无法启用（丢弃并提示）；
      · `unavailable`：在目录但引擎未实装 → 不启用（丢弃并提示）。
    """
    cat = CATALOG_BY_MODULE if catalog is None else catalog
    declared_set = {str(m) for m in (declared or ())}

    def _is_enableable(name: str) -> bool:
        if enableable is not None:
            return bool(enableable(name))
        entry = _entry_for(name, cat)
        return entry is not None and bool(entry.implemented)

    def _applicable(name: str) -> bool:
        return name in declared_set or _is_enableable(name)

    explicit: List[str] = []
    unknown: List[str] = []
    unavailable: List[str] = []
    for raw in modules or ():
        name = str(raw or "").strip()
        if not name or name in explicit:
            continue
        if _applicable(name):
            explicit.append(name)
        elif _entry_for(name, cat) is not None:
            if name not in unavailable:
                unavailable.append(name)
        elif name not in unknown:
            unknown.append(name)

    auto: List[str] = []
    visited = set(explicit)
    queue: List[str] = list(explicit)
    while queue:
        cur = queue.pop(0)
        entry = _entry_for(cur, cat)
        if entry is None:
            continue
        for req in entry.requires:
            name = str(req)
            if name in visited:
                continue
            visited.add(name)
            if not _applicable(name):
                entry_req = _entry_for(name, cat)
                if entry_req is not None:
                    if name not in unavailable:
                        unavailable.append(name)
                elif name not in unknown:
                    unknown.append(name)
                continue
            auto.append(name)
            queue.append(name)
    return {"ordered": explicit + auto, "auto_deps": auto,
            "unknown": unknown, "unavailable": unavailable}


def resolve_module_presets(
        pack_presets: Sequence[Mapping[str, Any]] = (),
        disabled: Sequence[object] = (),
        *,
        declared: Iterable[object] = (),
        catalog: Optional[Mapping[str, ModuleCatalogEntry]] = None,
        enableable: Optional[Any] = None) -> List[Dict[str, Any]]:
    """生效组合 + 逐条解析（供 API / 写入层共用；纯函数，不碰文件）。

    每条返回：`{id,label,help,audience,modules,modules_labels,auto_deps,auto_dep_labels,
    add_modules,add_labels,already,unknown,unavailable}`。
      · `modules`    = 闭包后**要确保启用**的模块全集（含自动依赖）；
      · `auto_deps`  = 其中由依赖闭包补进来的（前端提示"已自动带上"）；
      · `add_modules`= `modules` 里**当前尚未启用**的（一键应用实际会写入的）；
      · `already`    = `add_modules` 为空（组合已满足）。
    """
    cat = CATALOG_BY_MODULE if catalog is None else catalog
    declared_set = {str(m) for m in (declared or ())}

    def _label(name: str) -> str:
        entry = _entry_for(name, cat)
        return entry.label if entry is not None and entry.label else name

    out: List[Dict[str, Any]] = []
    for preset in merge_module_presets(pack_presets, disabled):
        resolved = preset_modules_with_deps(
            preset.get("modules") or (), declared=declared_set,
            catalog=cat, enableable=enableable)
        ordered = resolved["ordered"]
        add = [m for m in ordered if m not in declared_set]
        out.append({
            "id": _preset_id(preset),
            "label": str(preset.get("label") or _preset_id(preset)),
            "help": str(preset.get("help") or ""),
            "audience": str(preset.get("audience") or ""),
            "modules": ordered,
            "modules_labels": [_label(m) for m in ordered],
            "auto_deps": resolved["auto_deps"],
            "auto_dep_labels": [_label(m) for m in resolved["auto_deps"]],
            "add_modules": add,
            "add_labels": [_label(m) for m in add],
            "already": not add,
            "unknown": resolved["unknown"],
            "unavailable": resolved["unavailable"],
        })
    return out


def find_module_preset(presets: Sequence[Mapping[str, Any]], preset_id: object
                       ) -> Optional[Mapping[str, Any]]:
    """按 id 取一条已解析组合（未知 → None，不抛）。"""
    pid = str(preset_id or "")
    for item in presets or ():
        if _preset_id(item) == pid:
            return item
    return None


def framework_module_preset_errors() -> List[str]:
    """框架默认组合的**键合理性**自检（人话错误列表；空 = 全部合法）。

    检查：每条组合 `id/label/help/audience` 非空、id 唯一、`modules` 非空且每个模块键
    都在 `module_catalog.CATALOG_BY_MODULE` 真实登记——防臆造模块键。
    """
    errors: List[str] = []
    seen: set = set()
    for i, preset in enumerate(FRAMEWORK_MODULE_PRESETS):
        pid = _preset_id(preset)
        if not pid:
            errors.append(f"[{i}] 缺少 id")
            continue
        if pid in seen:
            errors.append(f"组合 id 重复：{pid}")
        seen.add(pid)
        for key in ("label", "help", "audience"):
            if not str(preset.get(key) or "").strip():
                errors.append(f"{pid} 缺少 {key}")
        modules = list(preset.get("modules") or ())
        if not modules:
            errors.append(f"{pid} 没有 modules")
        for m in modules:
            if str(m) not in CATALOG_BY_MODULE:
                errors.append(f"{pid} 引用未登记模块键：{m}")
    return errors


__all__ = [
    "FRAMEWORK_MODULE_PRESETS",
    "MODULE_PRESET_HINT",
    "MODULE_PRESET_TITLE",
    "find_module_preset",
    "framework_module_preset_errors",
    "merge_module_presets",
    "preset_modules_with_deps",
    "resolve_module_presets",
]
