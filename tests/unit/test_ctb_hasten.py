"""CTB 调度器「反击返还」单元测试（tests/unit/test_ctb_hasten.py）。

覆盖「反击返还」基础设施（怪猎采纳 C11）：
  - ctb_rules 配置键 counter_refund（缺省 200 / 覆盖 / 非法回落 / __all__ / settings 解析）
  - ctb_scheduler.hasten_actor：常规返还 / 下限钳制（不倒流）/ 空操作 /
    未知与阵亡单位 / 兄弟单位时序不变 / 与 delay_actor 的纯时间平移对偶

语义锚点（防反/闪反成功后由引擎侧调用）：`next_ready ← max(now, next_ready − refund_bars)`
（纯时间平移，不重算 recovery；下限钳到当前时刻=最多「立即行动」，不倒流）；
bump generation 使旧票失效，并为其余存活单位按现有时间表重签票据（除目标外时序不变）。

硬约束自检：本文件**不 import qbot_rpg.core.battle**，独立可跑绿
（对齐 tests/unit/test_ctb_scheduler.py 的口径）。
"""

from __future__ import annotations

import qbot_rpg.core.ctb_rules as ctb_rules
from qbot_rpg.core.ctb_rules import (
    DEFAULT_COUNTER_REFUND,
    CtbEvent,
    CtbRuleConfig,
    resolve_rule_config,
)
from qbot_rpg.core.ctb_scheduler import CTBScheduler


# ---------------------------------------------------------------------------
# 辅助：构造「玩家已重签 next_ready」的确定态调度器
# ---------------------------------------------------------------------------
def _setup_player_resigned() -> CTBScheduler:
    """玩家（SPD100）先于敌人（SPD50）ready；玩家走完一次行动并重签票据。

    推进后确定态：battle_time = 100.0；player.next_ready = 200.0（已重签，票有效）；
    enemy.next_ready = 200.0（首票尚未消费，时序基准）。
    """
    sched = CTBScheduler()
    sched.push_actor("player", side="player", effective_speed=100, is_player=True)
    sched.push_actor("enemy", side="enemy", effective_speed=50)
    sched.start()
    sched.advance_to_next_ready()   # 玩家 @100 ready → 暂停
    sched.complete_player_action()  # 玩家行动结算 → 重签 next_ready=200，解除暂停
    return sched


# ---------------------------------------------------------------------------
# 1. 常规返还：next_ready 精确前移（未触发下限钳制）
# ---------------------------------------------------------------------------
def test_hasten_moves_next_ready_back_exactly() -> None:
    sched = _setup_player_resigned()
    player = sched.get_actor("player")
    before = player.next_ready
    assert sched.battle_time == 100.0
    assert before == 200.0  # 重签后明显在未来（距当前 100，返还 60 不触发钳制）
    old_ticket = player.ticket

    assert sched.hasten_actor("player", 60) is True
    # 前后对照：恰好 −60（纯时间平移，不重算 recovery）
    assert before - player.next_ready == 60.0
    assert player.next_ready == 140.0
    # 旧票作废；新票为当前代
    assert sched.is_ticket_stale(old_ticket) is True
    assert sched.is_ticket_stale(player.ticket) is False
    # 平移体现在真实推进上：玩家下一拍 @140（而非 200）
    ev = sched.advance_to_next_ready()
    assert ev["event"] == CtbEvent.ACTOR_READY
    assert ev["actor_id"] == "player"
    assert ev["time"] == 140.0


# ---------------------------------------------------------------------------
# 2. 下限钳制：返还超过距当前量 → 钳到当前时刻（最多「立即行动」，不倒流）
# ---------------------------------------------------------------------------
def test_hasten_clamps_at_current_time() -> None:
    sched = _setup_player_resigned()
    player = sched.get_actor("player")
    assert player.next_ready - sched.battle_time == 100.0  # 距当前（100）不足 200

    assert sched.hasten_actor("player", 200) is True
    assert player.next_ready == sched.battle_time == 100.0  # max(now, …) 语义
    # 继续超量返还也不倒流：仍不早于当前时刻
    assert sched.hasten_actor("player", 9999) is True
    assert player.next_ready == sched.battle_time == 100.0


