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

模板配置化（2026-08-31 用户拍板：消息模板不写死代码 → battle_tpl 分区 + tpl_of）：
  全部输出模板字符串集中在 qbot_rpg/core/templates/battle_tpl.py（默认表 + 内容包
  templates.json 覆盖）；渲染处统一 `tpl_of(ctx, "battle_*", {...})`——ctx 为 None
  或缺 ctx["templates"] 时回落默认模板（逐字对齐既有输出，现有测试零破坏）。
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, List, Mapping, Optional, Tuple

from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    page_items,
    render_footer,
    resolve_page,
)
from qbot_rpg.core.message_format.prefix_render import render_prefix
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）

_logger = logging.getLogger("qbot_rpg.battle_render")

__all__ = [
    "render_battle_start",
    "render_battle_round",
    "render_battle_end",
    # CTB 重写（Agent 5 · DataRender）：单次行动 / 批量 NPC 行动 / 玩家 ready 三入口
    "render_battle_action",
    "render_battle_action_batch",
    "render_battle_ready",
    # M5-07（BREP-25 木桩明细分页块，/木桩 翻页消费）
    "render_battle_summary",
    # M5-04（BREP-07~09，玩家技能 / 状态差分 / 操作提示行）
    "DEFAULT_MAX_STATUS",
    "first_alive_enemy",
    "format_resource_cur_max",
    "render_action_hint",
    "render_skill_cast",
    "render_status_diff",
]


def render_battle_start(
    party: Any,
    enemy: Any,
    hint: Optional[str] = None,
    *,
    ctx: Any = None,
) -> str:
    """BREP-23 战斗开始（5e §6.1 / TC-24）：独立 1 条消息（铁律2 / 3d 承接表）。

    `与{怪物}的战斗开始！{怪物} {HP}/{最大HP}` + hint（意图/弱点情报行，如
    `弱点：火（×1.3）`，hint=None 时省略）。意见一同步：战斗开始消息**不再渲染
    前缀行**（去 `Lv35.阿伟` 前缀，只留 与{怪物}的战斗开始！+ 弱点行）；前缀是否
    注入由接线层 BattlePipeline.send() 决定（send_start 已改 prefix=False 跳过）。
    party 参数保留仅兼容既有签名，不再用于渲染前缀。

    取数：{怪物} 展示名取 enemy.name/enemy_name（缺省「怪物」）；HP/最大HP 取
    enemy.hp / enemy.max_hp（最大缺省回落当前 HP）。hint 由接线层提供（类型/元素
    弱点 ×1.3 / BOSS 阶段机制预告 / BREP-12 意图预告），纯文本禁 emoji（D-01）。
    模板 battle_start_line（battle_tpl 分区，内容包可覆盖）。

    兜底：渲染层不崩（CTB 重写后既有入口仍须可用）——enemy 属性缺失/异常时回落
    「怪物」，模板渲染异常时给出最简开始行。
    """
    try:
        name = str(
            getattr(enemy, "name", "") or getattr(enemy, "enemy_name", "") or "怪物"
        )
        hp = int(getattr(enemy, "hp", 0))
        max_hp = int(getattr(enemy, "max_hp", hp))
        lines: List[str] = [tpl_of(ctx, "battle_start_line", {
            "name": name, "hp": hp, "max_hp": max_hp})]   # BREP-23
        if hint:
            lines.append(str(hint))                        # 意图/弱点情报行（可选）
        return "\n".join(lines)
    except Exception:  # pragma: no cover - 渲染层兜底不崩
        _logger.exception("render_battle_start 渲染失败，返回最简开始行")
        return tpl_of(ctx, "battle_start_line", {"name": "怪物", "hp": 0, "max_hp": 0})


def _fold_message_lines(
    lines: List[str],
    *,
    max_lines: int = 16,
    ctx: Any = None,
) -> List[str]:
    """16 行折叠（铁律 11 / 3d §3.2 L184 / 5e TC-06 / TPL-09）：战斗轮消息超限时
    按「正文尾部 → 中间过程行」优先折叠。

    保留首行（前缀/首行动）与末尾关键段（状态差分/结算/操作提示行），折叠中间
    过程行（连段段行/拦截链行等）为省略行 `…（其余 {N} 行已折叠）`。折叠行计入
    ≤16 行上限（3d §3.2 L184）；只折叠不截断（3d §3.2 L183）。BREP-25 明细块的
    分页折叠走 _fold_item_lines（列表页可查），本函数服务战斗轮消息。
    折叠行模板 battle_fold_lines（battle_tpl 分区，内容包可覆盖）。
    """
    if len(lines) <= max_lines:
        return lines
    keep_head = 1          # 首行（前缀/首行动）
    keep_tail = max_lines - keep_head - 1  # 末段关键行（-1 给省略行）
    if keep_tail < 1:
        keep_tail = 1
    head = lines[:keep_head]
    tail = lines[-keep_tail:]
    folded = len(lines) - keep_head - keep_tail
    return head + [tpl_of(ctx, "battle_fold_lines", {"n": folded})] + tail


def render_battle_round(round_result: Any, *, ctx: Any = None) -> str:
    """战斗一轮渲染（IF31 · 先手→击杀→后手→结算，铁律 9 / 5e §1.2 军规4）。

    输入：引擎 TurnReport（outcomes 流水按行动时序输出）；输出玩家行动+怪物反击
    合并 1 条消息（5e 军规3 单行动单条）。取数口径（shared_contract §5.1）：
    战报伤害 = ActionOutcome.final_damage（拦截链后实际扣血）、目标 HP = target_hp
    （扣血后即时值）；**不直接复用引擎 message**（5e P2-8）。

    本路（M5-03）实装玩家行动基础模板 BREP-01~06（_render_player_* / _render_prefix_line）
    并按行序挂接 M5-04 模板（BREP-07 render_skill_cast / 08 render_status_diff /
    09 render_action_hint，数据经 round_result/outcome 可省略属性注入，缺数据时
    优雅省略，收口接线补齐）；怪物行动/结算/连段模板（BREP-10~22）由并行路
    M5-05/06 提供，经 _render_template 钩子按名接入（未落地时跳过不报错）。BREP-06
    防御受击归属后手行，由 M5-05 依玩家守卫态分发（5e §3.1）。

    模板配置化：全部行模板 battle_tpl 分区（ctx 可覆盖，None 回落默认）。

    兜底：渲染层不崩（CTB 重写后本入口仍须可用）——内部异常时返回已装配行。
    """
    lines: List[str] = []
    try:
        outcomes = tuple(getattr(round_result, "outcomes", ()) or ())

        # BREP-01 前缀行（D1，首行；委托 prefix_render.render_prefix，5e §1.5）
        prefix = _render_prefix_line(round_result)
        if prefix:
            lines.append(prefix)

        # 行序 = 回合死亡判定顺序执行序（军规4，数值层 L44-72）：先手→击杀→后手→结算
        for oc in outcomes:
            actor = str(getattr(oc, "actor", "") or "")
            if actor == "player":
                combo = _render_combo_segments(oc, ctx=ctx)        # M5-06 BREP-21（段行）
                if combo:
                    lines.extend(combo)                            # 连段行动：段行替代聚合单行（D-5C）
                    settle = _render_combo_settle(oc, ctx=ctx)     # M5-06 BREP-22
                    if settle:
                        lines.append(settle)
                else:
                    lines.extend(_render_player_action(oc, ctx=ctx))  # BREP-02~05（+07）
                    if int(getattr(oc, "target_hp", 1)) <= 0:      # 扣血后立即查击杀（L54）
                        kill = _render_template("_render_kill_line", oc, ctx=ctx)  # BREP-15
                        if kill:
                            lines.append(kill)
            elif actor == "enemy":
                # 后手行（M5-05 BREP-10~14；玩家防御中受击 → BREP-06，M5-05 分发）
                # 守卫：玩家 HP<=0（已倒下）时不渲染反击行（数值层 L49-52 写死语义防引擎时序异常）
                if int(getattr(round_result, "player", 1) or 1) <= 0:
                    continue
                enemy = _render_template("_render_enemy_action", oc, ctx=ctx)
                if enemy:
                    lines.append(enemy)

        # BREP-08 状态资源差分行（M5-04 render_status_diff，D-5D 只显实际变化轴）
        status_line = _render_status_diff_from_report(round_result, ctx=ctx)
        if status_line:
            lines.append(status_line)

        # 【M5 裁决 P1-1】结算（BREP-16~20）移入 render_battle_end（结束消息一次性输出，
        # TC-18「同一消息含胜利+汇总+掉落」）；当轮只出行动+击杀（BREP-15），不重复结算。

        # BREP-09 操作提示行（M5-04 render_action_hint，5e §1.5 战报末行）
        hint = _render_action_hint_from_report(round_result, ctx=ctx)
        if hint:
            lines.append(hint)

        # 2026-09-09：空模板行统一过滤（miss 播报移除等——模板置空即行消失）
        lines = [ln for ln in lines if isinstance(ln, str) and ln.strip()]
        # 16 行折叠（铁律 11 / 5e TC-06）：超限折叠中间过程行，保留首行 + 末段关键行
        return "\n".join(_fold_message_lines(lines, ctx=ctx))
    except Exception:  # pragma: no cover - 渲染层兜底不崩
        _logger.exception("render_battle_round 渲染失败，返回已装配行")
        return "\n".join(ln for ln in lines if isinstance(ln, str) and ln.strip())


