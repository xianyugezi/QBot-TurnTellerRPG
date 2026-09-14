"""CTB 黑盒验收用例（tests/ctb/test_ctb_blackbox_sequences.py）。

需求文档给定两个基准（**硬指标**）：

  | 场景     | 参数                                             | 期望行动序列 |
  |----------|--------------------------------------------------|--------------|
  | 基础     | 玩家 SPD=100，怪物 SPD=75，普攻 recovery=100     | P→E→P→E→P    |
  | 慢技能   | 使用重技能 recovery=150 后（其余普攻 recovery=100）| P(慢技能)→E→E→P |

本文件**用 Agent 2 的调度器/规则层直接跑真实序列**（不 mock）。

✅ 口径已裁决（2026-09-10，见 docs/ctb/02_wave_a_decisions.md 裁决 1 + 裁决 2）：

  裁决 1 · **recovery = 该 action 的总行动恢复值**（与 default_recovery 覆盖，非附加）。
  连带修正：需求文档 §25 场景 2 写的「重技能 recovery=150 → P→E→E→P」是**示例笔误**。
  数学推演（speed_reference=100, min_speed=1, action_delay=0）：
    ready(P) = 100.0；ready(E) = 133.333…；E 第二次 ready = 266.667
    场景 2 中 P 用重技能后 ready = 100 + recovery
      · recovery=150 → 250.0 < 266.667 → P 抢先 → P→E→P→E   ✗ 与文档期望不符
      · recovery=200 → 300.0 > 266.667 → E 连动两次 → P→E→E→P ✓
  阈值下界 = 166.67（> 该值方满足期望序列），故验收改用 **recovery=200**
  （常量 RECOVERY_DOC_EXAMPLE_SLOW，ctb_rules.py 已落值并在注释中说明）。

  裁决 2 · 被拒行动 = 零时间成本、直接重试（不推进行动条）。

另：Agent 2 的调度器已补 per-action recovery 注入入口（`_enqueue(recovery=)` /
`complete_player_action(recovery=)` / `_auto_resolve_npc(recovery=)`），
原 F2「无注入入口」缺口已闭合；本文件现**同时**用调度器真实序列验证（见
`test_scheduler_driven_blackbox_sequences`）。
"""

from __future__ import annotations

from typing import List

from qbot_rpg.core.ctb_rules import CtbRuleConfig, next_ready
from qbot_rpg.core.ctb_scheduler import CTBScheduler

PLAYER_SPD = 100.0
ENEMY_SPD = 75.0
NORMAL_RECOVERY = 100.0
HEAVY_RECOVERY = 200.0  # 裁决 1：文档原文 150 为示例笔误；> 166.67 才满足期望序列

CFG = CtbRuleConfig()


def _simulate_sequence(
    *,
    first_player_recovery: float,
    ticks: int = 4,
) -> List[str]:
    """在**规则层**直接模拟行动序列（不依赖调度器的内部 recovery —— 见下「已知缺口」）。

    为什么不用 `CTBScheduler` 跑场景 2：
      `CTBScheduler._schedule()`（ctb_scheduler.py:318-326）**固定**以
      `self._rule.default_recovery` 计算 next_ready，**不接收 per-action recovery**。
      调度器公开 API（`complete_player_action` / `advance_to_next_ready`）无注入行动
      recovery 的入口，故**无法从调度器产出慢技能序列**。这是调度器的接口缺口
      （见 scripts/ctb_guardian_findings.md F2），本文件改在规则层用官方公式复算。

    :param first_player_recovery: 玩家首次行动使用的 recovery
    :param ticks: 采样行动数
    :return: ['P'|'E', ...] 行动序列
    """
    p_next = next_ready(0.0, {"recovery": NORMAL_RECOVERY}, PLAYER_SPD, CFG)
    e_next = next_ready(0.0, {"recovery": NORMAL_RECOVERY}, ENEMY_SPD, CFG)
    seq: List[str] = []
    first_player = True
    while len(seq) < ticks:
        if p_next <= e_next:
            seq.append("P")
            rec = first_player_recovery if first_player else NORMAL_RECOVERY
            first_player = False
            p_next = next_ready(p_next, {"recovery": rec}, PLAYER_SPD, CFG)
        else:
            seq.append("E")
            e_next = next_ready(e_next, {"recovery": NORMAL_RECOVERY}, ENEMY_SPD, CFG)
    return seq


