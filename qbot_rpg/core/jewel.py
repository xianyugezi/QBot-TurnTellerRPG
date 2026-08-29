"""珠系统引擎（M8 批7-1·路A · qbot_rpg/core/jewel.py）——JewelSystem。

文件：qbot_rpg/core/jewel.py
创建：2026-08-29
作者：Hermes 子agent（M8 批7-1·路A）
功能：装饰珠体系纯引擎——槽级→珠档映射（BEL-03/SOCK-02）/ 珠实例堆叠键（BEL-15）/
      同名递减表驱动（BEL-10）/ 战斗触发上限（BEL-11）/ 镶嵌·无损拆珠（SOCK-02~05）/
      珠品质档读取。珠三合一升阶执行 = 复用批2 UpgradeEngine._exec_jewel（本引擎不做升阶
      执行，只做珠系统配套计算）。纯逻辑零 IO 零 NoneBot；构造器注入 settings +
      QualitySystem 兜底缺省（对齐 core/quality.py / core/gem_wallet.py 构造注入模式）。

依据：
  - docs/细化/细化_2c4c_珠与合成指令.md：
      BEL-02  珠等级=品质档（普通/精良/史诗/传说），槽级 1/2/3（【炼金】L257）
      BEL-03  槽级→珠档映射：1 级=普通；2 级=精良及以下；3 级=全部（含传说）（L258）
      BEL-09  战斗中不可插拔（战前换珠=核心策略）（L271/L284）
      BEL-10  同名递减表驱动：第 2 颗×0.5、第 3 颗×0.25，第 4 颗及以上不叠加（L272/L420）
      BEL-11  触发上限：战斗内特效触发 ≤3 次/场（按珠 ID 计，排除被动常驻）；计数落战斗
              快照（与 battle_alchemy_used 同层，中断恢复不清零）（L273/L299/L422）
      BEL-12  珠三合一升阶＝合成引擎 kind=upgrade 配置实例（执行器=批2 UpgradeEngine）
      BEL-15  装饰珠实例堆叠键 = ID+品质档+特性集（同键可堆叠，键变则分堆）（L401）
      SOCK-01 装备孔位 slots.json slot_level（1/2/3 级）；单件槽位数=slots 数组长度（工程补白）
      SOCK-02 镶嵌门票 = 槽级≥珠档；无会话（L275/L337/L258）
      SOCK-03 拆珠无损：珠原档/原特性/原堆叠键返还，槽位空闲可再嵌（L275/L337）
      SOCK-04 镶嵌后珠随装备绑定角色；战斗中不可插拔（L271）
      SOCK-05 珠为装备被动：进出战斗按快照结算；特效触发计数入战斗快照（L284/L299）
      EDGE-01 升阶↔镶嵌同品质档刻度联动（槽级准入随档位上升收紧）
      验收：TC-20~24（镶嵌/珠规则）、TC-01~06（珠升阶链，执行器复用 UpgradeEngine）
  - 模式参考 qbot_rpg/core/gem_wallet.py（构造注入 settings + QualitySystem 兜底、纯函数）、
    core/quality.py（QualitySystem 档位序号 tier_index/index_to_tier）、core/reward.py
    （ctx hook：count_item/add_item/remove_item）、core/upgrade.py（_exec_jewel 珠升阶
    执行器 + _commit 原子提交，批2 已落地）
  - 已落地数据 content/test_demo/items.json（type=装饰珠、quality、base_effects、traits）、
    slots.json（珠插槽条目 [{equip_id, slots:[{slot_level}]}]）、settings.json alchemy 段
    （gem_diminish [{n:2,mult:0.5},{n:3,mult:0.25}]、战斗道具.珠触发上限=3）

【工程补白 · 显式标注】（定稿/细化未给口径处，按最小必要推导，不得新增定稿外机制行为）：
  J-1  珠插槽定义来源：ctx["slot_defs"] = slots.json 珠插槽条目归一映射
       {equip_id: [{"slot_level": 1..3}, ...]}；槽位索引 0 起；单件槽位数 = slots 数组长度
       （SOCK-01 工程补白：定稿未写死槽数，默认 1-3 个槽，内容包可配）。
       注：不用 ctx["slots"] 键——该键被 M6 装备引擎「部位定义 slots.json」占用，避免冲突。
  J-2  珠绑定写入形态：ctx["equipment"][equip_id]["jewels"] = {slot_index: jewel_snapshot}，
       jewel_snapshot = {jewel_id, quality, traits, stack_key, slot_level,
       bound: True, bound_to: player}——珠随装备绑定角色（SOCK-04），战斗结算按快照引用
       stack_key/base_effects（SOCK-05）。ctx["equipment"] 由调用方构造（珠插槽视图，
       与 M6 装备引擎 EquipmentSlot 槽实例为不同维度，批7-2 指令壳组装）。
  J-3  触发上限计数落战斗快照接口（供批9）：ctx["battle_snapshot"]["jewel_triggers"]
       = {jewel_id: 已触发次数}，与 battle_alchemy_used 同层（中断恢复不清零，BEL-11）；
       提供 battle_trigger_bucket / record_trigger / trigger_remaining 三接口。
  J-4  珠持有/扣还 hook：持有 = ctx["count_item"](id) 优先、兜底 ctx["inventory"]；
       扣除 = ctx["remove_item"](id, count)；返还 = ctx["add_item"](id, count, bound)
       （对齐 reward/upgrade hook 签名；返还经 add_item 保留堆叠键——背包层按
       ID+档+特性集 计算堆叠键，同键可堆叠，SOCK-03）。
  J-5  战斗状态标记：ctx["in_battle"] is True → 战斗中（对齐 equipment.py 工程补白 6
       「player["in_battle"] is True → 拒绝战斗中不可更换装备」）。
  J-6  can_toggle_in_battle 语义：回答「当前是否允许插拔珠配置」——非战斗中 True（可插拔），
       战斗中 False（SOCK-05 战斗中不可插拔）。mount/unmount 首闸都走它。
  J-7  mount 槽级判定：slot_accepts(slot_level, tier)——槽级 3 直接放行全部档位（含传说）；
       槽级 1/2 按「档位序号 < 槽级」（common=0/uncommon=1 可装 2 级槽；rare=2/legendary=3
       仅 3 级槽），对齐 BEL-03 映射表逐档核验（EDGE-01 升阶后档位上升 → 槽级准入同步收紧）。
  J-8  槽位快照缺少 slot_level 时按 1 兜底（最小必要防御；slots.json 条目缺 slot_level 视为
       1 级槽，只装普通）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；不抛异常（配置缺省兜底、方法防御降级）；
      工程补白显式标注；不新增定稿外机制行为；珠升阶执行 = 复用 UpgradeEngine，本引擎零重复。
"""