def render_battle_end(
    player: Any,
    enemy: Any,
    winner: str,
    summary: Optional[Any] = None,
    *,
    status: Optional[str] = None,
    exp: int = 0,
    gold: int = 0,
    drops: Any = None,
    enemy_name: Optional[str] = None,
    final_damage: int = 0,
    leveled: Optional[Mapping[str, Any]] = None,
    ctx: Any = None,
) -> str:
    """BREP-17~20 结算 + BREP-24/25 汇总明细（5e §6.2/§6.3 / TC-18/25~27，铁律 11）。

    **M5 裁决（2026-08-27 用户拍板结算模板）**：
      - win：结束消息 = **用户结算模板**（叙事句 `您对{怪物}造成了{伤害}点伤害！{怪物}
        已死亡。` + `获得经验：{exp}` + `获得金币：{gold}` + `获得的战利品如下→` +
        逐行 `{序号}.{名称}×{数量}`），**不含** `✅ 战斗胜利！` 横幅与 BREP-24 汇总行
        （用户模板为主，2026-08-27）；当轮消息只出行动+击杀（BREP-15），结算统一在
        结束消息一次性输出（军规5，结算不重复）。
      - lose/draw：保留 BREP-16/18/19 + BREP-24 汇总行（用户未给失败模板，维持现状）。

    BREP-24 汇总行：`战斗结束：{胜负结果}｜行动数 N｜输入 /战斗记录 查看明细`
    （lose/draw 输出；行动数 N 依次取 enemy/player/summary 的 turns|turn）。
    status 非 None 时渲染结算块（final_damage 供 win 叙事句）；summary 非 None 时
    追加 BREP-25 木桩明细块（≤16 行折叠 TPL-09）。

    返回：单条消息字符串（首行前缀 + 结算 [+ 汇总] [+ 明细块]）。
    模板 battle_end_summary / battle_settle_*（battle_tpl 分区，ctx 可覆盖）。

    兜底：渲染层不崩（CTB 重写后本入口仍须可用）——内部异常时返回已装配行。
    """
    lines: List[str] = []
    try:
        prefix = _render_prefix_line(player)               # 前缀首行（TC-25）
        if prefix:
            lines.append(prefix)
        if status:
            settle = _render_settlement(SimpleNamespace(
                ended=True, status=status,
                exp=exp, gold=gold, drops=drops or (),
                enemy_name=enemy_name or (getattr(enemy, "name", "") if enemy else "") or "敌人",
                final_damage=final_damage,
                leveled=leveled,
            ), ctx=ctx)
            if settle:
                lines.extend(settle.split("\n"))           # 结算块（用户模板 / BREP-16~19）
        # 用户模板：win 无 BREP-24 汇总行（战利品列表为主）；lose/draw 保留汇总反馈
        if status != "win":
            label = _winner_label(winner)                  # 胜利/失败/平局
            turns = _battle_turns(player, enemy, summary)  # 回合数 N（CTB 下 = 行动数）
            lines.append(tpl_of(ctx, "battle_end_summary", {
                "label": label, "turns": turns}))          # BREP-24
        if summary is not None:
            block = _render_summary_block(summary, overhead=len(lines), ctx=ctx)
            if block:
                lines.extend(block)                        # BREP-25 木桩明细块
        return "\n".join(lines)
    except Exception:  # pragma: no cover - 渲染层兜底不崩
        _logger.exception("render_battle_end 渲染失败，返回已装配行")
        return "\n".join(ln for ln in lines if isinstance(ln, str) and ln.strip())


# ---------------------------------------------------------------------------
# M5-04 · BREP-07~09（玩家技能释放 / 状态资源差分行 / 操作提示行）
# 依据：细化_5e_战斗战报格式 §1.4（BREP-07/08/09）+ §2.3（技能释放）+ §1.3（长度控制）
#       + D-5D（状态行只显实际变化轴）+ 开发规则 L509（状态数默认前 5 个，超出追加
#       「还有 N 个状态」）+ shared_contract §5.2（引擎输出源：TurnReport + ActionOutcome）。
# 说明：模板文案 battle_tpl 分区（battle_skill_cast / battle_status_diff_* /
#       battle_action_hint / battle_resource_cur_max，ctx 可覆盖，None 回落默认）。
# ---------------------------------------------------------------------------

# 状态差分默认显示条数上限（开发规则 L509：状态数默认前 5 个，超出追加「还有 N 个状态」）
DEFAULT_MAX_STATUS: int = 5


def format_resource_cur_max(
    label: str,
    cur: int,
    max_value: int,
    *,
    ctx: Any = None,
) -> str:
    """资源「当前/最大」串（BREP-07 括号内资源变化文本的拼装）。

    - 入参：label 资源名（如 MP）；cur 当前值；max_value 最大值。
    - 出参：`MP 22/60` 形态字符串（模板 battle_resource_cur_max，battle_tpl 分区）。
    - 示例：format_resource_cur_max("MP", 22, 60) -> "MP 22/60"
    """
    return tpl_of(ctx, "battle_resource_cur_max",
                  {"label": label, "cur": cur, "max": max_value})


def render_skill_cast(
    skill_name: str,
    effect_desc: str,
    resource_text: str = "",
    *,
    ctx: Any = None,
) -> str:
    """BREP-07 玩家技能释放行。

    模板：`✅ 你施放{技能}：{效果描述}（{资源变化}）`（battle_skill_cast +
    battle_skill_cast_suffix，battle_tpl 分区）。
    示例：`✅ 你施放治疗术：回复 30 点 HP（MP 22/60）`（MP 消耗 8，落在小技 5-10）
    - resource_text：资源变化（当前/最大，如 `MP 22/60`），可用 format_resource_cur_max 拼装；
      空串时省略括号（无资源消耗的技能不输出空括号）。
    """
    line = tpl_of(ctx, "battle_skill_cast",
                  {"skill_name": skill_name, "effect_desc": effect_desc})
    if resource_text:
        line += tpl_of(ctx, "battle_skill_cast_suffix",
                       {"resource_text": resource_text})
    return line


def render_status_diff(
    changes: Any,
    max_status: int = DEFAULT_MAX_STATUS,
    *,
    ctx: Any = None,
) -> str:
    """BREP-08 状态资源差分行（`{状态项} {旧值}→{新值}`）。

    - 差分纪律（D-5D）：只渲染实际变化的资源轴——old == new 的项自动跳过，
      传入全量快照也只会输出变化轴（MP/印记/连段/护盾等）。
    - 状态数默认前 max_status（5）个，超出追加「还有 N 个状态」（开发规则 L509）。
    - 入参：changes 为 (label, old, new) 三元组序列，或含 label/old/new 键的 dict 序列。
    - 出参：差分行字符串；无变化项时返回空串（调用方据此省略该行）。
    - 模板 battle_status_diff_item / battle_status_diff_more（battle_tpl 分区）。
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
        items.append(tpl_of(ctx, "battle_status_diff_item",
                            {"label": label, "old": old, "new": new}))
    if not items:
        return ""
    shown = items[:max_status]
    text = " ｜ ".join(shown)
    rest = len(items) - len(shown)
    if rest > 0:
        text += tpl_of(ctx, "battle_status_diff_more", {"rest": rest})
    return text


def render_action_hint(
    player_hp: int,
    player_max_hp: int,
    target_hp: int,
    target_max_hp: int,
    target_name: str = "目标",
    *,
    player_pos: str = "",
    enemy_pos: str = "",
    ctx: Any = None,
) -> str:
    """BREP-09 操作提示行（战报末行）。

    模板：`你 {HP}/{最大}{方位} | {目标} {HP}/{最大}{方位} → /攻击[技能] /道具 /防御 /逃跑`
    （battle_action_hint + battle_action_hint_tail，battle_tpl 分区）。
    示例：`你 21/30 | 史莱姆 7/25 → /攻击[技能] /道具 /防御 /逃跑`
    - 方位 v0.6 HUD：player_pos/target_pos 中文方位格（缺省空串——无方位战斗省略）
    - 含 /最大 分母（5e 原文，【前缀】L31）；多怪时目标取战场第一个存活怪
      （调用方先用 first_alive_enemy 选取目标快照再传入本函数）。
    """
    tail = tpl_of(ctx, "battle_action_hint_tail")
    return tpl_of(ctx, "battle_action_hint", {
        "player_hp": player_hp, "player_max_hp": player_max_hp,
        "target_name": target_name,
        "player_pos": player_pos, "target_pos": enemy_pos, "target_hp": target_hp,
        "target_max_hp": target_max_hp, "tail": tail,
    })


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
# 模板：battle_crit_note / battle_blocked_note / battle_player_hit / battle_player_miss
#       / battle_player_defend / battle_player_defend_hit（battle_tpl 分区）。
# ---------------------------------------------------------------------------

# BREP-04 会心档位 → 展示文案（5e §1.4 / 数值层 L25-26：high/mid/low ×2.2/1.7/1.3）
_CRIT_TIERS: Mapping[str, Tuple[str, str]] = {
    "high": ("高阶", "2.2"),
    "mid": ("中阶", "1.7"),
    "low": ("低阶", "1.3"),
    # 负会心（怪猎采纳 E19，2026-09-12 批⑤）：负率命中 → 显示「负阶 ×0.75」
    # （非低档，默认渲染；倍率可经 formula.json crit.negative_crit 调，展示值同
    # 既有档位为静态展示常量）。
    "negative": ("负阶", "0.75"),
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
    action_name，其次普攻（normal/attack）→「攻击」，最后回落 action_type 原词。
    2026-09-03：skill 回退也归「攻击」（原回退裸英文 skill——玩家侧已有
    action_name 注入，此分支主要覆盖敌方/未注入场景，显示「攻击」可读）。"""
    name = getattr(outcome, "action_name", None)
    if name:
        return str(name)
    atype = str(getattr(outcome, "action_type", "") or "")
    if atype in ("normal", "attack", "skill", ""):
        return "攻击"
    return atype


def _render_crit_block_note(
    outcome: Any,
    *,
    include_low: bool = False,
    ctx: Any = None,
) -> str:
    """BREP-04 会心/格挡附注（5e §1.4 / TC-09）：
    会心 → `（会心·{档} {倍率}）`（high/mid/low ×2.2/1.7/1.3）；被格挡 → `（被格挡，伤害减半）`。

    会心优先于格挡（判定顺序 命中→会心→格挡，数值层 L16 写死）；两者并存时都输出。
    低级会心默认省略（D-5D 差分精神：引擎每击都会心档，low=基线 ×1.3 全显刷屏；
    TC-09 要求 low 可渲染 → include_low=True，作者可配），high/mid 始终输出。
    档位取 ActionOutcome.crit（crit_roll 三档 id，battle._action_outcome），倍率表 _CRIT_TIERS。
    模板 battle_crit_note / battle_blocked_note（battle_tpl 分区）。
    """
    notes: List[str] = []
    crit = str(getattr(outcome, "crit", "") or "")
    if crit in _CRIT_TIERS and (crit != "low" or include_low):
        tier, mult = _CRIT_TIERS[crit]
        notes.append(tpl_of(ctx, "battle_crit_note", {"tier": tier, "mult": mult}))
    if bool(getattr(outcome, "blocked", False)):
        notes.append(tpl_of(ctx, "battle_blocked_note"))
    # 背击附注（B5 背击闭环，批④）：位于怪背面结算 → 「（背击）」；零数值
    if bool(getattr(outcome, "backstab", False)):
        notes.append(tpl_of(ctx, "battle_backstab_note"))
    return "".join(notes)