def _scheduler_sequence(ticks: int = 5) -> List[str]:
    """用调度器（公开 API）跑基础场景的真实序列，取 ACTOR_READY 的 actor_id。"""
    sched = CTBScheduler()
    sched.push_actor("P", side="player", effective_speed=PLAYER_SPD, is_player=True)
    sched.push_actor("E", side="enemy", effective_speed=ENEMY_SPD)
    sched.start()
    sched.drain_events()
    seq: List[str] = []
    # 放宽迭代预算：玩家暂停拍需额外一次 complete_player_action 才产出一条 READY
    for _ in range(ticks * 4 + 8):
        if sched.finished or len(seq) >= ticks:
            break
        if sched.should_pause_for_input():
            if sched.paused:
                sched.complete_player_action()
                seq.extend(
                    str(e["actor_id"])
                    for e in sched.drain_events()
                    if e["event"] == "ACTOR_READY"
                )
                continue
            break
        sched.advance_to_next_ready()
        seq.extend(
            str(e["actor_id"])
            for e in sched.drain_events()
            if e["event"] == "ACTOR_READY"
        )
    return seq[:ticks]


# ===========================================================================
# 场景 1：基础 —— P→E→P→E→P（硬指标，strict）
# ===========================================================================
def test_basic_sequence_scheduler_p_e_p_e_p() -> None:
    """场景 1（调度器实测）：P→E→P→E→P 复现成功。"""
    assert _scheduler_sequence(ticks=5) == ["P", "E", "P", "E", "P"]


def test_basic_sequence_rule_layer_matches() -> None:
    """场景 1（规则层复算）：与调度器结果一致，证明公式口径一致。"""
    assert _simulate_sequence(first_player_recovery=NORMAL_RECOVERY, ticks=5) == [
        "P", "E", "P", "E", "P",
    ]


def test_basic_sequence_ready_times() -> None:
    """场景 1：关键 ready 时刻符合公式（100 / 133.33 / 200 / 266.67 / 300）。"""
    p = next_ready(0.0, {"recovery": 100}, PLAYER_SPD, CFG)
    e = next_ready(0.0, {"recovery": 100}, ENEMY_SPD, CFG)
    assert p == 100.0
    assert abs(e - 133.3333) < 1e-3
    assert next_ready(p, {"recovery": 100}, PLAYER_SPD, CFG) == 200.0
    assert abs(next_ready(e, {"recovery": 100}, ENEMY_SPD, CFG) - 266.6667) < 1e-3
    assert next_ready(200.0, {"recovery": 100}, PLAYER_SPD, CFG) == 300.0


# ===========================================================================
# 场景 2：慢技能 —— P(慢技能)→E→E→P（硬指标）
# ===========================================================================
def test_documented_150_would_not_yield_expected_sequence() -> None:
    """场景 2（诊断·留证）：若照文档原文取 recovery=150，公式产出 P→E→P→E。

    这是「文档示例数笔误」的**实证留档**：150 作总恢复值 → P 下次 ready=250.0
    < E 第二次 266.667 → 玩家抢先，无法形成 E→E 连动。故验收改用 200。
    """
    assert _simulate_sequence(first_player_recovery=150.0, ticks=4) == [
        "P", "E", "P", "E",
    ]


def test_slow_skill_requires_total_recovery_gt_166_67() -> None:
    """场景 2（诊断）：要使 E→E 连动，重技能的**总恢复值**须 > 166.67。

    阈值推导：P 下次 ready = 100 + R*100/100 = 100 + R；需 > E 第二次 266.667
    → R > 166.667。故验收值取 200（见 RECOVERY_DOC_EXAMPLE_SLOW）。
    """
    threshold = 266.6667 - 100.0  # 166.6667
    assert _simulate_sequence(first_player_recovery=threshold - 1, ticks=4) == [
        "P", "E", "P", "E",
    ]
    assert _simulate_sequence(first_player_recovery=threshold + 1, ticks=4) == [
        "P", "E", "E", "P",
    ]


def test_slow_skill_additive_recovery_yields_expected_sequence() -> None:
    """场景 2（对照·加算解释）：若 150 为**额外**恢复值（总 250）→ P→E→E→P ✓。

    注：2026-09-10 裁决 1 已定「recovery 为总恢复值」，故**加算不是采纳口径**。
    本用例保留为**对照实验**（说明两种解释都能满足期望序列，只是数值不同），
    防止后人误以为只有一种数值能成立。
    """
    total = NORMAL_RECOVERY + HEAVY_RECOVERY  # 300（=100 基准 + 200 附加）
    assert _simulate_sequence(first_player_recovery=total, ticks=4) == [
        "P", "E", "E", "P",
    ]