from __future__ import annotations

from typing import Any, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from qbot_rpg.core.quality import QualitySystem

__all__ = [
    "DEFAULT_TRIGGER_LIMIT",
    "JEWEL_TYPE",
    "REASON_IN_BATTLE",
    "REASON_JEWEL_NOT_FOUND",
    "REASON_SLOT_EMPTY",
    "REASON_SLOT_FULL",
    "REASON_SLOT_NOT_FOUND",
    "REASON_SLOT_TOO_LOW",
    "REASON_TRIGGER_LIMIT",
    "JewelSystem",
]

# 装饰珠 items.json type 值（BEL-05：items.json type 补「装饰珠」）
JEWEL_TYPE: str = "装饰珠"

# 战斗内珠特效触发上限缺省（BEL-11 / 【炼金】L422：战斗道具.珠触发上限 默认 3）
DEFAULT_TRIGGER_LIMIT: int = 3

# 缺省同名递减表（BEL-10 / 【炼金】L420：gem_diminish [{n:2,mult:0.5},{n:3,mult:0.25}]）
DEFAULT_DIMINISH_TABLE: Tuple[Tuple[int, float], ...] = ((2, 0.5), (3, 0.25))

# 拒绝原因常量（供批7-2 指令壳 / 批9 战斗接线复用）
REASON_SLOT_TOO_LOW: str = "slot_too_low"
REASON_IN_BATTLE: str = "in_battle"
REASON_JEWEL_NOT_FOUND: str = "jewel_not_found"
REASON_SLOT_FULL: str = "slot_full"
REASON_SLOT_EMPTY: str = "slot_empty"
REASON_SLOT_NOT_FOUND: str = "slot_not_found"
REASON_EQUIP_NOT_FOUND: str = "equip_not_found"
REASON_REMOVE_FAILED: str = "remove_failed"
REASON_ADD_FAILED: str = "add_failed"
REASON_NO_BATTLE_SNAPSHOT: str = "no_battle_snapshot"
REASON_TRIGGER_LIMIT: str = "trigger_limit"


