"""升级合成引擎（M8 批2·路2B · qbot_rpg/core/upgrade.py）——kind=upgrade 通用执行器 + 4 配置实例。

文件：qbot_rpg/core/upgrade.py
创建：2026-08-29
作者：Hermes 子agent-2B
功能：合成引擎 kind=upgrade 通用执行器（inputs N 入 / cost{coins,gem} / output 1 出）——
      珠三合一升阶（3×同档同 ID+宝石10→+1 阶，禁跳级，无职业硬门槛 拍板③）、成品合成
      （两成品+材料+宝石10→更强成品，原子提交 F-09）、配方合成（两已学配方+宝石5→永久
      解锁，组合表 F-12 / ATO-05 幂等）、特性合成（两同系特性+宝石20+材料→更高位特性，
      产出落位复核 group 互斥组与 repeatable，F-13 / TSC-15~18）。含组合表归一 + 玩家级
      解锁表读写（ctx["upgrade_unlocks"]，工程补白）。供批7B 珠升阶指令与批7C 成品合成/
      配方合成/特性合成指令消费。

依据：
  - docs/m8_batch_plan.md 批2 路2B（通用执行器 + 4 配置实例 + 组合表 + 玩家级解锁表）
  - docs/m8_contract_指令契约.md §9（F-09 成品合成 原子提交）、§12（F-12 配方合成 组合表
    命中→永久解锁；重复合成已解锁→提示已解锁不重复扣宝石 ATO-05）、§13（F-13 特性合成
    融合升阶为更高位特性；产出落位复核 group 互斥组与 repeatable；gem.特性合成=20）
  - docs/细化/细化_2c4e_品质与特性.md TSC-15~18（进化特性 = kind=upgrade 配置实例：
    inputs=2 同系特性、cost=宝石20+材料、output=更高位特性）
  - docs/m8_contract_核心机制.md §六 6.3（BATCH 原子性：材料×N+金币全量满足才执行否则全拒
    +差异提示；单事务提交任一步失败 ROLLBACK 零副作用——存储层事务由批7C 指令壳包裹，
    引擎进程内 best-effort 回滚）
  - 拍板③（珠升阶无职业硬门槛，准入靠槽级 SOCK-02，引擎不设职业门槛）+ 拍板④（复制费
    另批，本引擎不涉及复制）
  - 批0/批1 已落地：qbot_rpg/core/quality.py（QualitySystem tier_index/index_to_tier 档位
    序号换算——珠升阶 +1 阶联动）；content/test_demo/recipe.json（kind=upgrade 配置实例）；
    content/test_demo/settings.json alchemy 段（gem.珠升阶=10/成品合成=10/配方合成=5/
    特性合成=20）
  - 模式参考 qbot_rpg/core/shop.py + reward.py（ctx hook 模式：ctx["items"]/ctx["add_item"]/
    ctx["remove_item"]/ctx["count_item"]/ctx["currencies"]）+ quality.py（构造器配置注入兜底）
    + levelup.py LevelUpEngine（构造器配置注入 + 兜底）

【工程补白 · 显式标注】（定稿未给口径处，按最小必要推导，不新增定稿外机制行为）：
  U-S1 子类型判定：配方条目无显式 subtype 字段时按结构推断（对齐批0 recipe.json 形态）——
       combine_from 非空 → formula_merge；单输入条目且 count≥3 且 gem 费率=gem.珠升阶 →
       jewel_upgrade；gem 费率=gem.特性合成 → trait_merge；其余 → product_merge。
  U-J1 珠档位解析与产出档位联动：珠档位来源（按序首个可用）① 物品注册表 item def 的
       `quality` 字段（合法档位键）或 `tier` 数值（档位序号，经 index_to_tier）② 配方条目
       显式 `jewel_tier` 字段 ③ 均无 → 档位联动无法核验，退化为「同 ID×3+宝石10 → 按配方
       output 出货」数据直通（珠数据由批12B 补 quality 后自动启用档位校验）。禁跳级 =
       产出档位序号必须 == 输入档位序号+1（quality.index_to_tier），否则拒绝。
  U-J2 珠升阶输入：必须恰 1 个输入条目、count≥3（3×同档同 ID 由单条目同 ID 保证）；
       input_ids 若传则必须全等于配方输入 item（防御）。
  U-T1 特性落位目标：ctx["target_traits"]（成品已带特性 id 列表，由批7C 指令壳从成品
       ItemInstance.traits 注入）；缺失/非 list → 跳过落位操作（仅返回 produced）。
  U-T2 同系判定精确语义：配置 condition.same_family 显式系名 → 两特性均属该系（family==系名
       或 group 以系名前缀）；否则 group 相同即同系；再否则 family 字段相同即同系。满足其一
       即同系，否则拒绝（GU-42 非同系拒绝）。
  U-T3 「更高位特性」产出确定：组合表 combos 命中（2 输入特性 frozenset → {output, condition}）
       优先；未命中兜底 recipe output 字段（output.item 视为特性 id）。
  U-T4 特性注册表：ctx["traits"] dict 或 ctx["resolve_trait"] 解析器（traits.json 语义：
       group/repeatable 字段）。
  U-F1 配方合成产出确定：组合表 combos 命中优先；未命中兜底 recipe output 字段
       （output.item 视为新配方 id）。
  U-F2 玩家级解锁表：ctx["upgrade_unlocks"] dict（键=已解锁配方 id，值={source, gem_cost}），
       随玩家存档持久化；进化（/进化 批8A）与配方合成共用此表。引擎零 IO 不碰 SQLite
       （repository 归批7C 指令壳）。
  U-F3 已学配方判定（GU-38 两配方均已学）：a、b ∈ ctx["upgrade_unlocks"] 键集合。
  U-C1 组合表归一：combos 支持 dict（pair frozenset/tuple/list→{output, condition}）或 list
       （[{a,b,output,condition},...]）→ 归一为 frozenset(2 配方/特性 id)→dict。
  U-A1 原子提交回滚口径：引擎进程内「校验全过→提交」两段式（校验阶段纯读零副作用，全量
       不满足即全拒+差异提示）；提交阶段（扣货币→扣输入→产出/解锁/落位）任一 hook 失败 →
       best-effort 回滚进程内已改子结构（货币快照恢复/解锁表恢复/落位列表恢复）；跨进程
       存储事务与条件式 UPDATE 由批7C 指令壳包裹（对齐 shop D-03 职责划分，BATCH-06.3）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；工程补白显式标注；不抛异常（配置缺省
      兜底、hook 失败转 ok:False 拒绝）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from qbot_rpg.core.quality import QualitySystem

__all__ = [
    "UPGRADE_SUBTYPES",
    "DEFAULT_GEM_COST",
    "UpgradeEngine",
]

# 升级合成四个配置实例子类型（批2 路2B）
UPGRADE_SUBTYPES: Tuple[str, ...] = (
    "jewel_upgrade",  # 珠三合一升阶
    "product_merge",  # 成品合成
    "formula_merge",  # 配方合成
    "trait_merge",    # 特性合成
)

# 缺省 gem 费率（settings.alchemy.gem 段缺省，对齐批0 content/test_demo/settings.json）
DEFAULT_GEM_COST: Dict[str, int] = {
    "gem.珠升阶": 10,
    "gem.成品合成": 10,
    "gem.配方合成": 5,
    "gem.特性合成": 20,
}

# 品质档位键（对齐 quality.QUALITY_KEYS；引擎本地持有保持零依赖，拍板②）
_QUALITY_KEYS: Tuple[str, ...] = ("common", "uncommon", "rare", "legendary")

# 解锁来源标记（工程补白 U-F2：进化 / 配方合成 共用玩家级解锁表）
_UNLOCK_SOURCE_FORMULA = "formula_merge"


class _CommitFailed(Exception):
    """提交阶段 hook 失败（进程内回滚触发标记，不对外抛出）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason: str = reason