def _render_player_hit(
    outcome: Any,
    *,
    action_phrase: Optional[str] = None,
    target_max_hp: Optional[int] = None,
    include_low: bool = False,
    ctx: Any = None,
) -> str:
    """BREP-02 攻击命中行（5e §2.1 / TC-07）：
    `✅ 你{动作短语}，造成 {伤害} 伤害（{目标} {剩余HP}/{最大HP}）`。

    {目标} 可选仅指动作短语「你{动作短语}」（省略时 `你施放火球术，造成 …`，
    3d D-01 降级口径）；**HP 后缀 `（{目标} {剩余HP}/{最大HP}）` 必须保留**。
    取数（不读引擎 message，5e P2-8）：伤害=final_damage、目标剩余 HP=target_hp
    （ActionOutcome 真实字段，扣血后即时值，数值层 L54）；最大 HP 由调用方/接线层
    提供（ActionOutcome 无该字段），缺省回落当前 HP。会心/格挡附注（BREP-04）拼在
    伤害值与 HP 后缀之间（对齐 5e §2.1 示例 L150）。模板 battle_player_hit。
    """
    target = str(getattr(outcome, "target", "") or "?")
    damage = int(getattr(outcome, "final_damage", 0))
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        target_max_hp if target_max_hp is not None
        else getattr(outcome, "target_max_hp", hp)
    )
    phrase = action_phrase if action_phrase is not None else _default_action_phrase(outcome)
    note = _render_crit_block_note(outcome, include_low=include_low, ctx=ctx)  # BREP-04
    return tpl_of(ctx, "battle_player_hit", {
        "action": phrase, "damage": damage, "note": note,
        "target": target, "hp": hp, "max_hp": max_hp})


def _render_player_miss(
    outcome: Any,
    *,
    action_phrase: Optional[str] = None,
    target_max_hp: Optional[int] = None,
    ctx: Any = None,
) -> str:
    """BREP-03 未命中行（5e §2.1 / TC-08）：
    `❌ 未命中：{目标} 闪过了你的{攻击动作}（{目标} {HP}/{最大HP}）`。

    miss → 伤害 0 不扣血（数值层 L24）；{目标} HP 取 target_hp（真实字段）；
    「当前/最大」双值显示（TC-08 示例 `（史莱姆 25/25）`：未命中不扣血，当前=最大）。
    模板 battle_player_miss（battle_tpl 分区）。
    """
    target = str(getattr(outcome, "target", "") or "?")
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        target_max_hp if target_max_hp is not None
        else getattr(outcome, "target_max_hp", hp)
    )
    phrase = action_phrase if action_phrase is not None else _default_action_phrase(outcome)
    return tpl_of(ctx, "battle_player_miss", {
        "target": target, "action": phrase, "hp": hp, "max_hp": max_hp})


def _render_player_defend(outcome: Any, *, ctx: Any = None) -> str:
    """BREP-05 进入防御（5e §2.2 / TC-10）：
    `✅ 你进入防御姿态（本次行动受到伤害减半）`（防御指令 ×0.5，数值层 L36）。
    模板 battle_player_defend（battle_tpl 分区）。
    """
    return tpl_of(ctx, "battle_player_defend")


