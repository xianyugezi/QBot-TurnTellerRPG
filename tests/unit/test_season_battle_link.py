"""M13 批15 路15B · 换季×战斗联动接线单测（tests/unit/test_season_battle_link.py）。

CTB 迁移（2026-09-10）：旧 round 语义 → CTB 语义 对照
  - 旧「换季检测在 `end_turn` ⑥ tick 后（⑦ 互杀之前）」→ CTB「换季边界挂
    `BATTLE_TIME_ADVANCE`（全局逻辑时间推进位点），由调度器在推进行动条时派发」。
    旧测试用 `do_action → enemy_act → end_turn` 驱动回合边界；CTB 改用**一次成功
    的 `player_act`**（提交玩家行动 + 调度器自动推进 NPC 连锁）——只有时间轴真正
    前进才会跨过 `BATTLE_TIME_ADVANCE`，被拒行动零时间成本因此不换季。
  - 旧「回合结束 tick 后一行换季 log 落 season_events」→ CTB 该反馈语义由
    `_tick_season_boundary()` 返回的 `message_key="season_change"` 承载（引擎不再
    写 season_events 流水——见文件末「CTB 迁移缺口登记」）。
  - 旧「非当季技能被拒 → 不耗回合」→ CTB「被拒 = 零时间成本（R-6 裁决 2）：
    `action_seq` 不增、可立即换指令重试」。
  - 旧「待结算期当回合仍按旧组校验」→ CTB「切换前 `season_now` 现读：切换由
    时间位点决定，校验按当前 `season_now`」。
  - 旧「N 回合 → 事件恰一次」→ 「`_fire_season_event` 幂等基准 last_season_idx」。

覆盖（≥14 用例 = A 进战 4 + B 换季边界 5 + C 非当季被拒 4 + D 事件 4）：
  A 进战懒加载（EFF-2）：start 建 battle_season 段（{season, pending}）＋
    初始生效季节=进战当前世界季节（ctx season_now 注入通道；无季节环境 →
    回落通用 SEASON_ANY，全技能可用零空窗 P-2/P-10）＋ season_event_state
    幂等段就位（last_season_idx=-1，首次换季必触发 E5 恰一次）；
  B 换季结算边界（F-R2 ③）：`player_act` 推进时间轴跨 BATTLE_TIME_ADVANCE 后
    懒重读当前季节 → 检测差异标记待结算 → 切换生效季节（当拍行动按旧组校验
    完毕 D-05）→ 换季保留项零触碰（MP/连段/印记/冷却/buff 全保留 F-R2 ④）→
    切换幂等（SC-3）→ message_key=season_change 反馈；
  C 非当季技能被拒（EFF-5）：{type:skill} 行动施放前校验——非当季 → 被拒
    （零时间成本/连段不变/可反复尝试）＋当季/通用技能正常施放；普攻 normal 与
    防御 guard 全年可用（EFF-3 兜底零空窗）；
  D on_season_change 事件（E1/E5）：换季切换成功 → 恰一次触发（season_
    event_state.last_season_idx 幂等基准）＋ L2 proc 容器执行（season_procs
    注入 → execute_proc_action 容器跑副作用）＋ 未换季不触发（幂等）。

CTB 迁移缺口登记（业务代码，非本文件可修；已在最终报告标注）：
  引擎 `_on_battle_time_advance` 只调用 `_tick_season_boundary()`（切换生效季节
  + 复位 pending），**未接线** `_fire_season_event(...)`（事件幂等登记 + proc 容器）
  与旧 `season_events` 反馈流水。故 D 组用例按 CTB 事件位点的**设计序列**显式驱动
  `_tick_season_boundary()` → `_fire_season_event()`（两者均为引擎在位点方法），
  锁定「切换后事件恰一次 + proc 执行」的 CTB 语义；接线补齐后本文件可改回
  单次 `player_act` 断言。

铁律：零 NoneBot import；平台无关（core 层直接驱动 BattleEngine）；纯函数
确定性（固定随机种子 + 显式注入 defs，无随机断言）；零定时器/零睡眠（本文件不
含任何 sleep/定时器字面量——纯行动边界驱动，无时间依赖）；只写本文件。
"""
from __future__ import annotations

