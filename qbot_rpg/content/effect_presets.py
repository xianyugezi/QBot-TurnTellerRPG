"""框架级**特效预设集**（批54 · 预设集与结算轴；内容作者可直接选）。

定位
----
`特效整理设计_2_框架预设包.md` §1「预设词条集」把搜集报告收敛成**预设族**
（武器 / 护甲 / 饰品 / 通用 × 普通/进阶/稀有 三档）。本模块把这些预设族落成
**框架级声明**——内容作者在编辑器「新建条目」时直接选一个预设即可，**不必背轴名**。

与既有机制的关系（**复用，不新造一套**）
----------------------------------------
· 本表**不引入新的预设引擎**：每条预设经 `entry_presets_for()` 投影成既有
  `qbot_rpg/content/entry_presets.py` 的同形条目（`{id,label,help,fields,defaults,
  id_prefix,id_width}`），由同一 `merge_entry_presets()` 合并（框架默认 ∪ 包声明 −
  `entry_presets_disable`），经同一 `web/api.new_entry_detail` 供编辑器选择。
· 预设只是「命名 + 一组轴取值」，**不写进任何内容包**（框架预设 ≠ 内容数据）；
  包可覆盖 / 追加 / 关闭（口径见 `entry_presets.py` docstring）。
· 预设引用的轴键一律取 `data.gear_stats` 既有登记（特效轴 `GEAR_EFFECT_KEYS` 或
  既有装备数值键 `GEAR_NUMERIC_KEYS`），**不臆造键名**。

双向优先（设计最高原则）
------------------------
同一条轴的两个方向 = **两条预设**（不是两条轴）：如
`armor_heal_down`（重伤 = `healing_received_pct: -15/-30/-50`）与
`armor_heal_up`（强疗 = 同轴 `+15/+30/+50`），二者同 `conflict_group` → **互斥**。

档位（`tiers`）
---------------
每条预设声明 `normal/advanced/rare` 三档取值（设计 §1.0「档位只改数值，不改轴与触发」）。
编辑器「新建条目」落 **`normal`** 档（= `defaults`）；更高档由后续掉落/强化系统掷取，
**本批不接线**（登记待裁决）。数值全部取自设计 §1 的**档位示意**，非平衡终值。

叠加 / 互斥（`stack` / `conflict_group`）
----------------------------------------
· `stack` = 多来源叠加口径；与 `EFFECT_AXIS_SPECS` 的 `stack` 一致（当前一律 `add`，
  即百分点/差值相加）。
· `conflict_group` = **声明式**组名：同组 + `direction` 相反 = 互斥（如「坚壁」×「破绽之甲」）。
  **执行仍走既有装备互斥链**（`equipment.validate_slot_exclusions` / `excludes`）——
  预设只给作者判断依据，不新增第二套互斥引擎。

校验（`effect_preset_errors`）
------------------------------
纯函数：逐条检查「引用轴存在 / 取值在轴范围内（越界 = 红拦）/ id 唯一 / 部位与方向合法 /
`fields`·`defaults` 键已登记」。测试与自检共用，**不臆造键名、不写死数值**。

纪律：本模块只读仓库既有登记表；不写任何真实内容包业务名；不调任何数值平衡。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.data.gear_stats import GEAR_EFFECT_KEYS, normalize_effect_axes

# ---------------------------------------------------------------------------
# 声明口径常量（唯一源；改动即整表生效）
# ---------------------------------------------------------------------------
#: 预设档位（设计 §1.0：普通 / 进阶 / 稀有）。编辑器落 `DEFAULT_TIER` 档。
PRESET_TIERS: Tuple[str, ...] = ("normal", "advanced", "rare")
DEFAULT_TIER: str = "normal"

#: 适用部位（设计 §1.0：武器 / 护甲 / 饰品 / 通用）。`any` = 通用（触发/结构类）。
PRESET_SLOTS: Tuple[str, ...] = ("weapon", "armor", "accessory", "any")

#: 双向轴的两个方向（加法/多方向轴亦用 `up`/`down` 表示「正向/负向」）。
PRESET_DIRECTIONS: Tuple[str, ...] = ("up", "down")

#: 预设的宿主模块（**数据声明**，非逻辑分支）：装备条目（`kind=equipment`，含 `slot`）。
#: 本表只面对该模块；其它模块的既有预设（如 items 六种通用品类）不受影响。
EFFECT_PRESET_MODULE: str = "equipment"

#: 预设条目主区字段前缀（标识/部位 → 轴）：与既有装备预设的顺序口径一致。
_PRESET_BASE_FIELDS: Tuple[str, ...] = ("name", "type", "desc", "slot", "price")

#: `help` 长度上限（一号原则：Tip/帮助引导，**忌长文**）。
MAX_HELP_LEN: int = 60


def _preset(
    pid: str,
    *,
    label: str,
    help_: str,
    slot: str,
    family: str,
    direction: str,
    axis: str,
    tiers: Mapping[str, Any],
    conflict_group: str,
    id_prefix: str,
    stack: str = "add",
    fields: Optional[Tuple[str, ...]] = None,
    note: str = "",
) -> Dict[str, Any]:
    """构造一条框架预设（唯一构造点，保证形状齐备）。

    `defaults` 取 `DEFAULT_TIER` 档（编辑器落档值）；`fields` 缺省 = 标识/部位 + 轴。
    """
    return {
        "id": str(pid),
        "module": EFFECT_PRESET_MODULE,
        "label": str(label),
        "help": str(help_),
        "slot": str(slot),
        "family": str(family),
        "direction": str(direction),
        "axis": str(axis),
        "tiers": {t: tiers[t] for t in PRESET_TIERS if t in tiers},
        "stack": str(stack),
        "conflict_group": str(conflict_group),
        "id_prefix": str(id_prefix),
        "id_width": None,
        "fields": tuple(fields or (_PRESET_BASE_FIELDS + (str(axis),))),
        "defaults": {str(axis): tiers.get(DEFAULT_TIER)},
        "note": str(note),
    }


# ---------------------------------------------------------------------------
# 框架预设集（**唯一源**）——设计 §1.1 武器 / §1.2 护甲 / §1.3 饰品
# ---------------------------------------------------------------------------
# 逐条取值 = 设计 §1 的 `_mult` 档位 → 本框架的**百分点增量**（`pct = (mult-1)*100`）：
#   ×1.10 ⇔ +10 · ×0.85 ⇔ -15 · ×0.50 ⇔ -50 ……（转换口径见 §0.1 / 实现说明「批50」§13.2）
FRAMEWORK_EFFECT_PRESETS: Tuple[Mapping[str, Any], ...] = (
    # ---- 武器（weapon）：进攻轴为主，允许代价型负向 ----
    _preset(
        "weapon_dmg", label="破甲锋刃", slot="weapon", family="damage_dealt",
        direction="up", axis="damage_dealt_pct",
        tiers={"normal": 10, "advanced": 25, "rare": 45},
        conflict_group="damage_dealt", id_prefix="dmg",
        help_="造成伤害提升：终伤乘区 ×(1+值/100)（>0 增伤）。",
        note="设计 §1.1 `weapon_dmg_phys/elem/skill/dot/weakpoint` 的**无条件**形态；"
             "定向 scope（物理/元素/技能/DoT/弱点）走效果条目条件，登记待接线。",
    ),
    _preset(
        "weapon_crit_up", label="会心锋刃", slot="weapon", family="crit_damage",
        direction="up", axis="crit_damage_pct",
        tiers={"normal": 10, "advanced": 25, "rare": 40},
        conflict_group="crit_damage", id_prefix="crit",
        help_="会心倍率提升：暴击伤害 ×(1+值/100)（>0 强化）。",
    ),
    _preset(
        "weapon_crit_down", label="钝锋", slot="weapon", family="crit_damage",
        direction="down", axis="crit_damage_pct",
        tiers={"normal": -10, "advanced": -20, "rare": -30},
        conflict_group="crit_damage", id_prefix="blunt",
        help_="会心倍率下降：暴伤 ×(1+值/100)（<0 削弱，换更高白值的代价型）。",
    ),
    _preset(
        "weapon_cd_haste", label="循环加速", slot="weapon", family="cooldown",
        direction="down", axis="cooldown_pct",
        tiers={"normal": -10, "advanced": -20, "rare": -30},
        conflict_group="cooldown", id_prefix="haste",
        help_="冷却缩短：技能冷却 ×(1+值/100)（<0 更快；结果下钳 0）。",
    ),
    _preset(
        "weapon_cd_seal", label="封印回响", slot="weapon", family="cooldown",
        direction="up", axis="cooldown_pct",
        tiers={"normal": 15, "advanced": 30, "rare": 50},
        conflict_group="cooldown", id_prefix="seal",
        help_="冷却延长：技能冷却 ×(1+值/100)（>0 更慢，换高额伤害的代价型）。",
    ),
    _preset(
        "weapon_stack_gain", label="涌流之刃", slot="weapon", family="stack_gain",
        direction="up", axis="stack_gain_pct",
        tiers={"normal": 25, "advanced": 50, "rare": 100},
        conflict_group="stack_gain", id_prefix="flow",
        help_="层数获取提升：每次叠层量 ×(1+值/100)（>0 叠得快）。",
    ),
    _preset(
        "weapon_stack_cap", label="拓层之刃", slot="weapon", family="stack_cap",
        direction="up", axis="stack_cap_delta",
        tiers={"normal": 1, "advanced": 2, "rare": 3},
        conflict_group="stack_cap", id_prefix="cap",
        help_="层数上限加算（+1 层）：不是百分比，直接抬高层数上限。",
    ),
    _preset(
        "weapon_lifesteal", label="汲血", slot="weapon", family="lifesteal",
        direction="up", axis="absorb_hp",
        tiers={"normal": 3, "advanced": 6, "rare": 10},
        conflict_group="lifesteal", id_prefix="leech",
        help_="吸血：造成伤害后按该比例回复自身生命（单位 %，0-100）。",
        note="既有键 `absorb_hp`（数据既有、消费点既有）；本预设只打包命名与档位。",
    ),
    _preset(
        "weapon_pierce", label="破防", slot="weapon", family="pierce",
        direction="up", axis="pierce_pct",
        tiers={"normal": 10, "advanced": 20, "rare": 30},
        conflict_group="pierce", id_prefix="pierce",
        help_="物穿比：按比例无视目标物理防御（单位 %，0-100，既有封顶不放宽）。",
        note="既有键 `pierce_pct`；元素穿透 `pierce{target:elem_res}` 需参数化，登记待接线。",
    ),
    # ---- 护甲（armor）：防御轴为主，允许代价型正向 ----
    _preset(
        "armor_taken_down", label="坚壁", slot="armor", family="damage_taken",
        direction="down", axis="damage_taken_pct",
        tiers={"normal": -8, "advanced": -15, "rare": -25},
        conflict_group="damage_taken", id_prefix="wall",
        help_="减伤：受到的伤害 ×(1+值/100)（<0 减伤）。",
    ),
    _preset(
        "armor_taken_up", label="破绽之甲", slot="armor", family="damage_taken",
        direction="up", axis="damage_taken_pct",
        tiers={"normal": 8, "advanced": 15, "rare": 25},
        conflict_group="damage_taken", id_prefix="vuln",
        help_="易伤：受到的伤害 ×(1+值/100)（>0 受伤增加，换输出）。",
    ),
    _preset(
        "armor_heal_up", label="强疗", slot="armor", family="healing_received",
        direction="up", axis="healing_received_pct",
        tiers={"normal": 15, "advanced": 30, "rare": 50},
        conflict_group="healing_received", id_prefix="heal",
        help_="受疗提升：受到的治疗 ×(1+值/100)（>0 增疗）。与『重伤』同族互斥。",
    ),
    _preset(
        "armor_heal_down", label="重伤", slot="armor", family="healing_received",
        direction="down", axis="healing_received_pct",
        tiers={"normal": -15, "advanced": -30, "rare": -50},
        conflict_group="healing_received", id_prefix="wound",
        help_="受疗下降：受到的治疗 ×(1+值/100)（<0 减疗）。与『强疗』同族互斥。",
    ),
    _preset(
        "armor_ctrl_res", label="定神", slot="armor", family="status_resist",
        direction="up", axis="status_resist_pct",
        tiers={"normal": 20, "advanced": 35, "rare": 50},
        conflict_group="status_resist", id_prefix="calm",
        help_="状态抵抗：更难被挂上控制/减益（加算百分点，>0 更抗）。",
    ),
    _preset(
        "armor_ctrl_vuln", label="失神", slot="armor", family="status_resist",
        direction="down", axis="status_resist_pct",
        tiers={"normal": -20, "advanced": -40, "rare": -60},
        conflict_group="status_resist", id_prefix="daze",
        help_="状态抵抗下降：更易被挂上控制/减益（<0 易感，换收益）。",
    ),
    _preset(
        "armor_dur_down", label="涤净之躯", slot="armor", family="status_duration_taken",
        direction="down", axis="status_duration_taken_pct",
        tiers={"normal": -15, "advanced": -30, "rare": -50},
        conflict_group="status_duration_taken", id_prefix="clean",
        help_="受状态时长缩短：挂上的状态更快结束（<0 抗控）。",
    ),
    _preset(
        "armor_dur_up", label="缠身之甲", slot="armor", family="status_duration_taken",
        direction="up", axis="status_duration_taken_pct",
        tiers={"normal": 15, "advanced": 30, "rare": 50},
        conflict_group="status_duration_taken", id_prefix="cling",
        help_="受状态时长延长：挂上的状态持续更久（>0 代价型）。",
    ),
    # ---- 饰品（accessory）：资源与结构轴为主 ----
    _preset(
        "accessory_cost_down", label="节流", slot="accessory", family="resource_cost",
        direction="down", axis="resource_cost_pct",
        tiers={"normal": -10, "advanced": -20, "rare": -35},
        conflict_group="resource_cost", id_prefix="save",
        help_="省耗：技能资源消耗 ×(1+值/100)（<0 更省；下钳 0，-100 = 免费）。",
    ),
    _preset(
        "accessory_cost_up", label="挥霍", slot="accessory", family="resource_cost",
        direction="up", axis="resource_cost_pct",
        tiers={"normal": 10, "advanced": 25, "rare": 40},
        conflict_group="resource_cost", id_prefix="burn",
        help_="更耗：技能资源消耗 ×(1+值/100)（>0 更贵，换收益）。",
    ),
    _preset(
        "accessory_gain_up", label="灵泉", slot="accessory", family="resource_gain",
        direction="up", axis="resource_gain_pct",
        tiers={"normal": 15, "advanced": 30, "rare": 50},
        conflict_group="resource_gain", id_prefix="spring",
        help_="资源获取提升：资源获得量 ×(1+值/100)（>0 回得快）。",
    ),
    _preset(
        "accessory_first_strike", label="先手符", slot="accessory", family="action_bar",
        direction="up", axis="action_bar_shift",
        tiers={"normal": 3, "advanced": 6, "rare": 10},
        conflict_group="action_bar", id_prefix="first",
        help_="行动条提前（加算 +N）：正 = 提前行动。与『迟滞符』同族互斥。",
    ),
    _preset(
        "accessory_delay", label="迟滞符", slot="accessory", family="action_bar",
        direction="down", axis="action_bar_shift",
        tiers={"normal": -3, "advanced": -6, "rare": -10},
        conflict_group="action_bar", id_prefix="delay",
        help_="行动条延后（加算 -N）：负 = 延后行动，代价型。与『先手符』同族互斥。",
    ),
    _preset(
        "accessory_stack_gain", label="涌流", slot="accessory", family="stack_gain",
        direction="up", axis="stack_gain_pct",
        tiers={"normal": 25, "advanced": 50, "rare": 100},
        conflict_group="stack_gain", id_prefix="flow",
        help_="层数获取提升：每次叠层量 ×(1+值/100)（>0 叠得快）。",
    ),
    _preset(
        "accessory_stack_damp", label="抑层", slot="accessory", family="stack_gain",
        direction="down", axis="stack_gain_pct",
        tiers={"normal": -25, "advanced": -50, "rare": -75},
        conflict_group="stack_gain", id_prefix="damp",
        help_="层数获取下降：每次叠层量 ×(1+值/100)（<0 叠得慢，换收益）。",
    ),
    _preset(
        "accessory_stack_cap_down", label="缚层", slot="accessory", family="stack_cap",
        direction="down", axis="stack_cap_delta",
        tiers={"normal": -1, "advanced": -2, "rare": -3},
        conflict_group="stack_cap", id_prefix="bind",
        help_="层数上限加算（-1 层）：压低上限，对抗叠层型敌人或作代价。",
        note="与「叠得慢」（`stack_gain_pct`）**不是同一条轴**：一条改速度、一条改上限。",
    ),
    _preset(
        "accessory_bewitch", label="惑心", slot="accessory", family="status_chance",
        direction="up", axis="status_chance_pct",
        tiers={"normal": 15, "advanced": 30, "rare": 50},
        conflict_group="status_chance", id_prefix="hex",
        help_="状态命中提升：施加状态的基础命中 ×(1+值/100)（>0 更易挂上）。",
    ),
)


def framework_effect_presets() -> Tuple[Mapping[str, Any], ...]:
    """框架特效预设全表（只读）。"""
    return FRAMEWORK_EFFECT_PRESETS


def effect_preset_modules() -> Tuple[str, ...]:
    """框架特效预设覆盖的模块（去重、保持声明顺序）——`entry_presets` 合并用。"""
    out: List[str] = []
    for p in FRAMEWORK_EFFECT_PRESETS:
        m = str(p.get("module") or "")
        if m and m not in out:
            out.append(m)
    return tuple(out)


def find_effect_preset(preset_id: object) -> Optional[Mapping[str, Any]]:
    """按 id 取预设（未命中 → None）；只读。"""
    pid = str(preset_id or "")
    if not pid:
        return None
    for p in FRAMEWORK_EFFECT_PRESETS:
        if str(p.get("id") or "") == pid:
            return p
    return None


def effect_presets_for(module: object) -> Tuple[Mapping[str, Any], ...]:
    """某模块的框架特效预设（无 → 空元组）；只读。"""
    mod = str(module or "")
    return tuple(p for p in FRAMEWORK_EFFECT_PRESETS
                 if str(p.get("module") or "") == mod)


def entry_presets_for(module: object) -> Tuple[Mapping[str, Any], ...]:
    """投影成**既有 `entry_presets` 同形条目**（编辑器/合并链路直接吃）。

    保留 `entry_presets` 的六个键（id/label/help/fields/defaults/id_prefix/id_width），
    并**额外携带**预设族元数据（axis/slot/family/direction/tiers/stack/conflict_group）
    ——既有链路只读它认识的键，多出的键被忽略（不新造第二套机制）。
    """
    out: List[Mapping[str, Any]] = []
    for p in effect_presets_for(module):
        entry = {
            "id": str(p.get("id") or ""),
            "label": str(p.get("label") or ""),
            "help": str(p.get("help") or ""),
            "fields": tuple(p.get("fields") or ()),
            "defaults": dict(p.get("defaults") or {}),
            "id_prefix": str(p.get("id_prefix") or ""),
            "id_width": p.get("id_width"),
        }
        for key in ("axis", "slot", "family", "direction", "stack",
                    "conflict_group", "note"):
            entry[key] = p.get(key)
        entry["tiers"] = dict(p.get("tiers") or {})
        out.append(entry)
    return tuple(out)


# ---------------------------------------------------------------------------
# 校验（越界红拦 / 引用轴存在）——纯函数，测试与自检共用
# ---------------------------------------------------------------------------
def _field_table(table: object) -> object:
    """缺省元数据表（延迟 import：避免 content 包导入期重依赖）。"""
    if table is not None:
        return table
    from qbot_rpg.content.field_meta import default_field_meta_table  # noqa: PLC0415
    return default_field_meta_table()


def _axis_bounds(axis: str, module: str, table: object, cfg: Any = None
                 ) -> Tuple[Optional[float], Optional[float], bool]:
    """某轴的**有效取值区间** (min, max, is_effect_axis)。

    · 特效轴（`GEAR_EFFECT_KEYS`）→ `normalize_effect_axes(cfg)` 的声明区间
      （消费点与内容校验同一口径；缺省 = 登记表建议区间）；
    · 其它已登记数值键（如 `absorb_hp` / `pierce_pct`）→ 模块字段元数据的
      `range_min/range_max`（同源，不另写死）。
    轴不存在 → (None, None, False) 且由调用方判「引用轴不存在」。
    """
    if axis in GEAR_EFFECT_KEYS:
        entry = normalize_effect_axes(cfg).get(axis) or {}
        return entry.get("min"), entry.get("max"), True
    mmeta = table.module(module) if table is not None else None
    fields = getattr(mmeta, "fields", None) if mmeta is not None else None
    fm = fields.get(axis) if isinstance(fields, Mapping) else None
    if fm is None:
        return None, None, False
    return getattr(fm, "range_min", None), getattr(fm, "range_max", None), False


def effect_preset_errors(
    presets: Optional[Any] = None,
    cfg: Any = None,
    table: Optional[object] = None,
) -> List[str]:
    """框架特效预设的**逐条校验**（返回人话错误列表；空 = 全部合法）。

    检查项（对应验收「引用轴存在 / 取值在轴范围内 → 越界红拦」）：
      · `id` 非空且唯一；`label` / `help` / `family` / `conflict_group` 非空；
      · `help` 不超过 `MAX_HELP_LEN`（一号原则：忌长文）；
      · `slot` ∈ `PRESET_SLOTS`；`direction` ∈ `PRESET_DIRECTIONS`；
      · `axis` 在**宿主模块元数据**里真实登记（引用轴存在）；
      · `tiers` 覆盖三档、均为数值，且落在该轴有效区间内（越界 = 红拦）；
      · `defaults[axis]` == `normal` 档（编辑器落档口径）；
      · `fields` / `defaults` 的键都在宿主模块元数据里登记（不臆造键名）。
    """
    rows = tuple(FRAMEWORK_EFFECT_PRESETS if presets is None else presets)
    tbl = _field_table(table)
    errors: List[str] = []
    seen: set = set()
    for i, p in enumerate(rows):
        if not isinstance(p, Mapping):
            errors.append(f"[{i}] 预设条目不是对象")
            continue
        pid = str(p.get("id") or "")
        if not pid:
            errors.append(f"[{i}] 缺少 id")
            continue
        if pid in seen:
            errors.append(f"预设 id 重复：{pid}")
        seen.add(pid)
        module = str(p.get("module") or "")
        for key in ("label", "help", "family", "conflict_group", "axis"):
            if not str(p.get(key) or ""):
                errors.append(f"{pid} 缺少 {key}")
        help_text = str(p.get("help") or "")
        if len(help_text) > MAX_HELP_LEN:
            errors.append(f"{pid} help 过长（{len(help_text)} > {MAX_HELP_LEN}）：忌长文")
        if str(p.get("slot") or "") not in PRESET_SLOTS:
            errors.append(f"{pid} slot 非法：{p.get('slot')!r}（须 ∈ {PRESET_SLOTS}）")
        if str(p.get("direction") or "") not in PRESET_DIRECTIONS:
            errors.append(f"{pid} direction 非法：{p.get('direction')!r}")
        mmeta = tbl.module(module) if tbl is not None and module else None
        fields = getattr(mmeta, "fields", None) if mmeta is not None else None
        known = set(fields) if isinstance(fields, Mapping) else set()
        if not known:
            errors.append(f"{pid} 宿主模块未登记：{module!r}")
            continue
        axis = str(p.get("axis") or "")
        if axis and axis not in known:
            errors.append(f"{pid} 引用轴不存在：{axis}")
        elif axis:
            lo, hi, _is_effect = _axis_bounds(axis, module, tbl, cfg)
            tiers = p.get("tiers") if isinstance(p.get("tiers"), Mapping) else {}
            for tier in PRESET_TIERS:
                if tier not in tiers:
                    errors.append(f"{pid} 缺档位 {tier}")
                    continue
                val = tiers.get(tier)
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    errors.append(f"{pid}.{tier} 取值非数值：{val!r}")
                    continue
                fv = float(val)
                if lo is not None and fv < float(lo):
                    errors.append(f"{pid}.{tier} 越界：{fv} < {lo}")
                if hi is not None and fv > float(hi):
                    errors.append(f"{pid}.{tier} 越界：{fv} > {hi}")
            defaults = p.get("defaults") if isinstance(p.get("defaults"), Mapping) else {}
            if defaults.get(axis) != tiers.get(DEFAULT_TIER):
                errors.append(
                    f"{pid}.defaults 未取 {DEFAULT_TIER} 档：{defaults.get(axis)!r} "
                    f"!= {tiers.get(DEFAULT_TIER)!r}")
        for group in ("fields", "defaults"):
            raw = p.get(group)
            keys = (list(raw) if isinstance(raw, Mapping) else list(raw or ()))
            for key in keys:
                if str(key) not in known:
                    errors.append(f"{pid}.{group} 引用未登记键：{key}")
    return errors


__all__ = [
    "PRESET_TIERS",
    "DEFAULT_TIER",
    "PRESET_SLOTS",
    "PRESET_DIRECTIONS",
    "EFFECT_PRESET_MODULE",
    "MAX_HELP_LEN",
    "FRAMEWORK_EFFECT_PRESETS",
    "framework_effect_presets",
    "effect_preset_modules",
    "effect_presets_for",
    "entry_presets_for",
    "find_effect_preset",
    "effect_preset_errors",
]
