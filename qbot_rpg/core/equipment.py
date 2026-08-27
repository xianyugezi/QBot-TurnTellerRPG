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

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import EquipmentSlot, PlayerAttributes

__all__ = ["EquipmentEngine", "validate_slot_exclusions", "DEFAULT_SLOT_NAMES", "DEFAULT_SLOT_ORDER"]

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
    ) -> None:
        """构造装备引擎（配置注入，缺省默认值兜底，D1 B-2/B-4）。

        - slots：部位定义。形态：
            · None → 缺省六部位（DEFAULT_SLOT_NAMES，max=1，工程补白 3）；
            · slots.json 形态 {"slots": {id: def}, "mutual_exclusions": [[...]]}；
            · 平铺形态 {id: {"name", "max", "occupies"}}。
          def 字段：name（中文名）、max（可装备数量，默认 1）、occupies（占多部位，默认 []）。
        - mutual_exclusions：互斥组列表 [[slot_a, slot_b], ...]；缺省从 slots 包装形态读取，
          再缺省为 []（框架 5.1 全局互斥表）。
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
            }

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
        lst: List[ItemInstance] = []
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
        return [r for r in inv if r.item_id == item_id]

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
        self, player: MutableMapping[str, Any], slot_id: str, item_id: str
    ) -> Optional[ItemInstance]:
        """精确穿戴行解析：_worn_refs[slot] 行引用优先（同 id 多件/异词条取对行）；
        无引用（旧档/直接构造）兜底 item_id 第一匹配行（P1-1 保守）。"""
        ref = self._worn_refs(player).get(slot_id)
        inv = self._inv(player)
        if ref is not None:
            for r in inv:
                if r is ref:
                    return r
        for r in inv:
            if r.item_id == item_id:
                return r
        return None

    def _recalc(self, player: MutableMapping[str, Any]) -> dict:
        """aggregate_bonus（EQP-06）→ 全链重算（EQP-07）→ 返回 {snapshot, final_attributes}。"""
        snapshot = self.aggregate_bonus(player)
        attributes = player.get("attributes")
        final = (
            calc_all_final_attributes(attributes)
            if isinstance(attributes, PlayerAttributes)
            else {}
        )
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
        if row.slot != slot:
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
            replaced = old.item_id

        # B-3 双向一致：equipment[slot] 更新为槽实例（同件重穿保留既有强化/镶嵌）
        if old is not None and old.item_id == item.item_id:
            equipment[slot] = old
        else:
            equipment[slot] = EquipmentSlot(item_id=item.item_id, name=item.name)
        # P1-1/P1-2：登记穿戴行引用（精确聚合；覆盖时更新为新行）
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
        inv = self._inv(player)
        if not any(r.item_id == old.item_id for r in inv):
            inv.append(ItemInstance(
                item_id=old.item_id, name=old.name, count=1, quality="normal",
                bound=False, stack_max=1,
            ))
        del equipment[slot]
        # P1-1/P1-2：移除穿戴行引用（卸下后不再聚合该行）
        self._worn_refs(player).pop(slot, None)

        recalc = self._recalc(player)
        return {
            "ok": True,
            "slot": slot,
            "item_id": old.item_id,
            "returned_to_bag": True,
            "snapshot": recalc["snapshot"],
            "final_attributes": recalc["final_attributes"],
        }

    def aggregate_bonus(self, player: Any) -> Dict[str, Dict[str, float]]:
        """装备加成同层聚合（EQP-06）：各已穿戴件 stats_bonus flat / stats_pct pct
        同层求和 → 写入 attributes.bonus.flat / pct（equip_snapshot 语义 = attributes.bonus）。"""
        flat: Dict[str, float] = {}
        pct: Dict[str, float] = {}
        if isinstance(player, MutableMapping):
            equipment = player.get("equipment")
            if isinstance(equipment, Mapping):
                inv = self._inv(player)
                for slot_id, slot_obj in equipment.items():
                    item_id = getattr(slot_obj, "item_id", None) or slot_id
                    # P1-1/P1-2 修复（M6 批1A/1B 审查）：精确穿戴行解析——_worn_refs
                    # 行引用优先（同 item_id 多件/异词条只取穿戴行），兜底 item_id 首行。
                    worn = self._resolve_worn_row(player, slot_id, str(item_id))
                    if worn is None:
                        continue
                    bonus = getattr(worn, "stats_bonus", None)
                    if isinstance(bonus, Mapping):
                        for k, v in bonus.items():
                            try:
                                flat[str(k)] = flat.get(str(k), 0.0) + float(v)
                            except (TypeError, ValueError):
                                continue
                    pct_map = getattr(worn, "stats_pct", None)  # 钩子（ItemInstance 暂无该字段）
                    if isinstance(pct_map, Mapping):
                        for k, v in pct_map.items():
                            try:
                                pct[str(k)] = pct.get(str(k), 0.0) + float(v)
                            except (TypeError, ValueError):
                                continue
        attributes = player.get("attributes")
        if isinstance(attributes, PlayerAttributes):
            attributes.bonus["flat"] = flat
            attributes.bonus["pct"] = pct
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