def _render_player_defend_hit(
    outcome: Any,
    *,
    attacker_name: Optional[str] = None,
    action_phrase: Optional[str] = None,
    player_max_hp: Optional[int] = None,
    ctx: Any = None,
) -> str:
    """BREP-06 防御受击（5e §2.2 / TC-10）：
    `✅ 你防御了{目标}的{攻击动作}，受到 {伤害} 伤害（HP {剩余}/{最大}）`。

    因 ×0.5 生效（数值层 L36），玩家视角标记 ✅；本行归属后手受击，由 M5-05 依玩家
    守卫态分发（5e §3.1「防御中受击走 BREP-06，不再输出 BREP-10」）。取数：伤害=
    final_damage、玩家剩余 HP=target_hp（真实字段）；{目标}（怪物名）与玩家最大 HP
    由调用方/接线层提供（ActionOutcome 无展示名/最大 HP 字段）。
    模板 battle_player_defend_hit（battle_tpl 分区）。
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
    return tpl_of(ctx, "battle_player_defend_hit", {
        "attacker": attacker, "action": phrase, "damage": damage,
        "hp": hp, "max_hp": max_hp})


def _render_player_action(outcome: Any, *, ctx: Any = None) -> List[str]:
    """玩家先手行动行集（BREP-02~05 分发，5e §2.1/§2.2）：
    防御指令 → BREP-05；未命中 → BREP-03；非伤害技能 → M5-04 BREP-07（render_skill_cast）
    钩子（数据缺失时省略）；其余命中 → BREP-02（含 BREP-04 会心/格挡附注）；
    行动行之后追加方位落地行（air_land 事件，方位 v0.6 附录 A Step 3）。"""
    lines: List[str] = []
    atype = str(getattr(outcome, "action_type", "") or "")
    if atype in ("guard", "defense"):
        lines.append(_render_player_defend(outcome, ctx=ctx))  # BREP-05
    elif not bool(getattr(outcome, "hit", False)):
        # 2026-09-07 探针实测：被拒（资源/印记不足）outcome hit=False 且 message
        # 带拒因——原无条件渲染成「未命中」误导（玩家以为 miss 实为被拒）。
        # 拒因消息优先；utility/功能技（transform/revert/辅助——kind != damage）
        # 施放走 skill_cast 而非 miss；空消息才走 miss 模板。
        _msg = str(getattr(outcome, "message", "") or "")
        if _msg and ("被拒" in _msg or "不足" in _msg or "冷却" in _msg):
            lines.append(_msg)
        elif _msg and "形态" in _msg and int(getattr(outcome, "final_damage", 0) or 0) == 0:
            lines.append(_msg)  # 形态切换成功消息（同原 return 直出语义）
        else:
            lines.append(_render_player_miss(outcome, ctx=ctx))  # BREP-03
    elif atype == "skill" and int(getattr(outcome, "final_damage", 0)) <= 0:
        line = _render_skill_cast_line(outcome, ctx=ctx)      # M5-04 BREP-07
        if line:
            lines.append(line)                                # 数据未接则空行集
    else:
        lines.append(_render_player_hit(outcome, ctx=ctx))    # BREP-02（+BREP-04）
    # 方位 v0.6（附录 A Step 3/Step 4）：空中落地事件行（air_policy=land 结算）
    # + 方位变化行（reposition 原子结算）
    lines.extend(_render_air_land_lines(outcome, ctx=ctx))
    lines.extend(_render_air_drop_lines(outcome, ctx=ctx))
    lines.extend(_render_position_changed_lines(outcome, ctx=ctx))
    lines.extend(_render_part_break_lines(outcome, ctx=ctx))
    # 转向行（增补 v1 §三；批④ 时序修订）：行动结算**后**怪才转回面向——置于
    # 行动行之后（「你先在背后得手 → 怪才转身」；原「行动前」序已随 v1.3 修订）
    lines.extend(_render_enemy_turn_lines(outcome, ctx=ctx))
    return lines


# ---------------------------------------------------------------------------
# M5-03 挂接 M5-04 模板的数据提取辅助（缺数据优雅省略，收口接线补齐）
# ---------------------------------------------------------------------------

def _render_skill_cast_line(outcome: Any, *, ctx: Any = None) -> Optional[str]:
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
        ctx=ctx,
    )


def _render_status_diff_from_report(round_result: Any, *, ctx: Any = None) -> str:
    """BREP-08 状态资源差分行（M5-04 render_status_diff 委托，D-5D 只显实际变化轴）：
    数据源 round_result.status_changes（接线层注入）；无变化数据 → 空串（省略该行）。"""
    changes = getattr(round_result, "status_changes", None)
    if not changes:
        return ""
    return render_status_diff(changes, ctx=ctx)


def _render_action_hint_from_report(round_result: Any, *, ctx: Any = None) -> str:
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
    # 方位 v0.6 HUD：双方方位格（中文；缺省空串——旧快照/无方位战斗省略）
    _pp = getattr(round_result, "player_pos", None)
    _ep = getattr(round_result, "enemy_pos", None)
    player_pos = _position_cn(*_pp) if isinstance(_pp, (tuple, list)) and len(_pp) == 2 else ""
    enemy_pos = _position_cn(*_ep) if isinstance(_ep, (tuple, list)) and len(_ep) == 2 else ""
    return render_action_hint(
        int(player_hp), int(player_max), int(enemy_hp), int(enemy_max), target_name,
        player_pos=player_pos, enemy_pos=enemy_pos, ctx=ctx,
    )


def _render_template(name: str, *args: Any, ctx: Any = None) -> Optional[str]:
    """按名调用并行路模板函数（M5-05/06 的 BREP-10~22）；未实装返回 None。

    并行路收口前调用方不因缺函数报错（优雅跳过对应行）；收口后各模板就位，
    拼接顺序固定（军规4）。仅非空 str 视为有行。ctx 透传（tpl_of 渲染用）。
    """
    fn = globals().get(name)
    if fn is None:
        return None
    line = fn(*args, ctx=ctx)
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
# 模板：battle_enemy_hit / battle_enemy_miss / battle_enemy_intent /
#       battle_enemy_special(+_suffix) / battle_intercept_*（battle_tpl 分区）。
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
    ctx: Any = None,
) -> str:
    """BREP-10 怪物反击命中（5e §3.1 / TC-12）：
    `❌ {怪物}{攻击动作}，你受到 {伤害} 伤害（HP {剩余}/{最大}）`。

    玩家视角标记 ❌；取数：伤害=final_damage、玩家剩余 HP=target_hp（ActionOutcome
    真实字段，扣血后即时值）；{怪物}（attacker_name/actor_name）与玩家最大 HP
    （player_max_hp）由接线层提供（ActionOutcome 无展示名/最大 HP 字段），缺省回落
    当前 HP。{攻击动作} 取 _default_action_phrase（action_name 优先，普攻→「攻击」）。
    模板 battle_enemy_hit（battle_tpl 分区）。
    """
    name = attacker_name if attacker_name is not None else _enemy_name(outcome)
    damage = int(getattr(outcome, "final_damage", 0))
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        player_max_hp if player_max_hp is not None
        else getattr(outcome, "player_max_hp", hp)
    )
    phrase = action_phrase if action_phrase is not None else _default_action_phrase(outcome)
    return tpl_of(ctx, "battle_enemy_hit", {
        "name": name, "action": phrase, "damage": damage, "hp": hp, "max_hp": max_hp})


def _render_enemy_position_miss(
    outcome: Any,
    event: Mapping[str, Any],
    *,
    attacker_name: Optional[str] = None,
    player_max_hp: Optional[int] = None,
    ctx: Any = None,
) -> Optional[str]:
    """方位 miss 行（方位 v0.6 §四/附录 A Step 1）：
    `✅ 未命中：{怪物}的攻击未能命中{方位}的你（HP {剩余}/{最大}）`。

    玩家视角 ✅（打空=安全）；{方位} 由事件 side/height 格转中文（显示层映射，模板
    配置化见 battle_tpl battle_enemy_position_miss）；HP 取 target_hp（未扣血=当前）。
    """
    name = attacker_name if attacker_name is not None else _enemy_name(outcome)
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        player_max_hp if player_max_hp is not None
        else getattr(outcome, "player_max_hp", hp)
    )
    pos = _position_cn(str(event.get("side") or "front"),
                       str(event.get("height") or "ground"))
    return tpl_of(ctx, "battle_enemy_position_miss", {
        "name": name, "pos": pos, "hp": hp, "max_hp": max_hp})


def _position_cn(side: str, height: str) -> str:
    """方位格中文显示（显示层映射）：正面/背后/左侧/右侧；空中格追加「上空」（地面不追加）。"""
    _s = {"front": "正面", "back": "背后", "left": "左侧", "right": "右侧"}.get(side, "正面")
    return f"{_s}上空" if height == "air" else _s


def _fx_actor_cn(actor: str, outcome: Any) -> str:
    """方位事件 actor 中文映射（显示层）：player→你；enemy→怪名；未知原样。

    怪名解析：优先注入展示名（attacker_name/actor_name，怪行动自身场景）；玩家
    行动行集里引用怪（被打目标）时回退 outcome.target（M5-08 包装后=怪名中文，
    对齐 BREP-02 命中行 {目标} 同通道）；兜底「怪物」。
    """
    if actor == "player":
        return "你"
    if actor == "enemy":
        name = _enemy_name(outcome)
        if name == "怪物":
            name = str(getattr(outcome, "target", "") or "怪物")
        return name
    return actor


def _render_air_land_lines(outcome: Any, *, ctx: Any = None) -> List[str]:
    """空中落地行（方位 v0.6 §三.6/附录 A Step 3）：outcome.side_effects 的 air_land
    事件（引擎 action_end 后 air_policy=land 结算产出）→ 模板 battle_actor_landed
    一行；actor 名映射：player→你、enemy→怪名（显示层映射，模板配置化）。"""
    out: List[str] = []
    for e in getattr(outcome, "side_effects", ()) or ():
        if not isinstance(e, Mapping) or e.get("type") != "air_land":
            continue
        line = tpl_of(ctx, "battle_actor_landed",
                      {"actor": _fx_actor_cn(str(e.get("actor") or ""), outcome)})
        if line:
            out.append(line)
    return out


def _render_air_drop_lines(outcome: Any, *, ctx: Any = None) -> List[str]:
    """被击落行（跃空风险闭环，批③）：outcome.side_effects 的 air_drop 事件（对空
    必杀命中空中玩家——引擎 `_apply_air_hit_consequences` 产出）→ 模板
    battle_air_dropped 一行；{name} 经显示层怪名映射（与命中行同通道）；零数值
    （隐性口径，玩家不可见）。"""
    out: List[str] = []
    for e in getattr(outcome, "side_effects", ()) or ():
        if not isinstance(e, Mapping) or e.get("type") != "air_drop":
            continue
        line = tpl_of(ctx, "battle_air_dropped",
                      {"name": _fx_actor_cn(str(e.get("attacker") or "enemy"), outcome)})
        if line:
            out.append(line)
    return out


def _render_enemy_turn_lines(outcome: Any, *, ctx: Any = None) -> List[str]:
    """怪转向行（增补 v1 §三 转向事件化；批④ 时序修订）：outcome.side_effects 的
    enemy_turned 事件（引擎「行动结算后怪转回面向」产出）→ 模板 battle_enemy_turned 一行；
    {name} 经显示层怪名映射（与命中行同通道）；零数值（隐性口径，玩家不可见）。"""
    out: List[str] = []
    for e in getattr(outcome, "side_effects", ()) or ():
        if not isinstance(e, Mapping) or e.get("type") != "enemy_turned":
            continue
        line = tpl_of(ctx, "battle_enemy_turned",
                      {"name": _fx_actor_cn(str(e.get("actor") or "enemy"), outcome)})
        if line:
            out.append(line)
    return out


def _render_position_changed_lines(outcome: Any, *, ctx: Any = None) -> List[str]:
    """方位变化行（方位 v0.6 §三.5/附录 A Step 4）：outcome.side_effects 的
    position_changed 事件（reposition/reposition_all 原子产出）→ 模板
    battle_position_changed 一行；{pos} 由事件 side/height 格转中文（显示层映射，
    模板配置化）。"""
    out: List[str] = []
    for e in getattr(outcome, "side_effects", ()) or ():
        if not isinstance(e, Mapping) or e.get("type") != "position_changed":
            continue
        pos = _position_cn(str(e.get("side") or "front"),
                           str(e.get("height") or "ground"))
        line = tpl_of(ctx, "battle_position_changed", {
            "actor": _fx_actor_cn(str(e.get("actor") or ""), outcome), "pos": pos})
        if line:
            out.append(line)
    return out


def _render_part_break_lines(outcome: Any, *, ctx: Any = None) -> List[str]:
    """破位行（方位 v0.6 §三.3/附录 A Step 2/6）：outcome.side_effects 的 part_break
    事件 → 模板 battle_part_broken（knockdown>0 轰然倒地）/ battle_part_broken_no_knock
    （knockdown=0 部位不倒地）一行；{part} 部位中文名由引擎事件携带（part_name），
    {name} 怪名显示层映射（模板配置化）。"""
    out: List[str] = []
    for e in getattr(outcome, "side_effects", ()) or ():
        if not isinstance(e, Mapping) or e.get("type") != "part_break":
            continue
        part = str(e.get("part_name") or e.get("part") or "")
        name = _fx_actor_cn(str(e.get("target") or e.get("actor") or ""), outcome)
        kd = int(e.get("knockdown", 1) or 0)
        key = "battle_part_broken" if kd > 0 else "battle_part_broken_no_knock"
        line = tpl_of(ctx, key, {"part": part, "name": name})
        if line:
            out.append(line)
    return out


def _render_enemy_miss(
    outcome: Any,
    *,
    attacker_name: Optional[str] = None,
    player_max_hp: Optional[int] = None,
    ctx: Any = None,
) -> str:
    """BREP-11 怪物攻击未命中（5e §3.1）：
    `✅ {怪物}的攻击被你躲开（HP {剩余}/{最大}）`。

    miss → 伤害 0（数值层 L24），对玩家是成功 → 行首 ✅；HP 取 target_hp（真实字段，
    未命中不扣血，当前=剩余）；{怪物}（attacker_name/actor_name）与玩家最大 HP
    （player_max_hp）由接线层提供。模板 battle_enemy_miss（battle_tpl 分区）。
    """
    name = attacker_name if attacker_name is not None else _enemy_name(outcome)
    hp = int(getattr(outcome, "target_hp", 0))
    max_hp = int(
        player_max_hp if player_max_hp is not None
        else getattr(outcome, "player_max_hp", hp)
    )
    return tpl_of(ctx, "battle_enemy_miss", {
        "name": name, "hp": hp, "max_hp": max_hp})


def _render_enemy_intent(
    outcome: Any,
    *,
    attacker_name: Optional[str] = None,
    ctx: Any = None,
) -> Optional[str]:
    """BREP-12 怪物意图预告（5e §3.2 / TC-14，固定句式 D-5E）：
    `{怪物} 蓄力中（下次行动发动「{招名}」）`。

    无 emoji；招名取 outcome.intent_skill（接线层注入），缺失 → None（调用方省略该行）；
    预告行不计入怪物行动行数（5e §3.2「预告不是行动」）。
    模板 battle_enemy_intent（battle_tpl 分区）。
    """
    skill = getattr(outcome, "intent_skill", None)
    if not skill:
        return None
    name = attacker_name if attacker_name is not None else _enemy_name(outcome)
    return tpl_of(ctx, "battle_enemy_intent", {"name": name, "skill": str(skill)})


def _render_enemy_special(
    outcome: Any,
    *,
    attacker_name: Optional[str] = None,
    ctx: Any = None,
) -> str:
    """BREP-13 怪物特殊行动（5e §3.3 / TC-15）：
    `{怪物} {特殊行动}（{效果变化}）`。

    狂暴/召唤/印记等 HP 阈值触发行为（数值层 L149/L292-294）；特殊行动名取
    outcome.special_action（接线层注入，缺省回落动作短语），效果变化取 effect_change
    （纯文字，禁 emoji），空效果不输出空括号。
    模板 battle_enemy_special + battle_enemy_special_suffix（battle_tpl 分区）。
    """
    name = attacker_name if attacker_name is not None else _enemy_name(outcome)
    act = str(getattr(outcome, "special_action", "") or "")
    if not act:
        act = _default_action_phrase(outcome)
    change = str(getattr(outcome, "effect_change", "") or "")
    line = tpl_of(ctx, "battle_enemy_special", {"name": name, "action": act})
    if change:
        line += tpl_of(ctx, "battle_enemy_special_suffix", {"change": change})
    return line


def _render_interception_lines(outcome: Any, *, ctx: Any = None) -> List[str]:
    """BREP-14 拦截链效果行（5e §3.4）：
    `{盾} 吸收了 {n} 点伤害` / `反弹 {n} 伤害给{目标}` / `免疫了{效果}`。

    拦截链（减伤→护盾→反弹→吸收→免疫→续行→扣血，数值层 L38/L240）各环节触发时
    输出；数据源 ActionOutcome.side_effects（效果 dict 序列），按 kind/type/effect 键
    归类（absorb/shield / reflect / immune），无法识别环节跳过（不臆造文案）。反弹为
    派生伤害，渲染在段行之后、击杀判定之前（5e §3.4，扣血后即查 L54）。
    模板 battle_intercept_absorb / battle_intercept_reflect / battle_intercept_immune。
    """
    lines: List[str] = []
    for fx in getattr(outcome, "side_effects", ()) or ():
        if not isinstance(fx, dict):
            continue
        kind = str(fx.get("kind") or fx.get("type") or fx.get("effect") or "").lower()
        if kind in ("absorb", "shield", "absorption"):
            shield = str(fx.get("name") or fx.get("shield") or "护盾")
            n = _side_effect_int(fx, "amount", "absorbed", "value")
            lines.append(tpl_of(ctx, "battle_intercept_absorb",
                                {"shield": shield, "n": n}))
        elif kind in ("reflect", "counter", "rebound"):
            n = _side_effect_int(fx, "amount", "value")
            target = str(fx.get("target") or "目标")
            lines.append(tpl_of(ctx, "battle_intercept_reflect",
                                {"n": n, "target": target}))
        elif kind in ("immune", "immunity"):
            eff = str(fx.get("effect") or fx.get("name") or "该效果")
            lines.append(tpl_of(ctx, "battle_intercept_immune", {"effect": eff}))
    return lines


def _render_enemy_action(outcome: Any, *, ctx: Any = None) -> Optional[str]:
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

    # 2026-09-09 防反成功（用户拍板标签制）：parry 事件 → 格挡免伤行（替代伤害行）
    _fx_all = list(getattr(outcome, "side_effects", ()) or ())
    _parry_fx = next((e for e in _fx_all
                      if isinstance(e, Mapping) and e.get("type") == "parry"), None)
    if _parry_fx is not None:
        lines.append(tpl_of(ctx, "battle_parry_success",
                            {"action": _default_action_phrase(outcome)}))
    elif guarding and hit:
        lines.append(_render_player_defend_hit(outcome, ctx=ctx))  # BREP-06（5e §3.1）
    elif atype in _INTENT_TYPES or getattr(outcome, "intent_skill", None):
        line = _render_enemy_intent(outcome, ctx=ctx)              # BREP-12
        if line:
            lines.append(line)
    elif atype in _SPECIAL_TYPES or getattr(outcome, "special_action", None):
        lines.append(_render_enemy_special(outcome, ctx=ctx))      # BREP-13
    elif not hit:
        # 方位 miss（方位 v0.6 附录 A Step 1）：打空（未命中）≠ 躲开——engine 经
        # side_effects position_miss 事件标记（含 side/height 格），渲染专属模板行；
        # 无标记走既有 BREP-11 躲开行（零行为变化）。
        pm = next(
            (e for e in getattr(outcome, "side_effects", ()) or ()
             if isinstance(e, Mapping) and e.get("type") == "position_miss"),
            None,
        )
        if pm is not None:
            line = _render_enemy_position_miss(outcome, pm, ctx=ctx)
            if line:
                lines.append(line)
        else:
            lines.append(_render_enemy_miss(outcome, ctx=ctx))     # BREP-11
    else:
        lines.append(_render_enemy_hit(outcome, ctx=ctx))          # BREP-10

    lines.extend(_render_interception_lines(outcome, ctx=ctx))     # BREP-14
    # 2026-09-09 防反/闪反反击行（用户拍板成功派生）：parry_counter/dodge_counter
    for _e2 in _fx_all:
        if not isinstance(_e2, Mapping):
            continue
        if _e2.get("type") not in ("parry_counter", "dodge_counter"):
            continue
        _sid2 = str(_e2.get("skill_id") or "")
        _nm2 = _sid2
        _sk2 = (ctx or {}).get("skills") if isinstance(ctx, Mapping) else None
        if isinstance(_sk2, Mapping):
            _d2 = _sk2.get(_sid2)
            if isinstance(_d2, Mapping) and _d2.get("name"):
                _nm2 = str(_d2["name"])
        lines.append(tpl_of(ctx, "battle_counter_hit",
                            {"name": _nm2, "damage": int(_e2.get("damage") or 0)}))
    # 方位 v0.6（附录 A Step 3/Step 4）：怪物侧空中落地事件行 + 方位变化行
    # （怪行动 effects reposition/reposition_all 结算，如冲锋/转身）
    lines.extend(_render_air_land_lines(outcome, ctx=ctx))
    lines.extend(_render_air_drop_lines(outcome, ctx=ctx))
    lines.extend(_render_position_changed_lines(outcome, ctx=ctx))
    lines.extend(_render_part_break_lines(outcome, ctx=ctx))
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
# 模板：battle_kill_line / battle_reward_* / battle_settle_* / battle_combo_*（battle_tpl）。
# ---------------------------------------------------------------------------


def _render_kill_line(outcome: Any, *, ctx: Any = None) -> Optional[str]:
    """BREP-15 击杀行（5e §4.1 / 数值层 L54）：`✅ 你击败了{怪物}！`。

    紧跟造成击杀的伤害行（render_battle_round 扣血后立即查，target_hp<=0 即调，L54）；
    {怪物} 取 outcome.target（引擎真实字段），缺省「怪物」。兼容 mapping 形态
    （连段段行内部对 seg dict 复用本行，保持击杀文案单一来源）。
    模板 battle_kill_line（battle_tpl 分区）。
    """
    if isinstance(outcome, Mapping):
        target = str(outcome.get("target", "") or outcome.get("target_name", "") or "怪物")
    else:
        target = str(
            getattr(outcome, "target", "") or getattr(outcome, "target_name", "") or "怪物"
        )
    return tpl_of(ctx, "battle_kill_line", {"target": target})


def _render_reward_line(exp: int, gold: int, drops: Any = None, *, ctx: Any = None) -> str:
    """BREP-20 经验与掉落行（5e §4.3 / 数值层 L68/L171）：
    `✅ 获得 经验 {n}、金币 {n}、{素材}×{n}`——多素材以 `、` 分隔；只在战斗结束
    消息输出一次（军规5，调用方 _render_settlement 保证，禁止逐怪逐段刷掉落）。
    drops 为 (名称, 数量) 二元组序列或含 name/素材 + count/n 键的 dict 序列。
    模板 battle_reward_line / battle_reward_exp / battle_reward_gold / battle_reward_drop。
    """
    # 2026-09-06 硬编码清理：货币名走配置（ctx settings currencies[].name）
    from qbot_rpg.core.reward import currency_display_name  # noqa: PLC0415

    cur_name = currency_display_name(ctx or {}, "coins")
    parts: List[str] = [
        tpl_of(ctx, "battle_reward_exp", {"exp": exp}),
        tpl_of(ctx, "battle_reward_gold", {"gold": gold, "currency": cur_name}),
    ]
    for d in drops or ():
        if isinstance(d, Mapping):
            name = str(d.get("name", "") or d.get("素材", "") or "素材")
            count = int(d.get("count", d.get("n", 0)))
        else:
            name, count = str(d[0]), int(d[1])
        parts.append(tpl_of(ctx, "battle_reward_drop", {"name": name, "count": count}))
    return tpl_of(ctx, "battle_reward_line", {"items": "、".join(parts)})


def _render_settlement(round_result: Any, *, ctx: Any = None) -> Optional[str]:
    """结算行集（用户 2026-08-27 拍板模板；M5-06 BREP-16~20 按用户模板落地）。

    round_result.ended 时由 render_battle_end 调用一次，按引擎终态 status
    （win/lose/draw/escape，battle.py STATUS_*）分发：
      - win  → **用户结算模板**（2026-08-27 拍板）：
        `您对{怪物}造成了{伤害}点伤害！{怪物}已死亡。`（叙事句，回顾最后一击，
        final_damage 由接线层注入，缺省 `您击败了{怪物}！`）
        `获得经验：{exp}` / `获得金币：{gold}` / `获得的战利品如下→`
        + `{序号}.{名称}×{数量}` 逐行（掉落列表，军规5 只输出一次）；
      - lose → BREP-16 `❌ 你倒下了…` + BREP-18 `❌ 战斗失败：你被{怪物}击败了`
        （玩家死亡 → 失败标记，5e §4.1/§4.2；lose 即玩家死，数值层 L50-51）；
      - draw → BREP-19 `双方同归于尽，战斗以平局结束`（默认 draw；可配
        mutual_kill_result=player_loss 时引擎已落 lose → 走 BREP-18，本层只读
        status 不重复判定，5e §4.2）；
      - escape → 无横幅（不臆造胜负文案）。
    掉落数据（exp/gold/drops/final_damage）由接线层注入，缺省省略该行；胜利/掉落
    不输出时返回 None（调用方省略结算块）。
    模板 battle_settle_*（battle_tpl 分区）。
    """
    if not bool(getattr(round_result, "ended", False)):
        return None
    status = str(getattr(round_result, "status", "") or "")
    enemy_name = str(getattr(round_result, "enemy_name", "") or "敌人")
    lines: List[str] = []
    if status == "win":
        # 结算消息（2026-09-09 实机反馈：击杀信息去重——攻击行已含伤害、击败行已报
        # 击杀，narrative 句整行删除，结算只输出奖励）
        lines.append(tpl_of(ctx, "battle_settle_exp", {
            "exp": int(getattr(round_result, "exp", 0) or 0)}))
        from qbot_rpg.core.reward import currency_display_name  # noqa: PLC0415

        lines.append(tpl_of(ctx, "battle_settle_gold", {
            "gold": int(getattr(round_result, "gold", 0) or 0),
            "currency": currency_display_name(ctx or {}, "coins")}))
        drops = getattr(round_result, "drops", None)
        if drops:
            lines.append(tpl_of(ctx, "battle_settle_loot_header"))
            for i, d in enumerate(drops, start=1):
                if isinstance(d, Mapping):
                    name = str(d.get("name", "") or d.get("素材", "") or "素材")
                    count = int(d.get("count", d.get("n", 0)))
                else:
                    name, count = str(d[0]), int(d[1])
                lines.append(tpl_of(ctx, "battle_settle_loot_item", {
                    "index": i, "name": name, "count": count}))
        # 2026-09-03 战斗奖励结算：击杀经验触发升级 → 附升级行（模板可配，
        # 缺省单行合并 HP/MP 回复 + SP；leveled 由接线层注入，None 省略）
        leveled = getattr(round_result, "leveled", None)
        if isinstance(leveled, Mapping):
            level = int(leveled.get("level", 0) or 0)
            level_ups = int(leveled.get("level_ups", 0) or 0)
            sp = int(leveled.get("sp_earned_delta", 0) or 0)
            if level > 0:
                if level_ups > 1:
                    up_line = tpl_of(ctx, "battle_settle_levelup_multi",
                                    {"level": level, "level_ups": level_ups})
                else:
                    up_line = tpl_of(ctx, "battle_settle_levelup", {"level": level})
                if sp > 0:
                    up_line += tpl_of(ctx, "battle_settle_levelup_sp", {"sp": sp})
                lines.append(up_line)
    elif status == "lose":
        lines.append(tpl_of(ctx, "battle_settle_lose"))            # BREP-16
        lines.append(tpl_of(ctx, "battle_settle_lose_fail", {
            "enemy": enemy_name}))                                  # BREP-18
    elif status == "draw":
        lines.append(tpl_of(ctx, "battle_settle_draw"))            # BREP-19
    if not lines:
        return None
    return "\n".join(lines)


def _render_combo_seg_note(seg: Mapping[str, Any], *, ctx: Any = None) -> str:
    """BREP-21 段行附注：BREP-04 会心/格挡（复用 _CRIT_TIERS 档位表，数值层 L25-26）。

    段内判定各跑一次完整管线（L16/L132），段行尾可拼会心附注（5e §5.1 示例
    `（会心·中阶 ×1.7）`）；低级会心默认省略（D-5D 防噪声，对齐 _render_crit_block_note）。
    模板 battle_crit_note / battle_blocked_note（battle_tpl 分区）。
    """
    notes: List[str] = []
    crit = str(seg.get("crit", "") or "")
    if crit in _CRIT_TIERS and crit != "low":
        tier, mult = _CRIT_TIERS[crit]
        notes.append(tpl_of(ctx, "battle_crit_note", {"tier": tier, "mult": mult}))
    if bool(seg.get("blocked", False)):
        notes.append(tpl_of(ctx, "battle_blocked_note"))
    return "".join(notes)


def _render_combo_segments(outcome: Any, *, ctx: Any = None) -> List[str]:
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
    模板 battle_combo_seg / battle_derived_cap / battle_kill_line（battle_tpl 分区）。
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
        if dmg <= 0 and not bool(s.get("blocked", False)):
            # 2026-09-09：0 伤害段（miss/完全防穿）不渲染——无信息量噪音
            continue
        target = str(s.get("target", "") or getattr(outcome, "target", "") or "目标")
        hp = int(s.get("target_hp", 0))
        max_hp = int(s.get("target_max_hp", hp))
        note = _render_combo_seg_note(s, ctx=ctx)                  # BREP-04 附注
        line = tpl_of(ctx, "battle_combo_seg", {
            "seg": seg_no, "action": action, "damage": dmg, "note": note,
            "target": target, "hp": hp, "max_hp": max_hp})
        if bool(s.get("derived_capped", False)):
            line += tpl_of(ctx, "battle_derived_cap")              # 派生封顶附注（L133）
        lines.append(line)
        # 击杀行只渲染一次（致杀一击，L54）：已倒下的鞭尸段不再重复「你击败了…」
        if not killed and hp <= 0:
            kill = _render_kill_line(s, ctx=ctx)                   # BREP-15 紧跟伤害行
            if kill:
                lines.append(kill)
            killed = True
            if early_end:
                break                                              # 后续段作废（L57/L69）
    return lines


def _render_combo_settle_line(
    total_segs: int,
    remark: str = "",
    *,
    ctx: Any = None,
) -> str:
    """BREP-22 连段结算行模板：`连段 {N} 段已结算（{备注}）`（5e §5.2）。

    - 正常完结：`连段 3 段已结算`（remark 空串省略括号）；
    - 鞭尸（目标套中击杀，L55-56）：remark=`目标已倒下，下次行动退出战场`；
    - BOSS/最后目标提前结束（L57/L69）：remark=`BOSS 已倒下，战斗结束，后续段数作废`；
    - 派生倍率封顶（L133）：remark=`派生倍率已达上限 1.5×`。
    模板 battle_combo_settle + battle_combo_settle_suffix（battle_tpl 分区）。
    """
    line = tpl_of(ctx, "battle_combo_settle", {"total": total_segs})
    if remark:
        line += tpl_of(ctx, "battle_combo_settle_suffix", {"remark": remark})
    return line


def _render_combo_settle(outcome: Any, *, ctx: Any = None) -> Optional[str]:
    """BREP-22 连段结算行（M5-06；outcome.segments 存在时输出一次，5e §5.2）。

    段数 N = 实际执行段数：early_end（BOSS 提前结束）时击杀段即最后执行段，后续段数
    作废不计入（L57/L69，TC-23）；否则 = segments 长度。备注缺省按终态推断：
    early_end → BOSS 提前结束；target_hp<=0（目标已倒下）→ 鞭尸；否则正常完结无备注。
    备注可由接线层经 outcome.combo_remark 显式注入（覆盖推断）。无 segments 数据
    → None（调用方省略该行）。
    备注文案模板 battle_combo_remark_boss / battle_combo_remark_waste（battle_tpl）。
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
            remark = tpl_of(ctx, "battle_combo_remark_boss")
        elif int(getattr(outcome, "target_hp", 1)) <= 0:
            remark = tpl_of(ctx, "battle_combo_remark_waste")
    return _render_combo_settle_line(total, remark, ctx=ctx)


