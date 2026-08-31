"""M10 批1·路1B：钓鱼流程状态机核心（qbot_rpg/core/fishing.py）——FishingEngine。

文件名：qbot_rpg/core/fishing.py
创建时间：2026-08-31
作者：Hermes 子agent-1B（M10 钓鱼实现组批1·路1B：流程状态机核心；兄弟路1A 独占
      items/recipe 饵料体系，本文件零 import 之，只读勿探查）

功能描述：
  FishingEngine 承载钓鱼交互流程状态机核心（纯引擎层，不碰指令壳）——
  - start_fishing(ctx, spot_id)：守卫 GU-01(mode 非 off)/GU-02(日计数<daily_limit)/
    GU-03(spot 合法)/GU-04(无进行中钓局)；扣饵（无饵保底不卡死）+ 日计数+1 +
    注册懒计时期（cast_at = now + wait_sec 随机区间，0=即收 cast_at=now）；写
    fish_state（_ps_init 挂 player.persistent_state 形态：{state, cast_at, spot_id,
    wait_sec, bait_used, ...}）；返回 {ok, message, state}。
  - bite_check(ctx, king_hit=False)：懒计算到期判定（now >= cast_at）；未到期 →
    等待中；到期 → 按本局目标鱼种 rarity 生成鱼讯三类（normal→微动/rare→拉扯/
    gold→猛烈，细化 2c1b §3.1 实现约定）+ 金闪覆写位（king_hit 批4 接线，本路
    golden 默认 False）；状态 S2→S3；返回 {ok, bite, kind, golden, message}。
  - reel_in(ctx, choice)：收杆三选一（满力/自动/止损）入口——止损（不 roll，空收回
    S0）；满力/自动 roll 概率批2 路2C 实现（本路留 roll_hook 注入位，未注入返回
    {ok, choice, state} 骨架）；决策窗超时（carry_sec 默认 90，0=不限，now - bite_ts
    > carry）→ TR-07 SL 跑鱼回 S0。
  每日计数：fish_state 内 {today, casts} 对齐 dayroll 懒重置（today_of 05:00；
  跨日 casts 清零）。
  mode 路由：full 完整 FSM；simple 短接（S0→S1→ST 直接出鱼，无 S2/S3——本路实现
  simple 分支骨架，出鱼结算批3 接线）；off 全拒绝（GU-01）。

依据：细化_2c1b §二/§三 + 定稿 §1 M3-M5
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §二（状态集 S0-S3/ST/SL + 迁移表 TR-01~11
    + 守卫 GU-01~04 + §2.4 模式前缀 full/simple/off）§三（鱼讯三类 §3.1 rarity→讯类
    映射 + §3.2 表 + §3.3 金闪 + §3.4 决策含义）§四（收杆三选一 + carry_sec）
  - docs/m10_shared_contract.md（批0 接口权威）§二 IF-03（FishDef 访问器）/ §五 铁律
  - docs/m10_接口摸底.md §一（懒计算复用 harvest_at 时间戳模式）/ §二（鱼讯按 rarity
    直接映射 fish_intent_of）/ §八-3（ctx fish_table/fishing_cfg 注入形态）/ §八-4
    （每日计数放 fish_state {today, casts} 对齐 dayroll）/ §九（rng 注入 ctx["rng"]、
    零定时器、鱼讯意图预告不锁结局）
模式参考：
  - qbot_rpg/core/quest.py _daily_node（today_of 懒重置 05:00）
  - qbot_rpg/core/shop.py _now/_rng（ctx 注入确定性）
  - qbot_rpg/core/alchemy_harvest.py（harvest_at = now + sec 时间戳懒判模式，零实时计时器）
  - qbot_rpg/assembly/context.py _ps_init（persistent_state 键惰性挂回，引擎写 ctx 键即落档）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  B-1  状态落点：start_fishing 一次性完成 S0→S1→S2（TR-01 抛竿受理 + TR-02 抛竿受理
       完成进入等待期，同一命令内连续迁移），落档 state="S2"；S1 为瞬时态不落档。
  B-2  目标鱼种选定时机：细化 §3.1「在 S2 等待期到期时刻（TR-03）按本局出鱼目标生成
       意图预告」——本路在 bite_check 到期分支选定目标鱼种（spot 候选池经注入 rng
       等概率选一；无候选回落全池；无鱼种数据 → 拒绝 reason=no_species），写入
       fish_state{target_species_id, target_rarity} 供批3 结算。
  B-3  扣饵实现：本路不碰 items/recipe（兄弟路1A 独占）——引擎内置最小扣饵（从
       settings.fishing.bait_ids 5 档中取玩家持有第一档，经 ctx["remove_item"] hook
       或 ctx["inventory"] 计数映射扣 1）；无饵保底不卡死（bait_used=None 仍继续，
       不吃对口饵加成）。批2 装配注入 ctx["consume_bait"] 后委托完整饵选择。
  B-4  GU-03 口径：细化 GU-03「目标钓点属于当前地图可钓鱼点集（maps 采集点变体）」
       ——引擎层无地图语义（地图归属判定归批2 钓点列举），本路校验「spot_id 非空且
       属于已知钓点集（species 池 spots 并集）；已知钓点集为空（无鱼种数据）→ 宽松
       放行」。更严的「属于当前地图」由批2 指令壳叠加。
  B-5  carry_sec 配置来源：契约 settings.fishing 9 键未含 carry_sec（细化 §3.4 默认
       90 可配）——本路读原始 settings.fishing.carry_sec（非负 int 生效），缺省 90；
       0=不限。构造器 carry_sec 参数优先覆盖。
  B-6  收杆骨架：满力/自动 roll 概率（54/37/9 与 70/25/5 种子化）归批2 路2C；本路
       roll_hook 注入位（callable(ctx, fs, choice) -> dict），未注入返回
       {ok, choice, state:"ST", reeled:True, roll_pending:True, settle_pending:True}
       骨架，fish_state 记录 last 快照供批3 结算跨指令读取。
  B-7  GU-04 / TR-07：引擎层实现「同玩家仅一局」（活动会话 S2/S3 中发起新钓局 →
       拒绝 GU-04）与「决策窗超时 → TR-07 SL 跑鱼回 S0」；细化 TR-07 的「换区/新钓局
       被动脱钩」路径归批2 指令壳接线（引擎无地图/指令语义）。

铁律：零 NoneBot import；纯函数确定性零 IO；零定时器/零睡眠（时间戳懒判，无实时
      倒计时）；rng 必须注入（ctx["rng"] 或构造器 rng，禁止裸 random 破坏确定性）；
      输出文案不写死模板（批6 模板化，本路返回结构化 dict，文案常量 TODO 标注）；
      零 emoji。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Set, Tuple, cast

from qbot_rpg.content.fishing_models import FishDef
from qbot_rpg.core.dayroll import today_of
from qbot_rpg.core.fishing_settings import fishing_cfg

# =====================================================================================
# 状态常量（细化_2c1b §2.1 状态集：S0/S1/S2/S3/ST/SL）
# =====================================================================================
STATE_IDLE: str = "S0"        # 空闲（无进行中钓局）
STATE_CASTING: str = "S1"     # 下钩（抛竿动作已受理，瞬时态不落档，B-1）
STATE_WAITING: str = "S2"     # 等待鱼讯（懒计算期）
STATE_BITE: str = "S3"        # 咬钩（鱼讯已触发，等待收杆三选一，决策窗）
STATE_REELED: str = "ST"      # 结算（收杆成功路径：满力/自动→出鱼；止损→空收）
STATE_LOST: str = "SL"        # 跑鱼（决策窗超时被动脱钩，空手回 S0）

# 鱼讯三类（细化_2c1b §3.1/§3.2：normal→微动/rare→拉扯/gold→猛烈）
KIND_NIBBLE: str = "nibble"   # 微动（小鱼）
KIND_TUG: str = "tug"         # 拉扯（中鱼）
KIND_VIOLENT: str = "violent" # 猛烈（大鱼或鱼王）
KIND_LABELS: Dict[str, str] = {
    KIND_NIBBLE: "微动",
    KIND_TUG: "拉扯",
    KIND_VIOLENT: "猛烈",
}

# rarity → 鱼讯类映射（细化 §3.1 实现约定，0A 摸底 §二「normal→微动/rare→拉扯/
# gold→猛烈」写死映射；未知 rarity 保守回落微动）
RARITY_KIND: Dict[str, str] = {
    "normal": KIND_NIBBLE,
    "rare": KIND_TUG,
    "gold": KIND_VIOLENT,
}

# 收杆三选一（细化 §4.1：满力 full / 自动 auto / 止损 stop）
REEL_CHOICES: tuple = ("full", "auto", "stop")

# 决策窗超时默认秒（细化 §3.4：carry_sec 默认 90 可配、0=不限；契约 settings.fishing
# 9 键未含此键，读原始段 carry_sec 缺省此值，B-5）
DEFAULT_CARRY_SEC: int = 90

# 等待区间缺省秒（对齐 DEFAULT_FISHING_SETTINGS["wait_sec"]，防御兜底）
_DEFAULT_WAIT_MIN: int = 300
_DEFAULT_WAIT_MAX: int = 900

# =====================================================================================
# 消息常量（TODO 模板化：批6 fishing_tpl 分区接管，默认模板与旧输出逐字一致；本路
# 引擎返回结构化 dict，文案仅为骨架占位，批6 迁模板后指令壳经 tpl_of 渲染）
# =====================================================================================
MSG_OFF: str = "钓鱼功能已关闭"
MSG_DAILY_LIMIT: str = "今日钓鱼次数已达上限"
MSG_SPOT_INVALID: str = "钓点不存在或不可用"
MSG_SESSION_ACTIVE: str = "已有进行中的钓局"
MSG_NO_SESSION: str = "无进行中钓局"
MSG_WAITING: str = "等待中，尚未有鱼讯"
MSG_WAITING_CANNOT_REEL: str = "鱼尚未咬钩，无法收杆"
MSG_ALREADY_BITE: str = "鱼已咬钩，请选择收杆方式"
MSG_BITE: str = "鱼讯：{label}"
MSG_STOP: str = "止损收杆，本局空收"
MSG_REELED: str = "收杆成功，等待结算"
MSG_TIMEOUT_LOST: str = "收杆超时，鱼已跑掉"
MSG_SIMPLE_DIRECT: str = "已下钩并直接出鱼（simple 模式无等待/鱼讯）"
MSG_SIMPLE_NO_WAIT: str = "simple 模式无等待/鱼讯流程"
MSG_INVALID_CHOICE: str = "未知收杆方式"
MSG_CAST: str = "已抛竿，等待 {wait_sec} 秒后可收杆"
MSG_NO_SPECIES: str = "无可用鱼种数据"


# =====================================================================================
# 鱼讯意图（0A 摸底 §二：复用「意图预告」语义，轻量纯函数 rarity 直接映射；金闪
# 覆写位 king_hit 批4 接线，本路默认 False → golden 恒 False，B-6 前置位）
# =====================================================================================
def fish_intent_of(rarity: object, king_hit: bool = False) -> Dict[str, object]:
    """鱼讯三类意图（细化 §3.1/§3.3）：rarity 直接映射讯类 + 金闪覆写位。

    normal → 微动 nibble / rare → 拉扯 tug / gold → 猛烈 violent；
    king_hit=True 且讯类为猛烈 → 携带金闪 golden=True（金闪只可能出现在猛烈鱼讯，
    TC-13）；微动/拉扯永不携带金闪。未知 rarity 保守回落微动（不炸）。
    意图预告语义：真实预告本局出鱼档位，不锁死收杆结局（细化 §3.4）。
    """
    kind = RARITY_KIND.get(str(rarity) if rarity is not None else "", KIND_NIBBLE)
    golden = bool(king_hit) and kind == KIND_VIOLENT
    return {"kind": kind, "golden": golden}


# =====================================================================================
# 纯函数工具（零 NoneBot、确定性、ctx 注入）
# =====================================================================================
def _now_ts(ctx: Mapping[str, Any]) -> int:
    """UTC+8 秒级时间戳：ctx["now"] 注入优先（确定性可测）；缺省 = 当前 epoch 秒。"""
    now = ctx.get("now")
    if now is not None:
        return int(now)
    return int(time.time())


def _as_int(value: object) -> Optional[int]:
    """int 归一（bool 除外）；非 int/bool/可转数字串 → None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else None
    return None


