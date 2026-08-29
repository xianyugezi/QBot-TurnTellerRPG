"""复制登记引擎（M8 批7-1·路B · qbot_rpg/core/alchemy_register.py）——AlchemyRegister。

文件名：qbot_rpg/core/alchemy_register.py
创建时间：2026-08-29
作者：Hermes 子agent-7B（并发同仓：仅新建本文件 + tests/unit/test_alchemy_register.py；
  兄弟路 7A 在写 qbot_rpg/core/jewel.py（珠系统），只读勿探查；本文件只新建不改 shared 文件）

功能描述：AlchemyRegister 承载【量贩复制】全流程业务逻辑（细化_2c4c DUP-01~06 / TC-07~11）——
  /登记 模板持久化（DUP-06：登记表落点 ctx["registered"]，成本快照冻结、换包同 ID 保留）、
  /复制 量产标准版（DUP-04：仅标准版物品可复制）、复制消耗（DUP-03：⌊配方 cost.coins×费率⌋
  宝石 + 配方材料全量 + 可配额外消耗，拍板④）、数量上限提示不拦（DUP-05/拍板⑤）、
  原子校验全拒差异（DUP-05/TC-10）、快照-回滚事务（ATO-02 单事务）。纯函数零 IO 零 NoneBot；
  构造器注入 settings（单源，对齐 core/synthesis.py / core/gem_wallet.py 工程补白 1）；
  操作对象 = ctx 玩家表示（就地改写 currencies/inventory/registered）；
  返回 dict 结果、拒绝场景 {ok: False, reason, message} 不抛异常。

依据：
  - docs/细化/细化_2c4c_珠与合成指令.md：DUP-01（解锁=大师，SP 可解锁替代）/ DUP-02（先登记后复制，
    未登记 → 错误模板「未登记复制」）/ DUP-03（每次复制消耗 = ⌊配方 cost.coins×20%⌋ 宝石（只算
    cost.coins，向下取整，拍板④）+ 配方材料全量 + 可配额外消耗）/ DUP-04（产出=标准版，仅限有
    标准版的物品）/ DUP-05（数量上限默认 2147483647 超限提示不拦，拍板⑤；材料+宝石全量满足才执行，
    否则全拒并提示差异）/ DUP-06（登记模板持久化，换包按 ID 保留）；验收 TC-07~11。
  - docs/细化/细化_2c4a_炼金三层漏斗.md LAY-04a（标准版=品质固定、无特性/超特性/进化/核心类；
    标准珠带固定 base_effects）。
  - docs/m8_contract_指令契约.md §11 /登记 /复制（GU-34~36/F-11/M-11/P-11）+ §3.4（max_qty 拍板⑤）
    + ATO-01/02/07（全量原子校验/单事务/批量防双扣）。
  - 模式参考 core/synthesis.py（SynthesisEngine 构造注入 + 原子校验 + 快照-回滚 +
    _material_shortfall/_format_shortfall）、core/gem_wallet.py（标准版判定口径 GW-1 + 宝石配置
    读取）、core/reward.py（ctx hook 消费）。
  - 已落地数据 content/test_demo/settings.json alchemy 段（扁平键 "gem.复制"=0.2 /
    "gem.复制额外"=0 / max_qty=2147483647）+ recipe.json（materials[{id,count}]/output{item,count}/
    cost{coins,gem}）+ items.json（标准成品无 quality/traits；炼金成品带 quality+traits）。

【工程补白 · 显式标注】（定稿/细化未给口径处，按最小必要推导，不得新增定稿外机制行为）：
  AR-1  登记表落点：ctx["registered"] = {item_id: {item_id, cost_snapshot}}（玩家级 dict；指令壳
        持久化到存档/SQLite；DUP-06「换包同 ID 保留」= 按 item_id 键存储 + 成本快照冻结，不重算）。
  AR-2  成本快照 = copy_cost(recipe_def) 的每份基准 {gem, materials, extra}，登记时冻结；/复制
        一律以登记快照为准（DUP-06 持久化语义），copy() 的 recipe_def 仅作指令壳解析兜底参数。
  AR-3  标准版判定口径（DUP-04 输入侧推导）：is_copyable = item_def 为 Mapping 且无「非标准版
        标记」（traits/awaken/evolution/core 任一非空 → 非标准版拒绝；对齐 gem_wallet GW-1 口径
        倒置）。标准珠（quality+base_effects、无 traits）可复制；炼金成品/炼金珠（带 traits）不可。
  AR-4  可配额外消耗（拍板④/DUP-03）：settings.alchemy.gem.复制额外（兼容 test_demo 扁平键
        "gem.复制额外"）每份额外宝石数，缺省 0；并入原子校验与快照-回滚事务。
  AR-5  配置读取双形态：settings.alchemy.gem.复制 / 复制额外（嵌套 dict）与
        settings.alchemy."gem.复制" / "gem.复制额外"（test_demo 扁平键）均兼容（扁平覆盖嵌套）；
        复制费率缺省 0.2（DUP-03 / gem.复制）。
  AR-6  复制产出入包 bound=False（对齐 synthesis 工程补白 9：可交易普通商品；绑定态定稿未言，
        珠绑定 BEL-08 属珠实例侧，非复制产出侧）。
  AR-7  /复制 不产熟练经验、不耗能量、不点亮图鉴（M-11 契约仅消耗+产出，非合成层操作）。
  AR-8  登记需配方（成本基准）：recipe_def 未传且 ctx["recipe"] 无产出该物品的配方 →
        拒 recipe_not_found（无法冻结成本快照，最小必要推导）。
  AR-9  数量上限截断口径（拍板⑤/对齐 shop D-05 与 synthesis 工程补白 6）：超限「最多一次使用 N 个」
        提示不拦、按上限截断执行量；上限 = settings.alchemy.max_qty 缺省 2147483647。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；工程补白显式标注；不新增定稿外机制行为。
"""