# ---------------------------------------------------------------------------
# M5-07 · BREP-23~25（战斗开始/结束/木桩明细：开始 BREP-23 / 结束汇总 BREP-24 /
#        木桩明细块 BREP-25 + 16 行折叠 TPL-09）
# 依据：细化_5e_战斗战报格式 §6.1~§6.3（开始/结束/明细）+ TC-24~27
#       + 铁律 2（战斗开始=1 条 / 战斗结束=1 条）+ 铁律 11（结算一次性 + 16 行
#       折叠 TPL-09，3d D-03/L184）+ shared_contract §5.1（winner=胜负结果、
#       summary 承载 BREP-24/25 汇总与明细）+ m5_batch_plan M5-07。
# 挂接：render_battle_start / render_battle_end（公共入口，M5-08 接线消费）；
#       /木桩 分页浏览经 render_battle_summary（独立公共函数，5 条/页 + 页脚
#       TPL-08 复用 list_render，3d D-02 / 数值层 L348）。
# 取数：{怪物} 展示名 / HP / 行动数 / 收集器聚合（total/max_hit/crits/blocks/
#       items）由接线层注入（非 ActionOutcome 字段），缺省优雅回落（不报错）；
#       明细条目按总伤害降序、占比 = 总伤害占比取整（数值层 L340/L347）。
# 模板：battle_summary_header / battle_summary_item / battle_fold_items（battle_tpl）。
# ---------------------------------------------------------------------------