def _normalize_wait(wait_sec: object) -> Tuple[int, int]:
    """wait_sec 区间归一（细化 L78 0=即收）：{min,max} 非负 int，max 缺省=min。

    非法/缺失 → 默认区间 300-900（对齐 DEFAULT_FISHING_SETTINGS.wait_sec 防御兜底）。
    """
    if not isinstance(wait_sec, Mapping):
        return (_DEFAULT_WAIT_MIN, _DEFAULT_WAIT_MAX)
    wmin = _as_int(wait_sec.get("min"))
    wmax = _as_int(wait_sec.get("max"))
    if wmin is None:
        wmin = _DEFAULT_WAIT_MIN
    if wmax is None:
        wmax = wmin
    if wmin < 0:
        wmin = 0
    if wmax < wmin:
        wmax = wmin
    return (wmin, wmax)


def _persistent_state_of(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """persistent_state 可变容器定位：ctx["persistent_state"] → ctx["player"].
    persistent_state → ctx 自身（兄弟路直键兜底，对齐 adventure_log._persistent_state_of）。"""
    ps = ctx.get("persistent_state")
    if isinstance(ps, MutableMapping):
        return ps
    player = ctx.get("player")
    if isinstance(player, Mapping):
        ps2 = player.get("persistent_state")
        if isinstance(ps2, MutableMapping):
            return ps2
    if isinstance(ctx, MutableMapping):
        return ctx
    return None


# =====================================================================================
# FishingEngine：钓鱼流程状态机核心（纯引擎层，不碰指令壳）
# =====================================================================================
class FishingEngine:
    """钓鱼流程状态机核心引擎。

    构造器注入（确定性单源）：
      settings:  settings 全量 dict（fishing_cfg 归一 fishing 段 + dayroll refresh_time）；
                 缺省 None → 运行时读 ctx["settings"]。
      species:   FishDef 池（list[FishDef] 或 raw dict 列表）；缺省 None → 运行时读
                 ctx["fish_table"]（Def→raw dict）或 ctx["fishing"]["species"]。
      rng:       注入 rng（Random 实例，wait_sec/目标选择确定性）；缺省 None → 运行时
                 读 ctx["rng"]；再缺省 → 兜底 random.Random() 模块（对齐 shop._rng，
                 测试一律注入固定 rng）。
      carry_sec: 决策窗超时秒（0=不限）；缺省 None → settings.fishing.carry_sec → 90。
      roll_hook: 满力/自动收杆 roll 注入位（callable(ctx, fs, choice) -> dict）；缺省
                 None → 返回 {ok, choice, state:"ST"} 骨架（B-6，批2 路2C 接线）。

    ctx 契约（本路消费）：
      ctx["now"]        UTC+8 秒级时间戳（确定性时钟）
      ctx["rng"]        确定性 RNG（Random 实例）
      ctx["settings"]   settings 全量 dict（fishing_cfg / dayroll refresh_time）
      ctx["fish_table"] species Def→raw dict（批2 装配注入；本路未注入时用构造器 species）
      ctx["fishing"]    fishing.json 顶层 raw dict（含 species 段，备选）
      ctx["fish_state"] fish_state 落档（_ps_init 形态：引擎写 ctx 键即挂 player.
                        persistent_state 落档，跨指令可结算；本路不改 make_context，
                        装配层收口批2/批6）
      ctx["inventory"] 物品计数映射 {item_id: count}（内置扣饵读取）
      ctx["remove_item"] 扣物品 hook（callable(item_id, count) -> bool；批2 装配注入）
      ctx["consume_bait"] 饵消费 hook（callable(ctx, engine) -> Optional[str]；批2
                        装配注入后委托兄弟路1A 完整饵选择，B-3）

    返回：结构化 dict（ok/message/state 等），拒绝场景 {ok:False, guard/reason,
    message} 不抛异常（对齐 HarvestEngine 惯例）。
    """

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
        species: Optional[List[Any]] = None,
        rng: Any = None,
        carry_sec: Optional[int] = None,
        roll_hook: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._settings: Optional[Mapping[str, Any]] = settings
        self._species: Optional[List[FishDef]] = None
        if species is not None:
            self._species = [self._to_fishdef(s) for s in species]
        self._rng: Any = rng
        self._carry_sec: Optional[int] = carry_sec
        self._roll_hook: Optional[Callable[..., Any]] = roll_hook

    # ---- 静态归一 ----
    @staticmethod
    def _to_fishdef(entry: Any) -> FishDef:
        """raw dict / FishDef → FishDef（cast 消 mypy BaseDef 返回型，对齐 models 测试）。"""
        if isinstance(entry, FishDef):
            return entry
        if isinstance(entry, Mapping):
            return cast(FishDef, FishDef.from_entry(entry))
        raise TypeError(f"species entry must be FishDef or Mapping, got {type(entry)!r}")

    # ---- 运行期配置（构造器注入优先，ctx 兜底）----
    def _settings_of(self, ctx: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._settings is not None:
            return self._settings
        settings = ctx.get("settings")
        return settings if isinstance(settings, Mapping) else {}

    def _cfg(self, ctx: Mapping[str, Any]) -> Dict[str, object]:
        """settings.fishing 段归一（fishing_cfg：缺省合并默认值，纯函数确定性）。"""
        return fishing_cfg(self._settings_of(ctx))

    def _mode(self, ctx: Mapping[str, Any]) -> str:
        mode = self._cfg(ctx).get("mode")
        return mode if isinstance(mode, str) and mode in ("full", "simple", "off") else "full"

    def _resolve_rng(self, ctx: Mapping[str, Any]) -> Any:
        """rng 注入：构造器 rng 优先 → ctx["rng"] → 兜底 random 模块（shop._rng 惯例；
        测试一律注入固定 rng，生产装配层注入 ctx["rng"]，确定性）。"""
        if self._rng is not None:
            return self._rng
        rng = ctx.get("rng")
        if rng is not None:
            return rng
        import random

        return random

    def _carry_sec_of(self, ctx: Mapping[str, Any]) -> int:
        """决策窗秒：构造器 carry_sec 优先 → settings.fishing.carry_sec（原始段）→ 90。
        0=不限（细化 §3.4 / B-5）。"""
        if self._carry_sec is not None:
            return max(0, int(self._carry_sec))
        settings = self._settings_of(ctx)
        fseg = settings.get("fishing")
        if isinstance(fseg, Mapping):
            v = _as_int(fseg.get("carry_sec"))
            if v is not None and v >= 0:
                return v
        return DEFAULT_CARRY_SEC

    # ---- fish_state 落档（_ps_init 形态：引擎写 ctx 键即挂 player.persistent_state）----
    @staticmethod
    def _fish_state_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        """ctx["fish_state"] 惰性挂回（对齐 assembly/context.py _ps_init）。

        ctx 已有 → 直返；缺省 → 新建 dict 并挂回 player.persistent_state（ps["fish_state"]
        = node）+ ctx["fish_state"]=node——引擎写本键即落档，跨指令可结算（本路不改
        make_context，装配层收口批2/批6 后由装配注入同一键，逻辑一致幂等）。
        """
        fs = ctx.get("fish_state")
        if isinstance(fs, MutableMapping):
            return fs
        node: MutableMapping[str, Any] = {}
        ps = _persistent_state_of(ctx)
        if isinstance(ps, MutableMapping):
            ps["fish_state"] = node
        ctx["fish_state"] = node
        return node

    # ---- species 池与钓点集 ----
    def _species_pool(self, ctx: Mapping[str, Any]) -> List[FishDef]:
        """species 池：构造器 species 优先 → ctx["fish_table"]（Def→raw dict）→
        ctx["fishing"]["species"]（raw list）。无可解析 → []（宽松不炸）。"""
        if self._species is not None:
            return list(self._species)
        ft = ctx.get("fish_table")
        if isinstance(ft, Mapping):
            out: List[FishDef] = []
            for entry in ft.values():
                if isinstance(entry, Mapping):
                    out.append(self._to_fishdef(entry))
            return out
        fishing = ctx.get("fishing")
        if isinstance(fishing, Mapping):
            species = fishing.get("species")
            if isinstance(species, list):
                return [self._to_fishdef(e) for e in species]
        return []

    def _known_spots(self, ctx: Mapping[str, Any]) -> Set[str]:
        """已知钓点集 = species 池全部 spots 并集（GU-03 合法判定靶）。"""
        spots: Set[str] = set()
        for s in self._species_pool(ctx):
            spots.update(s.spots)
        return spots

    def _spot_ok(self, ctx: Mapping[str, Any], spot_id: object) -> bool:
        """GU-03：spot_id 非空 str 且属于已知钓点集；已知钓点集为空（无鱼种数据）→
        宽松放行（B-4，地图归属判定批2 叠加）。"""
        if not isinstance(spot_id, str) or not spot_id.strip():
            return False
        known = self._known_spots(ctx)
        if not known:
            return True
        return spot_id in known

    # ---- 每日计数（dayroll 懒重置 05:00，fish_state {today, casts}）----
    def _daily_roll(self, ctx: MutableMapping[str, Any], fs: MutableMapping[str, Any]) -> int:
        """日界懒重置（对齐 quest._daily_node）：today_of(last_key, now, settings)；
        跨日（today 变更）→ casts 清零并更新 today。返回 now（UTC+8 epoch 秒）。"""
        now = _now_ts(ctx)
        settings = self._settings_of(ctx)
        t = today_of(fs.get("today"), now, settings)
        if fs.get("today") != t["today"]:
            fs["today"] = t["today"]
            fs["casts"] = 0
        return now

    # ---- 扣饵（无饵保底不卡死，B-3）----
    def _consume_bait(
        self, ctx: MutableMapping[str, Any], cfg: Mapping[str, object]
    ) -> Optional[str]:
        """扣 1 饵 → 返回 bait_id；无饵/全失败 → None（无饵保底不卡死，不吃对口饵加成）。

        优先委托 ctx["consume_bait"] hook（批2 装配注入兄弟路1A 完整饵选择）；未注入 →
        内置最小扣饵：settings.fishing.bait_ids 5 档中取玩家持有第一档（ctx["remove_item"]
        hook 优先，回落 ctx["inventory"] 计数映射就地减 1）。
        """
        hook = ctx.get("consume_bait")
        if callable(hook):
            try:
                result = hook(ctx, self)
                return result if isinstance(result, str) and result else None
            except Exception:
                return None
        bait_ids = cfg.get("bait_ids")
        if not isinstance(bait_ids, list):
            return None
        remove_item = ctx.get("remove_item")
        inventory = ctx.get("inventory")
        for bid in bait_ids:
            if not isinstance(bid, str) or not bid.strip():
                continue
            if callable(remove_item):
                try:
                    if remove_item(bid, 1):
                        return bid
                except Exception:
                    pass
                continue
            if isinstance(inventory, MutableMapping):
                count = inventory.get(bid, 0)
                if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                    inventory[bid] = count - 1
                    return bid
        return None

    # ---- 等待时长（注入 rng 确定性，0=即收 cast_at=now）----
    def _roll_wait(self, ctx: Mapping[str, Any]) -> int:
        """wait_sec 随机区间（细化 L78 [min,max] 随机）：注入 rng randint；0=即收。

        wait_sec=0 → cast_at = now（下钩即收路径，S2 瞬时，TC-07）。
        """
        cfg = self._cfg(ctx)
        wmin, wmax = _normalize_wait(cfg.get("wait_sec"))
        rng = self._resolve_rng(ctx)
        return int(rng.randint(wmin, wmax))

    # ---- 目标鱼种选定（B-2：bite_check 到期时 spot 候选池 rng 选一）----
    def _pick_target(self, ctx: Mapping[str, Any], spot_id: str, rng: Any) -> Optional[FishDef]:
        """目标鱼种：spot 候选池（spots 含该 spot 的鱼种）经 rng 等概率选一；候选空 →
        回落全池；无鱼种数据 → None（bite 拒绝 reason=no_species）。"""
        pool = self._species_pool(ctx)
        if not pool:
            return None
        candidates = [s for s in pool if spot_id in s.spots]
        if not candidates:
            candidates = list(pool)
        if hasattr(rng, "choice"):
            return rng.choice(candidates)
        return candidates[0]  # 无 choice 能力的 rng → 首条（确定性兜底）

    # ---- 会话清理（终态回 S0；保留 today/casts 日计数）----
    @staticmethod
    def _clear_session(fs: MutableMapping[str, Any]) -> None:
        """会话字段清理回 S0（TR-08/TR-09：终态消息发出→清理会话）；today/casts 日计数
        保留（每日计数不回滚，TR-07 饵不返还、日计数不减）。"""
        for key in (
            "spot_id",
            "cast_at",
            "wait_sec",
            "bait_used",
            "target_species_id",
            "target_rarity",
            "bite_ts",
            "kind",
            "golden",
            "mode",
        ):
            fs.pop(key, None)
        fs["state"] = STATE_IDLE

    # =================================================================================
    # 状态机主方法
    # =================================================================================
    def start_fishing(self, ctx: MutableMapping[str, Any], spot_id: object) -> dict:
        """TR-01/TR-02（S0→S1→S2 连续迁移，B-1 落档 S2）：守卫四连 + 扣饵 + 日计数+1
        + 注册懒计时期；simple 短接（S0→S1→ST 直接出鱼骨架，批3 结算接线）。

        守卫序（细化 §2.3）：GU-01(mode 非 off) → GU-02(日计数<daily_limit) →
        GU-03(spot 合法) → GU-04(无进行中钓局)。返回 {ok, message, state, ...}。
        """
        fs = self._fish_state_of(ctx)
        cfg = self._cfg(ctx)
        mode = str(cfg.get("mode") or "full")

        # GU-01：mode 路由（off 全拒绝；full/simple 放行）
        if mode == "off":
            return {"ok": False, "guard": "GU-01", "reason": "mode_off",
                    "state": str(fs.get("state") or STATE_IDLE), "message": MSG_OFF}

        # 每日懒重置（对齐 dayroll 05:00；跨日 casts 清零）
        now = self._daily_roll(ctx, fs)

        # GU-02：每日上限（第 21 次下钩被拦截，L77）
        daily_limit = _as_int(cfg.get("daily_limit"))
        if daily_limit is not None:
            casts = int(fs.get("casts") or 0)
            if casts >= daily_limit:
                return {"ok": False, "guard": "GU-02", "reason": "daily_limit",
                        "state": str(fs.get("state") or STATE_IDLE), "message": MSG_DAILY_LIMIT}

        # GU-03：spot 合法（已知钓点集校验，B-4）
        if not self._spot_ok(ctx, spot_id):
            return {"ok": False, "guard": "GU-03", "reason": "spot_invalid",
                    "state": str(fs.get("state") or STATE_IDLE), "message": MSG_SPOT_INVALID}

        # GU-04：同玩家仅一局（活动会话 S2/S3 中发起新钓局 → 拒绝）
        state = str(fs.get("state") or STATE_IDLE)
        if state in (STATE_WAITING, STATE_BITE):
            return {"ok": False, "guard": "GU-04", "reason": "session_active",
                    "state": state, "message": MSG_SESSION_ACTIVE}

        # 扣饵（无饵保底不卡死，bait_used=None 仍继续）+ 日计数 +1
        bait_used = self._consume_bait(ctx, cfg)
        fs["today"] = str(today_of(fs.get("today"), now, self._settings_of(ctx))["today"])
        fs["casts"] = int(fs.get("casts") or 0) + 1
        fs["mode"] = mode

        if mode == "simple":
            # simple 短接：S0→S1→ST 直接出鱼（无 S2/S3 实例，无等待/鱼讯/鱼王，TC-09/14）。
            # 出鱼结算批3 接线——本路返回骨架 settle_pending=True。
            fs["spot_id"] = str(spot_id)
            fs["bait_used"] = bait_used
            fs["state"] = STATE_REELED
            return {
                "ok": True, "state": STATE_REELED, "mode": "simple", "direct": True,
                "settle_pending": True, "bait_used": bait_used,
                "message": MSG_SIMPLE_DIRECT,
            }

        # full：注册懒计时期（cast_at = now + wait_sec；wait_sec=0 即收 cast_at=now）
        wait_sec = self._roll_wait(ctx)
        cast_at = now + wait_sec
        fs["spot_id"] = str(spot_id)
        fs["cast_at"] = cast_at
        fs["wait_sec"] = wait_sec
        fs["bait_used"] = bait_used
        fs["state"] = STATE_WAITING  # S0→S1→S2（B-1）
        return {
            "ok": True, "state": STATE_WAITING, "spot_id": str(spot_id),
            "cast_at": cast_at, "wait_sec": wait_sec, "bait_used": bait_used,
            "message": MSG_CAST.format(wait_sec=wait_sec),
        }

    def bite_check(self, ctx: MutableMapping[str, Any], king_hit: bool = False) -> dict:
        """TR-03（S2→S3）：懒计算到期判定（now >= cast_at）；未到期 → 等待中；
        到期 → 按本局目标鱼种 rarity 生成鱼讯三类 + 金闪覆写位（king_hit 批4 接线，
        本路默认 False → golden 恒 False）。

        返回 {ok, bite, kind, golden, message, state, ...}：
          bite=False 未到期/无钓局；bite=True 已触发鱼讯（S3）。
        已咬钩（S3）时自环返回已有讯类（TR-11 / /鱼讯 查询语义），不重复 roll。
        """
        fs = self._fish_state_of(ctx)
        mode = self._mode(ctx)
        if mode == "off":
            return {"ok": False, "guard": "GU-01", "reason": "mode_off",
                    "state": str(fs.get("state") or STATE_IDLE), "message": MSG_OFF}
        state = str(fs.get("state") or STATE_IDLE)

        if mode == "simple":
            # simple 不实例化 S2/S3（TC-09/14）：无等待/鱼讯流程
            return {"ok": False, "reason": "simple_no_wait", "bite": False,
                    "state": str(fs.get("state") or STATE_IDLE), "message": MSG_SIMPLE_NO_WAIT}

        if state not in (STATE_WAITING, STATE_BITE):
            return {"ok": False, "reason": "no_session", "bite": False,
                    "state": STATE_IDLE, "message": MSG_NO_SESSION}

        if state == STATE_BITE:
            # 已咬钩：自环返回已有讯类（TR-11），不重复生成
            return {
                "ok": True, "bite": True,
                "kind": str(fs.get("kind") or KIND_NIBBLE),
                "golden": bool(fs.get("golden", False)),
                "state": STATE_BITE, "message": MSG_ALREADY_BITE,
            }

        # S2 等待中：懒计算到期判定（now >= cast_at，零实时计时器）
        now = _now_ts(ctx)
        cast_at = int(fs.get("cast_at") or 0)
        if now < cast_at:
            return {"ok": True, "bite": False, "kind": None, "golden": False,
                    "state": STATE_WAITING, "message": MSG_WAITING}

        # 到期 → 选定目标鱼种（B-2）→ 按 rarity 生成鱼讯三类
        spot_id = str(fs.get("spot_id") or "")
        target = self._pick_target(ctx, spot_id, self._resolve_rng(ctx))
        if target is None:
            return {"ok": False, "reason": "no_species", "bite": False,
                    "state": STATE_WAITING, "message": MSG_NO_SPECIES}
        rarity = target.rarity if isinstance(target.rarity, str) and target.rarity else "normal"
        intent = fish_intent_of(rarity, king_hit=bool(king_hit))
        kind = str(intent["kind"])
        golden = bool(intent["golden"])
        fs["target_species_id"] = target.id
        fs["target_rarity"] = rarity
        fs["kind"] = kind
        fs["golden"] = golden
        fs["bite_ts"] = now
        fs["state"] = STATE_BITE  # S2→S3（TR-03）
        return {
            "ok": True, "bite": True, "kind": kind, "golden": golden,
            "state": STATE_BITE, "target_species_id": target.id,
            "target_rarity": rarity,
            "message": MSG_BITE.format(label=KIND_LABELS.get(kind, kind)),
        }

    def reel_in(self, ctx: MutableMapping[str, Any], choice: object) -> dict:
        """收杆三选一入口（TR-04/05/06/07/08/09）。

        choice: full(满力)/auto(自动)/stop(止损)（细化 §4.1）。
          - stop：不 roll，空收回 S0（TR-06/08；饵已计耗、日计数不减）。
          - full/auto：roll 概率批2 路2C 实现——本路留 roll_hook 注入位，未注入返回
            {ok, choice, state:"ST"} 骨架（roll_pending=True, settle_pending=True，
            fs 记 last 快照供批3 结算跨指令读取）。
          - 决策窗超时（now - bite_ts > carry_sec，carry_sec>0）→ TR-07 SL 跑鱼回 S0
            （饵不返还、日计数不减）。
        simple 模式不实例化 S2/S3 → 拒绝（TC-09/14）。
        """
        fs = self._fish_state_of(ctx)
        mode = self._mode(ctx)
        if mode == "off":
            return {"ok": False, "guard": "GU-01", "reason": "mode_off",
                    "state": str(fs.get("state") or STATE_IDLE), "message": MSG_OFF}
        state = str(fs.get("state") or STATE_IDLE)

        if mode == "simple":
            return {"ok": False, "reason": "simple_no_wait", "choice": None,
                    "state": str(fs.get("state") or STATE_IDLE), "message": MSG_SIMPLE_NO_WAIT}

        if state != STATE_BITE:
            if state == STATE_WAITING:
                return {"ok": False, "reason": "waiting", "choice": None,
                        "state": STATE_WAITING, "message": MSG_WAITING_CANNOT_REEL}
            return {"ok": False, "reason": "no_session", "choice": None,
                    "state": STATE_IDLE, "message": MSG_NO_SESSION}

        if not isinstance(choice, str) or choice not in REEL_CHOICES:
            return {"ok": False, "reason": "invalid_choice", "choice": None,
                    "state": STATE_BITE, "message": MSG_INVALID_CHOICE}

        # 决策窗超时判定（now - bite_ts > carry；carry=0 不限，TR-07）
        now = _now_ts(ctx)
        bite_ts = int(fs.get("bite_ts") or now)
        carry = self._carry_sec_of(ctx)
        if carry > 0 and (now - bite_ts) > carry:
            self._clear_session(fs)  # SL 跑鱼 → 空手回 S0（TR-07/09）
            return {"ok": False, "reason": "timeout", "choice": choice,
                    "state": STATE_LOST, "message": MSG_TIMEOUT_LOST}

        if choice == "stop":
            # TR-06/08：止损不 roll，空收回 S0（饵已计耗不返还、日计数不回滚）
            self._clear_session(fs)
            return {"ok": True, "choice": choice, "state": STATE_REELED,
                    "reeled": False, "message": MSG_STOP}

        # full/auto：roll 概率批2 路2C 实现（本路 roll_hook 注入位/骨架，B-6）
        if self._roll_hook is not None:
            roll_result = self._roll_hook(ctx, fs, choice)
            fs["last"] = {
                "choice": choice, "kind": str(fs.get("kind") or KIND_NIBBLE),
                "golden": bool(fs.get("golden", False)),
                "target_species_id": fs.get("target_species_id"),
                "target_rarity": fs.get("target_rarity"),
                "spot_id": fs.get("spot_id"), "bite_ts": bite_ts,
                "reel_ts": now, "roll": roll_result,
            }
            self._clear_session(fs)
            return {"ok": True, "choice": choice, "state": STATE_REELED, "reeled": True,
                    "roll": roll_result, "settle_pending": True, "message": MSG_REELED}

        # 骨架：批2 路2C / 批3 结算接线（fs 留 last 快照跨指令可结算）
        fs["last"] = {
            "choice": choice, "kind": str(fs.get("kind") or KIND_NIBBLE),
            "golden": bool(fs.get("golden", False)),
            "target_species_id": fs.get("target_species_id"),
            "target_rarity": fs.get("target_rarity"),
            "spot_id": fs.get("spot_id"), "bite_ts": bite_ts, "reel_ts": now,
        }
        self._clear_session(fs)
        return {"ok": True, "choice": choice, "state": STATE_REELED, "reeled": True,
                "roll_pending": True, "settle_pending": True, "message": MSG_REELED}


__all__ = [
    # 状态常量
    "STATE_IDLE", "STATE_CASTING", "STATE_WAITING", "STATE_BITE",
    "STATE_REELED", "STATE_LOST",
    # 鱼讯类常量
    "KIND_NIBBLE", "KIND_TUG", "KIND_VIOLENT", "KIND_LABELS", "RARITY_KIND",
    # 收杆/决策窗
    "REEL_CHOICES", "DEFAULT_CARRY_SEC",
    # 鱼讯意图
    "fish_intent_of",
    # 引擎
    "FishingEngine",
]