from __future__ import annotations

import copy
import math
from typing import Any, Callable, List, Mapping, MutableMapping, Optional, Tuple, cast

__all__ = [
    "DEFAULT_COPY_EXTRA_GEM",
    "DEFAULT_COPY_RATE",
    "DEFAULT_MAX_QTY",
    "REASON_MATERIALS",
    "REASON_STANDARD_ONLY",
    "REASON_UNREGISTERED",
    "AlchemyRegister",
]

# ---------------------------------------------------------------------------
# 常量（DUP-03/DUP-05 / 拍板④⑤）
# ---------------------------------------------------------------------------
# 数量上限默认 = int32 max（DUP-05 / 拍板⑤ / m8_contract_指令契约 §3.4）
DEFAULT_MAX_QTY: int = 2147483647
# 复制费率缺省 = 0.2（DUP-03 / 定稿 L419 gem.复制 / test_demo "gem.复制"）
DEFAULT_COPY_RATE: float = 0.2
# 可配额外消耗缺省 = 0 宝石/份（拍板④ / DUP-03 / test_demo "gem.复制额外"）
DEFAULT_COPY_EXTRA_GEM: int = 0

# 未登记复制拒绝原因（DUP-02 / TC-07，指令壳可复用）
REASON_UNREGISTERED: str = "unregistered"
# 仅标准版可复制拒绝原因（DUP-04 / TC-09）
REASON_STANDARD_ONLY: str = "standard_only"
# 材料/宝石不足全拒差异拒绝原因（DUP-05 / TC-10）
REASON_MATERIALS: str = "materials"

# 非标准版标记键（LAY-04a：特性/超特性/进化/核心类；AR-3 判定口径）
_ADVANCE_MARKER_KEYS: Tuple[str, ...] = ("traits", "awaken", "evolution", "core")

# 快照-回滚覆盖的可变 ctx 子结构（对齐 synthesis._SNAP_KEYS：原子防双扣口径）
_SNAP_KEYS: Tuple[str, ...] = ("currencies", "inventory")