# 胜负结果中文标签（BREP-24 {胜负结果}，5e §4.2）：win/lose/draw → 胜利/失败/平局
_WINNER_LABELS: Mapping[str, str] = {
    "win": "胜利",
    "lose": "失败",
    "draw": "平局",
    "escape": "逃跑",
}

# BREP-24 明细入口指令（5e §6.2「输入 /战斗记录 查看明细」；折叠 TPL-09 页码同源）
_BREP24_ENTRY_COMMAND = "战斗记录"

# 单条消息总渲染行数上限（3d D-03 / 铁律 11：含前缀/正文/页脚/折叠行 TPL-09）
_FOLD_LIMIT = 16


def _winner_label(winner: Any) -> str:
    """胜负结果中文标签（BREP-24 {胜负结果}）：win/lose/draw → 胜利/失败/平局，
    escape → 逃跑；已是中文（胜利/失败/平局）原样透传；未知回落原文，空回落「?」。"""
    s = str(winner or "").strip()
    if s in _WINNER_LABELS:
        return _WINNER_LABELS[s]
    if s in ("胜利", "失败", "平局", "逃跑"):
        return s
    return s or "?"


def _battle_turns(player: Any, enemy: Any, summary: Any) -> int:
    """行动数提取（BREP-24 {N}）：依次取 enemy/player/summary 的 turns|turn
    （接线层注入；TurnReport.turn 亦可，回合数对照斩杀回合基准 L139-147），
    首个非负整数生效；全缺省回落 0。"""
    for obj in (enemy, player, summary):
        if obj is None:
            continue
        for attr in ("turns", "turn"):
            v = obj.get(attr) if isinstance(obj, Mapping) else getattr(obj, attr, None)
            if isinstance(v, int) and v >= 0:
                return v
    return 0


def _summary_field(summary: Any, *keys: str, default: int = 0) -> int:
    """收集器聚合字段提取（BREP-25）：Mapping 键 / 对象属性双形态，布尔跳过；
    首个可转 int 的键生效（对齐 _side_effect_int 口径）。"""
    for k in keys:
        v = summary.get(k) if isinstance(summary, Mapping) else getattr(summary, k, None)
        if v is None or isinstance(v, bool):
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            continue
    return default


def _summary_items(summary: Any) -> List[Tuple[str, int]]:
    """明细条目归一为 (来源, 总伤害) 序列（BREP-25 {来源} {总伤害}）：取
    items/entries/明细 键或属性；条目支持 Mapping（source/来源/name + damage/
    总伤害/value）/二元组/对象。按总伤害降序（占比降序，数值层 L340/L347）。"""
    if isinstance(summary, Mapping):
        raw = summary.get("items", summary.get("entries", summary.get("明细", ())))
    else:
        raw = getattr(summary, "items", None)
        if not raw:
            raw = getattr(summary, "entries", None)
    result: List[Tuple[str, int]] = []
    for item in raw or ():
        if isinstance(item, Mapping):
            source = str(
                item.get("source", item.get("来源", item.get("name", ""))) or "?"
            )
            damage = int(item.get("damage", item.get("总伤害", item.get("value", 0))))
        elif isinstance(item, (tuple, list)) and len(item) >= 2:
            source, damage = str(item[0]), int(item[1])
        else:
            source = str(
                getattr(item, "source", "") or getattr(item, "来源", "") or "?"
            )
            damage = int(getattr(item, "damage", getattr(item, "总伤害", 0)))
        result.append((source, damage))
    result.sort(key=lambda sd: sd[1], reverse=True)            # 占比降序
    return result


def _summary_header(summary: Any, *, ctx: Any = None) -> str:
    """BREP-25 摘要行：`摘要：总伤害 {N}｜最大单段 {M}｜会心 {K} 次｜格挡 {G} 次`
    （对齐收集器聚合字段，数值层 L340 / TC-26）。
    模板 battle_summary_header（battle_tpl 分区，内容包可覆盖）。
    """
    total = _summary_field(summary, "total", "总伤害")
    max_hit = _summary_field(summary, "max_hit", "max_seg", "最大单段")
    crits = _summary_field(summary, "crits", "crit", "会心")
    blocks = _summary_field(summary, "blocks", "block", "格挡")
    return tpl_of(ctx, "battle_summary_header", {
        "total": total, "max_hit": max_hit, "crits": crits, "blocks": blocks})


def _summary_item_line(
    index: int,
    source: str,
    damage: int,
    pct: int,
    *,
    ctx: Any = None,
) -> str:
    """BREP-25 条目行：`{序号}. {来源} {总伤害}（{占比}%）`（5e §6.3 / TC-26）。
    模板 battle_summary_item（battle_tpl 分区，内容包可覆盖）。
    """
    return tpl_of(ctx, "battle_summary_item", {
        "index": index, "source": source, "damage": damage, "pct": pct})


def _summary_item_lines(
    items: List[Tuple[str, int]],
    total: int,
    *,
    start: int = 1,
    ctx: Any = None,
) -> List[str]:
    """条目行批量渲染：占比 = 总伤害占比取整（total<=0 时 0，防除零）；序号可偏移
    （render_battle_summary 分页续号用）。"""
    return [
        _summary_item_line(
            i, src, dmg, round(dmg / total * 100) if total > 0 else 0, ctx=ctx,
        )
        for i, (src, dmg) in enumerate(items, start=start)
    ]


def _fold_item_lines(
    item_lines: List[str],
    *,
    keep: int,
    command: str,
    per_page: int,
    ctx: Any = None,
) -> List[str]:
    """16 行折叠（铁律 11 / 3d D-03 / TPL-09）：条目行超 keep 时按「正文尾部 →
    中间过程行」优先折叠为省略行 `…（其余 {N} 条已折叠，输入 /{command} {page}
    查看）`。

    保留前 keep 条（正文头部，占比降序前段），N = 被折叠条目数，page = 被折叠
    内容在 per_page 分页口径下第一条所在页码（`…` 折叠行亦计入 16 行，L184）。
    只折叠不截断语义：折叠内容仍在后续页可查（3d §3.2，L183）。
    折叠行模板 battle_fold_items（battle_tpl 分区）。
    """
    if len(item_lines) <= keep:
        return item_lines
    head = item_lines[:keep]
    folded = len(item_lines) - keep
    page = (keep + per_page) // per_page                    # 第一条被折叠条目所在页
    head.append(tpl_of(ctx, "battle_fold_items", {
        "n": folded, "command": command, "page": page}))
    return head


