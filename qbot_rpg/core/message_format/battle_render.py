"""战斗消息渲染（M1 实装 · 本里程碑仅骨架签名）。

归属：core/message_format（细化_3a §2.1 / §5，原 engine 渲染职责，D-04 归入引擎层）。
M1 实装依据：
  - 细化_1g2_回合时序与拦截链（回合迁移/行动+反击合并语义）
  - 细化_1a_伤害公式数值（伤害结果文案）
  - 细化_5e_战斗战报格式（含检测状态行）
  - 细化_3d_消息模板规范 §1.5/§3.1（前缀首行、一轮战斗仍 1 条消息、合并策略）
    §1.2 TPL-01（前缀）、§2.1 5 条/页（战斗日志流水分页日常见 M1 细化）。

契约约束（即使 M1 实装也必须遵守，见 3a §5.2）：
  - S1：返回 `str`；S2：无 "[CQ:"；S3：无 at/图片/表情段占位；
  - S4：一轮一条消息 —— 玩家行动结算 + 怪物反击结算合并为 1 条字符串；
  - S5：渲染层不截断不吞内容（超长分条是壳层 sender 职责）。
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Tuple

from qbot_rpg.core.message_format.prefix_render import render_prefix

__all__ = [
    "render_battle_start",
    "render_battle_round",
    "render_battle_end",
    # M5-04（BREP-07~09，玩家技能 / 状态差分 / 操作提示行）
    "DEFAULT_MAX_STATUS",
    "first_alive_enemy",
    "format_resource_cur_max",
    "render_action_hint",
    "render_skill_cast",
    "render_status_diff",
]

_NOT_IMPL_MSG = "M1 实装：战斗渲染（细化_1g / 细化_1a / 细化_5e / 细化_3d §三）"


def render_battle_start(
    party: Any,
    enemy: Any,
    hint: Optional[str] = None,
) -> str:
    """战斗开始渲染（围：锁定开战消息；含双方概况与操作提示）。TODO(M1)。"""
    raise NotImplementedError(_NOT_IMPL_MSG)


def render_battle_round(round_result: Any) -> str:
    """战斗一轮渲染（IF31 · 先手→击杀→后手→结算，铁律 9 / 5e §1.2 军规4）。

    输入：引擎 TurnReport（outcomes 流水按行动时序输出）；输出玩家行动+怪物反击
    合并 1 条消息（5e 军规3 单回合单条）。取数口径（shared_contract §5.1）：
    战报伤害 = ActionOutcome.final_damage（拦截链后实际扣血）、目标 HP = target_hp
    （扣血后即时值）；**不直接复用引擎 message**（5e P2-8）。

    本路（M5-03）实装玩家行动基础模板 BREP-01~06（_render_player_* / _render_prefix_line）
    并按行序挂接 M5-04 模板（BREP-07 render_skill_cast / 08 render_status_diff /
    09 render_action_hint，数据经 round_result/outcome 可省略属性注入，缺数据时
    优雅省略，收口接线补齐）；怪物行动/结算/连段模板（BREP-10~22）由并行路
    M5-05/06 提供，经 _render_template 钩子按名接入（未落地时跳过不报错）。BREP-06
    防御受击归属后手行，由 M5-05 依玩家守卫态分发（5e §3.1）。
    """
    outcomes = tuple(getattr(round_result, "outcomes", ()) or ())
    lines: List[str] = []

    # BREP-01 前缀行（D1，首行；委托 prefix_render.render_prefix，5e §1.5）
    prefix = _render_prefix_line(round_result)
    if prefix:
        lines.append(prefix)

    # 行序 = 回合死亡判定顺序执行序（军规4，数值层 L44-72）：先手→击杀→后手→结算
    for oc in outcomes:
        actor = str(getattr(oc, "actor", "") or "")
        if actor == "player":
            combo = _render_combo_segments(oc)                     # M5-06 BREP-21（段行，每段独立行）
            if combo:
                lines.extend(combo)                                # 连段行动：段行替代聚合单行（D-5C）
                settle = _render_combo_settle(oc)                  # M5-06 BREP-22（套完结/鞭尸/提前结束）
                if settle:
                    lines.append(settle)
            else:
                lines.extend(_render_player_action(oc))            # BREP-02~05（+07）
                if int(getattr(oc, "target_hp", 1)) <= 0:          # 扣血后立即查击杀（L54）
                    kill = _render_template("_render_kill_line", oc)  # M5-06 BREP-15
                    if kill:
                        lines.append(kill)
        elif actor == "enemy":
            # 后手行（M5-05 BREP-10~14；玩家防御中受击 → BREP-06，M5-05 分发）
            enemy = _render_template("_render_enemy_action", oc)
            if enemy:
                lines.append(enemy)

    # BREP-08 状态资源差分行（M5-04 render_status_diff，D-5D 只显实际变化轴）
    status_line = _render_status_diff_from_report(round_result)
    if status_line:
        lines.append(status_line)

    # 结算行（M5-06/07：击杀/胜负/经验掉落 BREP-15~20/24；军规5 只结算一次）
    if getattr(round_result, "ended", False):
        settle = _render_template("_render_settlement", round_result)
        if settle:
            lines.append(settle)

    # BREP-09 操作提示行（M5-04 render_action_hint，5e §1.5 战报末行）
    hint = _render_action_hint_from_report(round_result)
    if hint:
        lines.append(hint)

    return "\n".join(lines)


def render_battle_end(
    player: Any,
    enemy: Any,
    winner: str,
    summary: Optional[Any] = None,
) -> str:
    """战斗结束渲染（围：胜负/经验/掉落/存活状态）。TODO(M1)。"""
    raise NotImplementedError(_NOT_IMPL_MSG)


# ---------------------------------------------------------------------------
# M5-04 · BREP-07~09（玩家技能释放 / 状态资源差分行 / 操作提示行）
# 依据：细化_5e_战斗战报格式 §1.4（BREP-07/08/09）+ §2.3（技能释放）+ §1.3（长度控制）
#       + D-5D（状态行只显实际变化轴）+ 开发规则 L509（状态数默认前 5 个，超出追加
#       「还有 N 个状态」）+ shared_contract §5.2（引擎输出源：TurnReport + ActionOutcome）。
# 说明：M5-03 的 render_battle_round 骨架未落盘前，本路先独立实现纯模板函数（P2-8：
#       对外战报一律按 BREP 模板生成，不直接复用引擎 ActionOutcome.message）；
#       收口由主 agent 在 render_battle_round 内对齐挂接。
# ---------------------------------------------------------------------------

# 状态差分默认显示条数上限（开发规则 L509：状态数默认前 5 个，超出追加「还有 N 个状态」）
DEFAULT_MAX_STATUS: int = 5

# 操作提示行尾部指令段（BREP-09，【前缀】L31 原样；排版符号豁免 D-5B）
_ACTION_HINT_TAIL: str = "/攻击[技能] /道具 /防御 /逃跑"


def format_resource_cur_max(label: str, cur: int, max_value: int) -> str:
    """资源「当前/最大」串（BREP-07 括号内资源变化文本的拼装）。

    - 入参：label 资源名（如 MP）；cur 当前值；max_value 最大值。
    - 出参：`MP 22/60` 形态字符串。
    - 示例：format_resource_cur_max("MP", 22, 60) -> "MP 22/60"
    """
    return f"{label} {cur}/{max_value}"


def render_skill_cast(skill_name: str, effect_desc: str, resource_text: str = "") -> str:
    """BREP-07 玩家技能释放行。

    模板：`✅ 你施放{技能}：{效果描述}（{资源变化}）`
    示例：`✅ 你施放治疗术：回复 30 点 HP（MP 22/60）`（MP 消耗 8，落在小技 5-10）
    - resource_text：资源变化（当前/最大，如 `MP 22/60`），可用 format_resource_cur_max 拼装；
      空串时省略括号（无资源消耗的技能不输出空括号）。
    """
    suffix = f"（{resource_text}）" if resource_text else ""
    return f"✅ 你施放{skill_name}：{effect_desc}{suffix}"


def render_status_diff(
    changes: Any,
    max_status: int = DEFAULT_MAX_STATUS,
) -> str:
    """BREP-08 状态资源差分行（`{状态项} {旧值}→{新值}`）。

    - 差分纪律（D-5D）：只渲染实际变化的资源轴——old == new 的项自动跳过，
      传入全量快照也只会输出变化轴（MP/印记/连段/护盾等）。
    - 状态数默认前 max_status（5）个，超出追加「还有 N 个状态」（开发规则 L509）。
    - 入参：changes 为 (label, old, new) 三元组序列，或含 label/old/new 键的 dict 序列。
    - 出参：差分行字符串；无变化项时返回空串（调用方据此省略该行）。
    - 示例：render_status_diff([("MP", 30, 22), ("印记", 0, 2)])
          -> "MP 30→22 ｜ 印记 0→2"
    """
    items: list = []
    for ch in changes or ():
        if isinstance(ch, dict):
            label, old, new = str(ch.get("label", "")), ch.get("old"), ch.get("new")
        else:
            label, old, new = str(ch[0]), ch[1], ch[2]
        if old == new:  # D-5D：只显实际变化轴
            continue
        items.append(f"{label} {old}→{new}")
    if not items:
        return ""
    shown = items[:max_status]
    text = " ｜ ".join(shown)
    rest = len(items) - len(shown)
    if rest > 0:
        text += f" ｜ 还有 {rest} 个状态"
    return text


def render_action_hint(
    player_hp: int,
    player_max_hp: int,
    target_hp: int,
    target_max_hp: int,
    target_name: str = "目标",
) -> str:
    """BREP-09 操作提示行（战报末行）。

    模板：`你 {HP}/{最大} | {目标} {HP}/{最大} → /攻击[技能] /道具 /防御 /逃跑`
    示例：`你 21/30 | 史莱姆 7/25 → /攻击[技能] /道具 /防御 /逃跑`
    - 含 /最大 分母（5e 原文，【前缀】L31）；多怪时目标取战场第一个存活怪
      （调用方先用 first_alive_enemy 选取目标快照再传入本函数）。
    """
    return (
        f"你 {player_hp}/{player_max_hp} | {target_name} {target_hp}/{target_max_hp}"
        f" → {_ACTION_HINT_TAIL}"
    )


def first_alive_enemy(enemies: Any) -> Optional[Any]:
    """战场第一个存活怪（BREP-09 多怪目标选取）。

    - 入参：enemies 为怪物 combatant 快照序列（含 hp / dead_mark 字段）。
    - 出参：第一个 hp > 0 且未标记死亡的怪物 dict；全灭/空序列返回 None。
    """
    for e in enemies or ():
        if not isinstance(e, dict):
            continue
        if not bool(e.get("dead_mark", False)) and int(e.get("hp", 0)) > 0:
            return e
    return None


# ---------------------------------------------------------------------------
# M5-03 · BREP-01~06（玩家行动基础模板）
# 依据：细化_5e_战斗战报格式 §1.4（BREP-01/02/03/04/05/06）+ §2.1（攻击/会心/格挡）
#       + §2.2（防御/防御受击）+ TC-07~10 + shared_contract §5.1/§5.2（ActionOutcome
#       真实字段：伤害取 final_damage、目标 HP 取 target_hp；不直接复用引擎 message）。
# 说明：展示名/最大 HP 非 ActionOutcome 字段，经函数参数或 outcome 可省略属性注入；
#       低级会心默认省略（D-5D 差分精神：引擎每击都会心档，low=基线 ×1.3 全显刷屏，
#       TC-09 要求 low 可渲染 → include_low=True，作者可配）。
# ---------------------------------------------------------------------------

# BREP-04 会心档位 → 展示文案（5e §1.4 / 数值层 L25-26：high/mid/low ×2.2/1.7/1.3）
_CRIT_TIERS: Mapping[str, Tuple[str, str]] = {
    "high": ("高阶", "2.2"),
    "mid": ("中阶", "1.7"),
    "low": ("低阶", "1.3"),
}


def _render_prefix_line(
    round_result: Any = None,
    *,
    level: Optional[int] = None,
    name: Optional[str] = None,
    title: Optional[str] = None,
    extra: Optional[Mapping[str, object]] = None,
) -> str:
    """BREP-01 前缀行（D1，首行，5e §1.5）：委托 prefix_render.render_prefix。

    round_result 可省略承载玩家信息（level/name/title/prefix_extra，接线层 M5-08
    注入；默认模板 TPL-01 `Lv[等级].[玩家名] -[称号]-`，【前缀】L22）。玩家信息
    缺失（level 空或 name 空）→ 返回空串（无前缀，由装配层/收口补；前缀不计入
    正文防刷屏长度，【前缀】L17/L97-99）。显式参数优先于 round_result 属性。
    """
    if level is None:
        level = getattr(round_result, "level", None)
    if not name:
        name = getattr(round_result, "name", None)
    if title is None:
        title = getattr(round_result, "title", None)
    if extra is None:
        extra = getattr(round_result, "prefix_extra", None)
    if level is None or not name:
        return ""
    return render_prefix(int(level), str(name), title, extra=extra)


def _default_action_phrase(outcome: Any) -> str:
    """缺省动作短语（BREP-02/03/06 的 {攻击动作}）：优先接线层注入展示名
    action_name，其次普攻（normal/attack）→「攻击」，最后回落 action_type 原词。"""
    name = getattr(outcome, "action_name", None)
    if name:
        return str(name)
    atype = str(getattr(outcome, "action_type", "") or "")
    if atype in ("normal", "attack", ""):
        return "攻击"
    return atype


def _render_crit_block_note(outcome: Any, *, include_low: bool = False) -> str:
    """BREP-04 会心/格挡附注（5e §1.4 / TC-09）：
    会心 → `（会心·{档} {倍率}）`（high/mid/low ×2.2/1.7/1.3）；被格挡 → `（被格挡，伤害减半）`。

    会心优先于格挡（判定顺序 命中→会心→格挡，数值层 L16 写死）；两者并存时都输出。
    低级会心默认省略（D-5D 差分精神：引擎每击都会心档，low=基线 ×1.3 全显刷屏；
    TC-09 要求 low 可渲染 → include_low=True，作者可配），high/mid 始终输出。
    档位取 ActionOutcome.crit（crit_roll 三档 id，battle._action_outcome），倍率表 _CRIT_TIERS。
    """
    notes: List[str] = []
    crit = str(getattr(outcome, "crit", "") or "")
    if crit in _CRIT_TIERS and (crit != "low" or include_low):
        tier, mult = _CRIT_TIERS[crit]
        notes.append(f"（会心·{tier} ×{mult}）")
    if bool(getattr(outcome, "blocked", False)):
        notes.append("（被格挡，伤害减半）")
    return "".join(notes)


def _render_player_hit(
    outcome: Any,
    *,
    action_phrase: Optional[str] = None,
    target_max_hp: Optional[int] = None,
    include_low: bool = False,
) -> str:
    """BREP-02 攻击命中行（5e §2.1 / TC-07）：
    `✅ 你{动作短语}，造成 {伤害} 伤害（{目标} {剩余HP}/{最大HP}）`。

    {目标} 可选仅指动作短语「你{动作短语}」（省略时 `你施放火球术，造成 …`，
    3d D-01 降级口径）；**HP 后缀 `（{目标} {剩余HP}/{最大HP}）` 必须保留**。
    取数（不读引擎 message，5e P2-8）：伤害=final_damage、目标剩余 HP=target_hp
    （ActionOutcome 真实字段，扣血后即时值，数值层 L54）；最大 HP 由调用方/接线层
    提供（ActionOutcome 无该字段），缺省回落当前 HP。会心/格挡附注（BREP-04）拼在
    伤害值与 HP 后缀之间（对齐 5e §2.1 示例 L150）。
    """
    target = str(getattr(outcome, "target", "") or "?")
    damage = int(getattr(outcome, "final_damage", 0))
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        target_max_hp if target_max_hp is not None
        else getattr(outcome, "target_max_hp", hp)
    )
    phrase = action_phrase if action_phrase is not None else _default_action_phrase(outcome)
    note = _render_crit_block_note(outcome, include_low=include_low)  # BREP-04
    return f"✅ 你{phrase}，造成 {damage} 伤害{note}（{target} {hp}/{max_hp}）"


def _render_player_miss(
    outcome: Any,
    *,
    action_phrase: Optional[str] = None,
    target_max_hp: Optional[int] = None,
) -> str:
    """BREP-03 未命中行（5e §2.1 / TC-08）：
    `❌ 未命中：{目标} 闪过了你的{攻击动作}（{目标} {HP}/{最大HP}）`。
    miss → 伤害 0 不扣血（数值层 L24）；{目标} HP 取 target_hp（真实字段）；
    「当前/最大」双值显示（TC-08 示例 `（史莱姆 25/25）`：未命中不扣血，当前=最大）。
    """
    target = str(getattr(outcome, "target", "") or "?")
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        target_max_hp if target_max_hp is not None
        else getattr(outcome, "target_max_hp", hp)
    )
    phrase = action_phrase if action_phrase is not None else _default_action_phrase(outcome)
    return f"❌ 未命中：{target} 闪过了你的{phrase}（{target} {hp}/{max_hp}）"


def _render_player_defend(outcome: Any) -> str:
    """BREP-05 进入防御（5e §2.2 / TC-10）：
    `✅ 你进入防御姿态（本回合受到伤害减半）`（防御指令 ×0.5，数值层 L36）。"""
    return "✅ 你进入防御姿态（本回合受到伤害减半）"


def _render_player_defend_hit(
    outcome: Any,
    *,
    attacker_name: Optional[str] = None,
    action_phrase: Optional[str] = None,
    player_max_hp: Optional[int] = None,
) -> str:
    """BREP-06 防御受击（5e §2.2 / TC-10）：
    `✅ 你防御了{目标}的{攻击动作}，受到 {伤害} 伤害（HP {剩余}/{最大}）`。

    因 ×0.5 生效（数值层 L36），玩家视角标记 ✅；本行归属后手受击，由 M5-05 依玩家
    守卫态分发（5e §3.1「防御中受击走 BREP-06，不再输出 BREP-10」）。取数：伤害=
    final_damage、玩家剩余 HP=target_hp（真实字段）；{目标}（怪物名）与玩家最大 HP
    由调用方/接线层提供（ActionOutcome 无展示名/最大 HP 字段）。
    """
    attacker = attacker_name if attacker_name is not None else str(
        getattr(outcome, "attacker_name", "") or "?"
    )
    damage = int(getattr(outcome, "final_damage", 0))
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        player_max_hp if player_max_hp is not None
        else getattr(outcome, "player_max_hp", hp)
    )
    phrase = action_phrase if action_phrase is not None else _default_action_phrase(outcome)
    return f"✅ 你防御了{attacker}的{phrase}，受到 {damage} 伤害（HP {hp}/{max_hp}）"


def _render_player_action(outcome: Any) -> List[str]:
    """玩家先手行动行集（BREP-02~05 分发，5e §2.1/§2.2）：
    防御指令 → BREP-05；未命中 → BREP-03；非伤害技能 → M5-04 BREP-07（render_skill_cast）
    钩子（数据缺失时省略）；其余命中 → BREP-02（含 BREP-04 会心/格挡附注）。"""
    atype = str(getattr(outcome, "action_type", "") or "")
    if atype in ("guard", "defense"):
        return [_render_player_defend(outcome)]          # BREP-05
    if not bool(getattr(outcome, "hit", False)):
        return [_render_player_miss(outcome)]            # BREP-03
    if atype == "skill" and int(getattr(outcome, "final_damage", 0)) <= 0:
        line = _render_skill_cast_line(outcome)          # M5-04 BREP-07
        if line:
            return [line]
        return []                                        # 数据未接，收口补齐
    return [_render_player_hit(outcome)]                 # BREP-02（+BREP-04）


# ---------------------------------------------------------------------------
# M5-03 挂接 M5-04 模板的数据提取辅助（缺数据优雅省略，收口接线补齐）
# ---------------------------------------------------------------------------

def _render_skill_cast_line(outcome: Any) -> Optional[str]:
    """BREP-07 技能释放行（M5-04 render_skill_cast 委托，5e §2.3）：
    技能名/效果/资源变化经 outcome 可省略属性（skill_name/effect_desc/resource_text）
    注入；缺技能名（数据未接）→ None（调用方省略该行）。"""
    skill_name = getattr(outcome, "skill_name", None)
    if not skill_name:
        return None
    return render_skill_cast(
        str(skill_name),
        str(getattr(outcome, "effect_desc", "") or ""),
        str(getattr(outcome, "resource_text", "") or ""),
    )


def _render_status_diff_from_report(round_result: Any) -> str:
    """BREP-08 状态资源差分行（M5-04 render_status_diff 委托，D-5D 只显实际变化轴）：
    数据源 round_result.status_changes（接线层注入）；无变化数据 → 空串（省略该行）。"""
    changes = getattr(round_result, "status_changes", None)
    if not changes:
        return ""
    return render_status_diff(changes)


def _render_action_hint_from_report(round_result: Any) -> str:
    """BREP-09 操作提示行（M5-04 render_action_hint 委托，5e §1.5 战报末行）：
    数据源 round_result（player/enemy HP + 可省略最大 HP/目标名，接线层注入）；
    缺最大 HP 数据 → 空串（省略提示行，收口接线补齐）。"""
    player_hp = getattr(round_result, "player", None)
    enemy_hp = getattr(round_result, "enemy", None)
    player_max = getattr(round_result, "player_max_hp", None)
    enemy_max = getattr(round_result, "enemy_max_hp", None)
    target_name = str(getattr(round_result, "enemy_name", "") or "目标")
    if player_hp is None or enemy_hp is None or player_max is None or enemy_max is None:
        return ""
    return render_action_hint(
        int(player_hp), int(player_max), int(enemy_hp), int(enemy_max), target_name,
    )


def _render_template(name: str, *args: Any) -> Optional[str]:
    """按名调用并行路模板函数（M5-05/06 的 BREP-10~22）；未实装返回 None。

    并行路收口前调用方不因缺函数报错（优雅跳过对应行）；收口后各模板就位，
    拼接顺序固定（军规4）。仅非空 str 视为有行。
    """
    fn = globals().get(name)
    if fn is None:
        return None
    line = fn(*args)
    return line if isinstance(line, str) and line else None

# ---------------------------------------------------------------------------
# M5-05 · BREP-10~14（怪物行动模板：反击命中/未命中/意图预告/特殊行动/拦截链）
# 依据：细化_5e_战斗战报格式 §1.4（BREP-10/11/12/13/14）+ §3.1~§3.4 + TC-12~15
#       + D-5E（意图预告固定句式）+ shared_contract §5.1/§5.2（ActionOutcome
#       真实字段：伤害取 final_damage、目标 HP 取 target_hp；P2-8 不直接复用引擎
#       message）+ 数值层 L58-61（后手行动：目标死则不反击写死）、L38/L240（拦截链）。
# 挂接：render_battle_round 后手分支经 _render_template("_render_enemy_action", oc)
#       接入；玩家防御中受击 → 分发 BREP-06（5e §3.1），不再输出 BREP-10。
# 取数：{怪物} 展示名（attacker_name/actor_name）与玩家最大 HP（player_max_hp）
#       非 ActionOutcome 字段，由接线层（M5-08）注入，缺省回落「怪物」/当前 HP。
# ---------------------------------------------------------------------------

# 怪物行动 action_type 归类（接线层/行动 AI 注入；未命中识别走 hit 字段兜底）
_INTENT_TYPES: frozenset = frozenset(
    {"charge", "intent", "telegraph", "preview", "read"}
)
_SPECIAL_TYPES: frozenset = frozenset(
    {"special", "rage", "enrage", "summon", "mark", "buff", "heal_enemy"}
)


def _enemy_name(outcome: Any) -> str:
    """怪物展示名解析（后手模板 {怪物}）：优先接线层注入 attacker_name，其次 actor_name；
    缺省「怪物」（真实 ActionOutcome 无展示名字段，M5-08 注入）。"""
    name = getattr(outcome, "attacker_name", None) or getattr(outcome, "actor_name", None)
    return str(name) if name else "怪物"


def _side_effect_int(fx: Mapping[str, object], *keys: str, default: int = 0) -> int:
    """拦截链效果 dict 数值提取（首个可转 int 的键；全缺省 default）。"""
    for k in keys:
        v = fx.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, str, float)):
            return int(v)
    return default


def _render_enemy_hit(
    outcome: Any,
    *,
    attacker_name: Optional[str] = None,
    action_phrase: Optional[str] = None,
    player_max_hp: Optional[int] = None,
) -> str:
    """BREP-10 怪物反击命中（5e §3.1 / TC-12）：
    `❌ {怪物}{攻击动作}，你受到 {伤害} 伤害（HP {剩余}/{最大}）`。

    玩家视角标记 ❌；取数：伤害=final_damage、玩家剩余 HP=target_hp（ActionOutcome
    真实字段，扣血后即时值）；{怪物}（attacker_name/actor_name）与玩家最大 HP
    （player_max_hp）由接线层提供（ActionOutcome 无展示名/最大 HP 字段），缺省回落
    当前 HP。{攻击动作} 取 _default_action_phrase（action_name 优先，普攻→「攻击」）。
    """
    name = attacker_name if attacker_name is not None else _enemy_name(outcome)
    damage = int(getattr(outcome, "final_damage", 0))
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        player_max_hp if player_max_hp is not None
        else getattr(outcome, "player_max_hp", hp)
    )
    phrase = action_phrase if action_phrase is not None else _default_action_phrase(outcome)
    return f"❌ {name}{phrase}，你受到 {damage} 伤害（HP {hp}/{max_hp}）"


def _render_enemy_miss(
    outcome: Any,
    *,
    attacker_name: Optional[str] = None,
    player_max_hp: Optional[int] = None,
) -> str:
    """BREP-11 怪物攻击未命中（5e §3.1）：
    `✅ {怪物}的攻击被你躲开（HP {剩余}/{最大}）`。

    miss → 伤害 0（数值层 L24），对玩家是成功 → 行首 ✅；HP 取 target_hp（真实字段，
    未命中不扣血，当前=剩余）；{怪物}（attacker_name/actor_name）与玩家最大 HP
    （player_max_hp）由接线层提供。
    """
    name = attacker_name if attacker_name is not None else _enemy_name(outcome)
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        player_max_hp if player_max_hp is not None
        else getattr(outcome, "player_max_hp", hp)
    )
    return f"✅ {name}的攻击被你躲开（HP {hp}/{max_hp}）"


def _render_enemy_intent(
    outcome: Any,
    *,
    attacker_name: Optional[str] = None,
) -> Optional[str]:
    """BREP-12 怪物意图预告（5e §3.2 / TC-14，固定句式 D-5E）：
    `{怪物} 蓄力中（下回合发动「{招名}」）`。

    无 emoji；招名取 outcome.intent_skill（接线层注入），缺失 → None（调用方省略该行）；
    预告行不计入怪物回合行动行数（5e §3.2「预告不是行动」）。
    """
    skill = getattr(outcome, "intent_skill", None)
    if not skill:
        return None
    name = attacker_name if attacker_name is not None else _enemy_name(outcome)
    return f"{name} 蓄力中（下回合发动「{skill}」）"


def _render_enemy_special(
    outcome: Any,
    *,
    attacker_name: Optional[str] = None,
) -> str:
    """BREP-13 怪物特殊行动（5e §3.3 / TC-15）：
    `{怪物} {特殊行动}（{效果变化}）`。

    狂暴/召唤/印记等 HP 阈值触发行为（数值层 L149/L292-294）；特殊行动名取
    outcome.special_action（接线层注入，缺省回落动作短语），效果变化取 effect_change
    （纯文字，禁 emoji），空效果不输出空括号。
    """
    name = attacker_name if attacker_name is not None else _enemy_name(outcome)
    act = str(getattr(outcome, "special_action", "") or "")
    if not act:
        act = _default_action_phrase(outcome)
    change = str(getattr(outcome, "effect_change", "") or "")
    suffix = f"（{change}）" if change else ""
    return f"{name} {act}{suffix}"


def _render_interception_lines(outcome: Any) -> List[str]:
    """BREP-14 拦截链效果行（5e §3.4）：
    `{盾} 吸收了 {n} 点伤害` / `反弹 {n} 伤害给{目标}` / `免疫了{效果}`。

    拦截链（减伤→护盾→反弹→吸收→免疫→续行→扣血，数值层 L38/L240）各环节触发时
    输出；数据源 ActionOutcome.side_effects（效果 dict 序列），按 kind/type/effect 键
    归类（absorb/shield / reflect / immune），无法识别环节跳过（不臆造文案）。反弹为
    派生伤害，渲染在段行之后、击杀判定之前（5e §3.4，扣血后即查 L54）。
    """
    lines: List[str] = []
    for fx in getattr(outcome, "side_effects", ()) or ():
        if not isinstance(fx, dict):
            continue
        kind = str(fx.get("kind") or fx.get("type") or fx.get("effect") or "").lower()
        if kind in ("absorb", "shield", "absorption"):
            shield = str(fx.get("name") or fx.get("shield") or "护盾")
            n = _side_effect_int(fx, "amount", "absorbed", "value")
            lines.append(f"{shield} 吸收了 {n} 点伤害")
        elif kind in ("reflect", "counter", "rebound"):
            n = _side_effect_int(fx, "amount", "value")
            target = str(fx.get("target") or "目标")
            lines.append(f"反弹 {n} 伤害给{target}")
        elif kind in ("immune", "immunity"):
            eff = str(fx.get("effect") or fx.get("name") or "该效果")
            lines.append(f"免疫了{eff}")
    return lines


def _render_enemy_action(outcome: Any) -> Optional[str]:
    """怪物后手行动行集（M5-05 BREP-10~14，render_battle_round 后手分支接入）。

    分发序（5e §3.1~§3.4）：玩家防御中受击 → BREP-06（不再输出 BREP-10）；意图预告
    （action_type 蓄力/读招 或携带 intent_skill）→ BREP-12；特殊行动（action_type
    狂暴/召唤/印记 或携带 special_action）→ BREP-13；miss → BREP-11；其余命中 →
    BREP-10；side_effects 触发拦截链环节 → BREP-14 各一行，拼在行动行之后（§3.4）。
    先手击杀的怪物不产出本行——由引擎 enemy_act 保证（数值层 L61 写死，返回 None
    无 outcome，渲染层不收到后手流水即不渲染）。多行以换行拼接（单条消息内多行）。
    """
    lines: List[str] = []
    atype = str(getattr(outcome, "action_type", "") or "")
    hit = bool(getattr(outcome, "hit", False))
    guarding = bool(getattr(outcome, "player_guarding", False)) or bool(
        getattr(outcome, "defending", False)
    )

    if guarding and hit:
        lines.append(_render_player_defend_hit(outcome))          # BREP-06（5e §3.1）
    elif atype in _INTENT_TYPES or getattr(outcome, "intent_skill", None):
        line = _render_enemy_intent(outcome)                      # BREP-12
        if line:
            lines.append(line)
    elif atype in _SPECIAL_TYPES or getattr(outcome, "special_action", None):
        lines.append(_render_enemy_special(outcome))              # BREP-13
    elif not hit:
        lines.append(_render_enemy_miss(outcome))                 # BREP-11
    else:
        lines.append(_render_enemy_hit(outcome))                  # BREP-10

    lines.extend(_render_interception_lines(outcome))             # BREP-14
    if not lines:
        return None
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# M5-06 · BREP-15~22（结算模板：击杀/死亡/胜负/互杀平局/经验掉落 + 连段模板：段行/结算行）
# 依据：细化_5e_战斗战报格式 §4.1~§4.3（结算）+ §5.1~§5.2（连段）+ TC-16~23
#       + 铁律 11 / 军规5（结算一次性：胜负/奖励/掉落当轮事件末尾结算一次，经验/掉落
#       只在战斗结束消息输出一次）+ shared_contract §5.1/§5.2（取数 final_damage /
#       target_hp；P2-8 不直接复用引擎 message）+ 数值层 L50-57/L63-69/L132-133/L171。
# 挂接：render_battle_round 玩家分支经 _render_combo_segments/_render_combo_settle
#       接入（连段段行替代聚合单行，D-5C；段内击杀紧跟 BREP-15，铁律9）；胜负/掉落经
#       _render_template("_render_settlement") 接入（round_result.ended 时当轮事件
#       末尾结算一次，军规5）。击杀行经 _render_template("_render_kill_line") 接入
#       （扣血后立即查，L54）。
# 取数：{怪物} 展示名 / 连段 segments / 经验金币掉落 非 ActionOutcome 字段，由接线层
#       （M5-08）注入；缺省优雅省略（不报错不输出空行，收口接线补齐）。
# ---------------------------------------------------------------------------


def _render_kill_line(outcome: Any) -> Optional[str]:
    """BREP-15 击杀行（5e §4.1 / 数值层 L54）：`✅ 你击败了{怪物}！`。

    紧跟造成击杀的伤害行（render_battle_round 扣血后立即查，target_hp<=0 即调，L54）；
    {怪物} 取 outcome.target（引擎真实字段），缺省「怪物」。兼容 mapping 形态
    （连段段行内部对 seg dict 复用本行，保持击杀文案单一来源）。
    """
    if isinstance(outcome, Mapping):
        target = str(outcome.get("target", "") or outcome.get("target_name", "") or "怪物")
    else:
        target = str(
            getattr(outcome, "target", "") or getattr(outcome, "target_name", "") or "怪物"
        )
    return f"✅ 你击败了{target}！"


def _render_reward_line(exp: int, gold: int, drops: Any = None) -> str:
    """BREP-20 经验与掉落行（5e §4.3 / 数值层 L68/L171）：
    `✅ 获得 经验 {n}、金币 {n}、{素材}×{n}`——多素材以 `、` 分隔；只在战斗结束
    消息输出一次（军规5，调用方 _render_settlement 保证，禁止逐怪逐段刷掉落）。
    drops 为 (名称, 数量) 二元组序列或含 name/素材 + count/n 键的 dict 序列。
    """
    parts: List[str] = [f"经验 {exp}", f"金币 {gold}"]
    for d in drops or ():
        if isinstance(d, Mapping):
            name = str(d.get("name", "") or d.get("素材", "") or "素材")
            count = int(d.get("count", d.get("n", 0)))
        else:
            name, count = str(d[0]), int(d[1])
        parts.append(f"{name}×{count}")
    return "✅ 获得 " + "、".join(parts)


def _render_settlement(round_result: Any) -> Optional[str]:
    """结算行集（M5-06 BREP-16~20；当轮事件末尾结算一次，军规5 / 5e §4）。

    round_result.ended 时由 render_battle_round 调用一次，按引擎终态 status
    （win/lose/draw/escape，battle.py STATUS_*）分发胜负横幅 + 经验掉落：
      - win  → BREP-17 `✅ 战斗胜利！` + BREP-20 经验掉落（仅此一次）；
      - lose → BREP-16 `❌ 你倒下了…` + BREP-18 `❌ 战斗失败：你被{怪物}击败了`
        （玩家死亡 → 失败标记，5e §4.1/§4.2；lose 即玩家死，数值层 L50-51）；
      - draw → BREP-19 `双方同归于尽，战斗以平局结束`（默认 draw；可配
        mutual_kill_result=player_loss 时引擎已落 lose → 走 BREP-18，本层只读
        status 不重复判定，5e §4.2）；
      - escape → 无横幅（不臆造胜负文案）。
    掉落数据（exp/gold/drops）由接线层注入，缺省省略该行；胜利/掉落不输出时
    返回 None（调用方省略结算块）。
    """
    if not bool(getattr(round_result, "ended", False)):
        return None
    status = str(getattr(round_result, "status", "") or "")
    enemy_name = str(getattr(round_result, "enemy_name", "") or "敌人")
    lines: List[str] = []
    if status == "win":
        lines.append("✅ 战斗胜利！")                                # BREP-17
    elif status == "lose":
        lines.append("❌ 你倒下了…")                                 # BREP-16
        lines.append(f"❌ 战斗失败：你被{enemy_name}击败了")          # BREP-18
    elif status == "draw":
        lines.append("双方同归于尽，战斗以平局结束")                  # BREP-19
    # 经验/掉落只在战斗结束消息输出一次（军规5）；仅胜利结算掉落（TC-20 失败无掉落）
    if status == "win" and (
        hasattr(round_result, "exp")
        or hasattr(round_result, "gold")
        or hasattr(round_result, "drops")
    ):
        reward = _render_reward_line(
            int(getattr(round_result, "exp", 0)),
            int(getattr(round_result, "gold", 0)),
            getattr(round_result, "drops", None),
        )
        if reward:
            lines.append(reward)                                     # BREP-20
    if not lines:
        return None
    return "\n".join(lines)


def _render_combo_seg_note(seg: Mapping[str, Any]) -> str:
    """BREP-21 段行附注：BREP-04 会心/格挡（复用 _CRIT_TIERS 档位表，数值层 L25-26）。

    段内判定各跑一次完整管线（L16/L132），段行尾可拼会心附注（5e §5.1 示例
    `（会心·中阶 ×1.7）`）；低级会心默认省略（D-5D 防噪声，对齐 _render_crit_block_note）。
    """
    notes: List[str] = []
    crit = str(seg.get("crit", "") or "")
    if crit in _CRIT_TIERS and crit != "low":
        tier, mult = _CRIT_TIERS[crit]
        notes.append(f"（会心·{tier} ×{mult}）")
    if bool(seg.get("blocked", False)):
        notes.append("（被格挡，伤害减半）")
    return "".join(notes)


def _render_combo_segments(outcome: Any) -> List[str]:
    """BREP-21 连段段行（5e §5.1 / D-5C）：每段独立一行、每段独立取整。

    `第 {N} 段：{动作} 造成 {伤害} 伤害（{目标} {剩余HP}/{最大HP}）`——段号 N 即
    收集器 seg 字段（数值层 L319），段行即收集器记录的人类可读镜像（D-5C）。数据源
    outcome.segments（接线层注入的段记录序列，每段含 seg/action/final_damage/
    target_hp/target_max_hp/target/crit/blocked/derived_capped），缺省 → 空列表
    （调用方走聚合单行路径，收口接线补齐）。

    段内击杀（target_hp<=0）→ 紧跟 BREP-15 击杀行（L54，击杀行紧跟伤害行，铁律9）；
    early_end（BOSS/最后目标死亡，L57/L69）→ 击杀后立即结束，后续段数作废不渲染
    （TC-23，不鞭尸）。派生倍率封顶（≤1.5×，L133）→ 段行尾附 `（派生倍率已达上限
    1.5×）`——纯文字提示，禁 emoji。
    """
    segs = getattr(outcome, "segments", None)
    if not segs:
        return []
    early_end = bool(getattr(outcome, "early_end", False))
    killed = False
    lines: List[str] = []
    for s in segs:
        if not isinstance(s, Mapping):
            continue
        seg_no = int(s.get("seg", len(lines) + 1))
        action = str(s.get("action", "") or "")
        dmg = int(s.get("final_damage", 0))
        target = str(s.get("target", "") or getattr(outcome, "target", "") or "目标")
        hp = int(s.get("target_hp", 0))
        max_hp = int(s.get("target_max_hp", hp))
        note = _render_combo_seg_note(s)                             # BREP-04 附注
        line = f"第 {seg_no} 段：{action} 造成 {dmg} 伤害{note}（{target} {hp}/{max_hp}）"
        if bool(s.get("derived_capped", False)):
            line += "（派生倍率已达上限 1.5×）"                       # 派生封顶附注（L133）
        lines.append(line)
        # 击杀行只渲染一次（致杀一击，L54）：已倒下的鞭尸段不再重复「你击败了…」
        if not killed and hp <= 0:
            kill = _render_kill_line(s)                               # BREP-15 紧跟伤害行
            if kill:
                lines.append(kill)
            killed = True
            if early_end:
                break                                                 # 后续段作废（L57/L69）
    return lines


def _render_combo_settle_line(total_segs: int, remark: str = "") -> str:
    """BREP-22 连段结算行模板：`连段 {N} 段已结算（{备注}）`（5e §5.2）。

    - 正常完结：`连段 3 段已结算`（remark 空串省略括号）；
    - 鞭尸（目标套中击杀，L55-56）：remark=`目标已倒下，下一回合退出战场`；
    - BOSS/最后目标提前结束（L57/L69）：remark=`BOSS 已倒下，战斗结束，后续段数作废`；
    - 派生倍率封顶（L133）：remark=`派生倍率已达上限 1.5×`。
    """
    suffix = f"（{remark}）" if remark else ""
    return f"连段 {total_segs} 段已结算{suffix}"


def _render_combo_settle(outcome: Any) -> Optional[str]:
    """BREP-22 连段结算行（M5-06；outcome.segments 存在时输出一次，5e §5.2）。

    段数 N = 实际执行段数：early_end（BOSS 提前结束）时击杀段即最后执行段，后续段数
    作废不计入（L57/L69，TC-23）；否则 = segments 长度。备注缺省按终态推断：
    early_end → BOSS 提前结束；target_hp<=0（目标已倒下）→ 鞭尸；否则正常完结无备注。
    备注可由接线层经 outcome.combo_remark 显式注入（覆盖推断）。无 segments 数据
    → None（调用方省略该行）。
    """
    segs = getattr(outcome, "segments", None)
    if not segs:
        return None
    early_end = bool(getattr(outcome, "early_end", False))
    total = 0
    for s in segs:
        total += 1
        if early_end and int(s.get("target_hp", 0)) <= 0:
            break                                                     # 击杀段即最后执行段
    remark = str(getattr(outcome, "combo_remark", "") or "")
    if not remark:
        if early_end:
            remark = "BOSS 已倒下，战斗结束，后续段数作废"
        elif int(getattr(outcome, "target_hp", 1)) <= 0:
            remark = "目标已倒下，下一回合退出战场"
    return _render_combo_settle_line(total, remark)