def _as_int(value: object) -> Optional[int]:
    """int 归一（bool 除外）；非法 → None（防御）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


class UpgradeEngine:
    """升级合成引擎（kind=upgrade 通用执行器 + 4 配置实例）。

    构造器配置注入 + 缺省默认值兜底（对齐 quality/levelup 模式）：
      - quality：QualitySystem 实例，用于珠升阶档位联动（缺省兜底 new QualitySystem()）；
      - combos：配方合成组合表（2 输入 → {output, condition}，可配，缺省 {}）；
      - settings：settings.alchemy 段（gem 费率缺省 珠升阶10/成品合成10/配方合成5/特性合成20）。
    操作对象为 ctx dict（玩家上下文，hook 模式对齐 shop/reward），所有改写就地发生；
    返回 {ok, message, consumed, produced}，拒绝场景 {ok: False, reason, message} 不抛异常。
    """

    def __init__(
        self,
        quality: Optional[QualitySystem] = None,
        combos: object = None,
        settings: Optional[Mapping] = None,
    ) -> None:
        """构造升级引擎（配置注入 + 缺省默认值兜底，批2 路2B）。

        - quality：珠档位联动引擎；None/非 QualitySystem → 缺省 QualitySystem()。
        - combos：配方合成组合表（归一化后为 frozenset(2 id)→{output, condition}）；
          接受 dict（pair→{output,condition}）或 list（[{a,b,output,condition},...]，
          U-C1）；None/空 → {}。
        - settings：settings.alchemy 段；gem 费率键缺省回落 DEFAULT_GEM_COST。
        """
        self.quality: QualitySystem = (
            quality if isinstance(quality, QualitySystem) else QualitySystem()
        )
        self._settings: Dict[str, Any] = dict(settings) if isinstance(settings, Mapping) else {}
        self._combos: Dict[frozenset, dict] = self._normalize_combos(combos)

    # ------------------------------------------------------------------
    # 配置解析 / 子类型判定（U-S1）
    # ------------------------------------------------------------------
    def resolve_upgrade_recipe(self, recipe_def: object) -> Optional[dict]:
        """配方条目 → 升级配置（批0 数据契约 §1.1 kind=upgrade 形态）。

        入参：recipe_def recipe.json kind=upgrade 条目（inputs N 入/cost{coins,gem}/
              output 1 出/combine_from 可选；或已解析配置 dict 幂等直通）。
        出参：{kind, id, name, subtype, inputs, cost, output, condition, combine_from}
              ；非 kind=upgrade / 非 Mapping → None（防御）。
        核心：子类型按显式 subtype 字段或结构推断（U-S1）；inputs/cost/output 归一。
        """
        if not isinstance(recipe_def, Mapping):
            return None
        if recipe_def.get("kind") != "upgrade":
            return None

        subtype = recipe_def.get("subtype")
        if not isinstance(subtype, str) or subtype not in UPGRADE_SUBTYPES:
            subtype = self._infer_subtype(recipe_def)

        inputs: List[Dict[str, Any]] = []
        raw_inputs = recipe_def.get("inputs")
        if isinstance(raw_inputs, (list, tuple)):
            for e in raw_inputs:
                if not isinstance(e, Mapping):
                    continue
                item = e.get("item")
                if not isinstance(item, str) or not item:
                    continue
                count = _as_int(e.get("count", 1))
                c = count if count is not None and count > 0 else 1
                inputs.append({"item": item, "count": c})

        raw_output = recipe_def.get("output")
        output: Optional[Dict[str, Any]] = None
        if isinstance(raw_output, Mapping) and isinstance(raw_output.get("item"), str) \
                and raw_output["item"]:
            count = _as_int(raw_output.get("count", 1))
            output = {
                "item": raw_output["item"],
                "count": count if count is not None and count > 0 else 1,
            }

        raw_cost = recipe_def.get("cost")
        coins = _as_int(raw_cost.get("coins", 0)) if isinstance(raw_cost, Mapping) else None
        gem = _as_int(raw_cost.get("gem", 0)) if isinstance(raw_cost, Mapping) else None
        cost: Dict[str, int] = {
            "coins": coins if coins is not None and coins >= 0 else 0,
            "gem": gem if gem is not None and gem >= 0 else 0,
        }

        raw_cf = recipe_def.get("combine_from")
        combine_from: List[str] = (
            [str(x) for x in raw_cf if isinstance(x, str) and x]
            if isinstance(raw_cf, (list, tuple)) else []
        )

        raw_cond = recipe_def.get("condition")
        condition: Optional[Dict[str, Any]] = None
        if isinstance(raw_cond, Mapping):
            condition = dict(raw_cond)

        # 珠升阶显式档位标注（U-J1 ③：内容包/测试可显式声明珠档位，缺省 None）
        raw_jt = recipe_def.get("jewel_tier")
        jewel_tier: Optional[str] = str(raw_jt) if isinstance(raw_jt, str) and raw_jt else None

        return {
            "kind": "upgrade",
            "id": str(recipe_def.get("id", "")),
            "name": str(recipe_def.get("name", "")),
            "subtype": subtype,
            "inputs": inputs,
            "cost": cost,
            "output": output,
            "condition": condition,
            "combine_from": combine_from,
            "jewel_tier": jewel_tier,
        }

    def _infer_subtype(self, recipe_def: Mapping) -> str:
        """子类型结构推断（工程补白 U-S1）：combine_from → formula_merge；
        单输入条目 count≥3 且 gem=珠升阶费率 → jewel_upgrade；
        gem=特性合成费率 → trait_merge；其余 → product_merge。"""
        if recipe_def.get("combine_from"):
            return "formula_merge"
        raw_inputs = recipe_def.get("inputs")
        if isinstance(raw_inputs, (list, tuple)) and len(raw_inputs) == 1:
            e = raw_inputs[0]
            if isinstance(e, Mapping) and (_as_int(e.get("count", 1)) or 0) >= 3:
                raw_cost = recipe_def.get("cost")
                gem = _as_int(raw_cost.get("gem", 0)) if isinstance(raw_cost, Mapping) else None
                if gem is not None and gem == self._gem_cost("gem.珠升阶"):
                    return "jewel_upgrade"
        raw_cost = recipe_def.get("cost")
        gem = _as_int(raw_cost.get("gem", 0)) if isinstance(raw_cost, Mapping) else None
        if gem is not None and gem == self._gem_cost("gem.特性合成"):
            return "trait_merge"
        return "product_merge"

    # ------------------------------------------------------------------
    # 组合表归一（U-C1）/ 组合命中
    # ------------------------------------------------------------------
    @staticmethod
    def _pair_from_key(key: object) -> Optional[frozenset]:
        """组合表键归一：frozenset/tuple/list 恰 2 个互异 str → frozenset。"""
        if isinstance(key, frozenset):
            items = tuple(key)
        elif isinstance(key, (tuple, list)):
            items = tuple(key)
        else:
            return None
        if len(items) != 2 or not all(isinstance(x, str) and x for x in items):
            return None
        a, b = items[0], items[1]
        if a == b:
            return None
        return frozenset((a, b))

    def _normalize_combos(self, combos: object) -> Dict[frozenset, dict]:
        """组合表归一（工程补白 U-C1）：dict（pair→{output, condition}）或
        list（[{a,b,output,condition},...]）→ frozenset(2)→dict。非法条目跳过（防御）。"""
        out: Dict[frozenset, dict] = {}
        if isinstance(combos, Mapping):
            for key, val in combos.items():
                if not isinstance(val, Mapping):
                    continue
                pair = self._pair_from_key(key)
                if pair is None:
                    continue
                raw_cond = val.get("condition")
                out[pair] = {
                    "output": str(val.get("output", "")),
                    "condition": dict(raw_cond) if isinstance(raw_cond, Mapping) else None,
                }
        elif isinstance(combos, (list, tuple)):
            for e in combos:
                if not isinstance(e, Mapping):
                    continue
                a, b = e.get("a"), e.get("b")
                if not (isinstance(a, str) and isinstance(b, str) and a and b and a != b):
                    continue
                raw_cond = e.get("condition")
                out[frozenset((a, b))] = {
                    "output": str(e.get("output", "")),
                    "condition": dict(raw_cond) if isinstance(raw_cond, Mapping) else None,
                }
        return out

    def _combo_lookup(self, a: str, b: str) -> Optional[dict]:
        """组合表命中：{output, condition} 或 None（未命中，F-12 GU-39）。"""
        return self._combos.get(frozenset((a, b)))

    # ------------------------------------------------------------------
    # 工具：注册表 / 货币 / 费率
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_item(item_id: object, ctx: Mapping[str, Any]) -> Optional[Mapping]:
        """物品注册表解析：ctx["items"] dict 或 ctx["resolve_item"] 解析器；查无 → None。"""
        if not isinstance(item_id, str):
            return None
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

    @staticmethod
    def _resolve_trait(trait_id: object, ctx: Mapping[str, Any]) -> Optional[Mapping]:
        """特性注册表解析：ctx["traits"] dict 或 ctx["resolve_trait"] 解析器（U-T4）。"""
        if not isinstance(trait_id, str):
            return None
        traits = ctx.get("traits")
        if isinstance(traits, Mapping):
            hit = traits.get(trait_id)
            if isinstance(hit, Mapping):
                return hit
        resolver = ctx.get("resolve_trait")
        if callable(resolver):
            try:
                hit = resolver(trait_id)
            except Exception:
                hit = None
            if isinstance(hit, Mapping):
                return hit
        return None

    @staticmethod
    def _item_name(item_id: str, ctx: Mapping[str, Any]) -> str:
        """物品名：注册表 name 字段；查无 → 原 id（对齐 shop._item_name）。"""
        item = UpgradeEngine._resolve_item(item_id, ctx)
        if item is not None:
            name = item.get("name")
            if isinstance(name, str) and name:
                return name
        return item_id

    @staticmethod
    def _trait_name(trait_id: str, ctx: Mapping[str, Any]) -> str:
        """特性名：注册表 name 字段；查无 → 原 id。"""
        tdef = UpgradeEngine._resolve_trait(trait_id, ctx)
        if tdef is not None:
            name = tdef.get("name")
            if isinstance(name, str) and name:
                return name
        return trait_id

    @staticmethod
    def _currencies(ctx: Mapping[str, Any]) -> Optional[MutableMapping]:
        """玩家货币表：ctx["currencies"]（就地扣减/累加，hook 模式）。"""
        cur = ctx.get("currencies")
        return cur if isinstance(cur, MutableMapping) else None

    def _gem_cost(self, key: str) -> int:
        """gem 费率读取：settings.alchemy 段覆盖，缺省 DEFAULT_GEM_COST（对齐批0 settings）。"""
        v = self._settings.get(key)
        iv = _as_int(v)
        if iv is not None and iv >= 0:
            return iv
        return DEFAULT_GEM_COST[key]

    # ------------------------------------------------------------------
    # 通用校验（全量满足才执行，否则全拒+差异提示，BATCH-06.3）
    # ------------------------------------------------------------------
    def _held_count(self, item_id: str, ctx: Mapping[str, Any]) -> int:
        """背包持有数：ctx["count_item"] hook 优先，兜底 ctx["inventory"] dict（防御）。"""
        count_item = ctx.get("count_item")
        if callable(count_item):
            try:
                v = count_item(item_id)
                iv = _as_int(v)
                if iv is not None:
                    return max(0, iv)
            except Exception:
                pass
        inv = ctx.get("inventory")
        if isinstance(inv, Mapping):
            iv = _as_int(inv.get(item_id, 0))
            if iv is not None:
                return max(0, iv)
        return 0

    def _input_diffs(self, ctx: Mapping[str, Any], cfg: Mapping) -> List[str]:
        """输入持有差异清单：{item,count} 全量校验，不足项给差异提示（BATCH-06.3 全拒+差异）。"""
        diffs: List[str] = []
        for e in cfg.get("inputs", []):
            item = e.get("item")
            need = e.get("count", 1)
            held = self._held_count(item, ctx)
            if held < need:
                diffs.append(
                    f"缺少 {self._item_name(item, ctx)} ×{need - held}"
                    f"（持有 {held}，需 {need}）"
                )
        return diffs

    def _cost_diff(self, ctx: Mapping[str, Any], cfg: Mapping) -> Optional[str]:
        """cost{coins,gem} 全量校验：不足 → 差异提示串；货币表缺失 → 差异（防御）。"""
        cur = self._currencies(ctx)
        if cur is None:
            return "货币表缺失"
        cost = cfg.get("cost") or {}
        coins = cost.get("coins", 0) or 0
        gem = cost.get("gem", 0) or 0
        diffs: List[str] = []
        if coins > 0:
            held = _as_int(cur.get("coins", 0))
            held = held if held is not None else 0
            if held < coins:
                diffs.append(f"金币 ×{coins - held}（持有 {held}，需 {coins}）")
        if gem > 0:
            held = _as_int(cur.get("gem", 0))
            held = held if held is not None else 0
            if held < gem:
                diffs.append(f"宝石 ×{gem - held}（持有 {held}，需 {gem}）")
        if diffs:
            return "、".join(diffs)
        return None

    @staticmethod
    def _reject(reason: str, message: str) -> dict:
        """拒绝结果（零副作用）。"""
        return {
            "ok": False,
            "reason": reason,
            "message": message,
            "consumed": {},
            "produced": None,
        }

    # ------------------------------------------------------------------
    # 原子提交（U-A1：两段式 + 进程内 best-effort 回滚）
    # ------------------------------------------------------------------
    def _commit(
        self,
        ctx: MutableMapping[str, Any],
        *,
        removals: Sequence[Tuple[str, int]],
        currency_delta: Mapping[str, int],
        add_item: Optional[Tuple[str, int, bool]] = None,
        unlock_recipe: Optional[str] = None,
        traits: Optional[Mapping[str, Any]] = None,
    ) -> Optional[dict]:
        """原子提交（工程补白 U-A1）：扣货币 → 扣输入 → 产出/解锁/落位。

        - removals：[(item_id, count)] 背包扣除（remove_item hook）。
        - currency_delta：{币键: 增量}（负=扣，正=加）。
        - add_item：(item_id, count, bound) 产出入包（add_item hook）。
        - unlock_recipe：配方合成 → 写 ctx["upgrade_unlocks"]（U-F2）。
        - traits：{"remove": [trait_id...], "add": trait_id} → 操作 ctx["target_traits"]（U-T1）。
        返回 None 成功；失败 → 回滚后返回拒绝 dict。
        """
        snap_cur: Optional[Dict[str, Any]] = None
        cur = self._currencies(ctx)
        if cur is not None:
            snap_cur = dict(cur)
        snap_inv: Optional[Dict[str, Any]] = None
        inv = ctx.get("inventory")
        if isinstance(inv, MutableMapping):
            snap_inv = dict(inv)
        snap_unlocks: Optional[Dict[str, Any]] = None
        unlocks = ctx.get("upgrade_unlocks")
        if isinstance(unlocks, MutableMapping):
            snap_unlocks = dict(unlocks)
        snap_target: Optional[List[Any]] = None
        target = ctx.get("target_traits")
        if isinstance(target, list):
            snap_target = list(target)

        try:
            # 1) 货币扣减/累加（就地）
            if cur is not None:
                for key, delta in currency_delta.items():
                    if not delta:
                        continue
                    cur[key] = int(cur.get(key, 0) or 0) + delta
            # 2) 输入扣除
            remove_item = ctx.get("remove_item")
            for item_id, count in removals:
                if callable(remove_item):
                    try:
                        if remove_item(item_id, count) is False:
                            raise _CommitFailed("remove_item_failed")
                    except Exception:
                        raise _CommitFailed("remove_item_failed") from None
            # 3) 产出入包
            if add_item is not None:
                add = ctx.get("add_item")
                if not callable(add):
                    raise _CommitFailed("add_item_hook_missing")
                try:
                    if add(add_item[0], add_item[1], add_item[2]) is False:
                        raise _CommitFailed("add_item_failed")
                except Exception:
                    raise _CommitFailed("add_item_failed") from None
            # 4) 配方合成永久解锁（U-F2）
            if unlock_recipe:
                bucket = ctx.setdefault("upgrade_unlocks", {})
                bucket[unlock_recipe] = {
                    "source": _UNLOCK_SOURCE_FORMULA,
                    "gem_cost": -(currency_delta.get("gem", 0) or 0),
                }
            # 5) 特性落位（U-T1：移除两输入特性 + 落位产出特性）
            if traits is not None and isinstance(target, list):
                for tid in traits.get("remove", []):
                    if tid in target:
                        target.remove(tid)
                add_trait = traits.get("add")
                if isinstance(add_trait, str):
                    target.append(add_trait)
        except _CommitFailed as exc:
            self._rollback(ctx, snap_cur, snap_inv, snap_unlocks, snap_target)
            return self._reject(
                exc.reason,
                f"❌ 合成执行失败（{exc.reason}），已回滚",
            )
        return None

    @staticmethod
    def _rollback(
        ctx: MutableMapping[str, Any],
        snap_cur: Optional[Dict[str, Any]],
        snap_inv: Optional[Dict[str, Any]],
        snap_unlocks: Optional[Dict[str, Any]],
        snap_target: Optional[List[Any]],
    ) -> None:
        """进程内回滚（U-A1 best-effort）：恢复货币/背包/解锁表/落位列表快照。"""
        if snap_cur is not None:
            cur = ctx.get("currencies")
            if isinstance(cur, MutableMapping):
                cur.clear()
                cur.update(snap_cur)
        if snap_inv is not None:
            inv = ctx.get("inventory")
            if isinstance(inv, MutableMapping):
                inv.clear()
                inv.update(snap_inv)
        if snap_unlocks is not None:
            bucket = ctx.get("upgrade_unlocks")
            if isinstance(bucket, MutableMapping):
                bucket.clear()
                bucket.update(snap_unlocks)
        if snap_target is not None and isinstance(ctx.get("target_traits"), list):
            target = ctx["target_traits"]
            target.clear()
            target.extend(snap_target)

    # ------------------------------------------------------------------
    # 主入口（kind=upgrade 通用执行器）
    # ------------------------------------------------------------------
    def execute(
        self,
        ctx: MutableMapping[str, Any],
        recipe_def: object,
        input_ids: Optional[Sequence[str]] = None,
    ) -> dict:
        """升级合成通用执行器（批2 路2B）——按配置实例分发。

        入参：
          - ctx：玩家上下文（hook 模式：items/currencies/count_item/remove_item/add_item/
            traits/target_traits/upgrade_unlocks）。
          - recipe_def：recipe.json kind=upgrade 条目或已解析配置 dict。
          - input_ids：调用方选定的具体输入 id 列表（特性合成 = 2 个被选特性 id；
            珠升阶/成品合成/配方合成为背包计数口径，预留）。
        出参：{ok, message, consumed, produced, [reason], [already]}
          - consumed：实际消耗（inputs 物品/cost 货币/traits 特性）。
          - produced：{"item":..., "count":...} / {"trait":...} / {"recipe":...} / None。
        核心：校验 kind=upgrade → 实例校验（条件）→ 原子提交 → 合成结果文案。
        """
        cfg = self.resolve_upgrade_recipe(recipe_def)
        if cfg is None or cfg["kind"] != "upgrade":
            return self._reject("not_upgrade", "❌ 该配方不是升级合成")
        subtype = cfg["subtype"]
        if subtype == "jewel_upgrade":
            return self._exec_jewel(ctx, cfg, input_ids)
        if subtype == "product_merge":
            return self._exec_product(ctx, cfg)
        if subtype == "formula_merge":
            return self._exec_formula(ctx, cfg)
        if subtype == "trait_merge":
            return self._exec_trait(ctx, cfg, input_ids)
        return self._reject("unknown_subtype", f"❌ 未知升级子类型：{subtype}")

    # ------------------------------------------------------------------
    # 配置实例 1：珠三合一升阶（3×同档同 ID+宝石10→+1 阶，禁跳级，拍板③）
    # ------------------------------------------------------------------
    def _exec_jewel(
        self,
        ctx: MutableMapping[str, Any],
        cfg: Mapping,
        input_ids: Optional[Sequence[str]] = None,
    ) -> dict:
        """珠三合一升阶（批2 路2B / U-J1/U-J2）。

        校验：恰 1 输入条目且 count≥3（3× 同档同 ID）→ 持有全量 → 宝石全量 → 档位联动
              （产出档位序号 == 输入档位序号+1，禁跳级）。无职业硬门槛（拍板③：准入靠槽级
              SOCK-02，引擎不设职业门槛）。
        """
        inputs = cfg.get("inputs") or []
        if len(inputs) != 1:
            return self._reject("jewel_input_shape", "❌ 珠升阶必须 3 个同档同 ID 装饰珠")
        entry = inputs[0]
        item_id = entry["item"]
        need = entry["count"]
        if need < 3:
            return self._reject("jewel_input_count", "❌ 珠升阶需要 3 个同档同 ID 装饰珠")
        # U-J2 防御：input_ids 若传则必须全等于配方输入 item
        if input_ids:
            if any(x != item_id for x in input_ids):
                return self._reject("jewel_input_mismatch", "❌ 所选装饰珠与配方输入不符")
        # 持有全量（BATCH-06.3 差异）
        diffs = self._input_diffs(ctx, cfg)
        if diffs:
            return self._reject("inputs_insufficient", "❌ 材料不足：" + "、".join(diffs))
        # 宝石全量
        cdiff = self._cost_diff(ctx, cfg)
        if cdiff is not None:
            return self._reject("cost_insufficient", "❌ 资源不足：" + cdiff)
        # 档位联动 + 禁跳级（U-J1）
        in_tier = self._jewel_tier_of(item_id, ctx, cfg)
        out_item = cfg["output"]["item"]
        out_tier = self._jewel_tier_of(out_item, ctx, cfg)
        if in_tier is not None and out_tier is not None:
            expected = self.quality.index_to_tier(self.quality.tier_index(in_tier) + 1)
            if out_tier != expected:
                return self._reject(
                    "jewel_skip_tier",
                    f"❌ 禁跳级：{self._item_name(item_id, ctx)} 只能升到"
                    f" {self.quality.tier_label(expected)} 阶（禁止跨阶）",
                )
        # 原子提交（U-A1）
        gem = cfg["cost"].get("gem", 0)
        out_count = cfg["output"]["count"]
        err = self._commit(
            ctx,
            removals=[(item_id, need)],
            currency_delta={"gem": -gem},
            add_item=(out_item, out_count, True),
        )
        if err is not None:
            return err
        return {
            "ok": True,
            "message": f"✅ {self._item_name(out_item, ctx)} 合成成功（消耗 宝石×{gem}）",
            "consumed": {
                "inputs": [{"item": item_id, "count": need}],
                "cost": {"coins": 0, "gem": gem},
                "traits": [],
            },
            "produced": {"item": out_item, "count": out_count},
        }

    def _jewel_tier_of(self, item_id: str, ctx: Mapping[str, Any], cfg: Mapping) -> Optional[str]:
        """珠档位解析（工程补白 U-J1）：item def `quality`（合法档位键）/ `tier`（序号）→
        配方显式 `jewel_tier` → 均无 → None（档位联动无法核验，数据直通）。"""
        item = self._resolve_item(item_id, ctx)
        if item is not None:
            q = item.get("quality")
            if isinstance(q, str) and q in _QUALITY_KEYS:
                return q
            t = _as_int(item.get("tier"))
            if t is not None and t >= 0:
                return self.quality.index_to_tier(t)
        jt = cfg.get("jewel_tier")
        if isinstance(jt, str) and jt in _QUALITY_KEYS:
            return jt
        return None

    # ------------------------------------------------------------------
    # 配置实例 2：成品合成（两成品+材料+宝石10→更强成品，原子提交 F-09）
    # ------------------------------------------------------------------
    def _exec_product(
        self,
        ctx: MutableMapping[str, Any],
        cfg: Mapping,
    ) -> dict:
        """成品合成（F-09 / M-09）：inputs=两成品(+材料) 全量持有 + cost 宝石10+材料 →
        原子提交 → 产出更强成品（output 1 出）。"""
        diffs = self._input_diffs(ctx, cfg)
        if diffs:
            return self._reject("inputs_insufficient", "❌ 材料不足：" + "、".join(diffs))
        cdiff = self._cost_diff(ctx, cfg)
        if cdiff is not None:
            return self._reject("cost_insufficient", "❌ 资源不足：" + cdiff)
        gem = cfg["cost"].get("gem", 0)
        out_item = cfg["output"]["item"]
        out_count = cfg["output"]["count"]
        err = self._commit(
            ctx,
            removals=[(e["item"], e["count"]) for e in cfg.get("inputs", [])],
            currency_delta={"gem": -gem},
            add_item=(out_item, out_count, True),
        )
        if err is not None:
            return err
        return {
            "ok": True,
            "message": f"✅ {self._item_name(out_item, ctx)} 合成成功（消耗 宝石×{gem}）",
            "consumed": {
                "inputs": [dict(e) for e in cfg.get("inputs", [])],
                "cost": {"coins": 0, "gem": gem},
                "traits": [],
            },
            "produced": {"item": out_item, "count": out_count},
        }

    # ------------------------------------------------------------------
    # 配置实例 3：配方合成（两已学配方+宝石5→永久解锁，组合表 F-12 / ATO-05）
    # ------------------------------------------------------------------
    def _exec_formula(
        self,
        ctx: MutableMapping[str, Any],
        cfg: Mapping,
    ) -> dict:
        """配方合成（F-12 / M-12 / ATO-05）：combine_from 两已学配方（GU-38）→ 组合表命中
        （GU-39）→ 永久解锁新配方；重复合成已解锁 → 提示已解锁不重复扣宝石（ATO-05 幂等）。"""
        cf = cfg.get("combine_from") or []
        if len(cf) != 2:
            return self._reject("formula_input_shape", "❌ 配方合成需要两个已学配方")
        a, b = cf[0], cf[1]
        # GU-38 两配方均已学（U-F3：ctx["upgrade_unlocks"] 键集合）
        unlocks = ctx.get("upgrade_unlocks")
        if not isinstance(unlocks, MutableMapping):
            unlocks = {}
        if a not in unlocks or b not in unlocks:
            missing = [x for x in (a, b) if x not in unlocks]
            return self._reject(
                "formula_not_learned",
                "❌ 配方未全部习得：" + "、".join(missing),
            )
        # GU-39 组合表命中（U-F1：combos 优先，recipe output 兜底）
        combo = self._combo_lookup(a, b)
        if combo is None or not combo.get("output"):
            out = cfg.get("output")
            if out is None or not out.get("item"):
                return self._reject(
                    "formula_no_combo",
                    f"❌ 「{a}」+「{b}」没有已知组合",
                )
            out_recipe = out["item"]
        else:
            out_recipe = combo["output"]
        # ATO-05 幂等：已解锁 → 提示已解锁，不重复扣宝石
        if out_recipe in unlocks:
            return {
                "ok": True,
                "already": True,
                "message": f"✅ 配方「{out_recipe}」已解锁，无需重复合成",
                "consumed": {},
                "produced": {"recipe": out_recipe},
            }
        # 宝石全量（gem.配方合成=5）
        cdiff = self._cost_diff(ctx, cfg)
        if cdiff is not None:
            return self._reject("cost_insufficient", "❌ 资源不足：" + cdiff)
        gem = cfg["cost"].get("gem", 0)
        err = self._commit(
            ctx,
            removals=[],
            currency_delta={"gem": -gem},
            unlock_recipe=out_recipe,
        )
        if err is not None:
            return err
        return {
            "ok": True,
            "message": f"✅ 解锁新配方：〈{out_recipe}〉（消耗 宝石×{gem}）",
            "consumed": {
                "inputs": [],
                "cost": {"coins": 0, "gem": gem},
                "traits": [],
            },
            "produced": {"recipe": out_recipe},
        }

    # ------------------------------------------------------------------
    # 配置实例 4：特性合成（两同系特性+宝石20+材料→更高位特性，F-13 / TSC-15~18）
    # ------------------------------------------------------------------
    def _exec_trait(
        self,
        ctx: MutableMapping[str, Any],
        cfg: Mapping,
        input_ids: Optional[Sequence[str]] = None,
    ) -> dict:
        """特性合成（F-13 / TSC-15~18 / M-13）：input_ids=2 同系特性（GU-42）→ 材料持有 →
        宝石20 → 产出更高位特性（U-T3）→ 产出落位复核 group 互斥组与 repeatable（F-13）。"""
        if input_ids is None or len(input_ids) != 2:
            return self._reject("trait_input_shape", "❌ 特性合成需要两个同系特性")
        ta, tb = input_ids[0], input_ids[1]
        # 同系校验（GU-42 / U-T2）
        same, family = self._same_family(ta, tb, ctx, cfg)
        if not same:
            return self._reject("trait_not_same_family", "❌ 非同系特性，无法合成")
        # 材料持有全量（recipe inputs = 材料）
        diffs = self._input_diffs(ctx, cfg)
        if diffs:
            return self._reject("inputs_insufficient", "❌ 材料不足：" + "、".join(diffs))
        # 宝石全量（gem.特性合成=20）
        cdiff = self._cost_diff(ctx, cfg)
        if cdiff is not None:
            return self._reject("cost_insufficient", "❌ 资源不足：" + cdiff)
        # 产出确定（U-T3：combos 优先，recipe output 兜底）
        combo = self._combo_lookup(ta, tb)
        if combo is not None and combo.get("output"):
            out_trait = combo["output"]
        else:
            out = cfg.get("output")
            if out is None or not out.get("item"):
                return self._reject("trait_no_output", "❌ 该组合没有更高位特性产出")
            out_trait = out["item"]
        # 产出落位复核（F-13：group 互斥组 + repeatable；U-T1）
        # 排除本次消耗的两输入特性（TSC-17 原两条特性被消耗，不参与互斥复核）
        target = ctx.get("target_traits")
        conflict = self._placement_conflict(out_trait, target, ctx, exclude={ta, tb})
        if conflict is not None:
            return self._reject("trait_group_conflict", conflict)
        # 原子提交：扣材料+宝石，消耗两输入特性并落位产出（TSC-17 原两条特性被消耗）
        gem = cfg["cost"].get("gem", 0)
        err = self._commit(
            ctx,
            removals=[(e["item"], e["count"]) for e in cfg.get("inputs", [])],
            currency_delta={"gem": -gem},
            traits={"remove": [ta, tb], "add": out_trait},
        )
        if err is not None:
            return err
        return {
            "ok": True,
            "message": f"✅ {self._trait_name(out_trait, ctx)}（更高位特性，消耗 宝石×{gem}）",
            "consumed": {
                "inputs": [dict(e) for e in cfg.get("inputs", [])],
                "cost": {"coins": 0, "gem": gem},
                "traits": [ta, tb],
            },
            "produced": {"trait": out_trait},
        }

    def _same_family(
        self,
        ta: str,
        tb: str,
        ctx: Mapping[str, Any],
        cfg: Mapping,
    ) -> Tuple[bool, Optional[str]]:
        """同系判定（工程补白 U-T2）：condition.same_family 显式系名 → 两特性均属该系
        （family==系名 或 group 以系名前缀）；否则 group 相同即同系；再否则 family 相同即同系。"""
        condition = cfg.get("condition") or {}
        explicit = condition.get("same_family")

        def _family_group(tid: str) -> Tuple[Optional[str], Optional[str]]:
            tdef = self._resolve_trait(tid, ctx)
            if tdef is None:
                return None, None
            fam = tdef.get("family")
            grp = tdef.get("group")
            fam_s = str(fam) if isinstance(fam, str) and fam else None
            grp_s = str(grp) if isinstance(grp, str) and grp else None
            return fam_s, grp_s

        fam_a, grp_a = _family_group(ta)
        fam_b, grp_b = _family_group(tb)
        if explicit:
            ef = str(explicit)

            def _in_fam(f: Optional[str]) -> bool:
                return f is not None and (f == ef or f.startswith(ef + "_"))

            def _in_grp(g: Optional[str]) -> bool:
                return g is not None and (g == ef or g.startswith(ef + "_"))

            if (_in_fam(fam_a) or _in_grp(grp_a)) and (_in_fam(fam_b) or _in_grp(grp_b)):
                return True, ef
            return False, ef
        if grp_a is not None and grp_a == grp_b:
            return True, grp_a
        if fam_a is not None and fam_a == fam_b:
            return True, fam_a
        return False, None

    @staticmethod
    def _placement_conflict(
        out_trait: str,
        target: object,
        ctx: Mapping[str, Any],
        exclude: Optional[set] = None,
    ) -> Optional[str]:
        """产出落位复核（F-13 / U-T1）：产出特性非 repeatable 且与成品已带同组特性 →
        互斥组冲突拒绝（exclude = 本次消耗的两输入特性，TSC-17 已移除不参与互斥）；
        repeatable / 无目标 / 注册表缺失 → 通过（None）。"""
        out_def = UpgradeEngine._resolve_trait(out_trait, ctx)
        if out_def is None:
            return None
        out_group = out_def.get("group")
        if not isinstance(out_group, str) or not out_group:
            return None
        if out_def.get("repeatable") is True:
            return None
        if not isinstance(target, (list, tuple)):
            return None
        excluded = exclude or set()
        for tid in target:
            if tid in excluded:
                continue
            tdef = UpgradeEngine._resolve_trait(tid, ctx)
            if tdef is not None and tdef.get("group") == out_group:
                return (
                    f"❌ 产出特性与成品已带同组特性"
                    f"「{tdef.get('name', tid)}」冲突（互斥组，不可共存）"
                )
        return None