def _render_summary_block(
    summary: Any,
    *,
    overhead: int = 0,
    limit: int = _FOLD_LIMIT,
    command: str = _BREP24_ENTRY_COMMAND,
    per_page: int = DEFAULT_PAGE_SIZE,
    ctx: Any = None,
) -> List[str]:
    """BREP-25 木桩明细块（5e §6.3，render_battle_end 内联形态）：摘要行 + 条目行
    + ≤16 行折叠 TPL-09（铁律 11）。

    消息总行数（overhead = 前缀/BREP-24 行数，摘要行与 TPL-09 折叠行各占 1 行）
    ≤ limit（默认 16，3d D-03/L184）——超限时条目行按正文尾部折叠（keep =
    limit - overhead - 2：1 行留给摘要行、1 行留给 TPL-09）。占比降序（L347）。
    """
    items = _summary_items(summary)
    total = _summary_field(summary, "total", "总伤害")
    header = _summary_header(summary, ctx=ctx)
    item_lines = _summary_item_lines(items, total, ctx=ctx)
    keep = max(0, limit - overhead - 2)                     # 1=摘要行 1=TPL-09 折叠行
    return [header] + _fold_item_lines(
        item_lines, keep=keep, command=command, per_page=per_page, ctx=ctx,
    )


def render_battle_summary(
    summary: Any,
    *,
    page: Any = 1,               # 页码（int 或 str，经 list_render.resolve_page 归一/夹取/判非法）
    command: str = "木桩",
    per_page: int = DEFAULT_PAGE_SIZE,
    ctx: Any = None,
) -> str:
    """BREP-25 木桩明细分页块（5e §6.3 / TC-26）：摘要行 + 条目行 + 5 条/页 + 页脚 TPL-08。

    `/木桩` 战后明细浏览：摘要行 + 当页条目（每页最多 5 条，D-02）+ 多页时页脚
    TPL-08（复用 list_render.render_footer，3d §2.3「禁止各系统自造页脚」；
    单页无页脚）。页码非法（0/负数/非数字）→ ValueError（壳层应先经 resolve_page
    判定转 TPL-12，对齐 list_render 契约）。条目占比按总伤害占比取整、降序排列
    （数值层 L340/L347）。模板 battle_summary_header / battle_summary_item（battle_tpl）。
    """
    items = _summary_items(summary)
    total = _summary_field(summary, "total", "总伤害")
    res = resolve_page(page, len(items), per_page)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 resolve_page 判定并转 TPL-12（3d §2.2）"
        )
    assert res.page is not None                              # 非法已拦截，夹取后恒有页码
    page_slice = page_items(items, page, per_page)
    lines = [_summary_header(summary, ctx=ctx)]
    lines.extend(_summary_item_lines(page_slice, total, ctx=ctx))
    footer = render_footer(res.page, res.total_pages, len(items), command)
    if footer:
        lines.append(footer)                                 # TPL-08（多页时）
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CTB 重写 · 三渲染入口（Agent 5 · DataRender）
# 依据：docs/ctb/01_asset_inventory.md §0.2 CTB 事件位点词典（BATTLE_START / ACTOR_READY /
#       BEFORE_ACTION / ACTION_RESOLVE / AFTER_ACTION / ACTOR_TURN_START / ACTOR_TURN_END /
#       BATTLE_TIME_ADVANCE / ACTOR_DEATH / BATTLE_END）+ §0.1 三分类口径（回合制产物删除、
#       业务资产平移）；docs/ctb/02_wave_a_decisions.md 裁决 1（recovery = 总行动恢复值）+
#       裁决 3（同刻连动刻意设计）+ 修复 2（per-action recovery 注入入口）；
#       core/ctb_rules.ActionBatchReport（多 NPC 连锁行动合并上报载体）。
#
# 设计口径（复用而非重写）：CTB 的「一次行动」与既有 render_battle_round 的「一个 outcome」
#   是**同粒度**——两者都吃 outcomes 流水、都按 actor 分派玩家/怪物积木。故本三入口 = 新的
#   **编排层**：只做「事件链 → 既有 private 积木」的装配与折叠，绝不复制积木内部逻辑。
#     render_battle_ready       ← ACTOR_READY（玩家 ready 提示，CTB 下「轮到你行动」）
#     render_battle_action      ← 一次 action 完整链路（prefix + 行动积木 + 状态/提示/结算）
#     render_battle_action_batch ← 多个 NPC 连锁行动合并为一条（ActionBatchReport.entries）
# ---------------------------------------------------------------------------

#: CTB 行动状态前缀候选键（不同接线层形态差异；按序取首个非空）
_CTB_STATUS_KEYS: Tuple[str, ...] = (
    "status_line", "ctb_status", "ctb_status_line", "ready_hint",
)


def _ctb_status_line(ctx: Any, ready_in: Any = None) -> str:
    """CTB 状态行（「距离你行动：{n}」）——取 ctx 显式注入值或按 ready_in 组装。

    数据源 ctx.ctb_status_line（接线层注入，优先）或 ctx.ctb_status（含 {n} 模板串）；
    均缺 → 用 tpl_of 默认模板 battle_ctb_status（内容包可覆盖）；ready_in 为空/非法 →
    返回空串（省略该行，不臆造）。
    """
    for key in _CTB_STATUS_KEYS:
        val = (ctx or {}).get(key) if isinstance(ctx, Mapping) else getattr(ctx, key, None)
        if val:
            return str(val)
    if ready_in is None:
        return ""
    try:
        n = int(ready_in)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    return tpl_of(ctx, "battle_ctb_status", {"n": n})


def _render_outcome_lines(oc: Any, *, ctx: Any = None) -> List[str]:
    """单个 outcome → 行集（CTB 与回合制共用粒度：actor 分派玩家/怪物积木）。

    与 render_battle_round 内联的 actor 分派**同口径**（连段段行优先替代聚合单行，
    D-5C；其后紧跟击杀行，铁律 9）：本函数是复用的公共内层，render_battle_action 与
    render_battle_action_batch 都经它装配，避免两处各写一份 actor 分派。
    actor==player：连段段行 + 连段结算，或玩家行动积木 + 击杀；
    actor==enemy ：怪物行动积木（守卫：玩家已倒下则不渲染反击行）。

    兼容 Mapping 形态条目（ActionBatchReport.entries 经 to_dict() 后为 dict）——
    先归一为属性对象，再走同一积木分派（积木内部按属性读字段）。
    """
    if isinstance(oc, Mapping):
        oc = SimpleNamespace(**dict(oc))
    actor = str(getattr(oc, "actor", "") or "")
    lines: List[str] = []
    if actor == "player":
        combo = _render_combo_segments(oc, ctx=ctx)                # BREP-21 段行
        if combo:
            lines.extend(combo)
            settle = _render_combo_settle(oc, ctx=ctx)             # BREP-22
            if settle:
                lines.append(settle)
        else:
            lines.extend(_render_player_action(oc, ctx=ctx))       # BREP-02~05（+07）
            if int(getattr(oc, "target_hp", 1)) <= 0:              # 扣血后立即查击杀（L54）
                kill = _render_template("_render_kill_line", oc, ctx=ctx)  # BREP-15
                if kill:
                    lines.append(kill)
    elif actor == "enemy":
        enemy = _render_template("_render_enemy_action", oc, ctx=ctx)      # BREP-10~14
        if enemy:
            lines.append(enemy)
    return lines


def render_battle_action(
    action_result: Any,
    *,
    ctx: Any = None,
) -> str:
    """CTB 单次行动渲染（一次 action 的完整链路输出，ACTOR_READY→ACTOR_TURN_END）。

    输入：一次行动的**报告载体**（对象或 Mapping），承载：
      - outcomes      行动流水（ActionOutcome 序列；与回合制同粒度，必填）
      - actor_id      （可选）行动者标识——用于 ACTOR_TURN_START 头部行判定
      - turn_name     （可选）行动者展示名（缺省从 outcome.actor_name/attacker_name 推）
      - level/name/title/prefix_extra  玩家前缀信息（同 render_battle_round 口径）
      - status_changes / player_max_hp / enemy_max_hp / enemy_name / player_pos /
        enemy_pos / ready_in（CTB 距下次 ready）等 CTB 字段（可省略）
      - ended/status/exp/gold/drops/final_damage/leveled（行动即终局的结算，可选）
      - batch         （可选）ActionBatchReport.to_dict()——含多条 entries 时并入本入口

    输出：单条消息（prefix 首行 + 行动积木行 + BREP-08/09 + [结算]），≤16 行折叠。

    复用：actor 分派走 _render_outcome_lines（内含 _render_player_action /
    _render_enemy_action / 连段积木 / 击杀积木）；终局走 _render_settlement；
    行数控制复用 _fold_message_lines。**不复制任何积木内部逻辑**（编排层职责）。

    兜底：任何异常 → 记日志并返回已装配行（或空串），绝不抛出（渲染层不崩铁律）。
    """
    lines: List[str] = []
    try:
        # ① prefix 首行（BREP-01；玩家信息缺失自动省略）
        prefix = _render_prefix_line(action_result)
        if prefix:
            lines.append(prefix)

        # ② 行动头（CTB ACTOR_TURN_START：行动者是 NPC 时的归属行，玩家侧已有 prefix）
        head = _ctb_action_head(action_result, ctx=ctx)
        if head:
            lines.append(head)

        # ③ 行动积木（actor 分派：player/enemy 复用回合制同粒度积木）
        for oc in _iter_outcomes(action_result):
            lines.extend(_render_outcome_lines(oc, ctx=ctx))

        # ④ 【可选】并入批量 entries（同一 action_result 携带 ActionBatchReport 形态）
        for entry in _iter_batch_entries(action_result):
            lines.extend(_render_outcome_lines(entry, ctx=ctx))

        # ⑤ BREP-08 状态资源差分行 + ⑥ CTB 状态行（距下次 ready）
        status_line = _render_status_diff_from_report(action_result, ctx=ctx)
        if status_line:
            lines.append(status_line)
        ready_line = _ctb_status_line(ctx, getattr(action_result, "ready_in", None))
        if ready_line:
            lines.append(ready_line)

        # ⑦ 行动即终局 → 结算一次（军规5；未结束时不输出，结算走 render_battle_end）
        settle = _render_settlement(action_result, ctx=ctx)
        if settle:
            lines.extend(settle.split("\n"))

        # ⑧ BREP-09 操作提示行（末行；数据缺省优雅省略）
        hint = _render_action_hint_from_report(action_result, ctx=ctx)
        if hint:
            lines.append(hint)

        # ⑨ 空模板行过滤 + 16 行折叠（铁律 11）
        lines = [ln for ln in lines if isinstance(ln, str) and ln.strip()]
        return "\n".join(_fold_message_lines(lines, ctx=ctx))
    except Exception:  # pragma: no cover - 渲染层兜底不崩
        _logger.exception("render_battle_action 渲染失败，返回已装配行")
        return "\n".join(ln for ln in lines if isinstance(ln, str) and ln.strip())