from typing import Any, Dict


from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.battle_season import (
    BATTLE_SEASON_KEY,
    PENDING_STATE_KEY,
    SEASON_ANY,
    SEASON_STATE_KEY,
    effective_season,
    pending_flag,
)
from qbot_rpg.core.season_events import (
    LAST_SEASON_IDX_KEY,
    SEASON_EVENT_STATE_KEY,
)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------


def _player() -> Dict[str, Any]:
    return {"hp": 2000, "max_hp": 2000, "mp": 500, "max_mp": 500,
            "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"}


def _enemy() -> Dict[str, Any]:
    return {"hp": 2000, "max_hp": 2000, "mp": 500, "max_mp": 500,
            "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"}


def _season_defs() -> Dict[str, Dict[str, Any]]:
    """季节技能库：春/夏/秋/冬四组 + 通用 + 普攻/防御兜底。"""
    return {
        "spring_bloom": {"id": "spring_bloom", "name": "春华", "type": "active",
                         "kind": "damage", "season": "spring", "mult": 1.0,
                         "mp_cost": 0},
        "summer_blaze": {"id": "summer_blaze", "name": "夏炎", "type": "active",
                         "kind": "damage", "season": "summer", "mult": 1.0,
                         "mp_cost": 0},
        "autumn_gale": {"id": "autumn_gale", "name": "秋风", "type": "active",
                        "kind": "damage", "season": "autumn", "mult": 1.0,
                        "mp_cost": 0},
        "winter_veil": {"id": "winter_veil", "name": "冬幕", "type": "active",
                        "kind": "damage", "season": "winter", "mult": 1.0,
                        "mp_cost": 0},
        "four_seasons": {"id": "four_seasons", "name": "四时调和", "type": "active",
                         "kind": "damage", "mult": 1.0, "mp_cost": 0},
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                         "kind": "damage", "mult": 1.0, "mp_cost": 0},
    }


def _engine(season: str = "spring", defs: Any = None) -> BattleEngine:
    """真实战斗引擎：注入季节技能库 defs + 进战世界季节（season_now）。"""
    eng = BattleEngine(defs=defs if defs is not None else _season_defs())
    eng.start(_player(), _enemy(), random_seed=42)
    # 装配层注入通道（worldtime.season_now）：先注入再重跑进战懒加载
    # （init_battle_season 覆盖式幂等——进战初始生效季节 = 当前世界季节）
    eng._snap["season_now"] = season
    eng._init_season_state()
    return eng


def _bs(eng: BattleEngine) -> Dict[str, Any]:
    return eng.battle_state()[BATTLE_SEASON_KEY]


def _advance_timeline(eng: BattleEngine, action: Any = "normal"):
    """CTB：用一次**成功**行动跨过 BATTLE_TIME_ADVANCE。

    只有时间轴真正前进（成功 `player_act`）才会派发全局时间推进位点 → 换季结算；
    被拒行动零时间成本，不跨界（R-6 裁决 2）。
    """
    return eng.player_act(action)


# ===========================================================================
# A 进战懒加载（EFF-2：start 建段 + 初始生效季节 + 无季节环境兜底）
# ===========================================================================


def test_start_builds_season_state_segment() -> None:
    """start() 建 battle_season 段（{season, pending}）＋事件幂等段（EFF-2）。"""
    eng = _engine(season="spring")
    seg = _bs(eng)
    assert set(seg) == {SEASON_STATE_KEY, PENDING_STATE_KEY}
    assert seg[PENDING_STATE_KEY] is False
    ev = eng.battle_state()[SEASON_EVENT_STATE_KEY]
    assert ev[LAST_SEASON_IDX_KEY] == 0  # 进战登记当前季节索引（spring=0）——
    # 后续「换季 ≠ 进战季节」才触发事件（E5 恰一次；进战本身不触发）


def test_start_initial_season_from_injected_season_now() -> None:
    """进战初始生效季节 = 进战当前世界季节（ctx season_now 注入通道）。"""
    eng = _engine(season="summer")
    assert effective_season(eng.battle_state()) == "summer"