# ---------------------------------------------------------------------------
# 基础工具（纯函数，镜像 synthesis.py 同款实现）
# ---------------------------------------------------------------------------
def _as_int(value: object) -> Optional[int]:
    """int 归一（bool 除外）；非 int/bool/可转数字串 → None（对齐 synthesis._as_int）。"""
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


def _item_def(ctx: Mapping[str, Any], item_id: object) -> Optional[Mapping[str, Any]]:
    """物品 id → 物品定义（ctx["items"] dict/list 注册表或 resolve_item 解析器；缺省 None）。"""
    if not isinstance(item_id, str) or not item_id:
        return None
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        if isinstance(hit, Mapping):
            return hit
    elif isinstance(items, list):
        for e in items:
            if isinstance(e, Mapping) and e.get("id") == item_id:
                return e
    resolver = ctx.get("resolve_item")
    if callable(resolver):
        try:
            hit = resolver(item_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            return hit
    return None


def _item_name(item_id: object, ctx: Mapping[str, Any]) -> str:
    """物品 id → 显示名（ctx["items"] 注册表或 resolve_item 解析器；缺省回退原 id）。"""
    if not isinstance(item_id, str):
        return str(item_id)
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    elif isinstance(items, list):
        for e in items:
            if isinstance(e, Mapping) and e.get("id") == item_id:
                name = e.get("name")
                if isinstance(name, str) and name:
                    return name
    resolver = ctx.get("resolve_item")
    if callable(resolver):
        try:
            hit = resolver(item_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    return item_id


def _add_item(ctx: MutableMapping[str, Any], item_id: str, count: int, bound: bool) -> bool:
    """入包：优先 ctx["add_item"] hook；回退 ctx["inventory"] in-memory；均无 → False。"""
    hook = ctx.get("add_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count, bound))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        inv[item_id] = int(inv.get(item_id, 0)) + count
        return True
    return False


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    """扣减（不部分扣减）：优先 ctx["remove_item"] hook；回退 ctx["inventory"] in-memory。"""
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        cur = int(inv.get(item_id, 0))
        if cur < count:
            return False
        inv[item_id] = cur - count
        return True
    return False


def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    """持有计数：优先 ctx["count_item"] hook；回退 ctx["inventory"] in-memory。"""
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            return int(cast(Callable[[str], Any], hook)(item_id))
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


def _snapshot(ctx: Mapping[str, Any]) -> dict:
    """快照（对齐 synthesis._snapshot：事务内原子防双扣）。"""
    return {k: copy.deepcopy(ctx.get(k)) for k in _SNAP_KEYS}


def _restore(ctx: MutableMapping[str, Any], snap: dict) -> None:
    """回滚（对齐 synthesis._restore）。"""
    for k, v in snap.items():
        if v is None:
            ctx.pop(k, None)
        else:
            ctx[k] = v


class _Rollback(Exception):
    """结算阶段失败标记（进程内回滚触发，对齐 synthesis._Rollback）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# AlchemyRegister
# ---------------------------------------------------------------------------
class AlchemyRegister:
    """量贩复制登记引擎（细化_2c4c DUP-01~06 / TC-07~11）。

    构造器配置注入（settings）+ 缺省兜底；纯函数零 IO 零 NoneBot；拒绝场景
    {ok: False, reason, message} 不抛异常（对齐 core/synthesis.py / core/gem_wallet.py 铁律）。
    操作对象 ctx 为可变 dict：就地改写 ctx["currencies"]/ctx["inventory"]/ctx["registered"]，
    存储与持久化由调用方完成（AR-1：registered 为玩家级登记表，指令壳持久化）。
    """

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """构造复制登记引擎（构造器配置注入 + 缺省兜底）。

        入参：settings：settings dict（alchemy 段：max_qty / gem.复制 / gem.复制额外 等）；
          None/非 Mapping → {} → 默认值兜底（AR-5）。配置来源 = 构造器注入单源
          （对齐 synthesis.py 工程补白 1），不读 ctx["settings"]。
        """
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}

    # ------------------------------------------------------------------
    # 配置读取（构造器单源 + 缺省兜底；AR-5 双形态兼容）
    # ------------------------------------------------------------------
    def _alchemy_cfg(self) -> Mapping[str, Any]:
        """settings.alchemy 段归一（缺省 {}）。"""
        alchemy = self._settings.get("alchemy")
        return alchemy if isinstance(alchemy, Mapping) else {}

    def _gem_cfg(self) -> Mapping[str, Any]:
        """宝石配置段归一（AR-5）：合并嵌套 settings.alchemy.gem 与扁平 "gem.xxx" 键
        （扁平覆盖嵌套）。"""
        merged: dict = {}
        alchemy = self._alchemy_cfg()
        nested = alchemy.get("gem")
        if isinstance(nested, Mapping):
            for k, v in nested.items():
                merged[str(k)] = v
        for k, v in alchemy.items():
            if isinstance(k, str) and k.startswith("gem."):
                merged[k[len("gem."):]] = v
        return merged

    def _copy_rate(self) -> float:
        """复制费率（DUP-03 / 拍板④：settings.alchemy.gem.复制 缺省 0.2）。"""
        raw = self._gem_cfg().get("复制")
        if raw is None:
            return DEFAULT_COPY_RATE
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_COPY_RATE
        return v if v >= 0 else DEFAULT_COPY_RATE

    def _extra_gem(self) -> int:
        """可配额外消耗（AR-4：settings.alchemy.gem.复制额外 每份额外宝石，缺省 0）。"""
        v = _as_int(self._gem_cfg().get("复制额外"))
        return v if v is not None and v >= 0 else DEFAULT_COPY_EXTRA_GEM

    def _max_qty(self) -> int:
        """数量上限（DUP-05 / 拍板⑤：settings.alchemy.max_qty 缺省 2147483647）。"""
        v = _as_int(self._alchemy_cfg().get("max_qty"))
        return v if v is not None and v > 0 else DEFAULT_MAX_QTY

    # ------------------------------------------------------------------
    # 标准版判定（DUP-04 / LAY-04a，AR-3 口径）
    # ------------------------------------------------------------------
    @staticmethod
    def is_copyable(item_def: Any) -> bool:
        """标准版可复制判定（DUP-04 / TC-09）。

        入参：item_def 物品定义 dict（可含 quality/base_effects/traits/awaken/evolution/core）。
        出参：bool——无「非标准版标记」（traits/awaken/evolution/core 任一非空）→ True（标准版
              可复制：标准成品/标准珠）；带任一标记（炼金成品/炼金珠）→ False。
        核心：LAY-04a 标准版 = 品质固定 + 无特性/超特性/进化/核心类；非 Mapping → False 防御。
        """
        if not isinstance(item_def, Mapping):
            return False
        for key in _ADVANCE_MARKER_KEYS:
            v = item_def.get(key)
            if isinstance(v, bool) and v:
                return False
            if isinstance(v, (list, tuple, dict, str)) and v:
                return False
        return True

    # ------------------------------------------------------------------
    # 登记表（DUP-02 / DUP-06，AR-1/AR-2）
    # ------------------------------------------------------------------
    def is_registered(self, ctx: Mapping[str, Any], item_id: object) -> bool:
        """是否已登记（DUP-02：未登记 → /复制 拒「未登记复制」）。

        入参：ctx（玩家表示，含 registered 登记表）、item_id 物品 id。
        出参：bool——ctx["registered"][item_id] 存在即 True。
        """
        if not isinstance(item_id, str) or not item_id:
            return False
        table = ctx.get("registered")
        if not isinstance(table, Mapping):
            return False
        return item_id in table

    @staticmethod
    def _resolve_recipe(
        ctx: Mapping[str, Any],
        recipe_def: object,
        item_id: str,
    ) -> Optional[Mapping[str, Any]]:
        """登记用配方解析（AR-8）：recipe_def Mapping 直用 → str id 查注册表 →
        ctx["recipe"] 扫描 output.item/id == item_id；全未命中 → None。"""
        if isinstance(recipe_def, Mapping):
            return recipe_def
        recipes = ctx.get("recipe")
        if isinstance(recipe_def, str):
            if isinstance(recipes, Mapping):
                hit = recipes.get(recipe_def)
                if isinstance(hit, Mapping):
                    return hit
        candidates: List[Any] = []
        if isinstance(recipes, Mapping):
            candidates = list(recipes.values())
        elif isinstance(recipes, list):
            candidates = list(recipes)
        for r in candidates:
            if not isinstance(r, Mapping):
                continue
            out = r.get("output")
            if isinstance(out, Mapping) and (
                out.get("item") == item_id or out.get("id") == item_id
            ):
                return r
        return None

    # ------------------------------------------------------------------
    # 复制消耗计算（DUP-03 / 拍板④）
    # ------------------------------------------------------------------
    def copy_cost(self, recipe_def: Any) -> dict:
        """复制每份消耗（DUP-03 / 拍板④：⌊配方 cost.coins×费率⌋ 宝石 + 配方材料全量 + 可配额外）。

        入参：recipe_def 配方 dict（cost.coins / materials[{id,count}]）。
        出参：{gem, materials, extra}——gem = ⌊cost.coins×复制费率⌋（只算 cost.coins 向下取整，
              拍板④）；materials = 配方材料全量（[{"id", "count"}...] 深拷贝）；extra = {"gem": N}
              （可配额外消耗，缺省 0，AR-4）。
        核心：费率 = settings.alchemy.gem.复制（缺省 0.2，AR-5 双形态）；非法配方防御返回
              {gem:0, materials:[], extra:{gem:0}}。
        """
        cost = recipe_def.get("cost") if isinstance(recipe_def, Mapping) else None
        coins = _as_int(cost.get("coins")) if isinstance(cost, Mapping) else None
        coins = coins if coins is not None and coins > 0 else 0
        gem = int(math.floor(coins * self._copy_rate()))  # 拍板④：⌊cost.coins×费率⌋
        materials: List[dict] = []
        raw_materials = recipe_def.get("materials") if isinstance(recipe_def, Mapping) else None
        if isinstance(raw_materials, list):
            for m in raw_materials:
                if not isinstance(m, Mapping):
                    continue
                mid = m.get("id")
                cnt = _as_int(m.get("count"))
                if isinstance(mid, str) and mid and cnt is not None and cnt > 0:
                    materials.append({"id": mid, "count": cnt})
        extra = {"gem": self._extra_gem()}
        return {"gem": gem, "materials": materials, "extra": extra}

    # ------------------------------------------------------------------
    # /登记（DUP-02/DUP-04/DUP-06；F-11 前半）
    # ------------------------------------------------------------------
    def register(
        self,
        ctx: MutableMapping[str, Any],
        item_id: object,
        recipe_def: object = None,
    ) -> dict:
        """`/登记 <道具>`（DUP-02/04/06 / TC-07/09；F-11 前半）。

        入参：
          - ctx：玩家表示（就地改写 ctx["registered"]；含 items/recipe 注册表）。
          - item_id：待登记物品 id。
          - recipe_def：配方 dict 或配方 id（缺省 None → 自动从 ctx["recipe"] 按产出解析，AR-8）。
        校验链：物品存在 → is_copyable 标准版校验（DUP-04，非标准版 → 拒 standard_only，TC-09）→
          配方可解析（成本基准，AR-8）→ copy_cost 冻结成本快照（AR-2）→ 写入 ctx["registered"][id]
          （玩家级登记表，DUP-06，换包同 ID 保留）。
        出参：{ok, message, item_id, item_name, cost_snapshot?}；拒绝 {ok:False, reason, message}。
        """
        if not isinstance(item_id, str) or not item_id:
            return {"ok": False, "reason": "invalid_item", "message": "❌ 物品无效"}
        item_def = _item_def(ctx, item_id)
        if item_def is None:
            return {"ok": False, "reason": "item_not_found",
                    "message": f"❌ 未找到物品 {item_id}"}
        name = _item_name(item_id, ctx)
        if not self.is_copyable(item_def):
            # DUP-04 / TC-09：复制对象仅限标准版（品质浮动/带特性的炼金产出不可登记）
            return {"ok": False, "reason": REASON_STANDARD_ONLY,
                    "message": f"❌ {name} 非标准版（品质浮动/带特性），仅标准版可登记复制",
                    "item_id": item_id, "item_name": name}
        recipe = self._resolve_recipe(ctx, recipe_def, item_id)
        if recipe is None:
            # AR-8：登记需配方作成本基准（无产出该物品的配方 → 无法冻结成本快照）
            return {"ok": False, "reason": "recipe_not_found",
                    "message": f"❌ 未找到 {name} 的配方（无法登记成本快照）",
                    "item_id": item_id, "item_name": name}
        cost = self.copy_cost(recipe)
        table = ctx.get("registered")
        if not isinstance(table, MutableMapping):
            table = {}
            ctx["registered"] = table
        # DUP-06：登记表落点 = {item_id: {item_id, cost_snapshot}}；同 ID 重复登记覆盖快照
        table[item_id] = {"item_id": item_id, "cost_snapshot": copy.deepcopy(cost)}
        return {"ok": True, "reason": None, "item_id": item_id, "item_name": name,
                "message": f"✅ 已登记 {name} 复制模板（换包同 ID 保留）",
                "cost_snapshot": cost}

    # ------------------------------------------------------------------
    # 原子校验 / 差异提示（DUP-05 / TC-10）
    # ------------------------------------------------------------------
    def _shortfall(
        self,
        ctx: Mapping[str, Any],
        materials: List[Any],
        n: int,
        need_gem: int,
    ) -> Optional[dict]:
        """材料×N + 宝石×N 全量差额（DUP-05）；全满足 → None；
        否则 {items:[(名称, 缺额)], gem}。材料按登记快照序；宝石 = 复制费+额外（拍板④）。"""
        short: dict = {"items": [], "gem": 0}
        found = False
        for m in materials:
            mid = m.get("id") if isinstance(m, Mapping) else None
            cnt = _as_int(m.get("count")) if isinstance(m, Mapping) else None
            if not isinstance(mid, str) or not mid or cnt is None or cnt < 0:
                continue
            need = cnt * n
            if need <= 0:
                continue
            have = _count_item(ctx, mid)
            if have < need:
                short["items"].append((_item_name(mid, ctx), need - have))
                found = True
        if need_gem > 0:
            currencies = ctx.get("currencies")
            have = int(currencies.get("gem", 0)) if isinstance(currencies, Mapping) else 0
            if have < need_gem:
                short["gem"] = need_gem - have
                found = True
        return short if found else None

    @staticmethod
    def _format_shortfall(short: Mapping[str, Any]) -> str:
        """差异提示文案：「水结晶×5 + 宝石 30」（TC-10：材料×缺额 + 宝石 缺额）。"""
        parts: List[str] = []
        for name, deficit in short.get("items", []):
            parts.append(f"{name}×{deficit}")
        if short.get("gem"):
            parts.append(f"宝石 {short['gem']}")
        return " + ".join(parts)

    def _format_consume(
        self,
        ctx: Mapping[str, Any],
        materials: List[Any],
        need_gem: int,
        n: int,
    ) -> str:
        """成功消息消耗段（M-11）：「宝石×60 + 水结晶×50 + 草药×20」（宝石先行）。"""
        parts: List[str] = []
        if need_gem:
            parts.append(f"宝石×{need_gem}")
        for m in materials:
            mid = m.get("id") if isinstance(m, Mapping) else None
            cnt = _as_int(m.get("count")) if isinstance(m, Mapping) else None
            if isinstance(mid, str) and mid and cnt is not None and cnt > 0:
                total = cnt * n
                if total > 0:
                    parts.append(f"{_item_name(mid, ctx)}×{total}")
        return " + ".join(parts)

    def _material_totals(self, materials: List[Any], n: int) -> List[dict]:
        """消耗材料总量（×N）列表（供结果 cost 字段）。"""
        out: List[dict] = []
        for m in materials:
            mid = m.get("id") if isinstance(m, Mapping) else None
            cnt = _as_int(m.get("count")) if isinstance(m, Mapping) else None
            if isinstance(mid, str) and mid and cnt is not None and cnt > 0:
                out.append({"id": mid, "count": cnt * n})
        return out

    # ------------------------------------------------------------------
    # /复制 主入口（DUP-01~05；F-11 后半：守卫 → 数量上限 → 原子校验 → 快照-回滚）
    # ------------------------------------------------------------------
    def copy(
        self,
        ctx: MutableMapping[str, Any],
        item_id: object,
        count: object = 1,
        recipe_def: object = None,
    ) -> dict:
        """`/复制 <道具>*<数量>`（DUP-01~05 / TC-07~11；F-11 后半）。

        入参：
          - ctx：玩家表示（就地改写 currencies/inventory；含 items/registered）。
          - item_id：待复制物品 id。
          - count：数量（缺省 1；int≥1；超 max_qty → 提示「最多一次使用 N 个」不拦、按上限截断，
            拍板⑤/AR-9）。
          - recipe_def：配方 dict/id（仅指令壳解析兜底，成本一律以登记快照为准，AR-2）。
        流程（F-11）：前置 = 已登记（未登记 → 拒「未登记复制」，DUP-02/TC-07）+ 可复制
          （DUP-04，防御性重校验）→ 数量上限 check（拍板⑤）→ 原子校验（宝石×N + 材料×N 全量
          满足才执行，否则全拒+差异提示，DUP-05/TC-10）→ 快照-回滚事务扣宝石+材料 → 量产标准版
          add_item（DUP-04，无品质浮动/无特性，AR-6 bound=False）。
        出参：{ok, message, produced:{item_id,name,count}, cost:{gem,materials,extra}, advisory}；
          拒绝 {ok:False, reason, message, produced:None, advisory?}。
        """
        n = _as_int(count)
        if n is None or n < 1:
            return {"ok": False, "reason": "invalid_count", "message": "❌ 数量无效",
                    "produced": None, "advisory": None}
        if not isinstance(item_id, str) or not item_id:
            return {"ok": False, "reason": "invalid_item", "message": "❌ 物品无效",
                    "produced": None, "advisory": None}
        item_def = _item_def(ctx, item_id)
        if item_def is None:
            return {"ok": False, "reason": "item_not_found",
                    "message": f"❌ 未找到物品 {item_id}", "produced": None, "advisory": None}
        name = _item_name(item_id, ctx)
        # 前置 GU-35：先登记后复制（DUP-02 / TC-07：未登记 → 错误模板「未登记复制」）
        if not self.is_registered(ctx, item_id):
            return {"ok": False, "reason": REASON_UNREGISTERED,
                    "message": f"❌ 未登记复制：{name} 尚未登记，请先 /登记",
                    "item_id": item_id, "item_name": name, "produced": None, "advisory": None}
        # 防御性重校验：已登记但当前物品非标准版（换包后物品被改）→ 拒（DUP-04/TC-09）
        if not self.is_copyable(item_def):
            return {"ok": False, "reason": REASON_STANDARD_ONLY,
                    "message": f"❌ {name} 非标准版，不可复制",
                    "item_id": item_id, "item_name": name, "produced": None, "advisory": None}
        table = ctx.get("registered")
        snap_entry = table.get(item_id) if isinstance(table, Mapping) else None
        cost_snap = snap_entry.get("cost_snapshot") if isinstance(snap_entry, Mapping) else None
        if not isinstance(cost_snap, Mapping):
            # 防御：登记模板损坏/缺快照 → 拒并提示重新登记（AR-2 一致性）
            return {"ok": False, "reason": "invalid_registration",
                    "message": f"❌ {name} 登记模板损坏，请重新 /登记",
                    "item_id": item_id, "item_name": name, "produced": None, "advisory": None}

        # 数量上限（拍板⑤/AR-9：超限提示不拦、按上限截断执行量）
        cap = self._max_qty()
        advisory = None
        if n > cap:
            advisory = f"最多一次使用 {cap} 个"
            n = cap

        # 每份消耗（登记快照为准，DUP-06/AR-2）
        per_gem = _as_int(cost_snap.get("gem")) or 0
        extra_map = cost_snap.get("extra")
        per_extra = (
            _as_int(extra_map.get("gem")) if isinstance(extra_map, Mapping) else None
        )
        per_extra = per_extra if per_extra is not None and per_extra >= 0 else 0
        raw_materials = cost_snap.get("materials")
        materials: List[Any] = raw_materials if isinstance(raw_materials, list) else []
        need_gem = (per_gem + per_extra) * n

        # 货币桶检查（need_gem>0 时必须存在，对齐 synthesis 工程补白 7）
        if need_gem and not isinstance(ctx.get("currencies"), MutableMapping):
            return {"ok": False, "reason": "missing_bucket", "message": "❌ 无法结算货币",
                    "produced": None, "advisory": advisory}

        # 原子校验（DUP-05/TC-10：宝石×N + 材料×N 全量满足才执行，否则全拒+差异提示）
        short = self._shortfall(ctx, materials, n, need_gem)
        if short is not None:
            diff = self._format_shortfall(short)
            return {"ok": False, "reason": REASON_MATERIALS,
                    "message": f"❌ 材料不足：缺 {diff}",
                    "produced": None, "advisory": advisory, "shortfall": short}

        # 入包通道检查（否则扣料无落点，原子性破坏前拒绝，对齐 synthesis）
        if not callable(ctx.get("add_item")) and not isinstance(
            ctx.get("inventory"), MutableMapping
        ):
            return {"ok": False, "reason": "storage_missing",
                    "message": "❌ 无法入包（背包通道缺失）",
                    "produced": None, "advisory": advisory}

        # ---- 事务内：扣宝石+材料 → 量产标准版（快照-回滚，DUP-05/ATO-02 单事务语义）----
        snap = _snapshot(ctx)
        try:
            currencies = ctx.get("currencies")
            if isinstance(currencies, MutableMapping) and need_gem:
                currencies["gem"] = int(currencies.get("gem", 0)) - need_gem
            for m in materials:
                mid = m.get("id") if isinstance(m, Mapping) else None
                cnt = _as_int(m.get("count")) if isinstance(m, Mapping) else None
                if isinstance(mid, str) and mid and cnt is not None and cnt > 0:
                    total = cnt * n
                    if not _remove_item(ctx, mid, total):
                        raise _Rollback("material_remove_failed")
            # 标准版入包（DUP-04/TC-08：无品质浮动/无特性，直接 add_item；bound=False，AR-6）
            if not _add_item(ctx, item_id, n, bound=False):
                raise _Rollback("item_add_failed")
        except _Rollback as exc:
            _restore(ctx, snap)
            return {"ok": False, "reason": exc.reason, "message": "❌ 结算失败，已回滚",
                    "produced": None, "advisory": advisory}

        # 消息合成（M-11：✅ 魔力药水 ×5 复制完成（消耗 宝石×N + 材料…）；advisory 追加）
        consume = self._format_consume(ctx, materials, need_gem, n)
        msg = f"✅ {name} ×{n} 复制完成（消耗 {consume}）"
        if advisory:
            msg += f"；{advisory}"

        return {
            "ok": True,
            "reason": None,
            "message": msg,
            "produced": {"item_id": item_id, "name": name, "count": n},
            "cost": {
                "gem": need_gem,
                "materials": self._material_totals(materials, n),
                "extra": {"gem": per_extra * n},
            },
            "advisory": advisory,
            "idempotent": False,
        }