def render_battle_action_batch(
    batch_result: Any,
    *,
    ctx: Any = None,
) -> str:
    """CTB 批量行动渲染（多个 NPC 连锁行动**合并为一条消息**）。

    语义（core/ctb_rules.ActionBatchReport）：可暂停输入式 CTB 下，NPC 连锁行动时引擎
    自动推进不等待输入；多个 NPC 行动在玩家 Ready 前合并为一次上报 → 本入口把它们渲染
    为**同一条消息**（对齐 3d S4 单轮单条 / 铁律 9 合并策略）。

    输入：ActionBatchReport（对象或 to_dict() 形态）或含以下键的 Mapping：
      - entries         每条 NPC 行动的摘要（dict；可含 actor/action_type/hit/... 或
                        嵌套 outcome 键，两种形态均支持）
      - start_time/end_time   批次逻辑时间区间（可选，渲染时间头行）
      - paused_actor_id/paused_ready_at  触发暂停的玩家（可选，渲染 CTB ready 提示行）
      亦兼容直接传 outcomes 序列（等价于单 actor 多次行动）。

    输出：单条消息（prefix + [批次时间头] + 逐条 NPC 行动积木 + [CTB 状态行] + [提示]），
    ≤16 行折叠。**复用** _render_outcome_lines / _fold_message_lines；不复制积木逻辑。

    兜底：异常 → 记日志返回已装配行，绝不抛出。
    """
    lines: List[str] = []
    try:
        # ① prefix 首行（batch_result 或 ctx 可承载玩家信息）
        prefix = _render_prefix_line(batch_result if batch_result is not None else ctx)
        if prefix:
            lines.append(prefix)

        # ② 批次时间头（可选：start_time→end_time，纯数字不臆造文案）
        start_t = getattr(batch_result, "start_time", None)
        end_t = getattr(batch_result, "end_time", None)
        if isinstance(batch_result, Mapping):
            start_t = batch_result.get("start_time", start_t)
            end_t = batch_result.get("end_time", end_t)
        if start_t is not None and end_t is not None:
            head = tpl_of(ctx, "battle_ctb_batch_head", {
                "start": _fmt_time(start_t), "end": _fmt_time(end_t)})
            if head:
                lines.append(head)

        # ③ 逐条 NPC 行动积木（entries 优先；无 entries → 退化为 outcomes 序列）
        entries = _batch_entry_list(batch_result)
        if entries:
            for entry in entries:
                lines.extend(_render_outcome_lines(entry, ctx=ctx))
        else:
            for oc in _iter_outcomes(batch_result):
                lines.extend(_render_outcome_lines(oc, ctx=ctx))

        # ④ CTB 状态行（玩家 ready 距下次：paused_ready_at）
        paused_ready = getattr(batch_result, "paused_ready_at", None)
        if isinstance(batch_result, Mapping):
            paused_ready = batch_result.get("paused_ready_at", paused_ready)
        ready_line = _ctb_status_line(ctx, paused_ready)
        if ready_line:
            lines.append(ready_line)

        # ⑤ 批次状态资源差分行 + 操作提示行（可选）
        status_line = _render_status_diff_from_report(batch_result, ctx=ctx)
        if status_line:
            lines.append(status_line)
        hint = _render_action_hint_from_report(batch_result, ctx=ctx)
        if hint:
            lines.append(hint)

        # ⑥ 空模板行过滤 + 16 行折叠（铁律 11）
        lines = [ln for ln in lines if isinstance(ln, str) and ln.strip()]
        return "\n".join(_fold_message_lines(lines, ctx=ctx))
    except Exception:  # pragma: no cover - 渲染层兜底不崩
        _logger.exception("render_battle_action_batch 渲染失败，返回已装配行")
        return "\n".join(ln for ln in lines if isinstance(ln, str) and ln.strip())


def render_battle_ready(
    ready_info: Any = None,
    *,
    ctx: Any = None,
    player: Any = None,
    enemy: Any = None,
    ready_in: Any = None,
    hint: Optional[str] = None,
) -> str:
    """CTB 玩家 ready 提示（「轮到你行动」；对应 ACTOR_READY 事件位点）。

    语义（docs/ctb/01_asset_inventory.md §0.2）：CTB 下玩家 ready 时暂停并交还控制权；
    本入口渲染该暂停时点的提示消息（**独立 1 条**，对齐铁律 2 战斗开始=1 条）。

    输入（均可省略，缺数据优雅降级）：
      - ready_info：承载上述字段的对象/Mapping（与显式参数同键；显式参数优先）
      - player/enemy：HP 快照（供 hint 行渲染，走 render_action_hint 复用）
      - ready_in：距下次 ready 的逻辑时间（CTB 状态行 bat tle_ctb_status 的 {n}）
      - hint：显式提示文本（优先于自动组装的 HP/方位提示行）

    输出：单条消息（prefix 首行 + ready 行 + [CTB 状态行] + [提示/操作提示行]），≤16 行折叠。
    复用：_render_prefix_line（前缀首行）、render_action_hint（BREP-09 操作提示）/
    _render_action_hint_from_report（CTB 数据源）、_fold_message_lines。不复制积木逻辑。

    兜底：异常 → 记日志返回已装配行，绝不抛出。
    """
    lines: List[str] = []
    try:
        src = ready_info if ready_info is not None else ctx

        # ① prefix 首行（玩家信息；缺失自动省略）
        prefix = _render_prefix_line(src)
        if prefix:
            lines.append(prefix)

        # ② CTB ready 行（「轮到你行动」，模板可覆盖）
        ready_line = tpl_of(ctx, "battle_ctb_ready")
        if ready_line:
            lines.append(ready_line)

        # ③ CTB 状态行（距下次 ready 的逻辑时间；显式 ready_in 优先，其次 ready_info）
        if ready_in is None:
            ready_in = getattr(src, "ready_in", None)
            if isinstance(src, Mapping):
                ready_in = src.get("ready_in", ready_in)
        status_line = _ctb_status_line(ctx, ready_in)
        if status_line:
            lines.append(status_line)

        # ④ 提示行：显式 hint 优先；否则复用 HP/方位操作提示（缺数据自动省略）
        if hint:
            lines.append(str(hint))
        else:
            src_for_hint = src if src is not None else SimpleNamespace(
                player=player, enemy=enemy)
            if player is not None and getattr(src_for_hint, "player", None) is None:
                try:
                    src_for_hint.player = player          # 显式参数补位（对象形态）
                except Exception:  # pragma: no cover - SimpleNamespace 可写；防御
                    pass
            if enemy is not None and getattr(src_for_hint, "enemy", None) is None:
                try:
                    src_for_hint.enemy = enemy
                except Exception:  # pragma: no cover
                    pass
            auto_hint = _render_action_hint_from_report(src_for_hint, ctx=ctx)
            if auto_hint:
                lines.append(auto_hint)

        # ⑤ 空模板行过滤 + 16 行折叠（铁律 11）
        lines = [ln for ln in lines if isinstance(ln, str) and ln.strip()]
        return "\n".join(_fold_message_lines(lines, ctx=ctx))
    except Exception:  # pragma: no cover - 渲染层兜底不崩
        _logger.exception("render_battle_ready 渲染失败，返回已装配行")
        return "\n".join(ln for ln in lines if isinstance(ln, str) and ln.strip())


# ---------------------------------------------------------------------------
# CTB 入口内部辅助（纯装配，不产生业务数值）
# ---------------------------------------------------------------------------
def _iter_outcomes(action_result: Any) -> List[Any]:
    """从行动报告载体取 outcomes 流水（属性/Mapping 双形态；缺省空列表）。

    兼容 action_result 本身即 outcome（无 outcomes 键）→ 单元素列表；避免调用方
    为「只有一条流水」额外包壳。
    """
    if action_result is None:
        return []
    raw = (action_result.get("outcomes")
           if isinstance(action_result, Mapping)
           else getattr(action_result, "outcomes", None))
    if raw:
        return [oc for oc in raw if oc is not None]
    # 单 outcome 直传（含 batch entry 形态）：无 outcomes 键但本身像 outcome
    if isinstance(action_result, Mapping) or any(
        hasattr(action_result, k)
        for k in ("actor", "action_type", "hit", "final_damage")
    ):
        return [action_result]
    return []


def _batch_entry_list(batch_result: Any) -> List[Any]:
    """取批量 entries 列表（ActionBatchReport.entries / Mapping["entries"]；缺省空）。"""
    if batch_result is None:
        return []
    if isinstance(batch_result, Mapping):
        raw = batch_result.get("entries", ())
    else:
        raw = getattr(batch_result, "entries", ())
    return [e for e in (raw or ()) if e is not None]


def _iter_batch_entries(action_result: Any) -> List[Any]:
    """render_battle_action 的可选并入口：action_result 若携带 batch，取其 entries。"""
    batch = (action_result.get("batch")
             if isinstance(action_result, Mapping)
             else getattr(action_result, "batch", None))
    if not batch:
        return []
    # batch 可为 ActionBatchReport / to_dict() / 裸 entries 序列
    if isinstance(batch, Mapping):
        return [e for e in batch.get("entries", ()) or () if e is not None]
    if hasattr(batch, "entries"):
        return [e for e in (batch.entries or ()) if e is not None]
    if isinstance(batch, (list, tuple)):
        return [e for e in batch if e is not None]
    return []


def _ctb_action_head(action_result: Any, *, ctx: Any = None) -> Optional[str]:
    """CTB 行动头行（ACTOR_TURN_START 归属行）——仅 NPC 行动输出。

    玩家行动已有 prefix 首行（BREP-01），不再重复头行；NPC 行动时输出
    `battle_ctb_turn_start`（{actor} 展示名）标识「轮到谁」，缺展示名 → 省略
    （不臆造空白行）。数据源 action_result.turn_name / 首条 outcome 的
    actor_name/attacker_name。
    """
    if action_result is None:
        return None
    name = None
    if isinstance(action_result, Mapping):
        name = action_result.get("turn_name") or action_result.get("actor_name")
    else:
        name = (getattr(action_result, "turn_name", None)
                or getattr(action_result, "actor_name", None))
    if not name:
        outcomes = _iter_outcomes(action_result)
        if outcomes:
            first = outcomes[0]
            if isinstance(first, Mapping):
                name = first.get("actor_name") or first.get("attacker_name")
            else:
                name = (getattr(first, "actor_name", None)
                        or getattr(first, "attacker_name", None))
    # 玩家侧不输出头行（prefix 已承担首行职责，防重复刷屏）
    actor = (action_result.get("actor_id")
             if isinstance(action_result, Mapping)
             else getattr(action_result, "actor_id", None))
    if str(actor or "") == "player":
        return None
    if not name:
        return None
    return tpl_of(ctx, "battle_ctb_turn_start", {"actor": str(name)})


def _fmt_time(value: Any) -> str:
    """逻辑时间展示（秒；非数值 → 原样字符串）。纯数字/一位小数兼容。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{f:.1f}" if f != int(f) else str(int(f))