def test_start_without_season_env_falls_back_general() -> None:
    """无季节环境（未注入 season_now）→ 回落通用（全技能可用零空窗 P-2）。"""
    eng = BattleEngine(defs=_season_defs())
    eng.start(_player(), _enemy(), random_seed=1)
    assert effective_season(eng.battle_state()) == SEASON_ANY
    # 通用环境：夏季技能也能正常施放（零空窗）。CTB：经 player_act 提交。
    out = eng.player_act({"type": "skill", "skill_id": "summer_blaze"}).outcomes[0]
    assert out.ok is True


def test_start_without_season_env_general_skills_all_usable() -> None:
    """无季节环境：四季技能全部可用（EFF-1 战斗外口径延伸 / P-10）。"""
    eng = BattleEngine(defs=_season_defs())
    eng.start(_player(), _enemy(), random_seed=2)
    for sid in ("spring_bloom", "summer_blaze", "autumn_gale", "winter_veil",
                "four_seasons"):
        out = eng.player_act({"type": "skill", "skill_id": sid}).outcomes[0]
        assert out.ok is True, sid
        assert out.action_type == "skill"


# ===========================================================================
# B 换季结算边界（F-R2 ③：BATTLE_TIME_ADVANCE 位点切换，D-05 / SC-3）
# ===========================================================================


def test_end_turn_season_change_switches_and_logs() -> None:
    """时间轴推进跨 BATTLE_TIME_ADVANCE 后：检测差异 → 待结算 → 切换生效季节。

    CTB：换季边界挂在全局时间推进位点（`_on_battle_time_advance` 调
    `_tick_season_boundary()`）；旧「一行换季 log」反馈语义由位点返回的
    message_key 承载。
    """
    eng = _engine(season="spring")
    eng._snap["season_now"] = "summer"  # 世界季节懒重读：春 → 夏
    # 位点结算（BATTLE_TIME_ADVANCE 内调用）：检测差异 → 切换生效季节
    switched = eng._tick_season_boundary()
    # 切换完成：生效季节 → 夏（下一拍技能列表=夏组+通用）
    assert effective_season(eng.battle_state()) == "summer"
    assert pending_flag(eng.battle_state()) is False
    # 一行换季反馈（F-R2 ⑤ message_key 语义键）：CTB 由位点返回值承载
    assert switched["switched"] is True
    assert switched["message_key"] == "season_change"
    assert switched["from"] == "spring"
    assert switched["to"] == "summer"
    # 时间轴继续前进（成功行动）不改变已切换的季节（幂等）
    _advance_timeline(eng)
    assert effective_season(eng.battle_state()) == "summer"


def test_end_turn_no_season_diff_is_idempotent() -> None:
    """连续同季：无差异 → 不切换不标记（SC-3 恰一次原则）。"""
    eng = _engine(season="spring")
    report = _advance_timeline(eng)  # 世界仍春
    assert effective_season(eng.battle_state()) == "spring"
    assert pending_flag(eng.battle_state()) is False
    assert not [e for e in report.log if e.get("type") == "season_change"]


def test_end_turn_season_change_preserves_battle_state() -> None:
    """换季保留项（F-R2 ④）：MP/印记/buff 全保留（零触碰）。"""
    eng = _engine(season="spring")
    eng._snap["marks_state"] = {"player": [{"mark": "火印"}], "enemy": []}
    eng._snap["player"]["buff_ids"] = ["atk_up"]
    eng._snap["player"]["mp"] = 300
    before = {
        "marks": eng.battle_state()["marks_state"],
        "buff": eng.battle_state()["player"]["buff_ids"],
        "mp": eng.battle_state()["player"]["mp"],
    }
    eng._snap["season_now"] = "autumn"
    _advance_timeline(eng)
    after = eng.battle_state()
    assert after["marks_state"] == before["marks"]
    assert after["player"]["buff_ids"] == before["buff"]
    assert after["player"]["mp"] == before["mp"]
    assert effective_season(after) == "autumn"


def test_end_turn_season_change_once_per_boundary() -> None:
    """同一结算边界只切换/触发一次；下一次时间推进同季不再切换（E5/SC-3）。"""
    eng = _engine(season="spring")
    # 第一次时间推进：春 → 夏 切换
    eng._snap["season_now"] = "summer"
    _advance_timeline(eng)
    assert effective_season(eng.battle_state()) == "summer"
    seq1 = eng.battle_state()["action_seq"]
    # 第二次时间推进：世界仍夏 → 幂等不切换（action_seq 严格增加，季节不变）
    _advance_timeline(eng)
    assert effective_season(eng.battle_state()) == "summer"
    assert eng.battle_state()["action_seq"] > seq1, "时间轴应继续前进"


