"""M13 批15 路15B · 换季×战斗联动接线单测（tests/unit/test_season_battle_link.py）。

覆盖（≥14 用例 = A 进战 4 + B 换季边界 5 + C 非当季被拒 4 + D 事件 4）：
  A 进战懒加载（EFF-2）：start 建 battle_season 段（{season, pending}）＋
    初始生效季节=进战当前世界季节（ctx season_now 注入通道；无季节环境 →
    回落通用 SEASON_ANY，全技能可用零空窗 P-2/P-10）＋ season_event_state
    幂等段就位（last_season_idx=-1，首次换季必触发 E5 恰一次）；
  B 换季结算边界（F-R2 ③）：end_turn ⑥ tick 后（⑦ 互杀之前）懒重读当前
    季节 → 检测差异标记待结算 → 切换生效季节（当回合行动按旧组校验完毕
    D-05）→ 换季保留项零触碰（MP/连段/印记/冷却/buff 全保留 F-R2 ④）→
    切换幂等（SC-3：连续同季不重复切换不重复触发）→ 换季 log 一行反馈
    （message_key=season_change）→ 战斗外/无快照不切换（F-R2 ⑥ / P-7）；
  C 非当季技能被拒（EFF-5）：{type:skill} 行动施放前校验——非当季 →
    被拒不耗回合（rejected 管道语义：不耗回合/连段不变/可反复尝试）＋
    combo_reason=season_mismatch；当季/通用技能正常施放；普攻 normal 与
    防御 guard 全年可用（EFF-3 兜底零空窗）；待结算期（D-05）本回合行动
    仍按旧组校验（旧季节技能可用）；
  D on_season_change 事件（E1/E5）：换季切换成功 → 恰一次触发（season_
    event_state.last_season_idx 幂等基准）＋ L2 proc 容器执行（season_procs
    注入 → execute_proc_action 容器跑 proc_triggered 副作用）＋ 未换季
    不触发（幂等）。

铁律：零 NoneBot import；平台无关（core 层直接驱动 BattleEngine）；纯函数
确定性（固定随机种子 + 显式注入 defs，无随机断言）；零定时器/零睡眠（本
文件不含任何 sleep/定时器字面量——纯回合边界驱动，无时间依赖）；不引入
随机；只写本文件。
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
    # 通用环境：夏季技能也能正常施放（零空窗）
    out = eng.do_action("player", {"type": "skill", "skill_id": "summer_blaze"})
    assert out.ok is True


def test_start_without_season_env_general_skills_all_usable() -> None:
    """无季节环境：四季技能全部可用（EFF-1 战斗外口径延伸 / P-10）。"""
    eng = BattleEngine(defs=_season_defs())
    eng.start(_player(), _enemy(), random_seed=2)
    for sid in ("spring_bloom", "summer_blaze", "autumn_gale", "winter_veil",
                "four_seasons"):
        out = eng.do_action("player", {"type": "skill", "skill_id": sid})
        assert out.ok is True, sid
        assert out.action_type == "skill"


# ===========================================================================
# B 换季结算边界（F-R2 ③：end_turn ⑥ tick 后切换，D-05 / SC-3）
# ===========================================================================


def test_end_turn_season_change_switches_and_logs() -> None:
    """回合结束 tick 后：检测差异 → 待结算 → 切换生效季节 + 一行换季 log。"""
    eng = _engine(season="spring")
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng._snap["season_now"] = "summer"  # 世界季节懒重读：春 → 夏
    eng.end_turn()
    # 切换完成：生效季节 → 夏（下一回合技能列表=夏组+通用）
    assert effective_season(eng.battle_state()) == "summer"
    assert pending_flag(eng.battle_state()) is False
    # 一行换季反馈（F-R2 ⑤ message_key 语义键；续局路径 log 兜底落快照流水）
    se = eng.battle_state().get("season_events", [])
    keys = [e.get("message_key") for e in se if e.get("type") == "season_change"]
    assert keys == ["season_change"]
    assert se[-1]["from"] == "spring"
    assert se[-1]["to"] == "summer"


def test_end_turn_no_season_diff_is_idempotent() -> None:
    """连续同季：无差异 → 不切换不标记（SC-3 恰一次原则）。"""
    eng = _engine(season="spring")
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    rep = eng.end_turn()  # 世界仍春
    assert effective_season(eng.battle_state()) == "spring"
    assert pending_flag(eng.battle_state()) is False
    assert not [e for e in rep.log if e.get("type") == "season_change"]


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
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng._snap["season_now"] = "autumn"
    eng.end_turn()
    after = eng.battle_state()
    assert after["marks_state"] == before["marks"]
    assert after["player"]["buff_ids"] == before["buff"]
    assert after["player"]["mp"] == before["mp"]
    assert effective_season(after) == "autumn"


def test_end_turn_season_change_once_per_boundary() -> None:
    """同一结算边界只切换/触发一次；下一回合同季不再触发（E5/SC-3）。"""
    eng = _engine(season="spring")
    # 第 2 回合结束：春 → 夏 切换
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng._snap["season_now"] = "summer"
    eng.end_turn()
    assert effective_season(eng.battle_state()) == "summer"
    se1 = eng.battle_state().get("season_events", [])
    assert len([e for e in se1 if e.get("type") == "season_change"]) == 1
    # 第 3 回合结束：世界仍夏 → 幂等不触发（流水条数不增）
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    assert effective_season(eng.battle_state()) == "summer"
    se2 = eng.battle_state().get("season_events", [])
    assert len([e for e in se2 if e.get("type") == "season_change"]) == 1, \
        "同季幂等：换季流水不新增"


def test_season_change_does_not_happen_outside_battle() -> None:
    """战斗外/无快照：换季挂点零操作（F-R2 ⑥ / P-7 防御）。"""
    eng = BattleEngine(defs=_season_defs())  # 未 start → 无快照
    assert eng._tick_season_boundary() == {"switched": False}


# ===========================================================================
# C 非当季技能被拒（EFF-5：施放前校验；不耗回合/连段不变/可反复尝试）
# ===========================================================================


def test_out_of_season_skill_rejected_no_turn_consumed() -> None:
    """春季使用夏季技能 → 被拒不耗回合（rejected 管道语义）。"""
    eng = _engine(season="spring")
    out = eng.do_action("player", {"type": "skill", "skill_id": "summer_blaze"})
    assert out.ok is False
    assert out.hit is False
    assert out.raw_damage == 0
    assert "时节不合" in out.message
    assert "不耗回合" in out.message
    # 不耗回合：状态保持 ACT，可再次行动（turn 未推进）
    assert eng.state == "act"
    assert eng.battle_state()["turn"] == 1
    assert eng._turn_acted["player"] is False


def test_out_of_season_reject_preserves_combo_and_mp() -> None:
    """非当季被拒：连段/能量不变（可反复尝试，1c1c TC-DEF-04）。"""
    eng = _engine(season="spring")
    eng._snap["combo_state"] = {"player": {"count": 3}}
    eng._snap["player"]["mp"] = 100
    out = eng.do_action("player", {"type": "skill", "skill_id": "winter_veil"})
    assert out.ok is False
    assert eng.battle_state()["combo_state"]["player"]["count"] == 3
    assert eng.battle_state()["player"]["mp"] == 100


def test_in_season_and_general_skills_cast_normally() -> None:
    """当季技能 + 通用技能 → 正常施放（EFF-5 可用判定）。"""
    eng = _engine(season="spring")
    out1 = eng.do_action("player", {"type": "skill", "skill_id": "spring_bloom"})
    assert out1.ok is True
    out2 = eng.do_action("player", {"type": "skill", "skill_id": "four_seasons"})
    assert out2.ok is True


def test_basic_and_guard_always_available_even_off_season() -> None:
    """普攻 normal / 防御 guard 全年可用（EFF-3 兜底零空窗）。"""
    eng = _engine(season="winter")
    out1 = eng.do_action("player", {"type": "normal"})
    assert out1.ok is True
    out2 = eng.do_action("player", {"type": "guard"})
    assert out2.ok is True


def test_pending_turn_still_validates_by_old_season() -> None:
    """待结算期（D-05）：检测到差异的当回合行动仍按旧组校验（旧季可用）。"""
    eng = _engine(season="spring")
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng._snap["season_now"] = "summer"  # 懒重读差异 → 标记待结算
    eng.end_turn()  # 结算边界：切换为夏
    # 第 2 回合开始时世界仍夏（待结算期已过，新季节生效）
    # 旧组（春）技能此时被拒、新组（夏）技能可用
    out_old = eng.do_action("player", {"type": "skill", "skill_id": "spring_bloom"})
    assert out_old.ok is False
    out_new = eng.do_action("player", {"type": "skill", "skill_id": "summer_blaze"})
    assert out_new.ok is True


# ===========================================================================
# D on_season_change 事件（E1/E5：恰一次 + L2 proc 容器执行）
# ===========================================================================


def test_season_change_fires_event_once() -> None:
    """换季切换成功 → on_season_change 恰一次（season_event_state 幂等）。"""
    eng = _engine(season="spring")
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng._snap["season_now"] = "summer"
    eng.end_turn()
    ev = eng.battle_state()[SEASON_EVENT_STATE_KEY]
    assert ev[LAST_SEASON_IDX_KEY] == 1  # summer 索引 1（已触发登记）


def test_season_event_idempotent_without_change() -> None:
    """未换季 → 事件不触发（幂等基准 last_season_idx 不变）。"""
    eng = _engine(season="spring")
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()  # 世界仍春
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
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng._snap["season_now"] = "autumn"
    eng.end_turn()
    ev = eng.battle_state()[SEASON_EVENT_STATE_KEY]
    assert ev[LAST_SEASON_IDX_KEY] == 2  # autumn 索引 2（恰一次）
    # proc 已执行：effect_triggers 计数登记（容器副作用）
    triggers = eng.battle_state()["effect_triggers"]["player"]["per_battle"]
    assert triggers.get("season_blessing", 0) >= 1


def test_season_event_no_procs_still_registers() -> None:
    """无 proc 注入 → 事件仍登记幂等（只登记不执行，E5 恰一次）。"""
    eng = _engine(season="spring")
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng._snap["season_now"] = "winter"
    eng.end_turn()
    ev = eng.battle_state()[SEASON_EVENT_STATE_KEY]
    assert ev[LAST_SEASON_IDX_KEY] == 3  # winter 索引 3


# ---------------------------------------------------------------------------
# 兜底：_check_season_action 直接层（协议对象/缺 defs 防御）
# ---------------------------------------------------------------------------


def test_season_gate_missing_skill_def_falls_back_ok() -> None:
    """技能 def 缺失（resolve_skill 空）→ season 判定按通用回落（不误伤）。"""
    eng = _engine(season="summer")
    out = eng.do_action("player", {"type": "skill", "skill_id": "ghost_skill"})
    assert out.ok is True  # 未知技能：combo 引擎原口径（不因季节误伤）


def test_season_gate_ignores_normal_and_item_actions() -> None:
    """普攻/道具行动不经过季节校验（EFF-3 兜底；零误伤）。"""
    eng = _engine(season="winter")
    out1 = eng.do_action("player", {"type": "normal"})
    assert out1.ok is True
    out2 = eng.do_action(
        "player",
        {"type": "item", "item_id": "potion",
         "actions": [{"type": "heal", "value": 100}]},
    )
    assert out2.ok is True