# ---------------------------------------------------------------------------
# 3. 空操作：refund ≤ 0 → 无害返回 True（时序与 generation 均不变）
# ---------------------------------------------------------------------------
def test_hasten_non_positive_refund_is_noop() -> None:
    sched = _setup_player_resigned()
    player = sched.get_actor("player")
    before = player.next_ready
    gen_before = sched.generation

    assert sched.hasten_actor("player", 0) is True
    assert sched.hasten_actor("player", -50) is True
    assert player.next_ready == before
    assert sched.generation == gen_before  # 无害：连 generation 都不动


# ---------------------------------------------------------------------------
# 4. 未知 / 阵亡单位 → False（不改任何状态）
# ---------------------------------------------------------------------------
def test_hasten_unknown_or_dead_actor_returns_false() -> None:
    sched = CTBScheduler()
    assert sched.hasten_actor("nobody", 100) is False

    sched.push_actor("player", side="player", effective_speed=100, is_player=True)
    sched.push_actor("enemy", side="enemy", effective_speed=50)
    sched.start()
    assert sched.mark_dead("enemy") is True
    assert sched.hasten_actor("enemy", 100) is False


# ---------------------------------------------------------------------------
# 5. 兄弟单位时序不变：hasten 只平移目标（其余按现有时间表重签）
# ---------------------------------------------------------------------------
def test_hasten_keeps_sibling_timing_unchanged() -> None:
    sched = _setup_player_resigned()
    enemy = sched.get_actor("enemy")
    enemy_ready_before = enemy.next_ready
    gen_before = sched.generation

    assert sched.hasten_actor("player", 60) is True

    assert enemy.next_ready == enemy_ready_before == 200.0  # 时刻不变
    assert sched.generation == gen_before + 1               # bump 一次（reason="hasten"）
    assert enemy.ticket is not None
    assert sched.is_ticket_stale(enemy.ticket) is False     # 已重签为当前代


# ---------------------------------------------------------------------------
# 6. 配置键：counter_refund（缺省 200 / 可覆盖 / 非法回落 / settings 解析）
# ---------------------------------------------------------------------------
def test_counter_refund_config_defaults_and_overrides() -> None:
    assert DEFAULT_COUNTER_REFUND == 200.0
    assert "DEFAULT_COUNTER_REFUND" in ctb_rules.__all__
    assert CtbRuleConfig().counter_refund == 200.0
    # 可覆盖（怪猎参考区间 150~250，可调）
    assert CtbRuleConfig().with_overrides({"counter_refund": 150}).counter_refund == 150.0
    assert CtbRuleConfig().with_overrides({"counter_refund": 250}).counter_refund == 250.0
    # 非法值 → 回落缺省（不抛错）
    assert CtbRuleConfig().with_overrides({"counter_refund": "x"}).counter_refund == 200.0
    assert CtbRuleConfig().with_overrides({"counter_refund": None}).counter_refund == 200.0
    # settings["ctb"] 段解析（缺省包一层 / 直给段落两种形态）
    assert resolve_rule_config({"ctb": {"counter_refund": 250}}).counter_refund == 250.0
    assert resolve_rule_config({"counter_refund": 150}).counter_refund == 150.0
    assert resolve_rule_config(None).counter_refund == 200.0


# ---------------------------------------------------------------------------
# 7. 对偶检查：delay_actor(+X) 与 hasten_actor(−Y) 均为纯时间平移
# ---------------------------------------------------------------------------
def test_delay_and_hasten_are_dual_time_shifts() -> None:
    sched = _setup_player_resigned()
    player = sched.get_actor("player")
    base = player.next_ready  # 200.0

    assert sched.delay_actor("player", 100) is True
    assert player.next_ready == base + 100.0  # +100：纯平移（不重算 recovery）

    assert sched.hasten_actor("player", 60) is True
    assert player.next_ready == base + 100.0 - 60.0  # −60：反向平移，对偶成立