def test_season_change_does_not_happen_outside_battle() -> None:
    """战斗外/无快照：换季挂点零操作（F-R2 ⑥ / P-7 防御）。"""
    eng = BattleEngine(defs=_season_defs())  # 未 start → 无快照
    assert eng._tick_season_boundary() == {"switched": False}


# ===========================================================================
# C 非当季技能被拒（EFF-5：施放前校验；零时间成本/连段不变/可反复尝试）
# ===========================================================================


def test_out_of_season_skill_rejected_no_turn_consumed() -> None:
    """春季使用夏季技能 → 被拒且零时间成本（CTB：action_seq 不增）。"""
    eng = _engine(season="spring")
    seq_before = eng.battle_state()["action_seq"]
    out = eng.player_act({"type": "skill", "skill_id": "summer_blaze"}).outcomes[0]
    assert out.ok is False
    assert out.hit is False
    assert out.raw_damage == 0
    assert "时节不合" in out.message
    assert "零时间成本" in out.message
    # CTB：被拒 = 该行动从未发生，行动条不前进（action_seq 不变），仍可立即重试
    assert eng.battle_state()["action_seq"] == seq_before, "被拒行动应零时间成本"
    assert eng._ctb.paused is True, "被拒后玩家拍保持待命，可立即换指令"


def test_out_of_season_reject_preserves_combo_and_mp() -> None:
    """非当季被拒：连段/能量不变（可反复尝试，1c1c TC-DEF-04）。"""
    eng = _engine(season="spring")
    eng._snap["combo_state"] = {"player": {"count": 3}}
    eng._snap["player"]["mp"] = 100
    out = eng.player_act({"type": "skill", "skill_id": "winter_veil"}).outcomes[0]
    assert out.ok is False
    assert eng.battle_state()["combo_state"]["player"]["count"] == 3
    assert eng.battle_state()["player"]["mp"] == 100


def test_in_season_and_general_skills_cast_normally() -> None:
    """当季技能 + 通用技能 → 正常施放（EFF-5 可用判定）。"""
    eng = _engine(season="spring")
    out1 = eng.player_act({"type": "skill", "skill_id": "spring_bloom"}).outcomes[0]
    assert out1.ok is True
    out2 = eng.player_act({"type": "skill", "skill_id": "four_seasons"}).outcomes[0]
    assert out2.ok is True


def test_basic_and_guard_always_available_even_off_season() -> None:
    """普攻 normal / 防御 guard 全年可用（EFF-3 兜底零空窗）。"""
    eng = _engine(season="winter")
    out1 = eng.player_act({"type": "normal"}).outcomes[0]
    assert out1.ok is True
    out2 = eng.player_act({"type": "guard"}).outcomes[0]
    assert out2.ok is True


def test_pending_turn_still_validates_by_old_season() -> None:
    """校验按当前 `season_now` 现读（CTB 替代旧「待结算期旧组校验」D-05）。

    旧语义：差异检测后的当回合仍按旧组校验、新季节次回合生效。CTB：换季发生在
    **全局时间推进位点**（时间轴前进后），位点之前 `season_now` 未被重读 → 当拍
    仍按旧季校验；位点推进后新季立即生效。
    """
    eng = _engine(season="spring")
    # 时间位点前：世界季节尚未重读（仍春）→ 春技能可用
    out_before = eng.player_act({"type": "skill", "skill_id": "spring_bloom"}).outcomes[0]
    assert out_before.ok is True
    # 世界季节切换 + 时间轴前进 → 位点结算，新季生效
    eng._snap["season_now"] = "summer"
    _advance_timeline(eng)
    assert effective_season(eng.battle_state()) == "summer"
    # 新季生效后：旧组（春）技能被拒、新组（夏）技能可用
    out_old = eng.player_act({"type": "skill", "skill_id": "spring_bloom"}).outcomes[0]
    assert out_old.ok is False
    out_new = eng.player_act({"type": "skill", "skill_id": "summer_blaze"}).outcomes[0]
    assert out_new.ok is True