class JewelSystem:
    """珠系统引擎（细化_2c4c：BEL-01~15 / SOCK-01~05 / EDGE-01 配套计算）。

    构造器配置注入（settings）+ QualitySystem 兜底缺省；纯函数零 IO 零 NoneBot；
    拒绝场景 {ok: False, reason, message} 不抛异常（对齐 core/synthesis.py 铁律）。
    操作对象 ctx 为玩家表示 dict（可变）：槽位定义 ctx["slot_defs"]（J-1）、装备珠插槽
    ctx["equipment"][equip_id]["jewels"]（J-2）、战斗快照 ctx["battle_snapshot"]（J-3）、
    hook count_item/remove_item/add_item（J-4）、战斗标记 ctx["in_battle"]（J-5）。
    珠三合一升阶执行 = 复用 UpgradeEngine._exec_jewel（批2 已落地），本引擎不重复实现。
    """

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
        quality: Optional[QualitySystem] = None,
    ) -> None:
        """构造珠系统引擎（构造器配置注入 + 缺省兜底）。

        入参：
          - settings：settings dict（alchemy 段：gem_diminish / 战斗道具.珠触发上限）；
            None/非 Mapping → {} → 默认值兜底（BEL-10/BEL-11）。配置来源=构造器注入单源。
          - quality：QualitySystem（档位序号/中文档名）；None → 内部缺省构造（默认四档）。
        """
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
        if isinstance(quality, QualitySystem):
            self._quality: QualitySystem = quality
        else:
            self._quality = QualitySystem()

    # ------------------------------------------------------------------
    # 配置读取（构造器单源 + 缺省兜底）
    # ------------------------------------------------------------------
    def _alchemy_cfg(self) -> Mapping[str, Any]:
        """settings.alchemy 段归一（缺省 {}，对齐 gem_wallet._alchemy_cfg）。"""
        alchemy = self._settings.get("alchemy")
        return alchemy if isinstance(alchemy, Mapping) else {}

    @staticmethod
    def _to_int(value: object) -> Optional[int]:
        """int 归一（bool 除外）；非 int/bool/可转数字串 → None（对齐 gem_wallet._to_int）。"""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if float(value).is_integer() else None
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None

    def _diminish_table(self) -> dict:
        """同名递减表归一（BEL-10：settings.alchemy.gem_diminish 可配 0/空=无递减）。

        形态：list [{n, mult}]（默认）或 {n: mult} 映射；None/0/空 → {}（无递减 → 恒 1.0）。
        """
        raw = self._alchemy_cfg().get("gem_diminish")
        table: dict = {}
        if isinstance(raw, Mapping):
            for key, val in raw.items():
                n = self._to_int(key)
                try:
                    mult = float(val)
                except (TypeError, ValueError):
                    continue
                if n is not None and n > 1:
                    table[n] = mult
        elif isinstance(raw, (list, tuple)):
            for e in raw:
                if not isinstance(e, Mapping):
                    continue
                n = self._to_int(e.get("n"))
                raw_mult = e.get("mult")
                if raw_mult is None:
                    continue
                try:
                    mult = float(raw_mult)
                except (TypeError, ValueError):
                    continue
                if n is not None and n > 1:
                    table[n] = mult
        return table

    # ------------------------------------------------------------------
    # 纯函数规则（BEL-03/10/11/15）
    # ------------------------------------------------------------------
    def slot_accepts(self, slot_level: int, jewel_quality: str) -> bool:
        """槽级→珠档映射判定（SOCK-02/BEL-03，工程补白 J-7）。

        入参：
          - slot_level：装备孔位等级 1/2/3（slots.json slot_level，SOCK-01）。
          - jewel_quality：珠品质档键（common/uncommon/rare/legendary）。
        出参：bool——槽级可装该档珠。
        核心：槽级 3 = 全部（含传说，BEL-03「3 级=全部」）；槽级 1/2 按「档位序号 < 槽级」
              （common=0/uncommon=1 可装 2 级槽；rare=2/legendary=3 仅 3 级槽）——
              逐档核验：1 级槽=普通；2 级槽=精良及以下；3 级槽=全部。槽级非法（≤0）→ False。
        """
        sl = self._to_int(slot_level)
        if sl is None or sl <= 0:
            return False
        if sl >= 3:
            # 3 级槽=全部（含传说，BEL-03）
            return True
        index = self._quality.tier_index(jewel_quality)
        return index < sl

    def stack_key(self, jewel_id: str, quality: str, traits: Sequence[str]) -> str:
        """珠实例堆叠键（BEL-15：ID+品质档+特性集，同键可堆叠、键变则分堆）。

        入参：
          - jewel_id：珠物品 ID。
          - quality：珠品质档键。
          - traits：珠继承特性集（Sequence[str]，集合语义——顺序无关）。
        出参：str 堆叠键。
        核心：键 = "{jewel_id}|{quality}|{排序去重后的特性 join ','}"；特性集归一为
              排序去重（set 语义：同集不同顺序 → 同键可堆叠）；品质档/ID 任一变化或
              特性集变化 → 键变分堆（升阶使品质档变化 → 堆叠键变更，BEL-15）。
        """
        jid = str(jewel_id) if jewel_id is not None else ""
        q = str(quality) if quality else "common"
        seen: List[str] = []
        for t in traits or ():
            ts = str(t)
            if ts and ts not in seen:
                seen.append(ts)
        seen.sort()
        return f"{jid}|{q}|{','.join(seen)}"

    def diminish_mult(self, count: int) -> float:
        """同名珠效果乘数（BEL-10 表驱动：第 2 颗×0.5、第 3 颗×0.25，第 4 颗及以上不叠加）。

        入参：count 同名珠颗数/触发序次（第 N 颗；<1 归一为 1）。
        出参：float 乘数——第 1 颗恒 1.0；第 2 颗 0.5；第 3 颗 0.25；第 4 颗及以上 0.0
              （原表止于第 3 颗 → 无第 4 颗档位 → 不叠加，BEL-10 逻辑下限）。
        核心：settings.alchemy.gem_diminish 表驱动（默认 [{n:2,mult:0.5},{n:3,mult:0.25}]）；
              0/空 = 无递减 → 恒 1.0。count 精确命中表 → 对应 mult；超出表最大档 →
              0.0（无该档乘数 → 不叠加，BEL-10 逻辑下限「第 4 颗及以上不叠加」）；
              count 在 [2, 最大档) 间但表不连续（无精确档）→ 1.0（未达下一递减档，防御）。
        """
        n = self._to_int(count)
        if n is None or n < 1:
            n = 1
        table = self._diminish_table()
        if not table:
            # 无递减（配置 0/空，BEL-10）→ 恒 1.0
            return 1.0
        if n <= 1:
            return 1.0
        hit = table.get(n)
        if hit is not None:
            return float(hit)
        max_n = max(table)
        if n > max_n:
            # 超出表最大档 → 无该档乘数 → 不叠加（BEL-10：原表止于第 3 颗，第 4 颗及以上 0）
            return 0.0
        # n ∈ [2, max_n] 但表无精确档（表不连续）→ 未达下一递减档 → 1.0（防御）
        return 1.0

    def trigger_limit(self) -> int:
        """战斗内珠特效触发上限（BEL-11：settings.alchemy.战斗道具.珠触发上限，默认 3）。

        出参：int 每场每珠 ID 最大触发次数（排除被动常驻，L273/L422）。
        """
        battle = self._alchemy_cfg().get("战斗道具")
        if isinstance(battle, Mapping):
            v = self._to_int(battle.get("珠触发上限"))
            if v is not None and v > 0:
                return v
        return DEFAULT_TRIGGER_LIMIT

    def jewel_tier_of(self, jewel_def: Any) -> str:
        """珠品质档读取（BEL-02：珠等级=品质档；缺省 common）。

        入参：jewel_def 珠物品定义 dict（quality 字段：档位键字符串 / 品质分 int /
              {tier|key, score} 映射；或 tier 数值=档位序号）。
        出参：档位键 common/uncommon/rare/legendary；无法解析/非 Mapping → "common"（缺省）。
        """
        if not isinstance(jewel_def, Mapping):
            return "common"
        q = jewel_def.get("quality")
        if isinstance(q, str) and q:
            if q in ("common", "uncommon", "rare", "legendary"):
                return q
            # 未知档位键 → 经 QualitySystem 序号兜底（index_to_tier 防御）
            return self._quality.index_to_tier(self._quality.tier_index(q))
        if isinstance(q, bool):
            return "common"
        if isinstance(q, int):
            return self._quality.score_to_tier(q)
        if isinstance(q, Mapping):
            t = q.get("tier")
            if t is None:
                t = q.get("key")
            if isinstance(t, str) and t:
                return self._quality.index_to_tier(self._quality.tier_index(t))
            s = self._to_int(q.get("score"))
            if s is not None:
                return self._quality.score_to_tier(s)
        t = self._to_int(jewel_def.get("tier"))
        if t is not None and t >= 0:
            return self._quality.index_to_tier(t)
        return "common"

    # ------------------------------------------------------------------
    # 战斗插拔闸（SOCK-05 / BEL-09）
    # ------------------------------------------------------------------
    def can_toggle_in_battle(self, ctx: Mapping[str, Any]) -> bool:
        """战斗中是否允许插拔珠（SOCK-05/BEL-09：战斗中不可插拔，战前换珠=核心策略）。

        入参：ctx 玩家表示（战斗标记 ctx["in_battle"]，J-5）。
        出参：bool——非战斗中 True（可插拔）；战斗中 False（不可插拔）。
        """
        return ctx.get("in_battle") is not True

    # ------------------------------------------------------------------
    # ctx 辅助（J-1/J-2/J-4：槽位定义 / 装备珠插槽 / hook）
    # ------------------------------------------------------------------
    @staticmethod
    def _slot_defs(ctx: Mapping[str, Any], equip_id: str) -> Optional[list]:
        """珠插槽定义（J-1）：ctx["slot_defs"][equip_id] = [{"slot_level": 1..3}, ...]。

        槽位索引 0 起；单件槽位数 = slots 数组长度（SOCK-01 工程补白）。缺 → None。
        """
        reg = ctx.get("slot_defs")
        if not isinstance(reg, Mapping):
            return None
        slots = reg.get(equip_id)
        if not isinstance(slots, list):
            return None
        return slots

    @staticmethod
    def _jewels_bucket(ctx: Mapping[str, Any], equip_id: str) -> Optional[MutableMapping]:
        """装备珠插槽桶（J-2）：ctx["equipment"][equip_id]["jewels"] = {slot_index: 快照}。

        缺装备条目或 jewels 非可变映射 → None（equip_not_found）。
        """
        eq = ctx.get("equipment")
        if not isinstance(eq, Mapping):
            return None
        entry = eq.get(equip_id)
        if not isinstance(entry, Mapping):
            return None
        bucket = entry.get("jewels")
        if not isinstance(bucket, MutableMapping):
            return None
        return bucket

    @staticmethod
    def _resolve_item(ctx: Mapping[str, Any], item_id: str) -> Optional[Mapping[str, Any]]:
        """物品定义：ctx["items"] 注册表优先，兜底 ctx["resolve_item"] 解析器（对齐 reward）。"""
        items = ctx.get("items")
        if isinstance(items, Mapping):
            hit = items.get(item_id)
            if isinstance(hit, Mapping):
                return hit
        resolver = ctx.get("resolve_item")
        if callable(resolver):
            try:
                hit = resolver(item_id)
            except Exception:
                hit = None
            if isinstance(hit, Mapping):
                return hit
        return None

    def _item_name(self, item_id: str, ctx: Mapping[str, Any]) -> str:
        """物品 id → 显示名（注册表/解析器 name 字段；缺省回退原 id，对齐 gem_wallet）。"""
        hit = self._resolve_item(ctx, item_id)
        if hit is not None:
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
        return item_id

    def _held_count(self, item_id: str, ctx: Mapping[str, Any]) -> int:
        """背包持有数（J-4）：ctx["count_item"] hook 优先，兜底 ctx["inventory"] dict。"""
        count_item = ctx.get("count_item")
        if callable(count_item):
            try:
                v = count_item(item_id)
                iv = self._to_int(v)
                if iv is not None:
                    return max(0, iv)
            except Exception:
                pass
        inv = ctx.get("inventory")
        if isinstance(inv, Mapping):
            iv = self._to_int(inv.get(item_id, 0))
            if iv is not None:
                return max(0, iv)
        return 0

    def _remove_jewel(self, ctx: Mapping[str, Any], jewel_id: str, count: int) -> bool:
        """背包扣除珠（J-4）：ctx["remove_item"](id, count)；hook 缺失/False/抛错 → False。"""
        remove_item = ctx.get("remove_item")
        if not callable(remove_item):
            return False
        try:
            return remove_item(jewel_id, count) is not False
        except Exception:
            return False

    def _add_jewel(self, ctx: Mapping[str, Any], jewel_id: str, count: int) -> bool:
        """背包返还珠（J-4/SOCK-03 无损）：ctx["add_item"](id, count, bound=True)——
        返还保留原档/原特性，背包层按 stack_key 同键可堆叠；hook 缺失/False/抛错 → False。"""
        add_item = ctx.get("add_item")
        if not callable(add_item):
            return False
        try:
            return add_item(jewel_id, count, True) is not False
        except Exception:
            return False

    @staticmethod
    def _slot_level_of(slot_entry: Any, default: int = 1) -> int:
        """槽位条目 slot_level 归一（J-8：缺失/非法按 1 兜底——只装普通）。"""
        if isinstance(slot_entry, Mapping):
            v = slot_entry.get("slot_level")
            if isinstance(v, bool):
                return default
            if isinstance(v, int):
                return v if v > 0 else default
            if isinstance(v, str):
                try:
                    iv = int(v.strip())
                except ValueError:
                    return default
                return iv if iv > 0 else default
        return default

    # ------------------------------------------------------------------
    # 镶嵌（SOCK-02/04）
    # ------------------------------------------------------------------
    def mount(
        self,
        ctx: Mapping[str, Any],
        jewel_id: str,
        equip_id: str,
        slot_index: int,
        player: Any,
    ) -> dict:
        """/镶嵌 <珠> <装备>（SOCK-02/04：槽级≥珠档 → 珠随装备绑定 → 写入装备槽位）。

        入参：
          - ctx：玩家表示（slot_defs J-1 / equipment J-2 / count_item·remove_item J-4 /
            in_battle J-5）。
          - jewel_id：珠物品 ID（背包持有 1 颗起）。
          - equip_id：装备 ID（ctx["slot_defs"] 有珠插槽登记）。
          - slot_index：目标槽位序号（0 起，< slots 数组长度）。
          - player：绑定角色标识（写入快照 bound_to，SOCK-04 珠随装备绑定角色）。
        出参：
          - 成功 → {ok: True, message, jewel_id, quality, stack_key, slot_index, equip_id,
            slot_level}（珠已从背包扣除并写入装备槽位）。
          - 拒绝 → {ok: False, reason, message}；reason ∈
            in_battle（SOCK-05 战斗中不可插拔）/ jewel_not_found（珠定义缺失或背包未持有）/
            equip_not_found（装备无珠插槽）/ slot_not_found（槽位越界）/
            slot_too_low（槽级<珠档，SOCK-02 门票）/ slot_full（槽位已占用）/
            remove_failed（背包扣除失败）。
        核心：战斗闸 → 珠定义/档位 → 槽位定义/槽级校验（slot_accepts）→ 持有校验 →
              槽位空闲校验 → 扣珠 + 写入快照（含 stack_key，EDGE-01 档位联动基准）。
        """
        # 1) 战斗闸（SOCK-05/BEL-09：战斗中不可插拔）
        if not self.can_toggle_in_battle(ctx):
            return {
                "ok": False,
                "reason": REASON_IN_BATTLE,
                "message": "❌ 战斗中不可插拔珠（战前换珠=核心策略，SOCK-05/BEL-09）",
                "jewel_id": jewel_id,
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        # 2) 珠定义 + 档位（BEL-02）
        jewel_def = self._resolve_item(ctx, jewel_id)
        if jewel_def is None:
            return {
                "ok": False,
                "reason": REASON_JEWEL_NOT_FOUND,
                "message": f"❌ 装饰珠 {jewel_id} 不存在（items 注册表/解析器查无）",
                "jewel_id": jewel_id,
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        tier = self.jewel_tier_of(jewel_def)
        # 3) 槽位定义 + 槽级校验（SOCK-01/J-1/SOCK-02）
        slots = self._slot_defs(ctx, equip_id)
        if slots is None:
            return {
                "ok": False,
                "reason": REASON_EQUIP_NOT_FOUND,
                "message": f"❌ 装备 {equip_id} 无珠插槽登记（slots.json 缺该装备）",
                "jewel_id": jewel_id,
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        si = self._to_int(slot_index)
        if si is None or si < 0 or si >= len(slots):
            return {
                "ok": False,
                "reason": REASON_SLOT_NOT_FOUND,
                "message": f"❌ 槽位 {slot_index} 不存在（{equip_id} 共 {len(slots)} 个槽，0 起）",
                "jewel_id": jewel_id,
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        slot_level = self._slot_level_of(slots[si])
        if not self.slot_accepts(slot_level, tier):
            label = self._quality.tier_label(tier)
            return {
                "ok": False,
                "reason": REASON_SLOT_TOO_LOW,
                "message": (
                    f"❌ 槽级不足：{label}珠需 {max(1, self._quality.tier_index(tier) + 1)} 级槽，"
                    f"该槽为 {slot_level} 级（SOCK-02：槽级≥珠档；传说珠必须 3 级槽）"
                ),
                "jewel_id": jewel_id,
                "quality": tier,
                "equip_id": equip_id,
                "slot_index": slot_index,
                "slot_level": slot_level,
            }
        # 4) 持有校验（J-4：背包须有至少 1 颗）
        if self._held_count(jewel_id, ctx) < 1:
            return {
                "ok": False,
                "reason": REASON_JEWEL_NOT_FOUND,
                "message": f"❌ 背包中没有 {self._item_name(jewel_id, ctx)}（需 1 颗）",
                "jewel_id": jewel_id,
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        # 5) 槽位空闲校验（SOCK-02：一槽一珠）
        bucket = self._jewels_bucket(ctx, equip_id)
        if bucket is None:
            return {
                "ok": False,
                "reason": REASON_EQUIP_NOT_FOUND,
                "message": f"❌ 装备 {equip_id} 珠插槽桶缺失（equipment 数据未就绪）",
                "jewel_id": jewel_id,
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        if si in bucket:
            return {
                "ok": False,
                "reason": REASON_SLOT_FULL,
                "message": f"❌ 槽位 {si} 已镶嵌珠，需先 /拆珠（SOCK-03 无损拆珠）",
                "jewel_id": jewel_id,
                "equip_id": equip_id,
                "slot_index": slot_index,
                "slot_level": slot_level,
            }
        # 6) 执行：扣珠 → 写入槽位快照（J-2，含 stack_key）
        if not self._remove_jewel(ctx, jewel_id, 1):
            return {
                "ok": False,
                "reason": REASON_REMOVE_FAILED,
                "message": f"❌ 背包扣除 {self._item_name(jewel_id, ctx)} 失败（remove_item hook）",
                "jewel_id": jewel_id,
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        traits = [str(t) for t in (jewel_def.get("traits") or []) if str(t)]
        key = self.stack_key(jewel_id, tier, traits)
        bucket[si] = {
            "jewel_id": jewel_id,
            "quality": tier,
            "traits": list(traits),
            "stack_key": key,
            "slot_level": slot_level,
            "bound": True,
            "bound_to": player,
        }
        return {
            "ok": True,
            "message": (
                f"✅ {self._item_name(jewel_id, ctx)} 已镶嵌到 {equip_id} 槽位{si + 1}"
                f"（{self._quality.tier_label(tier)}档，绑定 {player}）"
            ),
            "jewel_id": jewel_id,
            "quality": tier,
            "stack_key": key,
            "slot_index": si,
            "equip_id": equip_id,
            "slot_level": slot_level,
            "bound_to": player,
        }

    # ------------------------------------------------------------------
    # 无损拆珠（SOCK-03）
    # ------------------------------------------------------------------
    def unmount(
        self,
        ctx: Mapping[str, Any],
        equip_id: str,
        slot_index: int,
        player: Any,
    ) -> dict:
        """/拆珠 <装备> <槽位>（SOCK-03：珠无损返还——原档/原特性/原堆叠键，槽位空闲可再嵌）。

        入参：
          - ctx：玩家表示（equipment J-2 / add_item J-4 / in_battle J-5）。
          - equip_id：装备 ID。
          - slot_index：槽位序号（0 起）。
          - player：绑定角色标识（记录在返回快照中供核对）。
        出参：
          - 成功 → {ok: True, message, jewel_id, quality, traits, stack_key, slot_index,
            equip_id}（珠经 add_item 无损返还背包，槽位清空）。
          - 拒绝 → {ok: False, reason, message}；reason ∈ in_battle / equip_not_found /
            slot_not_found / slot_empty（槽位无珠）/ add_failed（返还失败已回滚槽位）。
        核心：战斗闸 → 槽位有珠 → 弹出快照 → add_item 无损返还（保留原档/原特性/原堆叠键，
              同键可堆叠回原珠堆，SOCK-03）；返还失败则回滚槽位（珠不丢失）。
        """
        # 1) 战斗闸（SOCK-05/BEL-09：战斗中不可插拔）
        if not self.can_toggle_in_battle(ctx):
            return {
                "ok": False,
                "reason": REASON_IN_BATTLE,
                "message": "❌ 战斗中不可插拔珠（战前换珠=核心策略，SOCK-05/BEL-09）",
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        bucket = self._jewels_bucket(ctx, equip_id)
        if bucket is None:
            return {
                "ok": False,
                "reason": REASON_EQUIP_NOT_FOUND,
                "message": f"❌ 装备 {equip_id} 珠插槽桶缺失（equipment 数据未就绪）",
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        si = self._to_int(slot_index)
        if si is None or si < 0:
            return {
                "ok": False,
                "reason": REASON_SLOT_NOT_FOUND,
                "message": f"❌ 槽位 {slot_index} 不存在（0 起）",
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        if si not in bucket:
            return {
                "ok": False,
                "reason": REASON_SLOT_EMPTY,
                "message": f"❌ 槽位 {si} 未镶嵌珠，无可拆（SOCK-03）",
                "equip_id": equip_id,
                "slot_index": slot_index,
            }
        snap = bucket.pop(si)
        # 2) 无损返还（SOCK-03：原档/原特性/原堆叠键；add_item 保留堆叠键，J-4）
        if not self._add_jewel(ctx, str(snap.get("jewel_id", "")), 1):
            bucket[si] = snap  # 返还失败 → 回滚槽位，珠不丢失
            return {
                "ok": False,
                "reason": REASON_ADD_FAILED,
                "message": f"❌ 珠返还背包失败（add_item hook），已保留槽位 {si} 原状",
                "equip_id": equip_id,
                "slot_index": slot_index,
                "jewel_id": snap.get("jewel_id"),
            }
        return {
            "ok": True,
            "message": (
                f"✅ 已从 {equip_id} 槽位{si + 1} 无损拆下 "
                f"{self._item_name(str(snap.get('jewel_id', '')), ctx)}（原档原特性返还背包）"
            ),
            "jewel_id": snap.get("jewel_id"),
            "quality": snap.get("quality"),
            "traits": list(snap.get("traits") or []),
            "stack_key": snap.get("stack_key"),
            "slot_index": si,
            "equip_id": equip_id,
            "bound_to": snap.get("bound_to"),
        }

    # ------------------------------------------------------------------
    # 战斗触发上限计数接口（BEL-11 / 供批9 战斗接线，工程补白 J-3）
    # ------------------------------------------------------------------
    def battle_trigger_bucket(
        self, ctx: Mapping[str, Any]
    ) -> Optional[MutableMapping]:
        """战斗快照珠特效计数桶（BEL-11/J-3）：ctx["battle_snapshot"]["jewel_triggers"]。

        返回 {jewel_id: 已触发次数}（与 battle_alchemy_used 同层，中断恢复不清零）；
        battle_snapshot 缺失/非可变映射 → None（供批9 判断无战斗快照）。
        """
        snap = ctx.get("battle_snapshot")
        if not isinstance(snap, MutableMapping):
            return None
        bucket = snap.get("jewel_triggers")
        if not isinstance(bucket, MutableMapping):
            bucket = {}
            snap["jewel_triggers"] = bucket
        return bucket

    def record_trigger(self, ctx: Mapping[str, Any], jewel_id: str) -> dict:
        """珠特效触发计数（BEL-11：战斗内特效触发 ≤上限 次/场，按珠 ID 计，排除被动常驻）。

        入参：
          - ctx：玩家表示（battle_snapshot，J-3）。
          - jewel_id：触发特效的珠 ID（同珠 ID 计数；不同珠 ID 各自独立计数）。
        出参：
          - 未达上限 → {ok: True, jewel_id, count, limit, remaining}（计数 +1）。
          - 已达上限 → {ok: False, reason: 'trigger_limit', jewel_id, count, limit}（不触发）。
          - 无战斗快照 → {ok: False, reason: 'no_battle_snapshot'}。
        核心：被动常驻效果不走本接口（BEL-11「排除被动常驻」由战斗侧只对主动特效计数）；
              中断恢复不清零——计数落战斗快照（与 battle_alchemy_used 同层，L299）。
        """
        bucket = self.battle_trigger_bucket(ctx)
        if bucket is None:
            return {
                "ok": False,
                "reason": REASON_NO_BATTLE_SNAPSHOT,
                "message": "❌ 无战斗快照，珠特效计数无法落账（BEL-11/J-3）",
                "jewel_id": jewel_id,
            }
        limit = self.trigger_limit()
        n = bucket.get(jewel_id, 0)
        if n >= limit:
            return {
                "ok": False,
                "reason": REASON_TRIGGER_LIMIT,
                "message": f"❌ 珠特效触发已达上限（{limit} 次/场，BEL-11），本次不触发",
                "jewel_id": jewel_id,
                "count": n,
                "limit": limit,
            }
        bucket[jewel_id] = n + 1
        return {
            "ok": True,
            "message": f"✅ 珠特效触发计数 {n + 1}/{limit}（BEL-11）",
            "jewel_id": jewel_id,
            "count": n + 1,
            "limit": limit,
            "remaining": limit - (n + 1),
        }

    def trigger_remaining(self, ctx: Mapping[str, Any], jewel_id: str) -> int:
        """珠特效剩余可触发次数（BEL-11：上限 − 已触发；无战斗快照 → 0）。"""
        bucket = self.battle_trigger_bucket(ctx)
        if bucket is None:
            return 0
        return max(0, self.trigger_limit() - int(bucket.get(jewel_id, 0)))
