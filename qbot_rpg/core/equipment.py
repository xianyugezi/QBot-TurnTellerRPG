"""装备引擎（M6 批次1·路A · 实装版）——穿戴校验链/部位匹配/互斥与数量校验/后装覆盖/卸装回包/加成聚合/属性全链重算。

依据：
  - 细化_M6_三引擎与基础指令（D1）§三 equipment 引擎实装契约：规则 EQP-01~EQP-12、
    字段 F-15~F-20、边界异常 EQP-E1~EQP-E5、验收用例 TC-EQP-01~TC-EQP-06。
  - 【框架】L187-192（3.5 装备引擎：部位定义/互斥/同名数量/装饰珠插槽/战斗中不可插拔）、
    L815-830（5.1 部位定义 slots.json：name/max/occupies/mutual_exclusions、装备校验链
    「占用集合 → 互斥检查 → 数量检查 → 通过穿上」）、L1535-1537（互斥环加载期拦截/运行期
    人话拒绝）、L1390-1396（8.2 状态面板：部位名来自内容包）。
  - 【4b】EQP-01~04/EQP-R01~R08（穿戴规则）、INS-xx（实例快照）；【3b】TC-07（卸装即时
    重算）、§1.1（加成层来源：flat/pct 同层聚合）。
  - 现有代码 core/equipment.py（M1 空壳骨架 + equip_search 预留签名）+ data/player.py
    （EquipmentSlot）+ data/item.py（ItemInstance）。

【工程补白 · 显式标注】
  1) 操作对象 = 玩家状态 dict（ctx 玩家表示，可变，就地改写）：
     player["equipment"]：可变 dict {slot_id: EquipmentSlot}；player["inventory"]：可变
     list、元素 = ItemInstance（D1 B-3：inventory 元素用领域类型）。
  2) B-3 双向一致性：穿戴状态 = `player["equipment"]` 键集（槽位 → EquipmentSlot 槽实例）；
     背包行 ItemInstance.slot 语义 = 可装备槽位类型（data/item.py L34，非穿戴状态标记），
     引擎**不清空/改写**背包行 slot（清空会丢失「此件可穿入何槽」信息，导致再穿失败，
     见 EQP-02 部位匹配）。穿/脱只增删 equipment 键；装备词条经 equipment 槽实例的
     item_id 回查背包行读取（aggregate_bonus）。对 D1 EQP-05「写 ItemInstance.slot=null」
     的字面做法**偏离**：理由如上（工程补白 8）。
  3) 槽位定义缺省兜底（D1 B-2 兜底 + 任务要求对齐 basic_commands.DEFAULT_SLOT_NAMES /
     DEFAULT_SLOT_ORDER）：本文件内联同值缺省表（weapon/armor_head/armor_body/armor_hand/
     armor_leg/armor_foot，max=1），内容包 slots.json 经构造器注入覆盖。**不 import
     qbot_rpg.commands.basic_commands**——G0 架构门禁（tests/contract/test_g0_architecture.py
     R3/D-05：commands/web 不被任何 qbot_rpg 模块 import）禁止 core→commands 反向依赖，
     故同值内联 + 构造器注入。
  4) EQP-06 equip_snapshot 语义 = attributes.bonus：aggregate_bonus 把各已穿戴件
     stats_bonus（flat）同层求和写入 attributes.bonus["flat"]；stats_pct（getattr 钩子，
     ItemInstance 当前无此字段）写入 attributes.bonus["pct"]；两子层**全量重写**（装备聚合
     即加成层快照；若未来需叠加战斗外药剂加成，由装配层在聚合后追加——工程补白）。
  5) EQP-07 属性全链重算：穿/脱/聚合后调 calc_all_final_attributes(player["attributes"])。
  6) EQP-09 战斗内不可穿脱：player["in_battle"] is True → 拒绝「战斗中不可更换装备（战前
     换装）」；缺省 False=战斗外（战斗态由装配层写入）。
  7) EQP-08 互斥环拦截：validate_slot_exclusions 为加载期校验器（slots.json 互斥成环 →
     抛 ValueError 红色拦截，内容包不加载）；运行期穿装互斥冲突 → {ok: False,
     reason: "mutual_exclusion"} 人话拒绝。
  8) 返回 dict 结果，拒绝场景 {ok: False, reason, message} 不抛异常（仅 EQP-08 加载期
     校验抛 ValueError 由上层翻译）；message 为人话文案（命令壳薄适配层透传）。
  9) **P1-1 修复（M6 批1A 审查）**：aggregate_bonus 每槽只取一件匹配行（_worn_rows[0]）——
     同 item_id 多件实例行并存时不再遍历全部（防未穿戴行词条翻倍）；同 id 异词条的
     「穿戴行身份」精确区分需数据模型改进（EquipmentSlot 增行引用/ItemInstance 增
     instance_key），登记 M9 强化接线前置项。
  10) **P1-2 登记（M6 批1A 审查）**：unequip/后装覆盖会丢弃原 EquipmentSlot 的
     slot_level/locked/gems（强化/镶嵌数据）——当前强化/镶嵌未接线为潜伏；M9 锻造强化
     接线前必须在数据模型层解决（ItemInstance 补强化字段或引擎侧暂存恢复）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；工程补白显式标注。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, cast

from dataclasses import replace as _dcreplace

from qbot_rpg.core.panel_budget import (
    normalize_panel_budget,
    scale_panel_bonus,
)
from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.core.runes import RUNES_STATE_KEY, rune_effect_refs_of, sum_rune_stats
from qbot_rpg.data.gear_stats import GEAR_COMBAT_KEYS, PCT_SUFFIX, route_bonus_into
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import EquipmentSlot, PlayerAttributes

__all__ = ["EquipmentEngine", "validate_slot_exclusions", "DEFAULT_SLOT_NAMES", "DEFAULT_SLOT_ORDER",
           "item_requirement_error",
           # 批38 · H7 副手语义（通用、包声明驱动）
           "OFFHAND_ROLE_MAIN", "OFFHAND_ROLE_OFFHAND", "SLOT_ROLES",
           "DEFAULT_OFFHAND_SCALE", "OFFHAND_CONFIG_KEY",
           "normalize_offhand_config", "slot_role_of", "slot_defs_mapping",
           "offhand_penalized_slots", "offhand_penalized_item_ids",
           "offhand_penalized_slots_of_ctx"]


def _row_item_id(row: Any) -> str:
    """背包行 item_id 双读（ItemInstance 实例 / asdict dict 形态；M12.5/veinborn
    适配层 asdict 链路兼容——背包列表混入 dict 行时引擎不崩）。"""
    if isinstance(row, Mapping):
        return str(row.get("item_id") or "")
    return str(getattr(row, "item_id", "") or "")


def _row_uid(row: Any) -> str:
    """背包行 uid 双读（ItemInstance 实例 / asdict dict 形态；批40 · H4）。

    缺字段/旧档 → 空串（读取按 item_id 兜底，与迁移前一致）。
    """
    if isinstance(row, Mapping):
        return str(row.get("uid") or "")
    return str(getattr(row, "uid", "") or "")


def _slot_uid(slot_obj: Any) -> str:
    """装备槽实例 uid 双读（EquipmentSlot / asdict dict 形态；批40 · H4）。

    uid = 回指背包 ItemInstance.uid 的穿戴身份；空串 = 旧档/无匹配行 → item_id 兜底。
    """
    if isinstance(slot_obj, Mapping):
        return str(slot_obj.get("uid") or "")
    return str(getattr(slot_obj, "uid", "") or "")


def _same_worn_instance(old_slot: Any, row: Any) -> bool:
    """旧槽实例与新穿背包行是否**同一件实例**（批40 · H4，纯函数）。

    口径：item_id 不同 → 否；两侧均有 uid → 按 uid 相等判定（同 id 两件不串）；
    任一侧无 uid（旧档未迁移/测试直接构造）→ 回落 item_id 相等（与既有行为一致）。
    """
    old_iid = (old_slot.get("item_id") if isinstance(old_slot, Mapping)
               else getattr(old_slot, "item_id", None))
    if str(old_iid or "") != _row_item_id(row):
        return False
    old_uid, row_uid = _slot_uid(old_slot), _row_uid(row)
    if old_uid and row_uid:
        return old_uid == row_uid
    return True


def _attrs_from_dict(attrs: Mapping[str, Any]) -> PlayerAttributes:
    """dict 形态 attributes → PlayerAttributes（M12.5/veinborn：适配层 asdict 链路
    兼容——引擎契约收 PlayerAttributes，装配层 asdict 后为 dict）。"""
    def _sub(key: str, subkey: str) -> Dict[str, float]:
        node = attrs.get(key) if isinstance(attrs, Mapping) else None
        sub = node.get(subkey) if isinstance(node, Mapping) else None
        return {str(k): float(v) for k, v in sub.items()} if isinstance(sub, Mapping) else {}

    _b = attrs.get("base")
    _c = attrs.get("cond")
    return PlayerAttributes(
        base={str(k): float(v) for k, v in _b.items()} if isinstance(_b, Mapping) else {},
        bonus={"flat": _sub("bonus", "flat"), "pct": _sub("bonus", "pct")},
        temp={"pct": _sub("temp", "pct"), "flat": _sub("temp", "flat")},
        cond={str(k): float(v) for k, v in _c.items()} if isinstance(_c, Mapping) else {},
    )

# 槽位缺省中文名（slots.json 未配置时兜底；与 commands/basic_commands.DEFAULT_SLOT_NAMES
# 同值，工程补白 3）
DEFAULT_SLOT_NAMES: Dict[str, str] = {
    "weapon": "武器",
    "armor_head": "头部",
    "armor_body": "身体",
    "armor_hand": "手部",
    "armor_leg": "腿部",
    "armor_foot": "脚部",
}

# 槽位缺省顺序（4b §3.1：武器 + 五部位；与 basic_commands.DEFAULT_SLOT_ORDER 同值）
DEFAULT_SLOT_ORDER: tuple = (
    "weapon", "armor_head", "armor_body", "armor_hand", "armor_leg", "armor_foot",
)

# =====================================================================================
# 批38 · H7 副手（槽位角色 / 开关 / 折算与失活）——**槽位语义唯一入口**的归一与判定
#
# 依据：docs/深度打造_决策记录.md §一 H7 + §五 5.2（开关落点/字段名/关闭语义）+ 「打造系统_C」
#   Q3（归一放 slot_defs 解析处、数值折算与失活放 aggregate_bonus、其余失活在各自读取点）。
# 口径（全部包声明驱动、不硬编码）：
#   · settings.slot_defs.<部位>.role ∈ {main, offhand}（缺省 main）——槽位角色；
#   · settings.equipment_offhand.enabled（bool，缺省 false）——副手总开关；关闭 = 本系统引入前
#     行为**逐字段一致**（本模块所有判定返回空/原值）；
#   · settings.equipment_offhand.single_hand_scale（number，缺省 0.5）——「单手武器作副手」的
#     数值类属性折算比例（可配；数值口径裁定权归用户，见决策记录 §二）。
# 判定（不引入手数字段即可自洽，手数实装见批39+）：
#   某件「穿在 role=offhand 槽 + 该件自身可装备槽（ItemInstance.slot）的 role 非 offhand」→
#   判为「主手武器挪作副手」→ 折算 + 失活。offhand 类装备（自身 slot 也是 offhand 槽）
#   不折算（原案 §12「副手类装备可以享受本身的效果」）。
# =====================================================================================
OFFHAND_ROLE_MAIN = "main"
OFFHAND_ROLE_OFFHAND = "offhand"
SLOT_ROLES: tuple = (OFFHAND_ROLE_MAIN, OFFHAND_ROLE_OFFHAND)
DEFAULT_OFFHAND_SCALE = 0.5
OFFHAND_CONFIG_KEY = "equipment_offhand"


def normalize_offhand_config(cfg: Any) -> Dict[str, Any]:
    """`settings.equipment_offhand` → {enabled: bool, single_hand_scale: float}（缺省关闭/0.5）。

    缺段/非映射 → 关闭（回归零影响）；scale 非数或越界 → 回落默认 0.5（非法值由校验器红拦，
    引擎侧只做防御性回落，不静默改写作者数据）。纯函数、只读。
    """
    if not isinstance(cfg, Mapping):
        return {"enabled": False, "single_hand_scale": DEFAULT_OFFHAND_SCALE}
    scale = cfg.get("single_hand_scale")
    try:
        fscale = float(scale)
    except (TypeError, ValueError):
        fscale = DEFAULT_OFFHAND_SCALE
    if not (0.0 <= fscale <= 1.0):
        fscale = DEFAULT_OFFHAND_SCALE
    return {"enabled": cfg.get("enabled") is True, "single_hand_scale": fscale}


def slot_role_of(slot_def: Any) -> str:
    """槽位定义 → 角色（`main`/`offhand`；缺省/非法 → main）。"""
    if isinstance(slot_def, Mapping) and slot_def.get("role") == OFFHAND_ROLE_OFFHAND:
        return OFFHAND_ROLE_OFFHAND
    return OFFHAND_ROLE_MAIN


def slot_defs_mapping(slots: Any) -> Mapping[str, Any]:
    """槽位定义入参归一：包装形态 `{"slots": {...}}` 或平铺 `{id: def}` → 内层映射。"""
    if isinstance(slots, Mapping) and isinstance(slots.get("slots"), Mapping):
        return slots["slots"]
    return slots if isinstance(slots, Mapping) else {}


def _row_equippable_slot(row: Any) -> str:
    """背包行可装备槽类型（ItemInstance.slot；dict/实例双形态）。"""
    if isinstance(row, Mapping):
        return str(row.get("slot") or "")
    return str(getattr(row, "slot", "") or "")


def _first_worn_row(player: Any, item_id: str, uid: str = "") -> Any:
    """取背包行（判断件自身可装备槽用；空 → None）。

    批40 · H4：uid 非空时按 uid 精确命中（同 id 多件取对行）；无 uid / 未命中 →
    回落 item_id 首个匹配行（旧档兜底，与迁移前一致）。
    """
    inv = player.get("inventory") if isinstance(player, Mapping) else None
    if not isinstance(inv, (list, tuple)):
        return None
    if uid:
        for r in inv:
            if _row_uid(r) == uid:
                return r
    for r in inv:
        if _row_item_id(r) == item_id:
            return r
    return None


def offhand_penalized_slots(player: Any, slots: Any, offhand: Any = None) -> frozenset:
    """处于副手折算/失活状态的**槽位 id** 集合（判定见模块段注释；开关关闭 → 空集）。

    入参 slots 接受包装/平铺两种形态（见 slot_defs_mapping）；player 为玩家状态 dict。
    纯函数、只读、确定性（槽序 sorted）。
    """
    if not normalize_offhand_config(offhand)["enabled"]:
        return frozenset()
    defs = slot_defs_mapping(slots)
    if not defs:
        return frozenset()
    equipment = player.get("equipment") if isinstance(player, Mapping) else None
    if not isinstance(equipment, Mapping):
        return frozenset()
    out = set()
    for raw_slot in sorted(str(k) for k in equipment.keys()):
        if slot_role_of(defs.get(raw_slot)) != OFFHAND_ROLE_OFFHAND:
            continue
        slot_obj = equipment.get(raw_slot)
        iid = (slot_obj.get("item_id") if isinstance(slot_obj, Mapping)
               else getattr(slot_obj, "item_id", None))
        # 批40 · H4：槽 uid 优先精确取穿戴行（同 id 多件取对行）；空/未命中回落 item_id
        item_slot = _row_equippable_slot(
            _first_worn_row(player, str(iid or ""), _slot_uid(slot_obj))
        )
        # 件自身可装备槽的 role 非 offhand（含未声明/空）→ 主手件挪作副手 → 折算失活。
        if slot_role_of(defs.get(item_slot)) != OFFHAND_ROLE_OFFHAND:
            out.add(raw_slot)
    return frozenset(out)


def offhand_penalized_item_ids(player: Any, slots: Any, offhand: Any = None) -> frozenset:
    """副手折算/失活件的 **item_id** 集合（供孔位/符文等按装备 id 读取处过滤；关→空集）。"""
    penalized = offhand_penalized_slots(player, slots, offhand)
    if not penalized:
        return frozenset()
    equipment = player.get("equipment") if isinstance(player, Mapping) else None
    out = set()
    if isinstance(equipment, Mapping):
        for slot_id in penalized:
            slot_obj = equipment.get(slot_id)
            iid = (slot_obj.get("item_id") if isinstance(slot_obj, Mapping)
                   else getattr(slot_obj, "item_id", None))
            if iid:
                out.add(str(iid))
    return frozenset(out)


def offhand_penalized_slots_of_ctx(ctx: Any, player: Any) -> frozenset:
    """从指令 ctx 取副手失活槽位（优先已装配引擎，其次 ctx 声明；缺省空集）。

    供 equip_mods / forge_sets / jewel 等**已穿戴件读取点**统一过滤（一处判定，多处复用）。
    """
    if not isinstance(ctx, Mapping):
        return frozenset()
    engine = ctx.get("equip_engine")
    for candidate in (engine, getattr(engine, "_engine", None)):
        fn = getattr(candidate, "penalized_slots", None)
        if callable(fn):
            try:
                return frozenset(fn(player))
            except Exception:  # noqa: BLE001 - 判定失败按「无失活」保守处理，不阻断读取
                return frozenset()
    return offhand_penalized_slots(player, ctx.get("slots"), ctx.get(OFFHAND_CONFIG_KEY))


def _offhand_filtered_bonus(bonus: Mapping[str, Any], scale: float) -> Dict[str, float]:
    """副手折算：数值类键 ×scale；百分比键（`_pct`）与战斗键（GEAR_COMBAT_KEYS）丢弃。

    分层口径与 `data.gear_stats.route_bonus_into` **同一规则**（否则会出现"聚合折算"
    与"层路由"两套判定漂移）：`_pct` 结尾且非 COMBAT → 百分比层（丢弃）；COMBAT → 战斗
    键（丢弃）；其余 → 数值类（×scale）。非数值/布尔项丢弃。
    """
    out: Dict[str, float] = {}
    for k, v in bonus.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if isinstance(v, bool):
            continue
        ks = str(k)
        if ks in GEAR_COMBAT_KEYS:
            continue
        if ks.endswith(PCT_SUFFIX) and len(ks) > len(PCT_SUFFIX):
            continue
        out[ks] = fv * scale
    return out


def item_requirement_error(
    item_def: Any, *, job_id: str = "", level: int = 1
) -> Optional[str]:
    """装备/物品资格门槛（框架字段 `job_restrict` / `use_level`）→ 不满足返回人话，满足 None。

    口径（批22 · A1/A2；纯函数、只读不改写，两条判定**相互独立**）：
      - `job_restrict`（list<str>，元素引用 jobs.json 职业 id，与 skills.job_restrict
        同名同形）：非空且当前 `job_id` 不在其中 → **阻止穿戴/使用**。
        字段缺失 / 空列表 / 非列表 → 不限制（空 = 通用，与技能侧同口径）。
      - `use_level`（int ≥ 1）：为正整数且 `level` < `use_level` → **阻止穿戴/使用**；
        缺失 / 非正整数（0/负/非数值）→ 不限制（非法值由校验器 IV-1/R-2 拦截）。
      - 判定顺序：职业先、等级后（同一件两条件都不满足时先报职业）。
      - 两者都是**功能限制**（按既有「不可穿戴」拒绝路径处理），不是「只建议不拦截」的
        建议类字段——依据 §三 A1/A2。
    人话提示风格对齐既有装备拒绝文案（❌ 前缀 + 需要/当前）。
    """
    d = getattr(item_def, "raw", item_def)
    if not isinstance(d, Mapping):
        return None
    restrict = d.get("job_restrict")
    if isinstance(restrict, (list, tuple)) and restrict:
        need = [str(r) for r in restrict if str(r)]
        if need and str(job_id) not in need:
            return f"❌ 职业不符：需要 {'/'.join(need)}，当前 {job_id or '无职业'}"
    use_level = d.get("use_level")
    if isinstance(use_level, int) and not isinstance(use_level, bool) and use_level > 0:
        if int(level) < use_level:
            return f"❌ 等级不足：需要 {use_level} 级，当前 {int(level)} 级"
    return None


def validate_slot_exclusions(mutual_exclusions: Any) -> None:
    """互斥环加载期拦截（EQP-08/【框架】L1537）：mutual_exclusions 成环 → 抛 ValueError。

    - 每个互斥组视作两两互斥（clique），组内连续成员建无向边；
    - 并查集判环：同组已连通再建边（含自环 A-A）→ 环 → ValueError（红色拦截，内容包不加载）。
    - 单个两人组 [A, B]（框架 5.1 示例 [[\"weapon\",\"shield\"]]）→ 一条边无环，合法；
      三人及以上组 / 链式成环 / 自环 → 环 → 拒绝加载。
    """
    if mutual_exclusions is None:
        return
    if not isinstance(mutual_exclusions, (list, tuple)):
        raise ValueError("mutual_exclusions 必须是二维数组（互斥组列表）")
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> bool:
        """返回 False = 已连通（成环）。"""
        ra, rb = find(a), find(b)
        if ra == rb:
            return False
        parent[ra] = rb
        return True

    for group in mutual_exclusions:
        if not isinstance(group, (list, tuple)) or len(group) < 2:
            continue
        members = [str(m) for m in group]
        for i in range(len(members) - 1):
            a, b = members[i], members[i + 1]
            if not union(a, b):
                raise ValueError(
                    "装备互斥成环 → 红色拦截：你的武器、盾牌、副手互相排斥形成了一个圈…"
                    f"（EQP-08；涉及槽位 {a}↔{b}，内容包 slots.json 拒绝加载）"
                )


class EquipmentEngine:
    """穿戴/卸下/槽位互斥/词条聚合引擎（D1 §三：EQP-01~EQP-12）。"""

    def __init__(
        self,
        slots: Optional[Any] = None,
        mutual_exclusions: Optional[Sequence[Sequence[str]]] = None,
        offhand: Optional[Any] = None,
        panel_budget: Optional[Any] = None,
        runes: Optional[Any] = None,
        items: Optional[Any] = None,
        jewel: Optional[Any] = None,
    ) -> None:
        """构造装备引擎（配置注入，缺省默认值兜底，D1 B-2/B-4）。

        - slots：部位定义。形态：
            · None → 缺省六部位（DEFAULT_SLOT_NAMES，max=1，工程补白 3）；
            · slots.json 形态 {"slots": {id: def}, "mutual_exclusions": [[slot_a, slot_b], ...]}；
            · 平铺形态 {id: {"name", "max", "occupies"}}。
          def 字段：name（中文名）、max（可装备数量，默认 1）、occupies（占多部位，默认 []）、
          **role**（槽位角色 main/offhand，默认 main；批38 · H7）。
        - mutual_exclusions：互斥组列表 [[slot_a, slot_b], ...]；缺省从 slots 包装形态读取，
          再缺省为 []（框架 5.1 全局互斥表）。
        - offhand：`settings.equipment_offhand` 配置（{enabled, single_hand_scale}）；缺省/
          非映射 → 开关关闭（副手规则不生效，行为与本系统引入前逐字段一致；批38 · H7）。
        - panel_budget：`settings.panel_budget` 配置（批45 · 装备占比校准）——
          `equip_stat_mult` 乘在装备「面板轴」atk/dfn/hp 的加成上；缺省/非映射 → 1.0
          （装备数值不变，行为与本批引入前逐字段一致）。
        - runes / items / jewel（批47 · 43-B 符文数值贡献，三者缺一即本段零贡献）：
            · runes：`ctx["runes"]` 符文定义表 `{rune_id: def}`（by_equip_type 差异表）；
            · items：`ctx["items"]` 物品定义表（取 `items.type` 作差异类型键）；
            · jewel：`JewelSystem` 实例（**孔位激活读取唯一入口** `active_rune_sockets`
              + 总闸 `runes_enabled`）——duck-typed 注入，避免 core.equipment ↔ core.jewel
              模块级循环 import。缺省 None → 符文段整体跳过（既有行为逐字段一致）。
        """
        raw_slots: Mapping[str, Any]
        if slots is None:
            raw_slots = {
                sid: {"name": name, "max": 1}
                for sid, name in DEFAULT_SLOT_NAMES.items()
            }
            self._mutual: List[List[str]] = []
        else:
            if isinstance(slots, Mapping) and "slots" in slots and isinstance(slots["slots"], Mapping):
                raw_slots = slots["slots"]
                if mutual_exclusions is None:
                    ex = slots.get("mutual_exclusions")
                    if isinstance(ex, (list, tuple)):
                        self._mutual = [[str(m) for m in g] for g in ex if isinstance(g, (list, tuple))]
                    else:
                        self._mutual = []
            else:
                raw_slots = slots
                self._mutual = []
            if mutual_exclusions is not None:
                self._mutual = [[str(m) for m in g] for g in mutual_exclusions if isinstance(g, (list, tuple))]

        self._slots: Dict[str, Dict[str, Any]] = {}
        for sid, d in raw_slots.items():
            if not isinstance(d, Mapping):
                d = {}
            self._slots[str(sid)] = {
                "name": str(d.get("name") or str(sid)),
                "max": max(1, int(d.get("max", 1) or 1)),
                "occupies": [
                    str(o) for o in (d.get("occupies") or [])
                    if isinstance(o, str) and o
                ],
                # 批38 · H7：槽位角色（归一入口；缺省/非法 → main，非法值由校验器红拦）
                "role": slot_role_of(d),
            }
        # 批38 · H7：副手开关配置（缺省关闭 → 所有副手判定返回空/原值，回归零影响）
        self._offhand: Dict[str, Any] = normalize_offhand_config(offhand)
        # 批45 · 装备占比校准：面板预算（缺省 equip_stat_mult=1.0 → 装备数值不变）
        self._panel_budget: Dict[str, float] = normalize_panel_budget(panel_budget)
        # 批47 · 43-B：符文数值贡献数据源（缺省空表/None → 符文段整体跳过，回归零影响）
        self._runes: Mapping[str, Any] = runes if isinstance(runes, Mapping) else {}
        self._items: Mapping[str, Any] = items if isinstance(items, Mapping) else {}
        self._jewel: Any = jewel

    # ------------------------------------------------------------------
    # 批47 · 43-B 符文数值贡献（差异解析求值 + 孔位读取唯一入口转发）
    # ------------------------------------------------------------------
    def _rune_ctx(self, player: Any) -> Dict[str, Any]:
        """`jewel.active_rune_sockets` 所需最小 ctx（player/slots/副手开关/符文容器）。

        符文容器取 `player.persistent_state["rune_sockets"]`（落档源）；槽位定义用引擎
        自身归一后的 `self._slots`（与副手判定同源），不另造第二套孔位判定。
        """
        sockets: Any = None
        if isinstance(player, Mapping):
            ps = player.get("persistent_state")
            if isinstance(ps, Mapping):
                sockets = ps.get(RUNES_STATE_KEY)
        return {
            "player": player,
            "slots": self._slots,
            OFFHAND_CONFIG_KEY: self._offhand,
            RUNES_STATE_KEY: sockets if isinstance(sockets, MutableMapping) else {},
        }

    def _equip_type_of(self, item_id: str) -> str:
        """装备类型键（`items.type`，R-2/Q5 本批口径；缺定义/非 str → 空=仅 default）。"""
        d = self._items.get(item_id)
        if isinstance(d, Mapping):
            t = d.get("type")
            if isinstance(t, str):
                return t
        return ""

    def _equip_affinity_of(self, item_id: str) -> Mapping[str, Any]:
        """宿主装备相性声明 `items.affinities`（批48 · R-8：3 阶偏向性判定输入）。

        缺定义/非 Mapping → {}（不命中偏向；与批47 数值路径逐字段一致）。
        """
        d = self._items.get(item_id)
        if isinstance(d, Mapping):
            aff = d.get("affinities")
            if isinstance(aff, Mapping):
                return aff
        return {}

    def _rune_bonus_of(self, ctx: Any, item_id: str, uid: str) -> Dict[str, float]:
        """单件已穿戴装备的符文数值贡献（经 `jewel.active_rune_sockets` 读激活孔位）。

        链路：总闸（`runes_enabled`）→ 孔位激活读取（**唯一入口**，副手失活自动继承）
        → 按 `items.type` 解析 `by_equip_type`（default + 覆盖）→ 同键合并。
        批48 · R-8：3 阶偏向性按宿主装备主/副相性（`items.affinities`）判定加成。
        缺 runes/items/jewel/uid 或读取异常 → {}（防御性降级，不抛）。
        """
        if ctx is None or not self._runes or not uid or self._jewel is None:
            return {}
        enabled = getattr(self._jewel, "runes_enabled", None)
        if callable(enabled) and not enabled(ctx):
            return {}
        reader = getattr(self._jewel, "active_rune_sockets", None)
        if not callable(reader):
            return {}
        try:
            active = reader(ctx, str(item_id), uid)
        except Exception:  # noqa: BLE001 - 读取失败按无符文贡献（不阻断装备聚合）
            return {}
        return sum_rune_stats(
            active, self._runes, self._equip_type_of(str(item_id)),
            self._equip_affinity_of(str(item_id)),
        )

    def active_rune_effects(self, player: Any) -> List[Dict[str, Any]]:
        """已穿戴件**激活符文**声明的效果引用（批48 · 43-D；战斗接线唯一取数处）。

        与数值段（`_rune_bonus_of`）**同一** worn 枚举 + **同一**孔位读取入口
        （`jewel.active_rune_sockets` → 副手失活自动继承），差异解析按 `items.type`
        经 `core/runes.rune_effect_refs_of`。缺 runes/jewel/uid/总闸关/无符文 → []。
        """
        if not self._runes or self._jewel is None:
            return []
        if not isinstance(player, Mapping):
            return []
        ctx = self._rune_ctx(player)
        enabled = getattr(self._jewel, "runes_enabled", None)
        if callable(enabled) and not enabled(ctx):
            return []
        reader = getattr(self._jewel, "active_rune_sockets", None)
        if not callable(reader):
            return []
        equipment = player.get("equipment") if isinstance(player, Mapping) else None
        if not isinstance(equipment, Mapping):
            return []
        out: List[Dict[str, Any]] = []
        for slot_id, slot_obj in equipment.items():
            _iid = (
                slot_obj.get("item_id") if isinstance(slot_obj, Mapping)
                else getattr(slot_obj, "item_id", None)
            )
            item_id = str(_iid) if _iid else slot_id
            worn = self._resolve_worn_row(
                player, slot_id, str(item_id), _slot_uid(slot_obj))
            if worn is None:
                continue
            uid = _row_uid(worn)
            if not uid:
                continue
            try:
                active = reader(ctx, str(item_id), uid)
            except Exception:  # noqa: BLE001 - 读取失败按无符文（不阻断战斗装配）
                continue
            equip_type = self._equip_type_of(str(item_id))
            if not isinstance(active, (list, tuple)):
                continue
            for rid in active:
                if rid is None or rid == "":
                    continue
                d = self._runes.get(str(rid))
                if not isinstance(d, Mapping):
                    continue
                out.extend(rune_effect_refs_of(d, equip_type))
        return out

    # ------------------------------------------------------------------
    # 批38 · H7 副手语义（归一入口的只读读取面；跨模块复用同源判定）
    # ------------------------------------------------------------------
    def slot_role(self, slot_id: str) -> str:
        """槽位角色（main/offhand；未知槽 → main）。"""
        return slot_role_of(self._slot_def(slot_id))

    def offhand_active(self) -> bool:
        """副手开关是否启用（`settings.equipment_offhand.enabled`）。"""
        return bool(self._offhand.get("enabled"))

    def offhand_scale(self) -> float:
        """单手武器作副手的数值类属性折算比例（默认 0.5，包声明可配）。"""
        return float(self._offhand.get("single_hand_scale", DEFAULT_OFFHAND_SCALE))

    def equip_stat_mult(self) -> float:
        """装备面板倍率（批45；`settings.panel_budget.equip_stat_mult`，缺省 1.0）。

        作用于装备「面板轴」atk/dfn/hp 的加成（读时聚合），不改落档实例数值；
        1.0 = 现状（回归零影响）。
        """
        return float(self._panel_budget.get("equip_stat_mult", 1.0))

    def penalized_slots(self, player: Any) -> frozenset:
        """玩家当前处于副手折算/失活的槽位集合（开关关闭 → 空集）。"""
        return offhand_penalized_slots(player, self._slots, self._offhand)

    def _item_fits_slot(self, slot_id: str, item_slot: str) -> bool:
        """部位匹配（EQP-02 + 批38 副手放宽）：同槽类型直接通过；副手启用时，
        主手槽类型的件（如武器）可放进 role=offhand 的槽（「单手武器作副手」的载体）。"""
        if item_slot == slot_id:
            return True
        if not self.offhand_active():
            return False
        return (self.slot_role(slot_id) == OFFHAND_ROLE_OFFHAND
                and self.slot_role(item_slot) == OFFHAND_ROLE_MAIN)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _inv(player: MutableMapping[str, Any]) -> List[ItemInstance]:
        """player["inventory"] 归一为可变 list（元素 = ItemInstance）。"""
        raw = player.get("inventory")
        if isinstance(raw, list):
            return raw
        if isinstance(raw, tuple):
            lst = list(raw)
            player["inventory"] = lst
            return lst
        lst: List[ItemInstance] = []  # type: ignore[no-redef]
        player["inventory"] = lst
        return lst

    def _slot_def(self, slot_id: str) -> Dict[str, Any]:
        return self._slots.get(slot_id, {"name": slot_id, "max": 1, "occupies": []})

    def _occupied_without(self, player: MutableMapping[str, Any], exclude: Optional[str]) -> set:
        """当前占用物理槽位集合（排除目标槽，后装覆盖语义，EQP-03/04）。"""
        occupied: set = set()
        for sid, _obj in (player.get("equipment") or {}).items():
            if exclude is not None and sid == exclude:
                continue
            occupied.add(sid)
            occupied.update(self._slot_def(sid).get("occupies", []))
        return occupied

    def _worn_rows(
        self, inv: List[ItemInstance], slot_id: str, item_id: str
    ) -> List[ItemInstance]:
        """槽位对应背包行（B-3 双向一致）：按 equipment 槽实例的 item_id 回查背包行。

        注（工程补白 2/8 + P1-1/P1-2 修复）：ItemInstance.slot 为可装备槽位类型、非穿戴状态标记，
        故不以 slot 匹配；同 item_id 多件词条**不再假设一致**——精确穿戴行解析走
        `_resolve_worn_row`（_worn_refs 行引用优先），本函数仅作兜底匹配源。
        """
        return [r for r in inv if _row_item_id(r) == item_id]

    def _worn_refs(self, player: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        """穿戴行引用表 {slot_id: 背包行对象引用}（P1-1/P1-2 修复，引擎私有进程态）。

        equip 成功时登记、覆盖时更新、unequip 时移除；aggregate_bonus 按此精确取
        穿戴行（同 id 多件只取穿戴行词条、穿显示序行不取错）。装配层序列化时忽略
        `_worn_rows` 键（引擎私有态，随玩家状态 dict 但不入 Player 领域类型）。
        """
        refs = player.get("_worn_rows")
        if not isinstance(refs, MutableMapping):
            refs = {}
            player["_worn_rows"] = refs
        return refs

    def _resolve_worn_row(
        self, player: MutableMapping[str, Any], slot_id: str, item_id: str,
        slot_uid: str = "",
    ) -> Optional[ItemInstance]:
        """精确穿戴行解析（批40 · H4 落档身份优先）：

        ① 槽 uid（EquipmentSlot.uid，落档）命中 → 该背包行（同 id 多件取对行，**跨
           存档/重登仍精确**）；uid 存在但行缺失 → None（宁可少聚合，**不**跨实例兜底，
           防「聚合错实例的词条」——正是 E1 缺陷）；
        ② uid 空（旧档未迁移/直接构造）→ `_worn_refs[slot]` 行引用（进程态缓存）；
        ③ 再兜底 item_id 第一匹配行（P1-1 保守，与迁移前行为一致）。
        """
        inv = self._inv(player)
        if slot_uid:
            for r in inv:
                if _row_uid(r) == slot_uid:
                    return r
            return None
        ref = self._worn_refs(player).get(slot_id)
        if ref is not None:
            for r in inv:
                if r is ref:
                    return r
        for r in inv:
            if _row_item_id(r) == item_id:
                return r
        return None

    def _recalc(self, player: MutableMapping[str, Any]) -> dict:
        """aggregate_bonus（EQP-06）→ 全链重算（EQP-07）→ 返回 {snapshot, final_attributes}。"""
        snapshot = self.aggregate_bonus(player)
        attributes = player.get("attributes")
        # M12.5/veinborn：dict attributes（asdict 链路）转 PlayerAttributes 重算，
        # 否则 final 恒 {}（calc_all 只认实例）
        if isinstance(attributes, PlayerAttributes):
            final = calc_all_final_attributes(attributes)
        elif isinstance(attributes, Mapping):
            try:
                final = calc_all_final_attributes(_attrs_from_dict(attributes))
            except (TypeError, ValueError):
                final = {}
        else:
            final = {}
        return {"snapshot": snapshot, "final_attributes": final}

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def equip(self, player: Any, item: Any, slot: str) -> Any:
        """穿戴（EQP-01~EQP-04/EQP-06/EQP-07/EQP-09）。

        校验链：占用集合 → 互斥检查 → 数量检查 → 通过穿上（【框架】L830）；
        任一环失败即拒绝并人话提示。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        if not isinstance(item, ItemInstance):
            return {"ok": False, "reason": "invalid_item"}
        if not isinstance(slot, str) or not slot:
            return {"ok": False, "reason": "invalid_slot"}
        if slot not in self._slots:
            return {
                "ok": False, "reason": "unknown_slot",
                "message": f"没有这个装备槽位：{slot}",
            }
        if player.get("in_battle"):
            # EQP-09：战斗内不可穿脱（战前换装）
            return {
                "ok": False, "reason": "in_battle",
                "message": "战斗中不可更换装备（战前换装）",
            }

        inv = self._inv(player)
        # 背包内定位该件（同一性优先，字段等价兜底）
        row = next((r for r in inv if r is item or r == item), None)
        if row is None:
            return {
                "ok": False, "reason": "item_not_found",
                "message": "背包里没有这件物品",
            }

        # EQP-02 部位匹配：item.type（装备子类，此处为 ItemInstance.slot）须 = 槽位键
        if not row.slot:
            return {"ok": False, "reason": "slot_mismatch", "message": "这个位置穿不上"}
        # EQP-02 部位匹配 + 批38 副手放宽（主手件可进 role=offhand 槽；开关关闭时口径不变）
        if not self._item_fits_slot(slot, row.slot):
            return {"ok": False, "reason": "slot_mismatch", "message": "这个位置穿不上"}

        # EQP-03 互斥检查（占用集合 → 互斥）
        occupied = self._occupied_without(player, slot)
        for group in self._mutual:
            if slot not in group:
                continue
            others = set(group) - {slot}
            conflict = sorted(others & occupied)
            if conflict:
                return {
                    "ok": False, "reason": "mutual_exclusion",
                    "message": (
                        f"装备冲突：{slot} 与 {'/'.join(conflict)} 互斥，"
                        "无法同时穿戴（战前换装请先卸下旧件）"
                    ),
                }

        # EQP-03 数量检查（目标槽/占用槽 max）
        counts: Dict[str, int] = {}
        for sid, _obj in (player.get("equipment") or {}).items():
            if sid == slot:
                continue
            for phys in [sid] + self._slot_def(sid).get("occupies", []):
                counts[phys] = counts.get(phys, 0) + 1
        for phys in [slot] + self._slot_def(slot).get("occupies", []):
            maxn = self._slots.get(phys, {}).get("max", 1)
            if counts.get(phys, 0) + 1 > maxn:
                return {
                    "ok": False, "reason": "max_reached",
                    "message": f"槽位 {phys} 已达可装备数量上限（max={maxn}）",
                }

        equipment = player.get("equipment")
        if not isinstance(equipment, MutableMapping):
            equipment = {}
            player["equipment"] = equipment

        # EQP-04 后装覆盖：目标槽旧件自动卸下回背包（移除 equipment 键即视为回包，
        # 背包行 slot=可装备类型恒定保留，工程补白 2/8）
        old = equipment.get(slot)
        replaced: Optional[str] = None
        if old is not None:
            # M12.5/veinborn：装配层 asdict 后槽位实例为 dict 形态——item_id 双读
            replaced = old.get("item_id") if isinstance(old, Mapping) else old.item_id

        # B-3 双向一致：equipment[slot] 更新为槽实例（**同一件**重穿保留既有强化/
        # 镶嵌；批40 · H4：同一件 = uid 相等——同 item_id 两件实例换穿即换槽身份）。
        row_uid = _row_uid(row)
        if old is not None and _same_worn_instance(old, row):
            # P1-2 修复（M12.5 强化接线）：同件重穿同步最新强化等级（背包实例可能
            # 已被 /强化 提升过；槽位旧值过时 → 以实例为准刷新）；批40 · H4：同步
            # 落档身份 uid（旧档空 uid 首次重穿即补上）。
            _slot_enh = int(getattr(item, "enhance_level", 0) or 0)
            if isinstance(old, Mapping):
                old = dict(old)
                old["slot_level"] = _slot_enh
                if row_uid:
                    old["uid"] = row_uid
            else:
                old = _dcreplace(old, slot_level=_slot_enh, uid=row_uid or _slot_uid(old))
            equipment[slot] = old
        else:
            # P1-2 修复（M12.5 强化接线）：新建槽位实例携带背包实例强化等级
            # （原丢 slot_level → 强化后装备卡 +N 恒 0，P1-2 潜伏 bug）；批40 · H4：
            # 槽位实例携带穿戴行 uid（落档身份，跨存档精确回指该实例）。
            equipment[slot] = EquipmentSlot(
                item_id=item.item_id, name=item.name,
                slot_level=int(getattr(item, "enhance_level", 0) or 0),
                uid=row_uid,
            )
        # P1-1/P1-2：登记穿戴行引用（进程态缓存；落档身份以 EquipmentSlot.uid 为准）
        self._worn_refs(player)[slot] = row

        recalc = self._recalc(player)
        return {
            "ok": True,
            "slot": slot,
            "item_id": item.item_id,
            "replaced": replaced,
            "snapshot": recalc["snapshot"],
            "final_attributes": recalc["final_attributes"],
        }

    def unequip(self, player: Any, slot: str) -> Any:
        """卸下（EQP-05/EQP-07/EQP-09）：槽位清空、背包行 slot=null、移除该件聚合、全链重算。"""
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        if not isinstance(slot, str) or not slot:
            return {"ok": False, "reason": "invalid_slot"}
        if player.get("in_battle"):
            return {
                "ok": False, "reason": "in_battle",
                "message": "战斗中不可更换装备（战前换装）",
            }
        equipment = player.get("equipment")
        if not isinstance(equipment, MutableMapping):
            return {"ok": False, "reason": "empty_slot", "message": "该槽位没有装备"}
        old = equipment.get(slot)
        if old is None:
            return {"ok": False, "reason": "empty_slot", "message": "该槽位没有装备"}

        # EQP-05：槽位清空 → 回包。背包行 slot=可装备类型恒定保留（工程补白 2/8）；
        # 若背包已无对应行（状态不一致，B-3 兜底）→ 生成一行（EquipmentSlot 不含词条/
        # 品质/绑定，按缺省补全，装配层如需还原完整实例经 items 注册表补齐——工程补白）
        # M12.5/veinborn：槽位实例 dict 形态双读（asdict 链路）
        _oid = old.get("item_id") if isinstance(old, Mapping) else getattr(old, "item_id", "")
        _oname = old.get("name") if isinstance(old, Mapping) else getattr(old, "name", "")
        _oid = str(_oid or "")
        _oname = str(_oname or "")
        # P1-2 修复（M12.5 强化接线）：卸下回包携带强化等级（原丢 slot_level →
        # 强化后的装备卸下再穿回强化丢失，P1-2 潜伏 bug）
        _enh = (old.get("slot_level", old.get("enhance", 0))
                if isinstance(old, Mapping) else getattr(old, "slot_level", 0))
        inv = self._inv(player)
        # 批40 · H4：按槽 uid 精确回查**穿戴的那一件**背包行（同 item_id 多件不取错）；
        # uid 空（旧档未迁移/直接构造）→ 回落 item_id 首匹配（与迁移前一致）。
        _suid = _slot_uid(old)
        if _suid:
            _existing = next((r for r in inv if _row_uid(r) == _suid), None)
        else:
            _existing = next((r for r in inv if _row_item_id(r) == _oid), None)
        # **同一性**定位（uid compare=False → list.index 的 == 可能命中结构等价的首件，
        # 改写/删除错行）；_existing 已由 uid/item_id 取得，此处按对象身份取下标。
        _pos = (next((i for i, r in enumerate(inv) if r is _existing), None)
                if _existing is not None else None)
        if _existing is None:
            # 回包行携带槽 uid（缺失则 __post_init__ 补发），保持实例身份连续
            try:
                inv.append(ItemInstance(
                    item_id=_oid, name=_oname, count=1, quality="normal",
                    bound=False, stack_max=1,
                    enhance_level=int(_enh or 0), uid=_suid,
                ))
            except TypeError:  # pragma: no cover —— 旧实例无字段兜底
                inv.append(ItemInstance(
                    item_id=_oid, name=_oname, count=1, quality="normal",
                    bound=False, stack_max=1,
                ))
        elif isinstance(_existing, ItemInstance) and int(_enh or 0) and _pos is not None:
            _cur = int(getattr(_existing, "enhance_level", 0) or 0)
            if int(_enh or 0) != _cur:
                inv[_pos] = _dcreplace(
                    _existing, enhance_level=int(_enh or 0))
        elif isinstance(_existing, Mapping) and int(_enh or 0) and _pos is not None:
            if int(_existing.get("enhance_level", 0) or 0) != int(_enh or 0):
                # M12.5/veinborn：inv 可混 dict 行（asdict 链路）——cast 绕 mypy
                # list[ItemInstance] 索引检查（运行期 dict 行真实存在）
                inv[_pos] = cast(ItemInstance,
                                 {**_existing, "enhance_level": int(_enh or 0)})
        del equipment[slot]
        # P1-1/P1-2：移除穿戴行引用（卸下后不再聚合该行）
        self._worn_refs(player).pop(slot, None)

        recalc = self._recalc(player)
        return {
            "ok": True,
            "slot": slot,
            "item_id": _oid,
            "returned_to_bag": True,
            "snapshot": recalc["snapshot"],
            "final_attributes": recalc["final_attributes"],
        }

    def aggregate_bonus(self, player: Any) -> Dict[str, Dict[str, float]]:
        """装备加成同层聚合（EQP-06）：各已穿戴件 stats_bonus flat / stats_pct pct
        同层求和 → 写入 attributes.bonus.flat / pct（equip_snapshot 语义 = attributes.bonus）。

        批38 · H7 副手：处于副手折算槽的件（penalized_slots）——
          · 数值类属性（非 `_pct`、非 GEAR_COMBAT_KEYS）**×offhand_scale**；
          · 百分比类属性（`_pct` 键）、战斗键（GEAR_COMBAT_KEYS）、stats_pct 钩子 **不激活**。
        开关关闭 → penalized 空集，逐字段与既有实现一致（回归零影响）。

        批45 · 装备占比校准：聚合完成后按 `panel_budget.equip_stat_mult` 缩放**装备面板轴**
        （atk/dfn/hp，flat 与对应 pct stem）。缺省 1.0 → 不改动（回归零影响）；
        读时生效，不写回实例/内容数值（独立可回滚）。

        批47 · 43-B **符文数值贡献段（唯一收口）**：每件已穿戴装备的激活符文（1 阶纯数值）
        经同一 `route_bonus_into` 汇入**同一** flat/pct 层（**不新开第二套聚合/键**）。
        激活孔位一律经 `core/jewel.JewelSystem.active_rune_sockets`（副手折算件 → 空，
        失活零额外分支）；差异解析（default + `items.type` 覆盖）在
        `core/runes.rune_stats_of` 求值处。缺 runes/items/jewel/uid 或总闸关闭 → 零贡献
        （无符文时与基线逐字段一致）。
        """
        flat: Dict[str, float] = {}
        pct: Dict[str, float] = {}
        penalized = self.penalized_slots(player)
        if isinstance(player, MutableMapping):
            equipment = player.get("equipment")
            if isinstance(equipment, Mapping):
                inv = self._inv(player)
                # 批47：符文贡献 ctx（缺数据源 → None，符文段整体跳过）
                rune_ctx = (
                    self._rune_ctx(player)
                    if self._runes and self._jewel is not None else None
                )
                for slot_id, slot_obj in equipment.items():
                    # M12.5/veinborn：槽实例 dict 形态双读（asdict 链路——dict getattr
                    # 失效 → 原回落 slot_id 当 item_id 找背包行 → 全 miss 聚合丢词条）
                    _iid = (
                        slot_obj.get("item_id") if isinstance(slot_obj, Mapping)
                        else getattr(slot_obj, "item_id", None)
                    )
                    item_id = str(_iid) if _iid else slot_id
                    # P1-1/P1-2 + 批40 · H4：精确穿戴行解析——槽 uid（落档身份）优先
                    # （同 item_id 多件/异词条只取穿戴行、跨存档不串），uid 空回退
                    # _worn_refs 行引用，再兜底 item_id 首行。
                    worn = self._resolve_worn_row(
                        player, slot_id, str(item_id), _slot_uid(slot_obj))
                    if worn is None:
                        continue
                    is_penalized = slot_id in penalized
                    # M12.5/veinborn：背包行 dict 形态 stats_bonus 双读
                    bonus = (
                        worn.get("stats_bonus") if isinstance(worn, Mapping)
                        else getattr(worn, "stats_bonus", None)
                    )
                    if isinstance(bonus, Mapping):
                        # 批⑧：键 "..._pct" 拆进 pct 层（单位=百分点），其余进 flat
                        # （data.gear_stats.route_bonus_into；旧实例无 _pct 键时与
                        # 原逐键求和行为一致）
                        route_bonus_into(
                            _offhand_filtered_bonus(bonus, self.offhand_scale())
                            if is_penalized else bonus,
                            flat, pct,
                        )
                    # 批47 · 43-B：符文数值贡献（唯一收口；孔位读取经 jewel.active_rune_sockets
                    # → 副手失活自动继承；差异解析在 rune_stats_of；同层 flat/pct 路由）。
                    if rune_ctx is not None:
                        route_bonus_into(
                            self._rune_bonus_of(rune_ctx, item_id, _row_uid(worn)),
                            flat, pct,
                        )
                    if is_penalized:
                        continue  # 百分比钩子不激活（H7）
                    pct_map = getattr(worn, "stats_pct", None)  # 钩子（ItemInstance 暂无该字段）
                    if isinstance(pct_map, Mapping):
                        for k, v in pct_map.items():
                            try:
                                pct[str(k)] = pct.get(str(k), 0.0) + float(v)
                            except (TypeError, ValueError):
                                continue
        # 批45 · 装备占比校准：装备面板轴倍率（equip_stat_mult；1.0 = 原样）。
        # 读时聚合——不改任何落档实例/内容数值，可独立回滚；只作用 atk/dfn/hp，
        # 暴击/命中/格挡等战斗直读词条不触碰（决策记录：不得改暴击参数）。
        scale_panel_bonus(flat, pct, self.equip_stat_mult())
        attributes = player.get("attributes")
        if isinstance(attributes, PlayerAttributes):
            attributes.bonus["flat"] = flat
            attributes.bonus["pct"] = pct
        elif isinstance(attributes, MutableMapping):
            # M12.5/veinborn：装配层 asdict 后 attributes 为 dict 形态（适配层
            # basic_commands._player asdict(Player) 写回 ctx）——聚合结果写回 dict
            # bonus 子键（引擎契约兼容，否则穿装加成恒丢）
            _bn = attributes.get("bonus")
            if not isinstance(_bn, MutableMapping):
                _bn = {}
                attributes["bonus"] = _bn
            _bn["flat"] = flat
            _bn["pct"] = pct
        return {"flat": flat, "pct": pct}

    def equip_search(self, query: Any, encode: bool = True) -> Any:
        """编辑器器物检索（细化_5a 编辑器接管，M-y 实装；EQP-10 预留签名）。

        本里程碑仅登记接口签名、返回空结果；检索细节由 M-y 编辑器侧承接。
        """
        return {
            "ok": True,
            "results": [],
            "registered": True,
            "query": query,
            "encode": encode,
            "note": "equip_search 检索细节待 M-y 编辑器接管（EQP-10 登记签名，本里程碑不实现检索逻辑）",
        }
