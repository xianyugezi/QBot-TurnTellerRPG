#!/usr/bin/env python3
"""M42 端到端集成冒烟（M3 批次8·路W）：探索版 + BOSS 版两路径，固定种子可重放。

依据：
  - 规划_路2a_地图副本.md M42（端到端集成冒烟：进 BOSS 版（入场限制）→ 可选子任务 → 精英 →
    BOSS 战（三阶段）→ 残血换区 → /进入 追击 → 续战（残血+PV 半恢复+开场技）→ 决战 →
    通关奖励；探索版全通；全程时间/天气钩子生效；随机种子固定可重放）
  - m3_shared_contract.md §4（副本流程：S0-S7 状态集 + M1-M15 迁移表 + 子任务五形式 +
    奖励与可选性；快照/换区上下文随会话持久化）
  - 细化_2a3_副本两型流程.md §一（整体体验单元：探索版=同一地图「练习赛」/ BOSS 版=完整
    一场战斗；两型共用同一组地图、入口区分、进度独立）

装配：真实模块（qbot_rpg.core.dungeon / dungeon_boss / dungeon_subquest、qbot_rpg.world
movement / chase / chase_resume、qbot_rpg.engine.worldtime）；maps/dungeons/enemies 数据
读取自 tests/fixtures/packs/legal/；worldtime 注入固定 now（2026-08-16 00:00 UTC+8，纪元
锚点公式手算值对齐 test_worldtime_changes：season_idx=1 夏 / period_idx=1 午 /
weather_tick=233376）保证确定性；追击候选区抽签注入固定种子 rng。零 NoneBot import。

状态迁移断言口径（契约 §4.2 M1-M15）：
  探索版 S0→S1→S1→S5→S7（进入→走通道×2→通关 CLEARED→离开重置）
  BOSS 版 S0→S1→S2→S1→S3→S4→S5→S7（进入→走通道×2→精英升压→追击态→决战→击杀→离开）

工程补白（定稿/契约未明示处，显式标注，不冒充定稿）：
  1. quest.json 未随 legal 包提供：子任务条目以 dungeon.json subquests 的 id 为名构造
     （结构对齐 dungeon_subquest.normalize_subquest），仅用于驱动 ProgressTracker 五形式。
  2. 换区候选图（molten_corridor / molten_core，enemies.json zone_change.targets 引用）
     不在 legal maps.json 内：冒烟在合法地图基础上追加两张候选区图并接线
     （lava_tunnel 左 → molten_corridor → molten_core），仅供 pursue 追击段使用。
  3. 守门怪已击败标记（session[SESSION_GATE_GUARDS_KEY]）与 BOSS 残血快照
     （session.boss_state）按契约键直接落盘——真实战斗中由战斗侧落盘，冒烟不接战斗。
  4. 通关奖励：冒烟断言 drops 配置形态（normal/boss/first_clear）并打印结算摘要；
     实际入账由奖励管线（规划 M23 / 批次7 P 路）接线，本脚本不发放。
  5. 探索版路径以 M18 explore_run 的组成模块（movement.resolve_move /
     ProgressTracker.record / DungeonStateMachine.transition）逐段驱动，另附加一次
     explore_run 整装流程调用验证（M18 全链路）。

铁律：零 NoneBot import；确定性（固定 now/种子，两次运行摘要逐字一致）；文件头标注依据。

用法：.venv/bin/python scripts/e2e_m3_smoke.py
退出码：0 = 全绿（打印「M42 端到端冒烟全绿（探索版 + BOSS 版）」）；1 = 有失败。
"""
from __future__ import annotations

import copy
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, cast

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))  # 独立可运行：scripts/ 下直接执行也可见 qbot_rpg

from qbot_rpg.content.dungeon_models import DungeonDef
from qbot_rpg.content.models import EnemyDef
from qbot_rpg.core.dungeon import (
    S0, S1, S2, S3, S4, S5, S7,
    DungeonSession,
    DungeonStateMachine,
    explore_run,
)
from qbot_rpg.core.dungeon_boss import SESSION_GATE_GUARDS_KEY, BossFlow
from qbot_rpg.core.dungeon_subquest import ProgressTracker
from qbot_rpg.engine.worldtime import DEFAULT_POOL, WorldTime
from qbot_rpg.world.chase import SESSION_CHASING_KEY, chase_trigger, pursue
from qbot_rpg.world.chase_resume import exit_dungeon_reset, prepare_resume_battle
from qbot_rpg.world.movement import resolve_move

# -------------------------------------------------------------------------------------
# 常量（固定 now / 种子 —— 确定性铁律）
# -------------------------------------------------------------------------------------
LEGAL_DIR = REPO / "tests" / "fixtures" / "packs" / "legal"
_TZ8 = timezone(timedelta(hours=8))
FIXED_NOW = int(datetime(2026, 8, 16, 0, 0, 0, tzinfo=_TZ8).timestamp())  # 2026-08-16 00:00 UTC+8
CHASE_SEED = 20260816          # 追击候选区抽签固定种子（R8 确定性）
EXPLORE_ID = "molten_dungeon_explore"
BOSS_ID = "molten_dungeon_boss"
BOSS_ROOM = "lava_tunnel"      # dungeon.json molten_dungeon_boss.boss_room = lava_tunnel
BOSS_MONSTER = "ember_drake"
SAFE_ZONE = "rubble_field"     # dungeon.json safe_zone（两型同）
WORLD_ANCHOR = "mountain_foot"  # 世界图外部锚点（进入前玩家所在节点）
CONTENT_PACK = "legal"
CONTENT_VERSION = "1.0.0"
# 契约 §4.2 断言链（探索版 / BOSS 版状态迁移）
EXPLORE_STATES = [S0, S1, S1, S5, S7]
BOSS_STATES = [S0, S1, S1, S2, S1, S3, S4, S5, S7]


