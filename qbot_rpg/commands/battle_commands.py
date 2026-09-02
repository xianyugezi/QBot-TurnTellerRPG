"""战斗指令接线 battle_commands.py（M5-08 · 战斗接线 + 消息合并 · qbot_rpg/commands/battle_commands.py）。

依据：
  - docs/m5_shared_contract.md §二/§五（铁律 2/7/9：一轮=1 条 / 战斗开始=1 条 /
    战斗结束=1 条 / 单次操作 ≤1-2 条、发送走统一出口 Sender、渲染顺序对齐判定顺序）
    + §5.1/§5.2（TurnReport/ActionOutcome 真实字段、P2-8 不直接复用引擎 message）
  - docs/m5_batch_plan.md M5-08（战斗接线 + 消息合并：battle.py 引擎回合结果 →
    battle_render 渲染 → 消息合并 → Sender 统一出口；前缀首行 M5-01
    apply_message_prefix；无裸 send；验收：一轮 1 条/开始 1 条/结束 1 条）
  - docs/细化/细化_3d_消息模板规范.md §3.1（消息合并策略承接表：战斗一轮 1 条
    （玩家行动+怪物反击合并）/ 战斗开始 1 条 / 战斗结束 1 条；单次操作最多 1-2 条）
  - docs/细化/细化_5e_战斗战报格式.md（军规1 前缀只加合并消息首行 / 军规3 单回合单条 /
    军规5 结算一次性：经验/掉落只在战斗结束消息输出一次）
  - qbot_rpg/core/battle.py（引擎 1841 行：start/player_act → TurnReport(outcomes)，
    rewards 由世界层 1g4 消费 result 后统一结算——_settle 注释）
  - qbot_rpg/core/message_format/battle_render.py（BREP-01~25 模板全部就绪；本路只
    装配接线，不改引擎不改模板函数）

职责（细化_3a §1.3 壳层职责 · M5-08 战斗消息装配）：
  ① 引擎回合结果（TurnReport）→ battle_render 渲染（render_battle_start/round/end）；
  ② 消息合并（铁律 2/7/9）：战斗开始=1 条、一轮=1 条（玩家行动+怪物反击合并进
     render_battle_round 单条）、战斗结束=1 条（render_battle_end 含 BREP-24 汇总+
     可选 BREP-25 明细；军规5 结算一次性——经验/掉落经引擎结果注入当轮结算一次）；
  ③ 前缀只加首行（M5-01 apply_message_prefix 统一装配：enabled/per_channel 门控 +
     截断黄提示）；
  ④ 统一出口：全部战斗消息经 Sender 发送（无裸 send，铁律 7）；
  ⑤ 战斗指令（/攻击 /防御 /逃跑 /道具（战斗内））输出走此管线。

战斗 ctx 契约（装配层注入，批次7 装配待接线；注入前本层可纯函数单测直接构造 ctx）：
  ctx["battle_engine"]   BattleEngine 实例（战斗中；None=未进入战斗 → 「❌ 当前没有
                         进行中的战斗」）
  ctx["sender"]          Sender 统一出口（必填；缺省 → 【待接线】RuntimeError）
  ctx["to"]              发送目标（群/私聊 id）
  ctx["channel"]         group/private（缺省 group，前缀 per_channel 门控）
  ctx["player"]          玩家对象/dict（level/name/title 供前缀装配）
  ctx["level"]/["name"]/["title"]  玩家信息直给（player 缺省时兜底）
  ctx["prefix_settings"] message_prefix 段配置（M5-01；None=默认）
  ctx["prefix_extra"]    前缀额外占位符（{"群名":…, "职业":…}，IF01b）
  ctx["skills"]          技能配置 {id: {name,…}}（/攻击 <技能> 解析）
  ctx["items"]           物品配置 {id: {name, actions,…}}（/道具 <物品> 解析）
  ctx["battle_reward_fn"] callable(engine, report, ctx) -> {exp,gold,drops}
                         （世界层 1g4 消费 result 后统一结算；缺省 0/空，本层不自行结算）
  ctx["battle_rewards"]  {exp,gold,drops} 直给（reward_fn 缺省时兜底）
  ctx["battle_hint"]     战斗开始意图/弱点情报行（render_battle_start hint；TC-24）
  ctx["battle_status_changes"] (label, old, new) 序列（BREP-08 状态资源差分行）
  ctx["battle_summary"]  BREP-25 木桩明细（战斗结束消息内联块；普通战斗缺省 None）

--------------------------------------------------------------------------------
【工程补白 · 显式标注】
  1) **不改引擎不改模板函数**（M5-08 只做装配接线）：battle_render 全部模板函数
     原样消费；引擎只经公开 API（start/player_act/battle_state）。
  2) **逃跑/道具无 BREP 模板**（5e 25 条注册表无逃跑/道具行动行）：由本层合成文案
     （对齐 P2-8「对外战报按模板生成」精神，本层为兜底出口）；道具回合复用
     render_battle_round 渲染怪物反击段（剥离玩家 outcome）。
  3) **奖励/掉落由世界层（1g4）消费引擎 result 后统一计算**（battle._settle 注释：
     「奖励/掉落/消息登记由世界层消费 result 后统一执行」）：本层经
     ctx["battle_reward_fn"] 注入读取，不自行结算。
  4) **前缀由 apply_message_prefix 统一装配**（M5-01，铁律 1 前缀只加首行）：传给
     render_* 的对象剥离 level/name/title/prefix_extra（_prefix_free_ns），使
     battle_render 内嵌前缀优雅省略，由本层单一注入，防双前缀。
  5) **战斗外 /攻击 等指令**：ctx["battle_engine"] 为 None → 「❌ 当前没有进行中的
     战斗」（经管线发送 1 条），不触碰引擎/其他指令（铁律 2 单次操作 ≤1-2 条）。
  6) **统一返回格式**：战斗指令 handler 返回 ``{"ok": bool, "sent": List[str],
     "message": str}``——sent = 经 Sender 实际发送的段列表（无裸 send 断言依据）；
     消息合并（铁律 2/7/9）在管线内完成，装配层不再重复发送。
--------------------------------------------------------------------------------
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, cast

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规，与 sender.py 同口径）。
from .prefix_wiring import (
    CHANNEL_GROUP,
    PrefixWiringResult,
    apply_message_prefix,
)
from .router import CommandSpec
from .sender import format_tpl12

# core 层消费（commands → core 正向依赖，G0 矩阵合规）
from qbot_rpg.core.message_format.battle_render import (
    render_battle_end,
    render_battle_round,
    render_battle_start,
)
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）
from qbot_rpg.core.templates.battle_tpl import DEFAULT_TEMPLATES as _BATTLE_TPL  # 兼容导出默认文案

__all__ = [
    # 指令名
    "ATTACK_CMD",
    # 业务文案 key 常量
    "TPL_NO_BATTLE", "TPL_NO_SKILL",
    "TPL_NO_ITEM_ARG", "TPL_NO_ITEM",
    "TPL_FLEE_OK", "TPL_FLEE_FAILED",
    # 回合数据增强
    "EnrichedTurnReport", "enrich_round_report",
    # 前缀装配 / 发送管线
    "apply_battle_prefix", "BattlePipeline",
    # 一轮派发（合并策略落地）
    "dispatch_round",
    # 指令处理器（parsed + ctx → {"ok","sent","message"}）
    "cmd_battle_attack",
    # 装配
    "register_battle_commands",
]

# ---------------------------------------------------------------------------
# 常量：指令名 / 业务文案 key（模板 battle_tpl 分区，渲染统一 tpl_of）
# ---------------------------------------------------------------------------

ATTACK_CMD = "攻击"

# 未进入战斗（铁律 2 单次操作 ≤1-2 条；战斗外指令不受影响，工程补白 5）
_TPL_NO_BATTLE_KEY = "battle_no_battle"

# /攻击 技能解析失败（值域问题，命令合法，不走 TPL-12；对齐 quest「任务不存在」口径）
_TPL_NO_SKILL_KEY = "battle_no_skill"

# /道具 缺物品 / 物品不存在（值域问题，不走 TPL-12）
_TPL_NO_ITEM_ARG_KEY = "battle_no_item_arg"
_TPL_NO_ITEM_KEY = "battle_no_item"

# 逃跑结果（无 BREP 模板，本层合成；工程补白 2）
_TPL_FLEE_OK_KEY = "battle_flee_ok"
_TPL_FLEE_FAILED_KEY = "battle_flee_failed"

# 道具使用行（P2-4 补白合成文案）
_TPL_ITEM_USED_KEY = "battle_item_used"

# 参数为当前地图怪物名 → 开战引导（P2-3）
_TPL_NO_BATTLE_MAP_MONSTER_KEY = "battle_no_battle_map_monster"

# 指令返回 message 元数据（非发送正文；逐字迁移 battle_tpl 分区）
_TPL_RESULT_END_KEY = "battle_result_end"
_TPL_RESULT_ROUND_KEY = "battle_result_round"

# 向后兼容导出（= battle_tpl 默认文案；渲染一律 tpl_of(ctx, _KEY)，内容包可覆盖）
TPL_NO_BATTLE = _BATTLE_TPL[_TPL_NO_BATTLE_KEY]
TPL_NO_SKILL = _BATTLE_TPL[_TPL_NO_SKILL_KEY]
TPL_NO_ITEM_ARG = _BATTLE_TPL[_TPL_NO_ITEM_ARG_KEY]
TPL_NO_ITEM = _BATTLE_TPL[_TPL_NO_ITEM_KEY]
TPL_FLEE_OK = _BATTLE_TPL[_TPL_FLEE_OK_KEY]
TPL_FLEE_FAILED = _BATTLE_TPL[_TPL_FLEE_FAILED_KEY]


# ---------------------------------------------------------------------------
# 回合数据增强（TurnReport → 渲染用 EnrichedTurnReport）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnrichedTurnReport:
    """TurnReport + 接线层注入字段（battle_render 消费；shared_contract §5.1/§5.2）。

    引擎 TurnReport 承载 turn/phases/player/enemy/ended/status/log/outcomes；
    接线层补：enemy_name（BREP-09/15/18 怪物展示名）、player_max_hp/enemy_max_hp
    （BREP-09 操作提示行）、exp/gold/drops（BREP-20 经验与掉落，军规5 只在战斗
    结束消息输出一次）、status_changes（BREP-08 状态资源差分行，D-5D）。
    **不含 level/name/title**——前缀由 apply_message_prefix 统一装配（M5-01，
    铁律 1 前缀只加首行，防双前缀，工程补白 4）。
    """

    turn: int
    phases: Tuple[str, ...]
    player: int
    enemy: int
    ended: bool
    status: Optional[str]
    log: Tuple[Mapping[str, Any], ...] = ()
    outcomes: Tuple[Any, ...] = ()
    enemy_name: str = "怪物"
    player_max_hp: Optional[int] = None
    enemy_max_hp: Optional[int] = None
    exp: int = 0
    gold: int = 0
    drops: Tuple[Any, ...] = ()
    status_changes: Tuple[Any, ...] = ()

    @classmethod
    def from_report(
        cls,
        report: Any,
        *,
        enemy_name: str = "怪物",
        player_max_hp: Optional[int] = None,
        enemy_max_hp: Optional[int] = None,
        exp: int = 0,
        gold: int = 0,
        drops: Sequence[Any] = (),
        status_changes: Sequence[Any] = (),
    ) -> "EnrichedTurnReport":
        """TurnReport → EnrichedTurnReport（补齐接线层字段，其余字段透传）。"""
        return cls(
            turn=int(getattr(report, "turn", 0)),
            phases=tuple(getattr(report, "phases", ()) or ()),
            player=int(getattr(report, "player", 0)),
            enemy=int(getattr(report, "enemy", 0)),
            ended=bool(getattr(report, "ended", False)),
            status=getattr(report, "status", None),
            log=tuple(getattr(report, "log", ()) or ()),
            outcomes=tuple(getattr(report, "outcomes", ()) or ()),
            enemy_name=str(enemy_name or "怪物"),
            player_max_hp=player_max_hp,
            enemy_max_hp=enemy_max_hp,
            exp=int(exp or 0),
            gold=int(gold or 0),
            drops=tuple(drops or ()),
            status_changes=tuple(status_changes or ()),
        )


def enrich_round_report(
    report: Any,
    *,
    enemy_name: str = "怪物",
    player_max_hp: Optional[int] = None,
    enemy_max_hp: Optional[int] = None,
    exp: int = 0,
    gold: int = 0,
    drops: Sequence[Any] = (),
    status_changes: Sequence[Any] = (),
    segments: Optional[Sequence[Mapping[str, Any]]] = None,
    player_action: Optional[Mapping[str, Any]] = None,
    skill_name: Optional[str] = None,
) -> EnrichedTurnReport:
    """TurnReport → EnrichedTurnReport（纯函数，测试/装配可直接消费）。

    outcomes 经 _inject_display_outcomes 注入展示字段（怪物展示名/最大 HP——
    ActionOutcome.target 为战斗侧 "enemy"，非展示名，5e §2.1/§3.1 由接线层注入）；
    segments（P1-3）：本轮玩家多段行动段记录，>1 段注入连段段行（BREP-21）。
    skill_name（M13 6a 路3C）：技能行动的战报技能名，注入玩家 skill outcome。
    """
    outcomes = _inject_display_outcomes(
        getattr(report, "outcomes", ()) or (),
        enemy_name=enemy_name,
        player_max_hp=player_max_hp,
        enemy_max_hp=enemy_max_hp,
        segments=segments,
        player_action=player_action,
        skill_name=skill_name,
    )
    return EnrichedTurnReport(
        turn=int(getattr(report, "turn", 0)),
        phases=tuple(getattr(report, "phases", ()) or ()),
        player=int(getattr(report, "player", 0)),
        enemy=int(getattr(report, "enemy", 0)),
        ended=bool(getattr(report, "ended", False)),
        status=getattr(report, "status", None),
        log=tuple(getattr(report, "log", ()) or ()),
        outcomes=outcomes,
        enemy_name=str(enemy_name or "怪物"),
        player_max_hp=player_max_hp,
        enemy_max_hp=enemy_max_hp,
        exp=int(exp or 0),
        gold=int(gold or 0),
        drops=tuple(drops or ()),
        status_changes=tuple(status_changes or ()),
    )


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _prefix_free_ns(data: Any) -> SimpleNamespace:
    """对象/映射 → SimpleNamespace（render 层 getattr 取数用）；剥离 level/name/title/
    prefix_extra——前缀由 apply_message_prefix 统一装配（M5-01，防双前缀，工程补白 4）。"""
    if data is None:
        return SimpleNamespace()
    if isinstance(data, Mapping):
        d = dict(data)
        for k in ("level", "name", "title", "prefix_extra"):
            d.pop(k, None)
        return SimpleNamespace(**d)
    return data


def _enemy_ns(enemy: Any, *, turn: Optional[int] = None) -> SimpleNamespace:
    """怪物形态 → SimpleNamespace（render 取数：name/hp/max_hp/turn）；剥离前缀键。"""
    ns = _prefix_free_ns(enemy)
    if turn is not None and not hasattr(ns, "turn") and not hasattr(ns, "turns"):
        ns.turn = turn  # SimpleNamespace 允许动态属性（BREP-24 回合数，TC-25）
    return ns


def _player_prefix_fields(ctx: Mapping[str, Any]) -> dict:
    """玩家前缀字段（level/name/title）：ctx["player"] 对象/dict 优先，ctx 直给兜底。"""
    p = ctx.get("player")
    if p is not None and not isinstance(p, Mapping):
        level = getattr(p, "level", None)
        name = getattr(p, "name", None)
        title = getattr(p, "title", None)
        return {
            "level": int(level) if level is not None else int(ctx.get("level") or 1),
            "name": str(name) if name else str(ctx.get("name") or ""),
            "title": str(title) if title is not None else ctx.get("title"),
        }
    return {
        "level": int(ctx.get("level") or 1),
        "name": str(ctx.get("name") or ""),
        "title": ctx.get("title"),
    }


def _sender_of(ctx: Mapping[str, Any]) -> Any:
    """Sender 统一出口解析（M5-08：全部战斗消息经 Sender，无裸 send 铁律 7）。"""
    sender = ctx.get("sender")
    if sender is None:
        raise RuntimeError(
            "【待接线】battle_commands 需要 ctx['sender']（Sender 统一出口，M5-08 装配注入）"
        )
    return sender


def _first_player_outcome(report: Any) -> Optional[Any]:
    """玩家先手行动 outcome（行动类型判定：flee/item 无 BREP 模板，本层特殊出口）。"""
    for oc in getattr(report, "outcomes", ()) or ():
        if getattr(oc, "actor", "") == "player":
            return oc
    return None


def _battle_rewards(
    ctx: Mapping[str, Any],
    engine: Any,
    report: Any,
) -> dict:
    """奖励/掉落解析（世界层 1g4 消费 result 后统一结算；本层只读取不结算，工程补白 3）。

    ctx["battle_reward_fn"](engine, report, ctx) -> {exp,gold,drops} 注入优先；
    ctx["battle_rewards"] dict 直给次之；两者皆无 → 0/空（BREP-20 掉落行省略）。
    """
    fn = ctx.get("battle_reward_fn")
    if callable(fn):
        try:
            raw = fn(engine, report, ctx) or {}
        except Exception:
            raw = {}
    else:
        raw = ctx.get("battle_rewards") or {}
    if not isinstance(raw, Mapping):
        raw = {}
    return {
        "exp": int(raw.get("exp", 0) or 0),
        "gold": int(raw.get("gold", 0) or 0),
        "drops": tuple(raw.get("drops") or ()),
    }


def _without_player_outcomes(report: EnrichedTurnReport) -> SimpleNamespace:
    """剥离玩家行动 outcome 的报告（道具回合：只渲染怪物反击/结算/提示段）。"""
    return SimpleNamespace(
        turn=report.turn, phases=report.phases, player=report.player, enemy=report.enemy,
        ended=report.ended, status=report.status, log=report.log,
        outcomes=tuple(o for o in report.outcomes if getattr(o, "actor", "") != "player"),
        enemy_name=report.enemy_name, player_max_hp=report.player_max_hp,
        enemy_max_hp=report.enemy_max_hp, exp=report.exp, gold=report.gold,
        drops=report.drops, status_changes=report.status_changes,
    )


# ActionOutcome 全字段清单（frozen dataclass 复制用，shared_contract §5.1/§5.2）
_OUTCOME_FIELDS: Tuple[str, ...] = (
    "ok", "seq", "actor", "action_type", "target", "hit", "crit", "blocked",
    "raw_damage", "final_damage", "target_hp", "side_effects", "message",
    "battle_ended", "status",
)


def _outcome_copy(outcome: Any, **overrides: Any) -> SimpleNamespace:
    """ActionOutcome → 字段副本（frozen dataclass 不可原地改；复制为 SimpleNamespace
    并注入展示字段）。渲染层取数 getattr 全兼容（brep 模板只读字段）。"""
    ns = SimpleNamespace()
    for k in _OUTCOME_FIELDS:
        setattr(ns, k, getattr(outcome, k, None))
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _inject_display_outcomes(
    outcomes: Sequence[Any],
    *,
    enemy_name: str,
    player_max_hp: Optional[int],
    enemy_max_hp: Optional[int],
    segments: Optional[Sequence[Mapping[str, Any]]] = None,
    player_action: Optional[Mapping[str, Any]] = None,
    skill_name: Optional[str] = None,
) -> Tuple[Any, ...]:
    """ActionOutcome → 渲染用副本（接线层注入展示字段，M5-08；不改引擎不改模板）。

    ActionOutcome.target 为战斗侧 id（"player"/"enemy"）而非展示名（shared_contract
    §5.1）；5e §2.1/§3.1 的 {目标}/{怪物}/{剩余}/{最大} 展示名与最大 HP 非引擎字段，
    由接线层注入：
      - 玩家行动 outcome：target=怪物展示名、target_max_hp=怪物最大 HP（BREP-02/03/15）；
      - 怪物行动 outcome：attacker_name/actor_name=怪物展示名、player_max_hp=玩家最大 HP
        （BREP-10/11/13/06）；
      - segments（P1-3 连段段行生产可达）：本轮玩家多段行动（连段技能）的段记录序列，
        注入到玩家 outcome，供 _render_combo_segments 输出 BREP-21 段行（>1 段才触发，
        单段走聚合 BREP-02）。target_hp 用聚合末值近似（引擎逐段扣血未导出，段行 HP 示意）。
    其余字段原样复制；无法归类的 outcome 原样透传。
    """
    injected: List[Any] = []
    for oc in outcomes or ():
        actor = str(getattr(oc, "actor", "") or "")
        if actor == "player":
            overrides: dict = dict(target=enemy_name, target_max_hp=enemy_max_hp,
                                   player_max_hp=player_max_hp)
            # 技能名注入（M13 6a 路3C）：玩家技能行动 → 战报显示技能名（BREP-07）。
            # action_name 同注（2026-09-03 实机修复：渲染 _default_action_phrase 优先
            # 读 action_name，只注 skill_name 导致「你skill」裸英文回退）。
            if str(getattr(oc, "action_type", "") or "") == "skill" and skill_name:
                overrides["skill_name"] = skill_name
                overrides["action_name"] = skill_name
            if segments:
                final_hp = getattr(oc, "target_hp", None)
                overrides["segments"] = [
                    {**s, "target": enemy_name,
                     "target_max_hp": enemy_max_hp if enemy_max_hp is not None else final_hp,
                     "target_hp": final_hp}
                    for s in segments
                ]
            injected.append(_outcome_copy(oc, **overrides))
        elif actor == "enemy":
            injected.append(
                _outcome_copy(oc, attacker_name=enemy_name, actor_name=enemy_name,
                              player_max_hp=player_max_hp, target_max_hp=enemy_max_hp)
            )
        else:
            injected.append(oc)
    return tuple(injected)


def _build_segments(snap: Mapping[str, Any], turn: int) -> List[Mapping[str, Any]]:
    """从引擎快照 action_record 构造本轮玩家行动段记录（P1-3 连段段行生产可达）。

    action_record 每段（battle.py L602-612）：seq/turn/phase/actor/action/target/
    rating/damage/ts；段号 = 收集器 seg（累计 index，5e §5.1）。过滤本轮玩家行动，
    段数 >1（连段/多段技能）才返回段记录序列（单段走聚合 BREP-02 单行）。target_hp
    未导出 → 由 _inject_display_outcomes 用聚合末值近似填充。
    """
    ar = snap.get("action_record") or ()
    segs: List[Mapping[str, Any]] = []
    for i, entry in enumerate(ar):
        if not isinstance(entry, Mapping):
            continue
        if entry.get("turn") != turn or entry.get("actor") != "player":
            continue
        dmg = entry.get("damage") if isinstance(entry.get("damage"), Mapping) else {}
        rating = entry.get("rating") if isinstance(entry.get("rating"), Mapping) else {}
        segs.append({
            "seg": i + 1,                                   # 收集器 seg（累计段号）
            "action": str(entry.get("action") or ""),
            "final_damage": int(dmg.get("final", 0) or 0),  # type: ignore[union-attr]
            "target_hp": None,                              # 聚合末值由注入侧填充
            "target_max_hp": None,
            "target": str(entry.get("target") or ""),
            "crit": str(rating.get("crit", "low") or "low"),  # type: ignore[union-attr]
            "blocked": bool(rating.get("blocked", False)),  # type: ignore[union-attr]
            "derived_capped": False,
        })
    return segs if len(segs) > 1 else []


# ---------------------------------------------------------------------------
# 前缀装配（M5-01 apply_message_prefix 委托：战斗消息统一入口）
# ---------------------------------------------------------------------------

def apply_battle_prefix(
    text: str,
    *,
    level: int = 1,
    name: str = "",
    title: Optional[str] = None,
    channel: str = CHANNEL_GROUP,
    prefix_settings: Optional[Mapping[str, object]] = None,
    extra: Optional[Mapping[str, object]] = None,
) -> PrefixWiringResult:
    """前缀首行装配（M5-01 apply_message_prefix 委托，铁律 1 前缀只加首行）。

    多行战报仅首行带前缀（【前缀】L34/L82）；enabled=false / 渠道不符 / 系统豁免 →
    原样正文；截断黄提示（TC-13）经 PrefixWiringResult.hint 返回，不阻断正文。
    """
    return apply_message_prefix(
        text,
        level=level,
        name=name,
        title=title,
        channel=channel,
        settings=prefix_settings,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# 发送管线 BattlePipeline（合并策略 + 前缀 + Sender 统一出口）
# ---------------------------------------------------------------------------

class BattlePipeline:
    """战斗消息统一出口（M5-08 装配接线 · 铁律 2/7/9）。

    合并策略（3d §3.1 承接表）：战斗开始=1 条（render_battle_start）/ 一轮=1 条
    （render_battle_round，玩家行动+怪物反击合并，军规3）/ 战斗结束=1 条
    （render_battle_end 含 BREP-24 汇总+可选 BREP-25 明细，军规5 结算一次性）；
    单次操作 ≤1-2 条。全部消息经 Sender 发送（无裸 send，铁律 7）；前缀只加
    合并消息首行（M5-01 apply_message_prefix，铁律 1/8）。

    :param sender: Sender 统一出口（ctx["sender"]，装配层注入）
    :param to: 缺省发送目标（群/私聊 id；逐次调用 to= 可覆盖）
    :param level/name/title: 玩家前缀信息（apply_message_prefix 装配）
    :param channel: 消息来源渠道（group/private）
    :param prefix_settings: message_prefix 段配置（None=框架默认）
    :param extra: 前缀额外占位符（{"群名":…, "职业":…}，IF01b）
    :param ctx: 战斗 ctx（tpl_of 模板解析；None/无 templates → 默认模板）
    """

    def __init__(
        self,
        sender: Any,
        *,
        to: Any = None,
        level: int = 1,
        name: str = "",
        title: Optional[str] = None,
        channel: str = CHANNEL_GROUP,
        prefix_settings: Optional[Mapping[str, object]] = None,
        extra: Optional[Mapping[str, object]] = None,
        ctx: Any = None,
    ) -> None:
        self._sender = sender
        self._to = to
        self._level = int(level or 1)
        self._name = str(name or "")
        self._title = title
        self._channel = str(channel or CHANNEL_GROUP)
        self._prefix_settings = prefix_settings
        self._extra = extra
        self._ctx = ctx

    @classmethod
    def from_ctx(cls, ctx: Mapping[str, Any]) -> "BattlePipeline":
        """从战斗 ctx 构造（工程补白 5 契约：sender/player 信息/前缀设置/发送目标）。"""
        f = _player_prefix_fields(ctx)
        return cls(
            _sender_of(ctx),
            to=ctx.get("to"),
            level=f["level"],
            name=f["name"],
            title=f["title"],
            channel=ctx.get("channel") or CHANNEL_GROUP,
            prefix_settings=ctx.get("prefix_settings"),
            extra=ctx.get("prefix_extra"),
            ctx=ctx,
        )

    # -- 发送基元 ------------------------------------------------------------

    def send(self, text: str, *, to: Any = None, prefix: bool = True) -> List[str]:
        """单条发送：前缀首行装配（M5-01）+ Sender 统一出口（无裸 send，铁律 7）。

        prefix=False 时跳过前缀装配（意见一同步：战斗开始消息不渲染前缀行）。
        截断黄提示（PrefixWiringResult.hint，TC-13）作为归属发起群的独立短消息
        追加发送（不阻断正文；前缀截断为边界情形，单次操作仍 ≤2 条，铁律 2）。

        :return: 实际发送的段列表（顺序不颠倒）。
        """
        target = to if to is not None else self._to
        if prefix:
            res = apply_battle_prefix(
                text,
                level=self._level,
                name=self._name,
                title=self._title,
                channel=self._channel,
                prefix_settings=self._prefix_settings,
                extra=self._extra,
            )
        else:
            res = PrefixWiringResult(text=text)
        delivered: List[str] = []
        if res.text:
            delivered.extend(self._sender.send(res.text, to=target))
        if res.hint:
            delivered.extend(self._sender.send(res.hint, to=target))
        return delivered

    # -- 合并策略便捷出口 ------------------------------------------------------

    def send_start(self, player: Any, enemy: Any, *, hint: Optional[str] = None,
                   to: Any = None) -> List[str]:
        """战斗开始独立 1 条（BREP-23 + 意图/弱点情报行 hint；TC-24）。

        意见一同步：战斗开始消息不渲染前缀行（prefix=False，send() 跳过前缀装配，
        与 render_battle_start 去前缀行一致）。player 仅作占位（render_battle_start
        不再消费玩家信息渲染前缀）。
        """
        body = render_battle_start(_prefix_free_ns(player), _enemy_ns(enemy),
                                   hint=hint, ctx=self._ctx)
        return self.send(body, to=to, prefix=False)

    def send_round(self, report: Any, *, to: Any = None) -> List[str]:
        """一轮独立 1 条（玩家行动+怪物反击合并，render_battle_round；军规3/铁律 9）。

        输入为 EnrichedTurnReport（enrich_round_report 产出，承载接线层字段）。
        """
        return self.send(render_battle_round(report, ctx=self._ctx), to=to)

    def send_end(self, player: Any, enemy: Any, winner: str, *,
                 summary: Any = None, to: Any = None,
                 status: Optional[str] = None, exp: int = 0, gold: int = 0,
                 drops: Any = None, enemy_name: Optional[str] = None,
                 final_damage: int = 0) -> List[str]:
        """战斗结束独立 1 条（用户 2026-08-27 拍板结算模板 + BREP-24/25；TC-18/25，铁律 11）。

        **M5 裁决（用户拍板）**：win 结束消息 = 用户结算模板（叙事句回顾最后一击
        `您对{怪物}造成了{伤害}点伤害！{怪物}已死亡。` + 获得经验/金币分行 + 战利品
        列表），不含 `✅ 战斗胜利！` 横幅与 BREP-24 汇总行；军规5 掉落只输出一次；
        当轮消息只出行动+击杀。lose/draw 保留 BREP-16/18/19 + BREP-24 汇总行。
        final_damage（最后行动伤害，供叙事句）由 dispatch_round 从 report 取末注入。
        """
        body = render_battle_end(
            _prefix_free_ns(player), _enemy_ns(enemy), winner, summary=summary,
            status=status, exp=exp, gold=gold, drops=drops,
            enemy_name=enemy_name or (getattr(enemy, "name", "") if enemy else None),
            final_damage=final_damage, ctx=self._ctx,
        )
        return self.send(body, to=to)

    def send_flee(self, *, ok: bool, to: Any = None) -> List[str]:
        """逃跑结果 1 条（无 BREP 模板，本层合成；工程补白 2）。"""
        key = _TPL_FLEE_OK_KEY if ok else _TPL_FLEE_FAILED_KEY
        return self.send(tpl_of(self._ctx, key), to=to)


# ---------------------------------------------------------------------------
# 一轮派发（合并策略落地：行动+反击合并 1 条；结束追加汇总 1 条）
# ---------------------------------------------------------------------------

def _send_item_round(
    pipeline: BattlePipeline,
    report: EnrichedTurnReport,
    item_name: str,
) -> List[str]:
    """道具回合（无 BREP 行动模板，本层合成；工程补白 2）：

    道具使用行 + 怪物反击（复用 render_battle_round 渲染敌段）合并 1 条。
    道具使用行模板 battle_item_used（battle_tpl 分区，内容包可覆盖）。
    """
    body = tpl_of(pipeline._ctx, _TPL_ITEM_USED_KEY, {"item_name": item_name})
    counter = render_battle_round(_without_player_outcomes(report), ctx=pipeline._ctx)
    if counter:
        body = f"{body}\n{counter}"
    return pipeline.send(body)


def dispatch_round(
    engine: Any,
    report: Any,
    pipeline: BattlePipeline,
    ctx: Mapping[str, Any],
    *,
    player_action: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """一轮消息派发（铁律 2/7/9 合并策略落地）：

      - 常规行动（攻击/技能/防御）→ 行动+反击合并 1 条（render_battle_round）；
      - 逃跑 → 本层合成逃跑结果 1 条（无 BREP 模板）；
      - 道具 → 道具使用行 + 怪物反击合并 1 条（本层合成 + render 敌段）；
      - 战斗结束（report.ended）→ 追加战斗结束汇总 1 条（render_battle_end，
        BREP-24；军规5 掉落已当轮结算一次）。
    单次操作 ≤1-2 条；全部消息经 pipeline（无裸 send，铁律 7）。

    :param engine: BattleEngine（battle_state 取双方 HP/最大 HP/展示名）
    :param report: 引擎 player_act 返回的 TurnReport
    :param pipeline: 统一出口（前缀 + Sender）
    :param ctx: 战斗 ctx（奖励/状态差分/结束明细注入）
    :return: 已发送段列表。
    """
    snap = engine.battle_state()
    p: Mapping[str, Any] = snap.get("player") or {}
    e: Mapping[str, Any] = snap.get("enemy") or {}
    e_name = str(e.get("name") or "怪物")
    reward = _battle_rewards(ctx, engine, report)
    segments = _build_segments(snap, int(getattr(report, "turn", 0)))
    # 技能名注入（M13 6a 路3C）：player_action 含 skill_id → ctx["skills"] 查名
    skill_name = None
    if player_action and str(player_action.get("type") or "") == "skill":
        sid = str(player_action.get("skill_id") or "")
        skills = ctx.get("skills")
        if isinstance(skills, Mapping):
            d = skills.get(sid)
            if isinstance(d, Mapping):
                skill_name = str(d.get("name") or "") or None
    enriched = enrich_round_report(
        report,
        enemy_name=e_name,
        player_max_hp=p.get("max_hp"),
        enemy_max_hp=e.get("max_hp"),
        exp=reward["exp"],
        gold=reward["gold"],
        drops=reward["drops"],
        status_changes=ctx.get("battle_status_changes") or (),
        segments=segments,
        player_action=player_action,
        skill_name=skill_name,
    )
    player_outcome = _first_player_outcome(report)
    atype = str(getattr(player_outcome, "action_type", "") or "") if player_outcome else ""

    delivered: List[str] = []
    if atype == "flee":
        ok = bool(getattr(player_outcome, "ok", False))
        if ok:
            delivered.extend(pipeline.send_flee(ok=True))          # 逃跑成功：战斗结束，1 条
        else:
            # 逃跑失败：战斗继续 → 逃跑结果 + 怪物反击合并 1 条（铁律 2/军规3）
            body = tpl_of(ctx, _TPL_FLEE_FAILED_KEY)
            counter = render_battle_round(_without_player_outcomes(enriched), ctx=ctx)
            if counter:
                body = f"{body}\n{counter}"
            delivered.extend(pipeline.send(body))
    elif atype == "item":
        item_name = str((player_action or {}).get("item_name") or "道具")
        delivered.extend(_send_item_round(pipeline, enriched, item_name))
    else:
        delivered.extend(pipeline.send_round(enriched))

    if report.ended:
        winner = report.status or "draw"
        # M7 N-03 + 3f R-02：怪物击杀接线（battle 引擎无 ctx，落指令层结算点）
        #   - N-03 预置 [事件:怪物击杀] flat（条件引擎读取源；tag=event 不混入 R-02 六类分组）
        #   - 3f R-02 first_kill 首杀（[事件:首杀] nested 按怪物，首见 first_seen=true）
        if winner == "win":
            try:
                from qbot_rpg.core.adventure_log import log_first_kill
                from qbot_rpg.core.event_bus import bump_event
                bump_event(cast(MutableMapping, ctx), "[事件:怪物击杀]",
                           instance={"tag": "event"})
                log_first_kill(
                    cast(MutableMapping, ctx), e_name,
                    monster_id=str(e.get("id") or e.get("monster_id") or e_name),
                )
            except Exception:
                pass
            # M11 批2 路2C（4d G-8）：monster 册首杀点亮——mark_seen(killed=True)；
            # try/except 防图鉴异常吞战斗结算；不新增 send（图鉴为辅助钩子）
            try:
                from qbot_rpg.core.codex import mark_seen as _codex_mark_seen

                mid = str(e.get("id") or e.get("monster_id") or e_name)
                _codex_mark_seen(cast(MutableMapping, ctx), "monster", mid, e_name,
                                 killed=True)
            except Exception:
                pass
            # M11 批2 路2C（4d D-06）：图鉴点亮结算点 → 里程碑阶梯检查（幂等已授不重授）
            try:
                from qbot_rpg.core.codex_milestones import check_milestones

                check_milestones(cast(MutableMapping, ctx))
            except Exception:
                pass
        # 叙事句伤害 = 本轮最后一个玩家行动 outcome 的 final_damage（用户结算模板回顾最后一击）
        last_pd = 0
        for _oc in reversed(tuple(getattr(report, "outcomes", ()) or ())):
            if str(getattr(_oc, "actor", "") or "") == "player":
                last_pd = int(getattr(_oc, "final_damage", 0) or 0)
                break
        delivered.extend(
            pipeline.send_end(
                SimpleNamespace(),
                _enemy_ns(e, turn=report.turn),
                winner,
                summary=ctx.get("battle_summary"),
                status=report.status,
                exp=reward["exp"],
                gold=reward["gold"],
                drops=reward["drops"],
                final_damage=last_pd,
                enemy_name=e_name,          # _prefix_free_ns 剥离 dict name，显式注入
            )
        )
    return delivered


# ---------------------------------------------------------------------------
# 战斗指令处理器（parsed + ctx → {"ok","sent","message"}）
# ---------------------------------------------------------------------------

def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """RUL-08 注册门槛（2026-08-31 QA 修复：/攻击 此前缺门槛，未注册玩家可进入战斗）。

    本地导入避免跨包循环；ctx["registered"] is False → 拦截文案；缺省视为已注册。
    """
    if ctx.get("registered", True) is False:
        from .basic_commands import TPL_REGISTER_GATE  # noqa: PLC0415

        return TPL_REGISTER_GATE
    return None


def _fail(ctx: Mapping[str, Any], text: str) -> dict:
    """错误文案经管线发送（统一出口，无裸 send）。统一返回格式 {ok, sent, message}。"""
    sent = BattlePipeline.from_ctx(ctx).send(text)
    # send:False（同 _run_battle_action）：正文已由 pipeline 发送，阻止 runner 双发
    return {"ok": False, "sent": sent, "message": text, "send": False}


def _run_battle_action(ctx: Mapping[str, Any], action: Mapping[str, Any]) -> dict:
    """执行战斗行动并走消息管线（统一返回格式 {ok, sent, message}，工程补白 6）。

    ctx["battle_engine"] 为 None（未进入战斗）→ 管线发送「❌ 当前没有进行中的战斗」
    1 条（铁律 2 单次操作 ≤1-2 条；战斗外指令不受影响，工程补白 5）。
    """
    engine = ctx.get("battle_engine")
    pipeline = BattlePipeline.from_ctx(ctx)
    if engine is None:
        sent = pipeline.send(tpl_of(ctx, _TPL_NO_BATTLE_KEY))
        return {"ok": False, "sent": sent, "message": tpl_of(ctx, _TPL_NO_BATTLE_KEY)}
    report = engine.player_act(action)
    sent = dispatch_round(engine, report, pipeline, ctx, player_action=action)
    if report.ended:
        message = tpl_of(ctx, _TPL_RESULT_END_KEY, {"status": report.status})
    else:
        message = tpl_of(ctx, _TPL_RESULT_ROUND_KEY, {"turn": report.turn})
    # send:False —— 正文已由 dispatch_round/pipeline 发送（一轮 1 条铁律）；
    # 阻止 runner sender 闭包重复发送 message（processing L202 send 开关，2026-09-02
    # 实机双发修复：此前 runner 再发一遍「第 N 回合结算」造成重复消息）。
    return {"ok": True, "sent": sent, "message": message, "send": False}


def _resolve_skill(ctx: Mapping[str, Any], text: str) -> Optional[str]:
    """/攻击 <技能> 解析：技能 id/名称/序号 → skill_id（ctx["skills"] 配置）。"""
    skills = ctx.get("skills")
    if not isinstance(skills, Mapping):
        return None
    items = list(skills.items())
    for sid, d in items:
        name = d.get("name") if isinstance(d, Mapping) else getattr(d, "name", None)
        if sid == text or str(name) == text:
            return sid
    if text.isdigit():
        idx = int(text)
        if 1 <= idx <= len(items):
            return items[idx - 1][0]
    return None


def _attack_action(parsed: Any, ctx: Mapping[str, Any]) -> Tuple[Optional[dict], Optional[str]]:
    """/攻击 参数 → (action_dict, error|None)：无参 → 当前装配 basic 技能（普攻技能化，
    2026-09-02 用户拍板：普通攻击即技能，不写死硬编码；无装配/无 basic → 引擎普攻兜底）；
    参数 → 技能行动。"""
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        # 普攻技能化：解析当前装配快照的 basic 槽技能（每职业恰 1 个 basic，
        # 由内容包定义——如脊剑士的「脊斩」即其普攻）；无装配/无 basic → 引擎 normal 兜底
        try:
            from qbot_rpg.core.skill_slots_battle import (  # noqa: PLC0415
                _snapshot_of,
                slots_from_snapshot,
            )

            rows = slots_from_snapshot(_snapshot_of(ctx))
            for r in rows:
                if r.get("slot") == "basic":
                    _bsid = str(r.get("skill_id") or "")
                    if _bsid:
                        return {"type": "skill", "skill_id": _bsid}, None
                    break  # basic 占位 skill_id=None → 无普攻技能 → 兜底
        except Exception:  # pragma: no cover - 防御兜底
            pass
        return {"type": "normal"}, None
    if len(args) > 1:
        return None, format_tpl12(_fragment(parsed))
    # M13 批16 路16C：序号优先按装配快照行动位（basic+active 顺序）解析，
    # 未装配技能不进列表（契约 §1.5「按装配快照生成可用技能列表」）；名称/id
    # 仍走全表 _resolve_skill。
    sid: Optional[str] = None
    if str(args[0]).isdigit():
        try:
            from qbot_rpg.core.skill_slots_battle import (  # noqa: PLC0415
                _snapshot_of,
                slots_from_snapshot,
            )

            idx = int(str(args[0]))
            action_rows = [
                r for r in slots_from_snapshot(_snapshot_of(ctx))
                if r.get("slot") in ("basic", "active")
            ]
            if 1 <= idx <= len(action_rows):
                _cand = str(action_rows[idx - 1].get("skill_id") or "")
                sid = _cand or None
        except Exception:  # pragma: no cover - 防御兜底
            pass
        if sid is None:
            sid = _resolve_skill(ctx, str(args[0]))
    else:
        sid = _resolve_skill(ctx, str(args[0]))
    if sid is None:
        # 2026-08-31 QA P2-3：参数为当前地图怪物名（如「攻击 疾风狼」）→ 未开战时
        # 给出明确引导而非「没有这个技能」（开战链路未接线，后续里程碑）。
        if ctx.get("battle_engine") is None and _is_current_map_monster(ctx, str(args[0])):
            return None, tpl_of(ctx, _TPL_NO_BATTLE_MAP_MONSTER_KEY)
        return None, tpl_of(ctx, _TPL_NO_SKILL_KEY)
    # M13 批16 路16C：装配过滤——/攻击 <技能名> 只允许装配内技能（契约 §1.5
    # 「每次进战斗按装配快照生成可用技能列表」；未装配/被动/触发槽技能被拒）。
    # 判定经 core.skill_slots_battle.is_slot_equipped（行动位 = basic+active；
    # passive/trigger 槽不占行动位不可直接施放）。无 skill_slots_state 注入
    # （旧 ctx/未装配）→ False 拒绝（防御性：装配链路缺失时不臆造可用技能）。
    try:
        from qbot_rpg.core.skill_slots_battle import is_slot_equipped  # noqa: PLC0415

        equipped = is_slot_equipped(ctx, sid)
    except Exception:  # pragma: no cover - 防御兜底（模块缺失不崩）
        equipped = False
    if not equipped:
        return None, tpl_of(ctx, _TPL_NO_SKILL_KEY)
    return {"type": "skill", "skill_id": sid}, None


def _is_current_map_monster(ctx: Mapping[str, Any], text: str) -> bool:
    """参数是否为当前地图怪物名（ctx["maps"]+ctx["location"]+ctx["enemies"] 解析）。

    纯函数、无副作用；任何环节缺失 → False（不误伤技能名解析）。
    """
    maps = ctx.get("maps")
    location = ctx.get("location")
    enemies = ctx.get("enemies")
    if not isinstance(maps, (list, tuple)) or not location or not isinstance(enemies, Mapping):
        return False
    cur = next((m for m in maps if str(m.get("id")) == str(location)), None) if isinstance(
        maps[0], Mapping
    ) else None
    if not isinstance(cur, Mapping):
        return False
    rows = cur.get("monsters")
    if not isinstance(rows, (list, tuple)):
        return False
    for row in rows:
        eid = row.get("enemy") if isinstance(row, Mapping) else None
        entry = enemies.get(str(eid)) if eid else None
        name = entry.get("name") if isinstance(entry, Mapping) else None
        if str(eid) == text or str(name) == text:
            return True
    return False


def _resolve_item(ctx: Mapping[str, Any], text: str) -> Optional[Tuple[str, Mapping[str, Any]]]:
    """/道具 <物品> 解析：物品 id/名称 → (item_id, item_def)（ctx["items"] 配置）。"""
    items = ctx.get("items")
    if not isinstance(items, Mapping):
        return None
    for iid, d in items.items():
        name = d.get("name") if isinstance(d, Mapping) else getattr(d, "name", None)
        if iid == text or str(name) == text:
            return iid, (d if isinstance(d, Mapping) else {})
    return None


def _item_action(parsed: Any, ctx: Mapping[str, Any]) -> Tuple[Optional[dict], Optional[str]]:
    """/道具 <物品> → (action_dict, error|None)：经 items.json def 的
    battle_actions/actions 字段构造 L0 动作（引擎 _resolve_item_action 消费）。"""
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return None, tpl_of(ctx, _TPL_NO_ITEM_ARG_KEY)
    if len(args) > 1:
        return None, format_tpl12(_fragment(parsed))
    resolved = _resolve_item(ctx, str(args[0]))
    if resolved is None:
        return None, tpl_of(ctx, _TPL_NO_ITEM_KEY)
    item_id, item_def = resolved
    actions = list(item_def.get("battle_actions") or item_def.get("actions") or [])
    item_name = str(item_def.get("name") or item_id)
    return {"type": "item", "item_id": item_id, "actions": actions, "item_name": item_name}, None


def cmd_battle_attack(parsed: Any, ctx: MutableMapping[str, Any]) -> dict:
    """/攻击 [技能]：普攻或技能攻击一轮（玩家行动+怪物反击合并 1 条；
    结束追加战斗结束汇总 1 条，单次操作 ≤2 条）。"""
    if getattr(parsed, "error", False):
        return _fail(ctx, format_tpl12(_fragment(parsed)))
    gate = _gate(ctx)
    if gate is not None:
        return _fail(ctx, gate)
    action, err = _attack_action(parsed, ctx)
    if err is not None:
        return _fail(ctx, err)
    assert action is not None  # err=None → 行动已就绪（类型收窄）
    result = _run_battle_action(ctx, action)
    # G3 续战落档（2026-09-02）：战斗后 session 写（suspend 保留会话+payload 更新 /
    # 结束 release 清会话）——不在 handler 内执行（process_message 事务内不能开
    # 新 tx 嵌套死锁），经 result["_battle_persist"] 由 runner sender post-commit 执行。
    engine = ctx.get("battle_engine")
    sm = ctx.get("session_mgr")
    if engine is not None and sm is not None and result.get("ok"):
        try:
            qid = str(ctx.get("qid") or ctx.get("qq_id") or "")
            if bool(getattr(engine, "finished", False)):
                result["_battle_persist"] = ("release", qid)
            else:
                result["_battle_persist"] = ("suspend", qid, engine.to_snapshot())
        except Exception:  # noqa: BLE001 - 落档失败不阻断响应（下指令仍可恢复旧快照）
            pass
    return result


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次7 待接线）
# ---------------------------------------------------------------------------

def register_battle_commands(router: Any, *, make_context: Optional[Callable[[Any], dict]] = None) -> Any:
    """把 /攻击 /防御 /逃跑 /道具 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 战斗 ctx dict（battle_engine/sender/player/
        prefix_settings/channel/to 等，见模块头 ctx 契约）。None 时 handler 调用抛
        RuntimeError（【待接线】批次7 装配注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】battle_commands.register_battle_commands 需要 make_context"
                "（战斗 ctx 工厂，装配层注入）"
            )
        return make_context(parsed)

    def _wrap(fn: Callable[..., dict]) -> Callable[..., dict]:
        def handler(parsed: Any, *a: Any, **k: Any) -> dict:
            # 优先复用 runner 已构建 ctx（A-03 注入 k["ctx"]；含 sender/player/battle_engine
            # 等完整上下文）——否则回退 _ctx(parsed)（smoke/测试路径，批次7 待接线兜底）。
            # 【2026-08-30 实机修复】此前恒调 _ctx(parsed) → 运行中事件循环内同步调
            # async make_context 报【待接线】；对齐 basic_commands._wrap 注入优先。
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return fn(parsed, injected)
            return fn(parsed, _ctx(parsed))
        return handler

    router.register(CommandSpec(ATTACK_CMD, handler=_wrap(cmd_battle_attack)))
    return router
