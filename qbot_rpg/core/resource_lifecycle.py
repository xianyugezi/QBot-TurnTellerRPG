"""6c 资源轴回合结清与生命周期引擎（M13 批8·路8C）——F-R1 各时点增减·保留·清零。

文件：qbot_rpg/core/resource_lifecycle.py
创建：2026-09-02
作者：Hermes 子agent（路8C）

功能：按《细化_6c_资源轴与职业机制.md》§1.3 机制 M3 · 流程 F-R1 实现资源轴
      战斗生命周期纯函数引擎：
  - tick_round_end：回合结束结清（当前契约仅保留——本引擎零定时器/零睡眠，
    契约未定义任何「每回合自动衰减」字段，故回合结束不增减任何资源；提供
    钩子签名以便契约后续扩展每回合变化时挂载，现行为=保留）
  - battle_end_reset：战斗结束按 reset 策略三枚举清零/保留（battle→清零 /
    keep→跨战斗保留 / battle_start→下次战斗开始重置为 base）
  - battle_start_init：战斗开始初始化（数值型置 base；子池型各池置 base）
  - apply_gain：成功结算后 energy_gain 追加（与 mark_add 同拍：命中判定后/
    结算末尾），追加后封顶（数值型 ≤ max / 子池型每池 ≤ max_per_pool，
    超出部分不累计、不回滚）——0 值无操作（D-06）
  - try_apply_cost：施放前 energy_cost 检查并消耗（不足 → 被拒不耗回合：
    不增减、返回 False 可反复尝试；0 值无操作 D-06）
  - is_controlled_preserved：被控 skip_turn 保留判定（被控期间资源不增不减
    天然保留，本引擎显式声明该契约行为并返回 True）
  - 快照/恢复：snapshot_resource_state（数值型单键 / 子池型池级展开 D-04）
    + restore_resource_state（中断恢复还原；已删注册 → 字段缺失降级不报错，
    RS-5）；restore 前按 reset 策略应用战斗开始重置（battle_start 型每场战斗
    开始重置为 base，RS-2 口径）

依据：
  - docs/细化/细化_6c_资源轴与职业机制.md §1.3（F-R1 全时序）/ §1.4（RS-1~6）/
    D-02（多重集门）/ D-03（触发类不足不生效不耗不计上限）/ D-04（池级展开）/
    D-06（0=无操作）
  - docs/m13_6c摸底.md §八 批8 路8C（resource_state 快照 + _settle reset 策略）
  - 模式参考 qbot_rpg/core/transform_revert.py（纯函数 tick/清零/快照段携带）；
    qbot_rpg/core/energy_bar.py（构造器配置注入 + 缺省默认值兜底；零 NoneBot）

【工程补白 · 显式标注】（定稿未给口径处，本引擎最小必要推导，不新增定稿外行为）：
  E-1  注册段归一：type ∈ {resource, resource_custom}（D-01b 兼容别名归一）；
       reset 缺省 battle【资源轴 L48/L34】；max 缺省 100（0=不限）【资源轴 L47】。
  E-2  `any` 键消费 = 任意池通用门（D-02 总量门）：逐池扣减（先可扣池序），
       扣不足（任一键不足）→ 整体回滚、判定被拒（原子性，对齐 D-03 精神）。
       组合行多重集匹配（F-C1③）属批10 组合引擎，本引擎只消费池级键。
  E-3  被控保留 = 引擎不调用任何增减即保留（S4）；skip 判定钩子
       is_controlled_preserved 供装配层显式声明契约行为，不改变任何状态。
  E-4  战斗结束 reset 清零仅作用于 resource_state 段内注册的轴（battle 型）；
       keep 型跨战斗保留并随快照/存档携带（RS-3 存档落点由装配层消费）。
  E-5  快照恢复原子性：先整体恢复 resource_state，再对 battle_start 型轴
       应用战斗开始重置（RS-2 恢复语义 + F-R1 战斗开始置 base 合并口径）；
       已删注册轴 → 恢复时字段缺失降级（RS-5，不报错不悬空）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；零定时器/零睡眠；不抛异常
      （配置缺省兜底、方法防御降级）；工程补白显式标注。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple, cast

__all__ = [
    "DEFAULT_RESET",
    "DEFAULT_MAX",
    "RESET_BATTLE",
    "RESET_KEEP",
    "RESET_BATTLE_START",
    "ResourceLifecycle",
]


# reset 策略三枚举（【资源轴 L48/L51-55】；V4 枚举红拦）
RESET_BATTLE: str = "battle"
RESET_KEEP: str = "keep"
RESET_BATTLE_START: str = "battle_start"

# 缺省值（E-1：【资源轴 L47-48】max 缺省 100=不限 / reset 缺省 battle）
DEFAULT_RESET: str = RESET_BATTLE
DEFAULT_MAX: int = 100

# resource_state 段键名（细化_6c §1.4；1g3 快照容器顶层段）
RESOURCE_STATE_KEY: str = "resource_state"

# 子池型 type 兼容别名（D-01b 归一）
_RESOURCE_CUSTOM_ALIAS: Tuple[str, ...] = ("resource", "resource_custom")


class ResourceLifecycle:
    """6c 资源轴回合结清与生命周期引擎（细化_6c §1.3 机制 M3 · 流程 F-R1）。

    构造器注入注册表（stats.json 资源轴注册段：轴 ID → 注册 dict），
    缺省 {} 兜底（无注册 → 所有方法零操作降级）。操作对象为战斗快照
    （battle_state dict）与持久状态（keep 型落点），纯函数零 IO 零
    NoneBot，不抛异常。供批8A 注册段 / 批8B energy 运行时接线复用。
    """

    def __init__(self, registry: Optional[Mapping[str, Any]] = None) -> None:
        """构造生命周期引擎（注册表注入 + 缺省 {} 兜底）。

        registry：stats.json 资源轴注册段映射（轴 ID → 注册 dict，含
        type/base/max/reset/pools/max_per_pool 等字段）；None/缺省 → {}。
        """
        self._registry: Mapping[str, Any] = (
            registry if isinstance(registry, Mapping) else {}
        )

    # ------------------------- 注册段口径 -------------------------

    def axis_def(self, axis_id: str) -> Mapping[str, Any]:
        """取轴注册定义（缺省 {} 兜底，不抛异常）。"""
        raw = self._registry.get(axis_id)
        return raw if isinstance(raw, Mapping) else {}

    def is_pool_axis(self, axis_id: str) -> bool:
        """子池型判别（D-01：注册段含 pools 字段 = 子池型）。"""
        pools = self.axis_def(axis_id).get("pools")
        return isinstance(pools, (list, tuple)) and len(pools) > 0

    def pools_of(self, axis_id: str) -> List[str]:
        """子池型池枚举（非子池型 → 空列表）。"""
        pools = self.axis_def(axis_id).get("pools")
        if isinstance(pools, (list, tuple)):
            return [str(p) for p in pools]
        return []

    def reset_policy(self, axis_id: str) -> str:
        """清零策略（缺省 battle，E-1）。"""
        reset = self.axis_def(axis_id).get("reset", DEFAULT_RESET)
        if reset not in (RESET_BATTLE, RESET_KEEP, RESET_BATTLE_START):
            return DEFAULT_RESET
        return str(reset)

    def _max_of(self, axis_id: str) -> int:
        """数值型上限（缺省 100；0 = 不限）。"""
        try:
            return max(0, int(self.axis_def(axis_id).get("max", DEFAULT_MAX)))
        except (TypeError, ValueError):
            return DEFAULT_MAX

    def _pool_max_of(self, axis_id: str) -> int:
        """子池型每池上限（缺省 1；0 = 不限）。"""
        try:
            return max(0, int(self.axis_def(axis_id).get("max_per_pool", 1)))
        except (TypeError, ValueError):
            return 1

    def _base_of(self, axis_id: str) -> int:
        """初始值 base（缺省 0；负数钳制 0）。"""
        try:
            return max(0, int(self.axis_def(axis_id).get("base", 0)))
        except (TypeError, ValueError):
            return 0

    # ------------------------- 状态定位 -------------------------

    def resource_state(self, battle_state: Mapping[str, Any]) -> MutableMapping[str, Any]:
        """定位 resource_state 段（缺段 → 按 per-side 惯例惰性建段）。

        返回的 dict 直接挂在 battle_state 上（就地读写），缺省结构：
        {"player": {}, "enemy": {}}。battle_state 非 Mapping → 返回空 dict
        （防御降级，不抛异常）。
        """
        if not isinstance(battle_state, Mapping):
            return {}
        rs = battle_state.get(RESOURCE_STATE_KEY)
        if not isinstance(rs, MutableMapping):
            rs = {}
            battle_state[RESOURCE_STATE_KEY] = rs  # type: ignore[index]
        for side in ("player", "enemy"):
            if not isinstance(rs.get(side), MutableMapping):
                rs[side] = {}
        return rs

    def _side_state(
        self, battle_state: MutableMapping[str, Any], side: str
    ) -> MutableMapping[str, Any]:
        rs = self.resource_state(battle_state)
        side_state = rs.get(side)
        if not isinstance(side_state, MutableMapping):
            side_state = {}
            rs[side] = side_state
        return side_state

    # ------------------------- 战斗开始（F-R1 首行） -------------------------

    def battle_start_init(
        self,
        battle_state: MutableMapping[str, Any],
        side: str,
        axis_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """战斗开始初始化：数值型置 base / 子池型各池置 base（F-R1 首行）。

        对指定轴（缺省 = 注册表全部轴）写入 base 值（覆盖战斗开始前残留值，
        对齐【资源轴 L32/L46】）。返回写入后的该侧 resource_state（就地改写）。
        """
        side_state = self._side_state(battle_state, side)
        for axis_id in self._iter_axis_ids(axis_ids):
            base = self._base_of(axis_id)
            if self.is_pool_axis(axis_id):
                side_state[axis_id] = {
                    pool: base for pool in self.pools_of(axis_id)
                }
            else:
                side_state[axis_id] = base
        return dict(side_state)

    # ------------------------- 成功结算后追加（F-R1 命中判定后） -------------------------

    def apply_gain(
        self,
        battle_state: MutableMapping[str, Any],
        side: str,
        gains: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """energy_gain 追加（成功结算时，与 mark_add 同拍：命中判定后/结算末尾）。

        - 数值型键：axis_id → 当前值 + n，封顶 ≤ max（0=不限）（F-R1 封顶段）；
        - 子池型键：pool 名 → 该池 + n，封顶 ≤ max_per_pool（超出不累计不回滚）；
        - 0 值无操作（D-06）；未知键防御跳过（校验器 V1 红拦在加载期拦截）；
        - 已删注册轴 → 降级跳过（RS-5 精神，不报错）。
        返回该侧 resource_state（就地改写）。
        """
        side_state = self._side_state(battle_state, side)
        for key, raw in (gains or {}).items():
            if not isinstance(key, str) or key == "any":
                continue  # any 键仅 energy_cost 消费（E-2）
            n = self._int_or_none(raw)
            if n is None or n == 0:
                continue  # D-06：0=无操作；非数值防御跳过
            axis_id, pool = self._resolve_key(key)
            if axis_id is None:
                continue  # 未注册轴 → 降级跳过（RS-5）
            if pool is not None:
                self._gain_pool(side_state, axis_id, pool, n)
            else:
                self._gain_scalar(side_state, axis_id, n)
        return dict(side_state)

    def _gain_scalar(
        self, side_state: MutableMapping[str, Any], axis_id: str, n: int
    ) -> None:
        cur = self._int_or_none(side_state.get(axis_id)) or 0
        cap = self._max_of(axis_id)
        nxt = cur + n
        if cap > 0 and nxt > cap:
            nxt = cap  # 封顶：超出部分不累计，不回滚
        side_state[axis_id] = nxt

    def _gain_pool(
        self, side_state: MutableMapping[str, Any], axis_id: str, pool: str, n: int
    ) -> None:
        pools_state = side_state.get(axis_id)
        if not isinstance(pools_state, MutableMapping):
            pools_state = {p: self._base_of(axis_id) for p in self.pools_of(axis_id)}
            side_state[axis_id] = pools_state
        if pool not in self.pools_of(axis_id):
            return  # 池名未注册 → 降级跳过（RS-5 / V1 红拦在加载期）
        cur = self._int_or_none(pools_state.get(pool)) or 0
        cap = self._pool_max_of(axis_id)
        nxt = cur + n
        if cap > 0 and nxt > cap:
            nxt = cap  # 每池封顶：超出不累计，不回滚
        pools_state[pool] = nxt

    # ------------------------- 施放前检查与消耗（F-R1 施放前段） -------------------------

    def try_apply_cost(
        self,
        battle_state: MutableMapping[str, Any],
        side: str,
        costs: Mapping[str, Any],
    ) -> bool:
        """energy_cost 施放前检查并消耗（不足 → 被拒不耗回合：不增减、返回 False）。

        - 数值型键：axis_id → 当前值 ≥ n 才扣；
        - 子池型键：pool 名 → 该池 ≥ n 才扣；`any` 键 = 总量门（D-02）：
          任意池组合可扣（先可扣池序逐池扣，扣不足 → 整体回滚、返回 False）；
        - 原子性：任一键不足 → 整体回滚（本方法先全量检查再全量扣减）；
        - 0 值无操作（D-06）返回 True（无需消耗）；未知键防御跳过（V1 加载期拦截）。
        返回是否成功扣减（True=已扣/无消耗；False=被拒，未扣任何资源）。
        """
        side_state = self._side_state(battle_state, side)
        cost_items = self._normalize_costs(costs)
        if not cost_items:
            return True  # 无消耗（D-06：0=无操作）
        # 原子性：先全量校验（含 any 分解），任一不足 → 整体被拒
        plan: List[Tuple[str, str, int]] = []  # (axis_id, pool|"", n)
        for axis_id, pool, n in cost_items:
            if n <= 0:
                continue
            if pool == "any":
                ok, sub = self._plan_any(side_state, axis_id, n)
                if not ok:
                    return False
                plan.extend(sub)
            else:
                cur = self._current_of(side_state, axis_id, pool)
                if cur < n:
                    return False  # 不足 → 被拒不耗回合（F-R1 / S4）
                plan.append((axis_id, pool, n))
        # 全量校验通过 → 实际扣减（先匹配后消耗，CM-2 精神）
        for axis_id, pool, n in plan:
            self._cost_scalar(side_state, axis_id, pool, n)
        return True

    def _normalize_costs(
        self, costs: Mapping[str, Any]
    ) -> List[Tuple[str, str, int]]:
        """归一 costs 映射为 (axis_id, pool|"", n) 列表（未知键防御跳过）。"""
        out: List[Tuple[str, str, int]] = []
        for key, raw in (costs or {}).items():
            if not isinstance(key, str):
                continue
            n = self._int_or_none(raw)
            if n is None:
                continue
            axis_id, pool = self._resolve_key(key)
            if axis_id is None:
                continue  # 未注册轴 → 降级跳过（RS-5 / V1 加载期红拦）
            out.append((axis_id, pool or "", n))
        return out

    def _resolve_key(self, key: str) -> Tuple[Optional[str], Optional[str]]:
        """键空间解析（K1/K2/D-01）：数值型=资源 ID；子池型=池名。

        返回 (axis_id, pool|None)；any 键 → (轴, "any")（由调用方按轴消费）；
        未注册/非法 → (None, None)。解析优先级：轴 ID（K1）> 池名（K2，
        所属轴=含该池的子池型轴）> 点分池级引用 [axis.pool]（D-04）。
        """
        if key == "any":
            # any 键须挂子池型轴：取唯一子池型轴消费（校验器 V7 已红拦
            # 数值型技能 any 键；此处防御取第一个子池型轴）
            for axis_id in self._registry:
                if self.is_pool_axis(axis_id):
                    return axis_id, "any"
            return None, None
        # K1：轴 ID 优先（数值型键；轴 ID 与池名冲突时轴 ID 优先，工程补白）
        if key in self._registry:
            return key, None
        # K2：池名键 → 所属子池型轴
        for axis_id in self._registry:
            if self.is_pool_axis(axis_id) and key in self.pools_of(axis_id):
                return axis_id, key
        # D-04：点分池级引用 [axis.pool]
        axis_id, _, pool = key.partition(".")
        if axis_id in self._registry and pool:
            if self.is_pool_axis(axis_id) and pool in self.pools_of(axis_id):
                return axis_id, pool
            return None, None  # 数值型轴带点分 / 非法池名 → 跳过
        return None, None

    def _plan_any(
        self, side_state: MutableMapping[str, Any], axis_id: str, n: int
    ) -> Tuple[bool, List[Tuple[str, str, int]]]:
        """any 总量门分解（D-02）：任意池组合可扣，扣不足 → 整体被拒。

        按池枚举序贪心（先可扣池序），逐池可扣量累加；可扣总量 ≥ n →
        生成逐池扣减计划（补足差额，不超扣）；否则 (False, [])。
        """
        avail: List[Tuple[str, int]] = []
        total = 0
        for pool in self.pools_of(axis_id):
            cur = self._current_of(side_state, axis_id, pool)
            if cur > 0:
                avail.append((pool, cur))
                total += cur
        if total < n:
            return False, []
        plan: List[Tuple[str, str, int]] = []
        remain = n
        for pool, cur in avail:
            if remain <= 0:
                break
            take = min(cur, remain)
            plan.append((axis_id, pool, take))
            remain -= take
        return True, plan

    def _current_of(
        self, side_state: MutableMapping[str, Any], axis_id: str, pool: str
    ) -> int:
        """当前值读取（数值型=单键；子池型=池键；缺省 base 兜底）。"""
        if pool:
            pools_state = side_state.get(axis_id)
            if isinstance(pools_state, MutableMapping):
                return self._int_or_none(pools_state.get(pool)) or 0
            return 0
        return self._int_or_none(side_state.get(axis_id)) or 0

    def _cost_scalar(
        self, side_state: MutableMapping[str, Any], axis_id: str, pool: str, n: int
    ) -> None:
        """单键扣减（数值型或子池型池键；扣后下限 0）。"""
        if pool:
            pools_state = side_state.get(axis_id)
            if not isinstance(pools_state, MutableMapping):
                pools_state = {}
                side_state[axis_id] = pools_state
            cur = self._int_or_none(pools_state.get(pool)) or 0
            pools_state[pool] = max(0, cur - n)
        else:
            cur = self._int_or_none(side_state.get(axis_id)) or 0
            side_state[axis_id] = max(0, cur - n)

    # ------------------------- 被控保留（F-R1 被控段） -------------------------

    def is_controlled_preserved(self, battle_state: Mapping[str, Any]) -> bool:
        """被控 skip_turn 保留判定（S4：【狂战士 L78】【元素法师 L82】）。

        契约语义：被控期间能量/怒气不增不减（保留）。本引擎的增减只经
        apply_gain/try_apply_cost 显式触发，被控路径不调用即天然保留——
        本判定显式声明该契约行为（供装配层在被控 skip 时调用/断言），
        不改变任何状态。返回 True（保留语义成立）。
        """
        return True

    # ------------------------- 回合结束结清（F-R1 tick） -------------------------

    def tick_round_end(
        self,
        battle_state: MutableMapping[str, Any],
        axes: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """回合结束结清（F-R1 回合边界）。

        当前契约（细化_6c §1.3）未定义任何「每回合自动变化」字段（无
        每回合衰减/回复配置项）——本引擎的每回合资源变化只来自 proc 时点
        （on_turn_start 等，批8B 接线）与被控保留；故本方法现行为 = 保留
        （零增减，纯幂等钩子）。提供 axes 参数与返回侧状态，供契约后续
        扩展每回合变化时挂载（保持签名稳定）。返回各侧 resource_state
        （就地读取，无写入）。
        """
        del axes  # 预留参数（契约扩展位）；现契约无每回合变化，无操作
        if not isinstance(battle_state, Mapping):
            return {}
        rs = battle_state.get(RESOURCE_STATE_KEY)
        if not isinstance(rs, Mapping):
            return {}
        out: Dict[str, Any] = {}
        for side in ("player", "enemy"):
            side_state = rs.get(side)
            out[side] = side_state if isinstance(side_state, MutableMapping) else {}
        return out

    # ------------------------- 战斗结束清零/保留（F-R1 终段） -------------------------

    def battle_end_reset(
        self,
        battle_state: MutableMapping[str, Any],
        reset_policy: str = DEFAULT_RESET,
        axis_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """战斗结束按 reset 策略清零/保留（F-R1 终段 / S5）。

        - reset=battle → 清零（数值型=0；子池型各池=0）【狂战士 L79】【元素法师 L83】；
        - reset=keep → 跨战斗保留（不触碰；RS-3 存档双落由装配层消费）【资源轴 L53】；
        - reset=battle_start → 战斗内保留（不触碰；下次战斗开始置 base）【资源轴 L54】。
        策略以参数为准（缺省 battle），轴集合缺省 = 注册表全部轴；已删注册轴
        防御跳过（RS-5）。返回该侧清零结果（就地改写）。
        """
        if reset_policy not in (RESET_BATTLE, RESET_KEEP, RESET_BATTLE_START):
            reset_policy = DEFAULT_RESET
        out: Dict[str, Any] = {}
        for side in ("player", "enemy"):
            side_state = self._side_state(battle_state, side)
            if reset_policy == RESET_BATTLE:
                for axis_id in self._iter_axis_ids(axis_ids):
                    if self.reset_policy(axis_id) != RESET_BATTLE:
                        continue  # keep / battle_start 轴不参与 battle 清零（按注册表口径）
                    if self.is_pool_axis(axis_id):
                        side_state[axis_id] = {
                            pool: 0 for pool in self.pools_of(axis_id)
                        }
                    else:
                        side_state[axis_id] = 0
            # keep / battle_start：保留（不触碰）
            out[side] = dict(side_state)
        return out

    # ------------------------- resource_state 快照（机制 M4 / RS-1~6） -------------------------

    def snapshot_resource_state(
        self, battle_state: Mapping[str, Any]
    ) -> Dict[str, Any]:
        """快照导出（RS-1 回合边界写入 / RS-6 池级原子性）：深拷贝 resource_state。

        数值型=单键当前值；子池型=池级展开 {axis: {pool: v}}（D-04）。
        无 resource_state 段 → 返回 per-side 空骨架（结构稳定）。
        """
        if not isinstance(battle_state, Mapping):
            return {"player": {}, "enemy": {}}
        rs = battle_state.get(RESOURCE_STATE_KEY)
        if not isinstance(rs, Mapping):
            return {"player": {}, "enemy": {}}
        out: Dict[str, Any] = {}
        for side in ("player", "enemy"):
            side_state = rs.get(side)
            if isinstance(side_state, MutableMapping):
                out[side] = {
                    k: (dict(v) if isinstance(v, MutableMapping) else v)
                    for k, v in side_state.items()
                }
            else:
                out[side] = {}
        return out

    def restore_resource_state(
        self,
        battle_state: MutableMapping[str, Any],
        snapshot: Mapping[str, Any],
        axis_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """中断恢复还原（RS-2 / RS-5）：按快照还原各资源当前值。

        - 快照内该侧数值型键 → 原样还原；子池型池级展开 → 逐池还原
          （池级原子，RS-6；缺失池 → 补 base，防御降级）；
        - 已删注册轴 → 字段缺失降级（不写入、不报错、显示隐藏，RS-5）；
        - battle_start 型轴：战斗开始重置为 base（F-R1 首行 + RS-2 合并口径，
          恢复后续战从该值起算）。
        返回该侧恢复后的 resource_state（就地改写）。
        """
        side_state = self._side_state(battle_state, "player")
        snap_side = snapshot.get("player") if isinstance(snapshot, Mapping) else None
        if not isinstance(snap_side, Mapping):
            snap_side = {}
        for axis_id in self._iter_axis_ids(axis_ids):
            if axis_id not in snap_side:
                continue  # 快照缺轴 → 降级跳过（RS-5）
            raw = snap_side.get(axis_id)
            if self.is_pool_axis(axis_id):
                pools_state: MutableMapping[str, Any] = {}
                if isinstance(raw, MutableMapping):
                    pools_state.update(raw)
                for pool in self.pools_of(axis_id):
                    if pool not in pools_state:
                        pools_state[pool] = self._base_of(axis_id)
                side_state[axis_id] = pools_state
            elif self._int_or_none(raw) is not None:
                side_state[axis_id] = max(0, int(cast(Any, raw)))
            # battle_start：战斗开始重置为 base（F-R1 / RS-2）
            if self.reset_policy(axis_id) == RESET_BATTLE_START:
                if self.is_pool_axis(axis_id):
                    side_state[axis_id] = {
                        pool: self._base_of(axis_id) for pool in self.pools_of(axis_id)
                    }
                else:
                    side_state[axis_id] = self._base_of(axis_id)
        return side_state

    # ------------------------- 工具 -------------------------

    def _iter_axis_ids(
        self, axis_ids: Optional[Sequence[str]]
    ) -> List[str]:
        """轴集合归一（缺省 = 注册表全部轴；过滤未注册/非 str 防御）。"""
        if axis_ids is None:
            return [a for a in self._registry if isinstance(a, str)]
        out: List[str] = []
        for a in axis_ids:
            if isinstance(a, str) and a in self._registry:
                out.append(a)
        return out

    @staticmethod
    def _int_or_none(raw: Any) -> Optional[int]:
        """数值归一（非数值/布尔 → None；负数保留原值由调用方钳制）。"""
        if isinstance(raw, bool):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