def test_slow_skill_sequence_hard_indicator() -> None:
    """场景 2（硬指标）：重技能 recovery=200 → 期望 P→E→E→P。

    2026-09-10 裁决 1 转正：recovery 为总恢复值，文档原文 150 系示例笔误；
    取 200（> 阈值 166.67）稳定满足期望序列。
    """
    assert _simulate_sequence(first_player_recovery=HEAVY_RECOVERY, ticks=4) == [
        "P", "E", "E", "P",
    ]


# ===========================================================================
# 附加：0 拍 / 大 recovery 的边界
# ===========================================================================
def test_zero_recovery_does_not_infinite_loop() -> None:
    """边界：recovery=0 → next_ready 不推进时间；序列仍可产出（不死循环，采样有限）。

    注：recovery=0 在调度器层会造成同刻并列；本用例仅验证规则层公式不抛错、序列有限。
    """
    seq = _simulate_sequence(first_player_recovery=0.0, ticks=4)
    assert len(seq) == 4


def test_huge_recovery_delays_player() -> None:
    """边界：重技能 recovery 极大 → 玩家被推迟到敌人多次行动之后。"""
    seq = _simulate_sequence(first_player_recovery=1000.0, ticks=4)
    assert seq[0] == "P" and seq[1] == "E" and seq[2] == "E"
    assert seq[3] == "E"  # 1000 起步 → 1100，敌人第三次 400 仍更早


# ===========================================================================
# 调度器真实驱动（2026-09-10 · F2 缺口闭合后新增）
#
# 上方用例走「规则层复算」（不依赖调度器内部 recovery）。F2 修复后，
# CTBScheduler 已支持 per-action recovery 注入，故此处用**真实调度器**再验一遍，
# 确保端到端（而非仅公式）满足黑盒指标。
# ===========================================================================
def _drive_scheduler(*, first_player_recovery: float, ticks: int = 4) -> List[str]:
    """用真实 CTBScheduler 跑行动序列（玩家首次行动注入指定 recovery）。

    :param first_player_recovery: 玩家首次行动的 recovery
    :param ticks: 采样行动数
    :return: 行动者标识序列（"P" / "E"）
    """
    ctb = CTBScheduler(config=CtbRuleConfig())
    ctb.push_actor("P", side="player", effective_speed=PLAYER_SPD, is_player=True)
    ctb.push_actor("E", side="enemy", effective_speed=ENEMY_SPD)
    ctb.start()
    seq: List[str] = []
    first = True
    for _ in range(ticks):
        ev = ctb.advance_to_next_ready()
        if ev is None:
            break
        seq.append(str(ev.get("actor_id") or ""))
        if ctb.should_pause_for_input():
            # 玩家 ready：注入本次行动的 recovery 后继续（F2 注入入口）
            ctb.complete_player_action(
                recovery=first_player_recovery if first else NORMAL_RECOVERY
            )
            first = False
    return seq


def test_scheduler_driven_scenario1_basic_order() -> None:
    """场景 1（调度器真实驱动）：SPD 100 vs 75、普攻 recovery=100 → P→E→P→E→P。"""
    assert _drive_scheduler(first_player_recovery=NORMAL_RECOVERY, ticks=5) == [
        "P", "E", "P", "E", "P",
    ]


def test_scheduler_driven_scenario2_slow_skill() -> None:
    """场景 2（调度器真实驱动）：重技能 recovery=200 → P→E→E→P。"""
    assert _drive_scheduler(first_player_recovery=HEAVY_RECOVERY, ticks=4) == [
        "P", "E", "E", "P",
    ]


def test_scheduler_recovery_injection_changes_order() -> None:
    """对照：同一角色，注入不同 recovery 会改变后续行动顺序（证明注入生效）。

    普攻（100）→ 下一步 P 早于 E 第二次；重技能（200）→ P 被推到 E 两次之后。
    """
    fast = _drive_scheduler(first_player_recovery=NORMAL_RECOVERY, ticks=4)
    slow = _drive_scheduler(first_player_recovery=HEAVY_RECOVERY, ticks=4)
    assert fast != slow, "注入不同 recovery 应产生不同行动序列（注入未生效）"
    assert fast == ["P", "E", "P", "E"]
    assert slow == ["P", "E", "E", "P"]
