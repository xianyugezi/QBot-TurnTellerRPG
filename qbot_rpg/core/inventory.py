"""背包引擎（M6 批次1·路A · 实装版）——堆叠合并/超上限拆行/不可堆叠实例/扣减清理/绑定拒移/数量截断/格数上限/到期惰性移除。

依据：
  - 细化_M6_三引擎与基础指令（D1）§二 inventory 引擎实装契约：规则 INV-01~INV-11、
    字段 F-08~F-14、边界异常 INV-E1~INV-E5、验收用例 TC-INV-01~TC-INV-06。
  - 【框架】L129-138（3.3 背包引擎：堆叠/类型/局内道具不耗回合/药剂同类型回合限次 1/绑定）、
    L130（堆叠语义）、L138（绑定不可赠送/掉落）。
  - 【4b】INV-R01~R07（堆叠合并/不可堆叠/入包原子/数量上限/格数上限/到期惰性移除/使用入口）、
    ITM-07（stack_max 默认 99）、ITM-10（bound）、LIF-R05（同类药剂不叠加）、LIF-R10（消耗即删）。
  - 现有代码 core/inventory.py（M1 空壳骨架）+ data/item.py（ItemInstance）。

【工程补白 · 显式标注】
  1) 操作对象 = 玩家状态 dict（ctx 玩家表示，可变，就地改写），player["inventory"] 为可变
     list、元素 = ItemInstance 领域对象（D1 B-3）；行级字段经 dataclasses.replace 重建
     （frozen 实例不可变，替换为同字段新实例）。
  2) 配置注入 = 构造器参数，缺省默认值兜底（对齐 D1 B-1）：
     inventory_capacity：背包格数上限（INV-09/F 行数口径），None → 默认不限。
     max_single_add：单次入包数量上限（INV-08/INV-E1），默认 99（对齐 4b INV-R04）。
     now_fn：到期惰性移除的时间源（INV-10，现实时间计时），可调用 -> epoch 秒；
       None → 到期检查停用（【工程补白】ItemInstance 领域类型暂无 expires_at 字段，
       装配层经带 expires_at 的行/子类 + now_fn 注入启用本规则）。
  3) 单次入包截断（INV-08/B-4）：数量截断作用于单次 add 的 count 参数（> max_single_add
     按 max_single_add 截断执行 + 提示「最多一次购买 99 个」）；「格数上限」独立作用于
     背包总行数（INV-09），两条独立校验、互不替代。
  4) 绑定拒移（INV-07/TC-INV-05）：remove_item 优先从非绑定行扣减；目标不足或须动用
     绑定行 → 拒绝 {ok: False, reason: "bound"}，不产生部分扣减（出售/赠送/掉落共用
     remove 入口的语义；消耗路径如需放行由装配层提供显式 use 通道）。
  5) 到期惰性移除（INV-10/INV-E5）：任何背包操作先查 expires_at（getattr 钩子），已到期
     行整行移除并调用 calc_all_final_attributes 重算（移除药剂的加成撤销由使用入口在写入
     加成层时登记、装配层在移除时同步撤销——纯逻辑引擎只触发重算钩子）；不阻塞主操作。
  6) 引擎零 IO、零 NoneBot import、纯函数（3a R1）；入包/扣减事务由装配层 save_player 包裹
     （INV-04/LIF-R10，防重放双扣）。
  7) **INV-07 add 侧绑定来源（P2-02 标注，M6 批1A 审查）**：add_item 无 source 参数，行级
     绑定完全由调用方传入的 item.bound 决定（购买/奖励/掉落/锻造按来源写绑定的职责在装配
     层构造 item 时实现，引擎不越权）；与扣减侧绑定拒移（工程补白 4）对称，均在引擎侧只做
     校验、装配层定来源。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；now 注入确定性；工程补白显式标注。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import PlayerAttributes

__all__ = ["InventoryEngine", "POTION_USE_COUNTS_KEY"]

_SINGLE_ADD_CAP: int = 99   # 单次入包数量上限默认（INV-08/4b INV-R04）
_TRUNCATE_MSG: str = "最多一次购买 99 个"

# 战斗内同类型药剂一回合限 1 次的计数落点键（INV-11/LIF-R05：回血+回蓝可各 1 次，
# 回血不能 2 次；回合推进重置、中断恢复不重置——判定归战斗/使用入口，引擎只提供落点）
POTION_USE_COUNTS_KEY: str = "potion_use_counts"


class InventoryEngine:
    """背包增删查/堆叠/绑定校验引擎（D1 §二：INV-01~INV-11）。

    操作对象为玩家状态 dict（ctx 玩家表示），player["inventory"] 为可变 list；
    返回 dict 结果，拒绝场景返回 {ok: False, reason: ...} 不抛异常。
    """

    def __init__(
        self,
        inventory_capacity: Optional[int] = None,
        max_single_add: Optional[int] = None,
        now_fn: Optional[Callable[[], int]] = None,
    ) -> None:
        """构造背包引擎（配置注入，缺省默认值兜底，D1 B-1）。

        - inventory_capacity：背包格数上限（INV-09，行数口径）；None → 默认不限。
        - max_single_add：单次入包数量上限（INV-08）；None → 默认 99。
        - now_fn：到期惰性移除时间源（INV-10）；None → 到期检查停用。
        """
        self.inventory_capacity: Optional[int] = (
            None if inventory_capacity is None else int(inventory_capacity)
        )
        self.max_single_add: int = (
            _SINGLE_ADD_CAP if max_single_add is None else int(max_single_add)
        )
        self.now_fn: Optional[Callable[[], int]] = now_fn

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _as_list(player: MutableMapping[str, Any]) -> List[ItemInstance]:
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

    @staticmethod
    def _mergeable(a: ItemInstance, b: ItemInstance) -> bool:
        """堆叠合并判定（INV-01）：同 item_id + 同实例键（null，以 stack_max>1 表示非实例化）
        + 同品质 + 同绑定态；count ≤ stack_max 才合并（stack_max=1 即不可堆叠，INV-03）。"""
        if not isinstance(a, ItemInstance) or not isinstance(b, ItemInstance):
            return False
        if a.stack_max <= 1 or b.stack_max <= 1:
            return False
        return (
            a.item_id == b.item_id
            and a.quality == b.quality
            and a.bound == b.bound
        )

    @staticmethod
    def _row_with(row: ItemInstance, **changes: Any) -> ItemInstance:
        """按变更重建 frozen 行（dataclasses.replace，保留全部字段与子类扩展字段）。"""
        return replace(row, **changes)

    def _purge_expired(
        self, player: MutableMapping[str, Any], now: Optional[int]
    ) -> List[str]:
        """到期惰性移除（INV-10/INV-E5）：移除 expires_at ≤ now 的行并重算加成层属性。

        任何背包操作前调用；不阻塞主操作。返回被移除的 item_id 列表。
        """
        if now is None:
            return []
        inv = self._as_list(player)
        kept: List[ItemInstance] = []
        purged: List[str] = []
        for row in inv:
            expires_at = getattr(row, "expires_at", None)
            if expires_at is not None and int(expires_at) <= now:
                purged.append(row.item_id)
                continue
            kept.append(row)
        if purged:
            inv[:] = kept
            attributes = player.get("attributes")
            if isinstance(attributes, PlayerAttributes):
                calc_all_final_attributes(attributes)  # INV-10 重算（加成层属性）
        return purged

    def _now(self) -> Optional[int]:
        """注入时间源（确定性可测）；无 now_fn → None（到期检查停用）。"""
        if self.now_fn is None:
            return None
        try:
            return int(self.now_fn())
        except Exception:
            return None

    # ------------------------------------------------------------------
    # INV-11 药剂类型键与回合限次计数落点（引擎只提供键与落点，判定归使用入口）
    # ------------------------------------------------------------------
    @staticmethod
    def potion_type_of(row: Any) -> str:
        """药剂类型键（INV-11/ITM-17）：getattr(row, "potion_type")，缺省 "auto"。"""
        if not isinstance(row, ItemInstance):
            return "auto"
        typ = getattr(row, "potion_type", "auto")
        return str(typ) if typ else "auto"

    @staticmethod
    def potion_use_counts(player: MutableMapping[str, Any]) -> MutableMapping[str, int]:
        """战斗内同类型药剂一回合限 1 次的计数落点（INV-11/LIF-R05）。

        返回 player["potion_use_counts"] 可变 dict（potion_type → 已用次数）；
        回合推进重置 / 入战斗快照（中断恢复不重置）由战斗入口负责，本引擎不越权。
        """
        raw = player.get(POTION_USE_COUNTS_KEY)
        if not isinstance(raw, MutableMapping):
            raw = {}
            player[POTION_USE_COUNTS_KEY] = raw
        return raw

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def add_item(self, player: Any, item: Any, count: int = 1) -> Any:
        """入包（INV-01~INV-03/INV-08/INV-09/INV-10）。

        返回 {ok, added, rows, truncated, message?} 或拒绝 {ok: False, reason, message?}。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        if not isinstance(item, ItemInstance):
            return {"ok": False, "reason": "invalid_item"}
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            return {"ok": False, "reason": "invalid_count"}

        inv = self._as_list(player)
        self._purge_expired(player, self._now())  # INV-10 惰性移除（先清到期行）

        truncated = False
        if count > self.max_single_add:  # INV-08：单次入包数量上限，提示不拦截
            count = self.max_single_add
            truncated = True

        # 计算合并/拆行计划（INV-01/INV-02/INV-03）
        working: List[ItemInstance] = list(inv)
        plan: List[ItemInstance] = []
        remaining = count
        if item.stack_max <= 1:
            # INV-03：不可堆叠实例（stack_max=1）→ 每件独立行、恒 count=1，永不合并且不计数叠加
            for _ in range(count):
                plan.append(self._row_with(item, count=1))
        else:
            # INV-01：先并入既有可合并行（count ≤ stack_max 才合并）
            for idx, row in enumerate(working):
                if remaining <= 0:
                    break
                if not self._mergeable(row, item):
                    continue
                space = row.stack_max - row.count
                if space <= 0:
                    continue
                take = min(space, remaining)
                working[idx] = self._row_with(row, count=row.count + take)
                remaining -= take
            # INV-02：余量按上限拆新行（满行 + 余量）
            while remaining > 0:
                n = min(item.stack_max, remaining)
                plan.append(self._row_with(item, count=n))
                remaining -= n

        # INV-09：格数上限校验（整单拒绝，INV-E2）
        if self.inventory_capacity is not None:
            final_rows = len(working) + len(plan)
            if final_rows > self.inventory_capacity:
                return {
                    "ok": False, "reason": "inventory_full",
                    "message": "背包已满，无法放入更多物品",
                }

        inv[:] = working + plan
        new_rows = [r.item_id for r in plan]  # 本次实际新增行（INV-01/02/03 计划产出）
        result: dict = {
            "ok": True,
            "added": count,
            "new_rows": new_rows,
            # P2-10 语义澄清（M6 批1A 审查）：rows = 全量行快照（含既有行），
            # 新消费方用 new_rows 判新增；rows 仅为快照参考，勿按 rows 计新增。
            "rows": new_rows + [r.item_id for r in working],
            "truncated": truncated,
        }
        if truncated:
            result["message"] = _TRUNCATE_MSG
        return result

    def remove_item(self, player: Any, item_id: str, count: int = 1) -> Any:
        """扣减与行清理（INV-04/INV-05/INV-07/INV-10）。

        - INV-05：目标不存在或合计数量不足 → 拒绝 {ok: False, reason: "not_enough"}，
          不产生部分扣减。
        - INV-07/TC-INV-05：绑定行拒移——优先扣非绑定行，须动用绑定行 → 拒绝
          {ok: False, reason: "bound"}，背包数量不变。
        - INV-04：行级 count - N；count=0 整行清理（实例行删除）。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        if not isinstance(item_id, str) or not item_id:
            return {"ok": False, "reason": "invalid_item_id"}
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            return {"ok": False, "reason": "invalid_count"}

        inv = self._as_list(player)
        self._purge_expired(player, self._now())  # INV-10 惰性移除

        # 命中行按「非绑定优先」排序（INV-07：绑定行与未绑定行分开成行）
        hits = [r for r in inv if r.item_id == item_id]
        hits_unbound = [r for r in hits if not r.bound]
        hits_bound = [r for r in hits if r.bound]
        total = sum(r.count for r in hits)
        unbound_total = sum(r.count for r in hits_unbound)

        if total < count:
            # INV-05：不足 → 拒绝，不部分扣减
            return {
                "ok": False, "reason": "not_enough",
                "message": f"背包里只有 {total} 个{item_id}",
            }
        if count > unbound_total and hits_bound:
            # INV-07/TC-INV-05：须动用绑定行 → 拒绝（绑定不可移出玩家所有权）
            return {
                "ok": False, "reason": "bound",
                "message": f"{item_id} 是绑定物品，不可出售/赠送/丢弃",
            }

        remaining = count
        for idx in range(len(inv) - 1, -1, -1):
            row = inv[idx]
            if row.item_id != item_id or row.bound:
                continue
            if remaining <= 0:
                break
            if row.count <= remaining:
                remaining -= row.count
                del inv[idx]  # INV-04：count=0 整行清理
            else:
                inv[idx] = self._row_with(row, count=row.count - remaining)
                remaining = 0
        return {"ok": True, "removed": count, "item_id": item_id}

    def count(self, player: Any, item_id: str) -> int:
        """跨行求和（INV-06）：堆叠行按 count、实例行按 1；仅统计可消费数量
        （绑定拒用判定归使用入口）。背包操作 → 先做到期惰性移除（INV-10）。"""
        if not isinstance(player, MutableMapping):
            return 0
        if not isinstance(item_id, str) or not item_id:
            return 0
        inv = self._as_list(player)
        self._purge_expired(player, self._now())  # INV-10 惰性移除
        return sum(
            1 if r.stack_max <= 1 else r.count
            for r in inv
            if r.item_id == item_id
        )