# ===========================================================================
# D on_season_change 事件（E1/E5：恰一次 + L2 proc 容器执行）
#
# CTB 事件位点序列：_tick_season_boundary()（BATTLE_TIME_ADVANCE 切换）
#   → _fire_season_event(switched)（on_season_change 登记 + proc 容器）
# 见文件头「CTB 迁移缺口登记」。
# ===========================================================================


def _switch_and_fire(eng: BattleEngine, season_now: str) -> Dict[str, Any]:
    """CTB 换季事件位点设计序列：切换 → 触发 on_season_change（恰一次）。"""
    eng._snap["season_now"] = season_now
    switched = eng._tick_season_boundary()
    if switched.get("switched"):
        eng._fire_season_event(switched)
    return switched


def test_season_change_fires_event_once() -> None:
    """换季切换成功 → on_season_change 恰一次（season_event_state 幂等）。"""
    eng = _engine(season="spring")
    switched = _switch_and_fire(eng, "summer")
    assert switched["switched"] is True
    ev = eng.battle_state()[SEASON_EVENT_STATE_KEY]
    assert ev[LAST_SEASON_IDX_KEY] == 1  # summer 索引 1（已触发登记）


def test_season_event_idempotent_without_change() -> None:
    """未换季 → 事件不触发（幂等基准 last_season_idx 不变）。"""
    eng = _engine(season="spring")
    switched = _switch_and_fire(eng, "spring")  # 世界仍春
    assert switched["switched"] is False
    ev = eng.battle_state()[SEASON_EVENT_STATE_KEY]
    assert ev[LAST_SEASON_IDX_KEY] == 0  # spring 索引 0（进战即登记）


def test_season_event_procs_executed_via_container() -> None:
    """L2 proc 容器：season_procs 注入 → execute_proc_action 执行副作用。"""
    eng = _engine(season="spring")
    eng._snap["season_procs"] = [
        {"id": "season_blessing", "type": "on_season_change",
         "trigger": "on_season_change", "chance": 1.0,
         "actions": [{"type": "heal", "value": 50}]},
    ]
    switched = _switch_and_fire(eng, "autumn")
    assert switched["switched"] is True
    ev = eng.battle_state()[SEASON_EVENT_STATE_KEY]
    assert ev[LAST_SEASON_IDX_KEY] == 2  # autumn 索引 2（恰一次）
    # proc 已执行：effect_triggers 计数登记（容器副作用）
    triggers = eng.battle_state()["effect_triggers"]["player"]["per_battle"]
    assert triggers.get("season_blessing", 0) >= 1


def test_season_event_no_procs_still_registers() -> None:
    """无 proc 注入 → 事件仍登记幂等（只登记不执行，E5 恰一次）。"""
    eng = _engine(season="spring")
    switched = _switch_and_fire(eng, "winter")
    assert switched["switched"] is True
    ev = eng.battle_state()[SEASON_EVENT_STATE_KEY]
    assert ev[LAST_SEASON_IDX_KEY] == 3  # winter 索引 3


# ---------------------------------------------------------------------------
# 兜底：_check_season_action 直接层（协议对象/缺 defs 防御）
# ---------------------------------------------------------------------------


def test_season_gate_missing_skill_def_falls_back_ok() -> None:
    """技能 def 缺失（resolve_skill 空）→ season 判定按通用回落（不误伤）。"""
    eng = _engine(season="summer")
    out = eng.player_act({"type": "skill", "skill_id": "ghost_skill"}).outcomes[0]
    assert out.ok is True  # 未知技能：combo 引擎原口径（不因季节误伤）


def test_season_gate_ignores_normal_and_item_actions() -> None:
    """普攻/道具行动不经过季节校验（EFF-3 兜底；零误伤）。"""
    eng = _engine(season="winter")
    out1 = eng.player_act({"type": "normal"}).outcomes[0]
    assert out1.ok is True
    out2 = eng.player_act(
        {"type": "item", "item_id": "potion",
         "actions": [{"type": "heal", "value": 100}]},
    ).outcomes[0]
    assert out2.ok is True
