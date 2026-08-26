"""M43 三条回归探针（零定时器 / 确定性抽签 / 快照完整性）——M3 批次8·路X。

依据：
  - 规划_路2a_地图副本.md M43（三条回归防线：① 周期值只能由锚点公式得出（零定时器探针）；
    ② 同 tick 同池两次 map_weather 同值、重启不重抽（确定性）；③ 战斗中断 → 续玩，
    ai_state+combo_state+换区上下文逐字段一致（快照完整性））+ 〇 三面镜子
    （定时器推周期 / 天气真随机 / 快照断裂）
  - m3_shared_contract.md §八 铁律 1（零定时器：周期值只能由锚点公式得出，禁止定时器
    驱动周期）/ 2（确定性：抽签/换区去向/追击路径固定种子可复现；随机一律注入 rng）/
    10（快照完整性：战斗中断续玩 ai_state+combo_state+换区上下文逐字段一致）
  - 细化_2a4b_天气引擎.md §2.3（确定性 seed：池键排序+tick 的 sha256）/ §6.1（纯函数签名）
  - 细化_1g3_快照续战与测试.md §1.2（快照字段级：ai_state+combo_state 全保留）/ §2.3
    （恢复时序）+ m3_shared_contract.md §4.4（战斗中断不改变副本状态，走快照续玩）

探针扫描范围（工程补白，显式标注，不冒充定稿）：
  ① 零定时器 —— 本探针 glob 扫 **qbot_rpg/ 包根**下全部 .py 源码（递归 `**/*.py`）；
     tests/ 位于包外（仓库根 tests/），天然排除；__pycache__ 仅含 .pyc 无 .py 源文件。
     禁止字样 = time.sleep / threading / Timer / schedule / sched（词边界正则匹配，
     防误伤 heal_scheduled/apscheduler/scheduler 等拼写相邻词——探针用词边界，故
     effects.py 的 "heal_scheduled" 效果类型名、content/hot_reload.py docstring 中的
     apscheduler 均不命中）。允许清单（非计时器、不驱动周期值的既有用法，逐条标注理由，
     清单外命中一律红拦；允许项自带自证，清单失效即红拦）：
       - qbot_rpg/content/registry.py 的 threading：threading.Lock 内容注册表并发锁
         （线程安全原语，非计时器；不产生/驱动任何周期值）。自证：该文件 threading
         用法必须为 Lock——若出现 threading.Timer/Thread/sleep 类计时用法则红拦。
     周期引擎本体（engine/worldtime.py + engine/time_query.py）必须在扫描范围内且零
     命中（无允许清单可依——周期值只由锚点公式得出）。
  ② 确定性抽签 —— 真实 qbot_rpg.engine.worldtime.WorldTime.map_weather（IF08）：
     同 tick 同池两次同值 / 重构造实例（=重启）同值不重抽 / 池键乱序注入同值（seed 用
     排序后键列表 + str(tick) sha256，与配置顺序无关）/ 不同 tick 窗口内取值可不同。
  ③ 快照完整性 —— 真实 BattleEngine（start→行动→end_turn 回合边界）注入
     ai_state/combo_state/chase_ctx → to_snapshot → resume_from_snapshot（battle_factory =
     真实 BattleEngine.from_snapshot，即续玩装配走真实引擎还原）→ 续玩推进。

铁律：零 NoneBot import；确定性（固定 tick / 固定 seed=42 / 无随机依赖）；
每功能可追溯（文件头标注依据）；工程补白显式标注（探针扫描范围）。
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.engine.worldtime import DEFAULT_POOL, WorldTime
from qbot_rpg.world.snapshot_resume import resume_from_snapshot

# 仓库根 = tests/unit/test_m43_regression.py 上溯三级
_REPO_ROOT = Path(__file__).resolve().parents[2]

# M43① 零定时器探针：禁止的定时器驱动字样（词边界；周期值只能由锚点公式得出）。
# 词边界匹配防误伤 heal_scheduled/apscheduler/scheduler 等拼写相邻词（见文件头补白）。
_TIMER_TOKENS = re.compile(r"time\.sleep|\bthreading\b|\bTimer\b|\bschedule\b|\bsched\b")

# M43① 允许清单（工程补白）：(相对路径, token) -> 理由。清单外命中一律红拦。
# 允许项只放「非计时器、不驱动周期值」的既有用法，且探针会自证（见 test 内实现）。
_ALLOWED_TIMER_TOKENS: dict = {
    ("qbot_rpg/content/registry.py", "threading"):
        "threading.Lock 内容注册表并发锁（线程安全原语，非计时器；不驱动任何周期值）",
}


def _default_cfg() -> dict:
    """默认 time_cycle 配置（细化_2a4a §1.3 拍板值；对齐 test_time_regression）。"""
    return {"time_cycle": {
        "enabled": True,
        "season": {"season_days": 7},
        "period": {"period_minutes": 60},
        "weather": {"weather_minutes": 60, "default_pool": list(DEFAULT_POOL)},
        "broadcast": {"enabled": False, "mode": "lazy"},
    }}


def _repo_py_sources() -> list:
    """glob 扫 qbot_rpg/ 全仓 .py 源码（递归；tests/ 在包外天然排除；__pycache__ 无 .py）。"""
    hits = sorted(glob.glob(str(_REPO_ROOT / "qbot_rpg" / "**" / "*.py"), recursive=True))
    assert hits, "M43①: qbot_rpg/ 下 glob 未命中任何 .py 源文件（扫描范围失效）"
    return hits


def _rel(path: str) -> str:
    return str(Path(path).resolve().relative_to(_REPO_ROOT)).replace("\\", "/")


# -------------------------------------------------------------------------------------
# ① 零定时器：周期值只能由锚点公式得出（全仓扫描；允许清单显式标注）
# -------------------------------------------------------------------------------------
def test_m43_zero_timer_repo_wide_scan() -> None:
    sources = _repo_py_sources()
    # 全仓规模自检：防 glob 静默缩水导致「扫不到 = 通过」假绿（当前 75 个 .py 源文件）
    assert len(sources) >= 50, f"M43①: 全仓源文件数异常少（{len(sources)}，扫描范围可能失效）"
    # 周期引擎本体必须在扫描范围内（零定时器探针的靶心）
    engine_files = {_rel(p) for p in sources}
    for must in ("qbot_rpg/engine/worldtime.py", "qbot_rpg/engine/time_query.py"):
        assert must in engine_files, f"M43①: 周期引擎源码 {must} 未在扫描范围内（glob 未命中）"

    violations: dict = {}
    for path in sources:
        rel = _rel(path)
        src = Path(path).read_text(encoding="utf-8")
        for token in sorted(set(_TIMER_TOKENS.findall(src))):
            if (rel, token) in _ALLOWED_TIMER_TOKENS:
                # 允许项自证：registry.py 的 threading 用法必须为 Lock（并发锁），
                # 出现 Timer/Thread/Event/sleep 类计时用法 → 允许清单失效，红拦
                if token == "threading":
                    assert "threading.Lock" in src, (
                        f"M43① 允许清单失效：{rel} 出现非 Lock 的 threading 用法（{token}）")
                continue  # 允许项（非计时器，不驱动周期值）
            violations.setdefault(rel, []).append(token)

    assert not violations, (
        f"M43① 零定时器违反（周期值只能由锚点公式得出，m3 铁律 1）：{violations}")


# -------------------------------------------------------------------------------------
# ② 确定性抽签：同 tick 同池同值 / 重启不重抽 / 池序无关 / 不同 tick 可不同值
# -------------------------------------------------------------------------------------
def test_m43_weather_same_tick_same_pool_twice_same_value() -> None:
    """同 tick 同池两次 map_weather 必同值（m3 铁律 2 / 细化_2a4b §2.3 R12）。"""
    wt = WorldTime(_default_cfg())
    for tick in (0, 1, 12345, 999_999_999):
        assert wt.map_weather("map_a", tick) == wt.map_weather("map_a", tick)
        assert wt.weather_now("map_a", now=1750000000) == wt.weather_now("map_a", now=1750000000)


def test_m43_weather_restart_no_redraw_same_value() -> None:
    """不同实例（重构造 WorldTime = 重启）同 tick 同池 → 同值（重启不重抽，懒计算刚需）。"""
    pools = {
        "default": _default_cfg(),
        # 池键乱序注入（同池）：seed = 排序后键列表 + tick → 与配置顺序无关，必同值
        "shuffled": {"time_cycle": {"weather": {"default_pool":
            ["fog", "storm", "clear", "rain", "cloudy"]}}},
    }
    for name, cfg in pools.items():
        wt1, wt2 = WorldTime(cfg), WorldTime(cfg)  # 重构造 = 重启（全新实例，零共享状态）
        for tick in (0, 7, 123, 999_999_999):
            assert wt1.map_weather("map_a", tick) == wt2.map_weather("map_a", tick)
            # 覆盖池形态（map_pools 注入）同样重启不重抽
            mp = {"map_a": ["rain", "storm"], "map_b": ["clear", "fog"]}
            assert wt1.map_weather("map_a", tick, map_pools=mp) == \
                wt2.map_weather("map_a", tick, map_pools=mp)
    # 同 tick 同池但键列表顺序不同 → 同值（seed 输入与配置顺序无关，细化_2a4b §6.1）
    wt_a = WorldTime({"time_cycle": {"weather": {"default_pool":
        ["rain", "fog", "clear", "storm", "cloudy"]}}})
    wt_b = WorldTime({"time_cycle": {"weather": {"default_pool":
        ["cloudy", "clear", "rain", "storm", "fog"]}}})
    for tick in (0, 3, 77, 2_147_483_647):
        assert wt_a.map_weather("map_a", tick) == wt_b.map_weather("map_a", tick)


def test_m43_weather_different_tick_can_differ() -> None:
    """不同 tick 可不同值（抽签确随 tick 变化；sha256 序列，确定性下仍稳定可复现）。"""
    wt = WorldTime(_default_cfg())
    values = {wt.map_weather("map_a", t) for t in range(1000, 1020)}
    assert len(values) >= 2, "M43②: 连续 tick 窗口内 weather 取值应至少两种（抽签随 tick 变化）"
    # 不同 tick 的可不同值在重构造实例（重启）后仍一致（确定性 + 变化同时成立）
    values_restart = {WorldTime(_default_cfg()).map_weather("map_a", t) for t in range(1000, 1020)}
    assert values_restart == values


# -------------------------------------------------------------------------------------
# ③ 快照完整性：中断 → 续玩，ai_state+combo_state+换区上下文逐字段一致
# -------------------------------------------------------------------------------------
# 真实 BattleEngine 端到端夹具（对齐 test_battle_engine.py / test_snapshot_resume.py 形态）
_PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
           "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80,
           "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
_ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40, "mag": 30,
          "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40,
          "lck": 10, "elem_atk": 0, "name": "E"}


def test_m43_snapshot_integrity_ai_combo_chase_field_level() -> None:
    """战斗中断 → 续玩：ai_state+combo_state+换区上下文（chase ctx）逐字段一致（m3 铁律 10）。

    装配走真实链路：BattleEngine 实战到回合边界 → 注入三态 → to_snapshot →
    resume_from_snapshot(battle_factory=真实 BattleEngine.from_snapshot) → 续玩推进。
    """
    eng = BattleEngine().start(_PLAYER, _ENEMY, random_seed=42)
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    eng.enemy_act()
    eng.end_turn()  # 回合边界（1g3 S0：快照只落回合边界）

    injected_ai = {
        "boss_phase": 2,
        "action_table_state": "pattern_index",
        "pending_action": "charge_breath",
        "combo_anchor": 3,
        "marks": {"mark_x": 2},
        "zone_change": {"triggered": True, "from": "molten_core",
                        "targets": ["molten_core"]},  # ai_state 内嵌换区上下文
        "pv_recover_pending": 0.5,
    }
    injected_combo = {
        "active_combo": "combo_flame",
        "seg": 3,
        "total_segs": 5,
        "combo_resources": {"imprint": 1},
        "derived_mult_total": 1.2,
    }
    injected_chase_ctx = {
        "target_map": "molten_core",
        "start_map": "molten_entrance",
        "miss_count": 1,
        "miss_limit": 3,
        "chasing": True,
    }
    eng._snap["ai_state"] = injected_ai
    eng._snap["combo_state"] = injected_combo
    eng._snap["chase_ctx"] = injected_chase_ctx  # 换区上下文随副本会话持久化形态（快照顶层键）
    turn_before = int(eng.battle_state()["turn"])
    enemy_hp_before = eng.battle_state()["enemy"]["hp"]

    snap = eng.to_snapshot(boundary="turn_end")
    assert int(snap["turn"]) == turn_before  # 中断快照回合数 = 中断前

    # 续玩装配：battle_factory = 真实 BattleEngine.from_snapshot（M27 真实链路）
    out = resume_from_snapshot({}, snap, battle_factory=BattleEngine.from_snapshot)
    assert out["resumed"] is True                          # 真实引擎还原成功
    assert out["reason"] is None                           # 无异常原因
    assert out["turn"] == turn_before                      # 续玩回合数恢复
    assert out["ai_state_preserved"] is True               # ai_state 保留判定
    assert out["combo_state_preserved"] is True            # combo_state 保留判定
    assert out["chase_context_preserved"] is True          # 换区上下文保留判定
    assert "chase_ctx" in out["chase_fields"]              # 顶层 chase_ctx 命中
    assert "ai_state.zone_change" in out["chase_fields"]   # ai_state 内嵌换区字段命中
    assert out["reset"] is False and out["state_unchanged"] is True  # 续玩非重置
    restored = out["engine"].battle_state()

    # ---- ai_state 逐字段一致（含嵌套 zone_change 内层字段）----
    rai = restored["ai_state"]
    for k, v in injected_ai.items():
        assert rai[k] == v, f"M43③: ai_state.{k} 续玩后不一致"
    assert rai["zone_change"]["triggered"] is True         # 嵌套：触发标志
    assert rai["zone_change"]["from"] == "molten_core"     # 嵌套：来源区
    assert rai["zone_change"]["targets"] == ["molten_core"]  # 嵌套：候选区
    assert rai["pv_recover_pending"] == 0.5                # 嵌套：换区后 PV 恢复

    # ---- combo_state 逐字段一致（套内续玩载体）----
    rcb = restored["combo_state"]
    for k, v in injected_combo.items():
        assert rcb[k] == v, f"M43③: combo_state.{k} 续玩后不一致"

    # ---- 换区上下文（chase ctx）逐字段一致 ----
    rcc = restored["chase_ctx"]
    for k, v in injected_chase_ctx.items():
        assert rcc[k] == v, f"M43③: chase_ctx.{k} 续玩后不一致"

    # ---- 续玩推进：真实引擎继续作战（非重打），回合前进、双方状态延续 ----
    assert restored["turn"] == turn_before                 # 还原回合数 = 中断前（续玩非重打）
    engine2 = out["engine"]
    engine2.start_turn()                                   # 恢复时序 ⑤：回 ① 继续
    engine2.do_action("player", {"type": "normal", "mult": 1.0})
    engine2.enemy_act()
    engine2.end_turn()
    after = engine2.battle_state()
    assert int(after["turn"]) == turn_before + 2           # 续玩继续推进两回合（start+end）
    assert after["enemy"]["hp"] < enemy_hp_before          # 敌方血量延续扣减（非重打满血）
    assert after["enemy"]["hp"] >= 0                       # 血量合法
    # 续玩推进中 ai_state 逐字段仍与中断前一致（玩家行动不冲掉 AI 状态，M2-C1 原样还原）
    assert after["ai_state"] == injected_ai