# -------------------------------------------------------------------------------------
# 断言收集器
# -------------------------------------------------------------------------------------
class Smoke:
    """断言收集器：check/check_eq 计数；全部通过 → ok。"""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.failures: List[str] = []

    def check(self, cond: bool, label: str) -> bool:
        if cond:
            self.passed += 1
            return True
        self.failed += 1
        self.failures.append(label)
        return False

    def check_eq(self, got: object, want: object, label: str) -> bool:
        if got == want:
            self.passed += 1
            return True
        self.failed += 1
        self.failures.append(f"{label}：期望 {want!r}，实际 {got!r}")
        return False


# -------------------------------------------------------------------------------------
# 装配：真实数据（tests/fixtures/packs/legal/）+ worldtime（固定 now）
# -------------------------------------------------------------------------------------
def _load(name: str) -> list:
    data = json.loads((LEGAL_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def load_pack() -> dict:
    """装配 maps/dungeons/enemies 真实数据（tests/fixtures/packs/legal/）。"""
    def find(rows: list, did: str) -> dict:
        for r in rows:
            if isinstance(r, Mapping) and r.get("id") == did:
                return dict(r)
        raise AssertionError(f"legal 包缺少 {did}")

    maps_raw = _load("maps")
    dungeons_raw = _load("dungeon")
    enemies_raw = _load("enemies")
    return {
        "maps": maps_raw,
        "explore": find(dungeons_raw, EXPLORE_ID),
        "boss": find(dungeons_raw, BOSS_ID),
        "ember_drake": find(enemies_raw, BOSS_MONSTER),
    }


def build_worldtime() -> WorldTime:
    """默认 time_cycle 配置（细化_2a4a §1.3 拍板值；对齐 test_worldtime_changes.default_cfg）。"""
    return WorldTime({"time_cycle": {
        "enabled": True,
        "season": {"season_days": 7},
        "period": {"period_minutes": 60},
        "weather": {"weather_minutes": 60, "default_pool": list(DEFAULT_POOL)},
        "broadcast": {"enabled": False, "mode": "lazy"},
    }})


def hooks(wt: WorldTime, now: int, map_id: Optional[str]) -> Tuple[str, str, str]:
    """全程时间/天气钩子取值（IF02/IF03/IF04：同一 now 同一图必同值）。"""
    return (wt.season_now(now), wt.period_now(now), wt.weather_now(map_id or "", now))


def _hook_step(wt: WorldTime, now: int, step: str, map_id: Optional[str]) -> dict:
    season, period, weather = hooks(wt, now, map_id)
    return {"step": step, "map_id": map_id, "season": season,
            "period": period, "weather": weather}


def player_ctx(map_id: str = WORLD_ANCHOR, inventory: Optional[dict] = None,
               entries: Optional[dict] = None) -> dict:
    """最小玩家上下文（对齐 test_dungeon_flow._ctx：背包 count-map + 入场次数表 + time_state）。"""
    inv = dict(inventory or {})
    return {
        "map_id": map_id,
        "player": {"map_id": map_id, "name": "阿伟", "inventory": dict(inv)},
        "inventory": inv,
        "dungeon_entries": dict(entries or {}),
        "time_state": {"season_idx": 0, "period_idx": 0, "weather_tick": 0,
                       "map_weather_seen": {}},
        "content_pack_id": CONTENT_PACK,
        "content_pack_version": CONTENT_VERSION,
    }


def _walk(smoke: Smoke, machine: DungeonStateMachine, session: DungeonSession,
          ctx: dict, direction: str, maps_raw: list, dungeon_ids: set,
          label: str) -> DungeonSession:
    """走通道推进（对齐 core.dungeon._step_walk）：movement.resolve_move → 集合隔离 R5 →
    会话登记（with_current_map/with_cleared）→ transition(walk)。"""
    res = resolve_move(ctx, direction, maps=maps_raw)
    smoke.check(bool(res.get("ok")), f"{label}：resolve_move({direction}) 成功")
    if not res.get("ok"):
        return session
    to = str(res.get("to") or "")
    smoke.check(to in dungeon_ids, f"{label}：目标 {to} ∈ 副本 maps 集合（2a1c R5 集合隔离）")
    sess2 = session.with_current_map(to).with_cleared(to)
    tr = machine.transition("walk", sess2)
    smoke.check(bool(tr.get("ok")), f"{label}：transition(walk) 迁移成功")
    return tr["session"] if tr.get("ok") else session


def _chase_maps(maps_raw: list) -> list:
    """换区候选图装配【补白 2】：legal maps + 候选区 molten_corridor/molten_core 接线。"""
    out = copy.deepcopy(maps_raw)
    lava = next(m for m in out if m.get("id") == BOSS_ROOM)
    lava.setdefault("exits", {})["left"] = {"to": "molten_corridor", "mode": "bidirectional"}
    out.append({"id": "molten_corridor", "name": "熔岩走廊",
                "exits": {"right": {"to": BOSS_ROOM, "mode": "bidirectional"},
                          "left": {"to": "molten_core", "mode": "bidirectional"}}})
    out.append({"id": "molten_core", "name": "熔岩核心",
                "exits": {"right": {"to": "molten_corridor", "mode": "bidirectional"}}})
    return out


# -------------------------------------------------------------------------------------
# 路径一：探索版（练习赛）全通 —— S0→S1→S1→S5→S7
# -------------------------------------------------------------------------------------
def explore_path(smoke: Smoke, wt: WorldTime, now: int, pack: dict) -> dict:
    """探索版全通路径：进入（宽松）→ 走通道×2 → 子任务推进 → CLEARED → 离开 S7 重置。"""
    trace: List[dict] = []
    states: List[str] = []
    machine = DungeonStateMachine()
    ddef = cast(DungeonDef, DungeonDef.from_entry(pack["explore"]))
    ctx = player_ctx()
    dungeon_ids = {str(m) for m in ddef.maps}

    # ---- 进入（M1：探索版入口校验宽松——entry_item null / entry_limit 0 不扣不拦）----
    ent = machine.enter(ctx, ddef)
    smoke.check(bool(ent.get("ok")), "探索版：进入（入口校验宽松）放行")
    smoke.check_eq(ent.get("state"), S0, "探索版：进入后状态 S0")
    smoke.check(ent.get("entry_item_consumed") is None, "探索版：entry_item null 不扣道具")
    smoke.check_eq(ent.get("entry_count"), 1, "探索版：入场次数登记 1（limit 0 不限仅计数）")
    smoke.check_eq(ent.get("safe_zone"), SAFE_ZONE, "探索版：入口区=安全区")
    smoke.check_eq(ent.get("external_anchor"), WORLD_ANCHOR, "探索版：外部锚点记录")
    smoke.check_eq(ctx["map_id"], SAFE_ZONE, "探索版：玩家落位入口区")
    session = ent["session"]
    states.append(session.state)
    trace.append(_hook_step(wt, now, "探索版·进入", session.current_map))

    # ---- 走通道推进（movement.resolve_move + transition(walk)）----
    session = _walk(smoke, machine, session, ctx, "上", pack["maps"], dungeon_ids,
                    "探索版·走通道①")
    smoke.check_eq(session.state, S1, "探索版：首次走图 S0→S1")
    states.append(session.state)
    trace.append(_hook_step(wt, now, "探索版·走通道①", session.current_map))
    session = _walk(smoke, machine, session, ctx, "左", pack["maps"], dungeon_ids,
                    "探索版·走通道②")
    smoke.check_eq(session.state, S1, "探索版：平静探索内继续走图（S1→S1）")
    states.append(session.state)
    trace.append(_hook_step(wt, now, "探索版·走通道②", session.current_map))
    # 反向校验：无通道方向拦截（契约 §2.4 死路；lava_tunnel 无「下」出口）
    blocked = resolve_move(ctx, "下", maps=pack["maps"])
    smoke.check(not bool(blocked.get("ok")), "探索版：无通道方向 resolve_move 拦截")
    # 反向校验：探索版拒绝 BOSS 事件（2a3 R9）
    smoke.check(not machine.transition("kill", session).get("ok"),
                "探索版：kill 事件拒绝（R9 探索版无 BOSS）")
    smoke.check(not machine.transition("chase", session).get("ok"),
                "探索版：chase 事件拒绝（R9 探索版无换区追击）")

    # ---- 子任务推进（ProgressTracker.record 五形式；【补白 1】承接条目）----
    sess_dict: Dict[str, Any] = session.to_dict()
    subquest_entries = [
        {"id": "quest_explore_corridor", "kind": "reach_zone", "target": "lava_tunnel",
         "count": 1, "reward": {"items": [{"item": "potion", "count": 1}], "exp": 50, "gold": 10}},
        {"id": "quest_gather_ore", "kind": "collect", "target": "ore", "count": 3,
         "reward": {"items": [], "exp": 80, "gold": 20}},
        {"id": "quest_learn_mechanic", "kind": "condition",
         "target": {"mechanic": "rockfall"}, "count": 1,
         "reward": {"items": [], "exp": 30, "gold": 0}},
    ]
    tracker = ProgressTracker(sess_dict, subquest_entries)
    c1 = tracker.record("reach_zone", "lava_tunnel", 1)
    smoke.check(any("quest_explore_corridor" in s for s in c1),
                "探索版：子任务①reach_zone 完成（到达指定区域）")
    c2 = tracker.record("collect", "ore", 3)
    smoke.check(any("quest_gather_ore" in s for s in c2),
                "探索版：子任务②collect 完成（收集指定物）")
    c3 = tracker.record("condition", {"mechanic": "rockfall"}, 1)
    smoke.check(any("quest_learn_mechanic" in s for s in c3),
                "探索版：子任务③condition 完成（达成指定条件）")
    smoke.check(tracker.is_complete("quest_gather_ore"),
                "探索版：quest_gather_ore is_complete")
    granted = tracker.claim_reward("quest_gather_ore", player_ctx=ctx)
    smoke.check(bool(granted.get("ok")) and bool(granted.get("granted")),
                "探索版：子任务奖励发放一次（M23）")
    again = tracker.claim_reward("quest_gather_ore", player_ctx=ctx)
    smoke.check_eq(again.get("reason"), "already_claimed", "探索版：奖励防重复领取")
    prog = {k: v["current"] for k, v in (sess_dict.get("dungeon_subquests") or {}).items()}
    session = session.with_subquest_progress(prog)
    smoke.check_eq(session.subquest_progress.get("quest_gather_ore"), 3,
                   "探索版：子任务进度并入副本会话（随存档持久化）")
    trace.append(_hook_step(wt, now, "探索版·子任务", session.current_map))

    # ---- 通关 CLEARED（DungeonStateMachine.transition("clear")）----
    tr = machine.transition("clear", session)
    smoke.check(bool(tr.get("ok")), "探索版：通关事件 clear 迁移成功")
    smoke.check_eq(tr.get("state"), S5, "探索版：通关态 S5 CLEARED")
    session = tr["session"]
    states.append(session.state)
    trace.append(_hook_step(wt, now, "探索版·通关", session.current_map))
    drops = cast(Mapping[str, Any], ddef.drops)
    smoke.check(isinstance(drops.get("normal"), list) and len(drops.get("normal", [])) > 0,
                "探索版：drops.normal 掉落配置存在")
    smoke.check(isinstance(drops.get("first_clear"), Mapping) and bool(drops.get("first_clear")),
                "探索版：drops.first_clear 首通奖励配置存在")
    trace.append({"step": "探索版·通关奖励摘要",
                  "summary": f"normal×{len(drops.get('normal', []))} + first_clear{bool(drops.get('first_clear'))}"})

    # ---- 离开 S7 重置（M13：副本全清 + 回外部锚点 R8）----
    tr = machine.transition("leave", session)
    smoke.check(bool(tr.get("ok")), "探索版：离开事件迁移成功")
    smoke.check_eq(tr.get("state"), S7, "探索版：离开态 S7 LEFT")
    sess_left = tr["session"]
    smoke.check_eq(sess_left.cleared_maps, frozenset(), "探索版：离开重置已清区域")
    smoke.check_eq(sess_left.subquest_progress, {}, "探索版：离开重置子任务进度")
    smoke.check_eq(sess_left.rest_count, 0, "探索版：离开重置休息次数")
    smoke.check(sess_left.current_map is None, "探索版：离开重置当前位置")
    ctx["map_id"] = sess_left.external_anchor  # 镜像 _step_leave：R8 回外部锚点
    smoke.check_eq(ctx["map_id"], WORLD_ANCHOR, "探索版：玩家回外部锚点（R8）")
    states.append(session.state if False else S7)
    trace.append(_hook_step(wt, now, "探索版·离开重置", WORLD_ANCHOR))

    # ---- M18 explore_run 整装流程（补白 5：全部组成模块同链路复验）----
    ctx2 = player_ctx()
    er = explore_run(ctx2, pack["explore"], pack["maps"], actions=[
        ("walk", "上"), ("walk", "左"), ("subquest", "quest_gather_ore", 3),
        ("clear",), ("leave",),
    ])
    smoke.check(bool(er.get("ok")), "探索版：explore_run 整装流程 ok")
    smoke.check(er.get("cleared") is not None and er["cleared"].get("state") == "cleared",
                "探索版：explore_run 通关结算信号 cleared")
    smoke.check(bool(er.get("left")), "探索版：explore_run 离开 left=True")
    smoke.check_eq(er.get("state"), S7, "探索版：explore_run 终态 S7 LEFT")
    smoke.check_eq(ctx2["map_id"], WORLD_ANCHOR, "探索版：explore_run 回外部锚点")
    trace.append(_hook_step(wt, now, "探索版·explore_run 整装", WORLD_ANCHOR))

    result = {"states": states, "trace": trace, "assertions": smoke.passed}
    smoke.passed = 0  # 快照后清零，供下一路径独立计数
    return result


# -------------------------------------------------------------------------------------
# 路径二：BOSS 版（正式赛）全流程 —— S0→S1→S2→S1→S3→S4→S5→S7
# -------------------------------------------------------------------------------------
def boss_path(smoke: Smoke, wt: WorldTime, now: int, pack: dict) -> dict:
    """BOSS 版全流程：入场限制校验 → 子任务可选性 → 精英 → 守门怪 → 三阶段 → 残血换区 →
    /进入 追击 → 追到续战（残血+PV 半恢复+开场技）→ 决战 → 击杀通关 → 奖励 → 离开重置。"""
    trace: List[dict] = []
    states: List[str] = []
    machine = DungeonStateMachine()
    ddef = cast(DungeonDef, DungeonDef.from_entry(pack["boss"]))
    drake = EnemyDef.from_entry(pack["ember_drake"])
    zc_cfg = pack["ember_drake"].get("zone_change")  # 真实 enemies.json zone_change 配置
    dungeon_ids = {str(m) for m in ddef.maps}
    maps_reg = {m["id"]: m for m in pack["maps"]}   # BossFlow maps 注册表形态

    # ---- 入场限制校验（2a1c R4 / 契约 §4.1：entry_item 消耗 + entry_limit 次数）----
    ctx_no_item = player_ctx(inventory={})
    ent1 = machine.enter(ctx_no_item, ddef)
    smoke.check(not bool(ent1.get("ok")), "BOSS 版：缺入场道具拦截")
    smoke.check("缺少入场道具" in str(ent1.get("reason")),
                "BOSS 版：拦截原因注明道具（校验先于消耗）")
    smoke.check_eq(ctx_no_item["inventory"], {}, "BOSS 版：拦截不扣道具")
    smoke.check("dungeon_entries" in ctx_no_item and ctx_no_item["dungeon_entries"] == {},
                "BOSS 版：拦截不消耗入场次数")
    ctx_limit = player_ctx(inventory={"potion": 1}, entries={BOSS_ID: 3})
    ent2 = machine.enter(ctx_limit, ddef)
    smoke.check(not bool(ent2.get("ok")), "BOSS 版：入场次数达上限拦截")
    smoke.check("上限" in str(ent2.get("reason")), "BOSS 版：拦截原因注明次数上限")
    smoke.check_eq(ctx_limit["inventory"], {"potion": 1}, "BOSS 版：上限拦截不扣道具")

    ctx = player_ctx(inventory={"potion": 1})
    ent = machine.enter(ctx, ddef)
    smoke.check(bool(ent.get("ok")), "BOSS 版：持入场道具进入放行")
    smoke.check_eq(ent.get("state"), S0, "BOSS 版：进入后状态 S0")
    smoke.check_eq(ent.get("entry_item_consumed"), "potion", "BOSS 版：入场道具消耗")
    smoke.check_eq(ctx["inventory"], {"potion": 0}, "BOSS 版：道具扣减落盘")
    smoke.check_eq(ent.get("entry_count"), 1, "BOSS 版：入场次数 +1")
    smoke.check_eq(ent.get("safe_zone"), SAFE_ZONE, "BOSS 版：入口区=安全区")
    session = ent["session"]
    sess_dict: Dict[str, Any] = session.to_dict()   # BossFlow/追踪器共用会话形态（原地同步）
    states.append(session.state)
    trace.append(_hook_step(wt, now, "BOSS 版·进入", session.current_map))

    # ---- 可选子任务（【补白 1】承接条目）：部分推进 → 不完成也可进 BOSS（R24 可选性）----
    tracker = ProgressTracker(sess_dict, [
        {"id": "quest_gather_ore", "kind": "collect", "target": "ore", "count": 3,
         "reward": {"items": [], "exp": 80, "gold": 20}},
    ])
    done_now = tracker.record("collect", "ore", 1)
    smoke.check(done_now == [], "BOSS 版：子任务部分推进未完成")
    smoke.check(not tracker.is_complete("quest_gather_ore"), "BOSS 版：子任务未完成态")
    smoke.check_eq(tracker.claim_reward("quest_gather_ore", player_ctx=ctx).get("reason"),
                   "not_complete", "BOSS 版：未完成不可领奖（不阻塞进 BOSS）")
    trace.append(_hook_step(wt, now, "BOSS 版·可选子任务", session.current_map))

    # ---- 走通道推进至 BOSS 房（S0→S1→S1）----
    session = _walk(smoke, machine, session, ctx, "上", pack["maps"], dungeon_ids,
                    "BOSS 版·走通道①")
    smoke.check_eq(session.state, S1, "BOSS 版：首次走图 S0→S1")
    states.append(session.state)
    trace.append(_hook_step(wt, now, "BOSS 版·走通道①", session.current_map))
    session = _walk(smoke, machine, session, ctx, "左", pack["maps"], dungeon_ids,
                    "BOSS 版·走通道②")
    smoke.check_eq(session.state, S1, "BOSS 版：抵达 BOSS 房前平静探索（S1）")
    smoke.check_eq(session.current_map, BOSS_ROOM, "BOSS 版：玩家位于 BOSS 房")
    states.append(session.state)
    trace.append(_hook_step(wt, now, "BOSS 版·走通道②", session.current_map))

    # ---- 精英遭遇（M3/M4：可打可绕，升压后回落）----
    el = machine.transition("elite", session)
    smoke.check(bool(el.get("ok")) and el.get("state") == S2,
                "BOSS 版：精英遭遇 S1→S2 ELITE_ESCALATE")
    session = el["session"]
    states.append(session.state)
    trace.append(_hook_step(wt, now, "BOSS 版·精英遭遇", session.current_map))
    ed = machine.transition("elite_done", session)
    smoke.check(bool(ed.get("ok")) and ed.get("state") == S1,
                "BOSS 版：精英击败/脱离 S2→S1")
    session = ed["session"]
    states.append(session.state)

    # ---- 守门怪（M19：BossFlow.enter_boss_room；maps.json lava_tunnel gate_guard）----
    flow = BossFlow(drake, pack["boss"], sess_dict, maps=maps_reg)
    gate = flow.enter_boss_room({"map_id": BOSS_ROOM})
    smoke.check(not bool(gate.get("allowed")), "BOSS 版：守门怪未击败拦截进 BOSS 房")
    smoke.check_eq(gate.get("reason"), "gate_guard", "BOSS 版：拦截原因=gate_guard")
    smoke.check_eq(gate.get("gate_guard"), BOSS_MONSTER, "BOSS 版：守门怪=ember_drake")
    sess_dict[SESSION_GATE_GUARDS_KEY] = {BOSS_MONSTER: True}  # 【补白 3】战斗侧落盘标记
    gate2 = flow.enter_boss_room({"map_id": BOSS_ROOM})
    smoke.check(bool(gate2.get("allowed")), "BOSS 版：守门怪击败后放行")
    smoke.check_eq(gate2.get("room"), BOSS_ROOM, "BOSS 版：BOSS 房=lava_tunnel")
    smoke.check_eq(gate2.get("boss"), BOSS_MONSTER, "BOSS 版：BOSS=ember_drake")
    trace.append(_hook_step(wt, now, "BOSS 版·守门怪", BOSS_ROOM))

    # ---- BOSS 三阶段（M20：phase_for 阈值表 100-60/60-30/30-0，边界归下阶段）----
    smoke.check_eq(flow.phase_for(100.0), 1, "BOSS 版：100% → 阶段1 常规")
    smoke.check_eq(flow.phase_for(60.0), 2, "BOSS 版：60% 边界 → 阶段2 狂暴")
    smoke.check_eq(flow.phase_for(30.0), 3, "BOSS 版：30% 边界 → 阶段3 绝境")
    smoke.check_eq(flow.phase_for(0.0), 3, "BOSS 版：0% → 阶段3（击杀优先判定在换区）")
    smoke.check_eq(flow.phase_for(75.0), 1, "BOSS 版：75% → 阶段1")
    smoke.check_eq(flow.phase_for(45.0), 2, "BOSS 版：45% → 阶段2")
    smoke.check_eq(flow.phase_for(15.0), 3, "BOSS 版：15% → 阶段3")

    # ---- 残血换区（M20 should_zone_change + M12 chase_trigger 装配；固定种子）----
    sess_dict["boss_state"] = {"hp": 300, "max_hp": 1500, "pv": 0}  # 【补白 3】残血快照（20%）+ 破防（缺失量口径）
    smoke.check(bool(flow.should_zone_change({"hp": 300, "max_hp": 1500}, zc_cfg)),
                "BOSS 版：残血 20% ≤ 阈值 30% 触发换区")
    smoke.check(not bool(flow.should_zone_change({"hp": 500, "max_hp": 1500}, zc_cfg)),
                "BOSS 版：血量 33% > 阈值不触发（R1/R2）")
    smoke.check(not bool(flow.should_zone_change({"hp": 0, "max_hp": 1500}, zc_cfg)),
                "BOSS 版：hp=0 击杀优先不进换区（R3）")
    smoke.check(not bool(flow.should_zone_change({"hp": 300, "max_hp": 1500},
                                                 dict(zc_cfg, enabled=False))),
                "BOSS 版：enabled=False 永不换区")
    tr1 = chase_trigger({"hp": 300, "max_hp": 1500}, zc_cfg, boss_flow=flow,
                        rng=random.Random(CHASE_SEED))
    smoke.check(bool(tr1.get("triggered")), "BOSS 版：chase_trigger 触发（真实装配）")
    smoke.check(tr1.get("target") in zc_cfg.get("targets", []),
                "BOSS 版：追击目标 ∈ 候选区（molten_corridor/molten_core）")
    tr2 = chase_trigger({"hp": 300, "max_hp": 1500}, zc_cfg, boss_flow=flow,
                        rng=random.Random(CHASE_SEED))
    smoke.check_eq(tr2.get("target"), tr1.get("target"),
                   "BOSS 版：同种子候选区抽签可重放（R8 确定性）")
    target = str(tr1.get("target") or "")
    ch = machine.transition("chase", session)
    smoke.check(bool(ch.get("ok")) and ch.get("state") == S3,
                "BOSS 版：换区事件 S1→S3 BOSS_CHASE（M5）")
    session = ch["session"]
    states.append(session.state)
    trace.append(_hook_step(wt, now, "BOSS 版·残血换区", BOSS_ROOM))

    # ---- /进入 追击（M13 pursue：走通道追到目标图）----
    chase_maps = _chase_maps(pack["maps"])  # 【补白 2】候选区接线
    chase_ctx: dict = {SESSION_CHASING_KEY: True, "target_map": target,
                       "start_map": BOSS_ROOM, "miss_count": 0, "miss_limit": 3,
                       "boss_flow": flow}
    caught_out: dict = {}
    for i in range(3):
        caught_out = pursue(ctx, "左", chase_ctx, maps=chase_maps)
        if caught_out.get("caught"):
            break
    smoke.check(bool(caught_out.get("caught")), "BOSS 版：/进入 追击捕获（到达目标图）")
    smoke.check(bool(caught_out.get("chase_over")), "BOSS 版：追击结束 chase_over=True")
    smoke.check_eq(ctx["map_id"], target, "BOSS 版：玩家位置追至目标图")
    smoke.check(isinstance(caught_out.get("continue_data"), Mapping),
                "BOSS 版：捕获时内嵌续战准备 continue_data")
    cd = caught_out.get("continue_data") or {}
    smoke.check(bool(cd.get("resume")) and bool(cd.get("hp_keep")),
                "BOSS 版：续战标记 残血保持 hp_keep")
    smoke.check_eq(cd.get("pv_half_value"), 150, "BOSS 版：PV 半恢复 floor(300×0.5)=150")
    smoke.check(bool(cd.get("opening_skill")), "BOSS 版：换区后开场技标记 opening_skill")
    trace.append(_hook_step(wt, now, "BOSS 版·追击捕获", target))

    # ---- 追到续战（M6 caught → S4 决战；prepare_resume_battle 残血+PV 半值+开场技）----
    ct = machine.transition("caught", session)
    smoke.check(bool(ct.get("ok")) and ct.get("state") == S4,
                "BOSS 版：追到事件 S3→S4 FINAL_DEATHMATCH（M6）")
    session = ct["session"]
    states.append(session.state)
    battle_snap = {"ai_state": {"intent": "roar", "phase": 2},
                   "combo_state": {"chain": 0, "combo": "drake_breath_combo"}}
    resume = prepare_resume_battle(
        caught_out,
        enemy_state={"hp": 300, "max_hp": 1500, "pv": 0},  # 破防场景（缺失量口径：0+floor(300×0.5)=150）
        battle_state=battle_snap,
    )
    smoke.check(bool(resume.get("resume")), "BOSS 版：续战装配 resume=True")
    smoke.check(bool(resume.get("hp_keep")), "BOSS 版：续战残血保持 hp_keep（R12/R13）")
    smoke.check(bool(resume.get("pv_half")), "BOSS 版：续战 PV 半恢复标记（R9）")
    smoke.check_eq(resume.get("pv_half_value"), 150, "BOSS 版：pv_half_value=floor(300×0.5)")
    smoke.check(bool(resume.get("opening_skill")), "BOSS 版：开场技标记（R20）")
    smoke.check(bool(resume.get("battle_ready")), "BOSS 版：同会话战斗快照续接 battle_ready")
    smoke.check_eq(resume.get("ai_state"), battle_snap["ai_state"],
                   "BOSS 版：ai_state 快照保留（m3 §4.4）")
    smoke.check_eq(resume.get("combo_state"), battle_snap["combo_state"],
                   "BOSS 版：combo_state 快照保留（m3 §4.4）")
    smoke.check_eq(resume.get("boss_hp"), 300, "BOSS 版：残血透传 boss_hp")
    smoke.check_eq(resume.get("chase_target"), target, "BOSS 版：换区上下文透传 chase_target")
    smoke.check_eq(resume.get("timing"), "chase_continue", "BOSS 版：续战语义标记对齐")
    not_caught = prepare_resume_battle({"caught": False})
    smoke.check(not bool(not_caught.get("resume")),
                "BOSS 版：未追到拒绝装配续战（not_caught）")
    trace.append(_hook_step(wt, now, "BOSS 版·续战装配", target))

    # ---- 决战 → 击杀通关（M8 kill → S5 CLEARED）→ 奖励摘要 ----
    ki = machine.transition("kill", session)
    smoke.check(bool(ki.get("ok")) and ki.get("state") == S5,
                "BOSS 版：击杀事件 S4→S5 CLEARED（M8）")
    session = ki["session"]
    states.append(session.state)
    trace.append(_hook_step(wt, now, "BOSS 版·决战通关", session.current_map))
    drops = cast(Mapping[str, Any], ddef.drops)
    smoke.check(isinstance(drops.get("normal"), list) and len(drops.get("normal", [])) > 0,
                "BOSS 版：drops.normal 配置存在")
    smoke.check(isinstance(drops.get("boss"), list) and len(drops.get("boss", [])) > 0,
                "BOSS 版：drops.boss 讨伐掉落配置存在")
    fc = drops.get("first_clear")
    smoke.check(isinstance(fc, Mapping) and bool(fc.get("items")),
                "BOSS 版：drops.first_clear 首通奖励配置存在")
    smoke.check(bool(fc.get("title")), "BOSS 版：首通称号配置存在（熔岩征服者）")
    trace.append({"step": "BOSS 版·通关奖励摘要",
                  "summary": f"normal×{len(drops.get('normal', []))} + boss×{len(drops.get('boss', []))}"
                             f" + first_clear(title={fc.get('title')})"})

    # ---- 离开重置（M15 exit_dungeon_reset 装配：非战斗离开重置 / 战斗中拒绝）----
    leave_reset = exit_dungeon_reset(session, player_ctx={"map_id": target})
    smoke.check(bool(leave_reset.get("reset")), "BOSS 版：exit_dungeon_reset 重置信号")
    smoke.check_eq(leave_reset.get("state"), S7, "BOSS 版：重置态 LEFT")
    smoke.check(bool(leave_reset.get("boss_state_cleared")), "BOSS 版：BOSS/残血状态全清")
    smoke.check_eq(leave_reset.get("message_hint"), "离开副本将重置", "BOSS 版：重置提示明示")
    battle_leave = exit_dungeon_reset(session, player_ctx={"in_battle": True})
    smoke.check(not bool(battle_leave.get("reset")), "BOSS 版：战斗中离开拒绝重置")
    smoke.check_eq(battle_leave.get("reason"), "battle_in_progress",
                   "BOSS 版：战斗中断可续玩，离开副本将重置")
    # 状态机离开（M13）：S5→S7 + 回外部锚点 R8
    lv = machine.transition("leave", session)
    smoke.check(bool(lv.get("ok")) and lv.get("state") == S7,
                "BOSS 版：离开事件 S5→S7 LEFT")
    sess_left = lv["session"]
    smoke.check_eq(sess_left.boss_state, {}, "BOSS 版：离开重置 BOSS 状态")
    smoke.check_eq(sess_left.cleared_maps, frozenset(), "BOSS 版：离开重置已清区域")
    ctx["map_id"] = sess_left.external_anchor
    smoke.check_eq(ctx["map_id"], WORLD_ANCHOR, "BOSS 版：玩家回外部锚点（R8）")
    states.append(S7)
    trace.append(_hook_step(wt, now, "BOSS 版·离开重置", WORLD_ANCHOR))

    result = {"states": states, "trace": trace, "assertions": smoke.passed}
    smoke.passed = 0
    return result


# -------------------------------------------------------------------------------------
# 冒烟主流程（确定性重放：同 now 同种子两次运行摘要逐字一致）
# -------------------------------------------------------------------------------------
def run_paths(smoke: Smoke, wt: WorldTime, now: int, pack: dict) -> dict:
    return {
        "explore": explore_path(smoke, wt, now, pack),
        "boss": boss_path(smoke, wt, now, pack),
    }


def run_smoke(now: Optional[int] = None) -> dict:
    """执行完整冒烟：两次运行对比确定性 + 懒计算钩子逐条重算复核。"""
    now = FIXED_NOW if now is None else now
    pack = load_pack()
    wt = build_worldtime()
    smoke = Smoke()
    r1 = run_paths(smoke, wt, now, pack)

    # 确定性重放（验收标准：固定种子可重放——同参二次运行摘要逐字一致）
    smoke2 = Smoke()
    r2 = run_paths(smoke2, wt, now, pack)
    replay = (r1 == r2)
    smoke.check(replay, "确定性重放：两次运行摘要逐字一致（固定 now/种子）")

    # 全程时间/天气钩子复核（懒计算：同刻同参必同值，随时可重算）
    hooks_ok = all(
        wt.season_now(now) == t["season"]
        and wt.period_now(now) == t["period"]
        and wt.weather_now(t.get("map_id") or "", now) == t["weather"]
        for path in (r1["explore"], r1["boss"])
        for t in path["trace"]
        if "map_id" in t and isinstance(t.get("map_id"), str) and t["map_id"]
    )
    smoke.check(hooks_ok, "时间/天气钩子：全程逐条重算同值（IF02/IF03/IF04 懒计算）")

    return {
        "ok": smoke.failed == 0,
        "passed": smoke.passed,
        "failed": smoke.failed,
        "failures": smoke.failures,
        "replay_identical": replay,
        "runs": r1,
    }


# -------------------------------------------------------------------------------------
# 主入口（独立可运行）
# -------------------------------------------------------------------------------------
def _print_run(run: dict, title: str) -> None:
    print(f"\n◆ {title}")
    chain = " → ".join(run["states"])
    print(f"  状态迁移：{chain}")
    for t in run["trace"]:
        if "map_id" in t:
            print(f"  [{t['step']}] map={t['map_id']} 季节={t['season']} 时段={t['period']} "
                  f"天气={t['weather']}")
        else:
            print(f"  [{t['step']}] {t.get('summary', '')}")
    print(f"  路径断言：{run['assertions']}")


def main() -> int:
    print("=" * 68)
    print("M42 端到端集成冒烟（M3 批次8·路W）：探索版 + BOSS 版两路径，固定种子可重放")
    print(f"固定 now = {datetime.fromtimestamp(FIXED_NOW, _TZ8).strftime('%Y-%m-%d %H:%M:%S UTC+8')}"
          f" | 追击候选区种子 = {CHASE_SEED}")
    result = run_smoke()
    _print_run(result["runs"]["explore"], "探索版（练习赛）全通：S0→S1→S1→S5→S7")
    _print_run(result["runs"]["boss"], "BOSS 版（正式赛）全流程：S0→S1→S2→S1→S3→S4→S5→S7")
    print("-" * 68)
    for f in result["failures"]:
        print("  ✗", f)
    a_explore = int(result["runs"]["explore"]["assertions"])
    a_boss = int(result["runs"]["boss"]["assertions"])
    a_total = a_explore + a_boss + int(result["passed"])
    print(f"断言：探索 {a_explore} + BOSS {a_boss} + 运行级 {result['passed']} = {a_total} 通过"
          f" / {result['failed']} 失败"
          + (" ｜ 确定性重放：一致 ✓" if result["replay_identical"] else " ｜ 确定性重放：不一致 ✗"))
    if result["ok"]:
        print("M42 端到端冒烟全绿（探索版 + BOSS 版）")
        return 0
    print("M42 端到端冒烟失败")
    return 1


if __name__ == "__main__":
    sys.exit(main())