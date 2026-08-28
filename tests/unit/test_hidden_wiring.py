"""tests/unit/test_hidden_wiring.py — M7 BCH-07 3f 隐藏任务接线（F-09）+ hunt 对接（F-08）。

依据：
  - docs/细化/细化_3f_单机向体验.md（R-13 隐藏任务触发契约 / D-05 条件数组全与 /
    D-06 不上任务板 / R-12 隐藏 BOSS 触发契约）
  - docs/细化/细化_M7_NPC对话接线.md（RN-08 隐藏任务接缝：quest.npc conditions 全与，
    满足才主动发；不满足 → 普通对话分支零暗示）
  - docs/细化/细化_M7_交互补全总纲.md（BCH-07 批序）

覆盖：
  - 隐藏任务条件全与（RN-08 / D-05）：available_quests 发任务候选过滤处前置求值
    quest.npc.conditions——全部满足才列入可发候选；任一不满足 → 剔除（普通对话分支
    零暗示，无任务 id）；无 npc 节点/无 conditions/空数组 → 无门槛（普通任务不受影响）；
    候选 condition 与 quest.npc.conditions 双条件叠加全与。
  - hunt 对接 BOSS 战（R-12 / F-08）：hunt 信号 + ctx battle 发起能力（battle_engine
    注入 callable / 对象方法 / start_battle hook）→ 发起真实 BOSS 战（launch 返回
    started + 正确 boss_ref）；无能力/发起失败/非 hunt/无 boss_ref → None（保持信号文本）。

零 NoneBot import；纯函数确定性；最小侵入（不改既有 npc/investigate 测试断言）。
"""

from __future__ import annotations

from typing import Any, MutableMapping

from qbot_rpg.commands.investigate_commands import (
    KIND_HUNT,
    cmd_investigate,
    launch_hunt_battle,
)
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.core.npc import available_quests, dispatch_action


# ---------------------------------------------------------------------------
# 夹具：隐藏任务（quest.npc.conditions 全与）
# ---------------------------------------------------------------------------

def _hidden_quest_ctx(**over: Any) -> dict:
    """带 quest 定义（npc.conditions 图鉴+事件双条件）的 ctx。"""
    ctx: dict = {
        "quest_active": {},
        "quest_completed": [],
        "quest_daily": {},
        "quests": {
            "q_hidden": {
                "id": "q_hidden",
                "name": "雨夜之谜",
                "board": {"slot": "daily", "accept_limit": 5, "daily_limit": 10},
                "npc": {
                    "id": "npc1",
                    "conditions": [
                        {"var": "codex", "op": "ge", "value": 50},
                        {"var": "[事件:雨夜]", "op": "ge", "value": 1},
                    ],
                },
            },
        },
    }
    ctx.update(over)
    return ctx


def _met_ctx() -> dict:
    """图鉴 60 + 雨夜事件 2 次（全满足）。"""
    return _hidden_quest_ctx(codex=60, event_counts={"[事件:雨夜]": 2})


# ---------------------------------------------------------------------------
# 隐藏任务条件全与（RN-08 / 3f D-05）
# ---------------------------------------------------------------------------

def test_available_quests_npc_conditions_all_met_offered() -> None:
    """D-05：quest.npc.conditions 全部满足 → 任务列入可发候选。"""
    deliver = {"quests": [{"quest_id": "q_hidden"}]}
    avail = available_quests(deliver, _met_ctx())
    assert [q["quest_id"] for q in avail] == ["q_hidden"]


def test_available_quests_npc_conditions_codex_unmet_excluded() -> None:
    """D-05：图鉴完成度不满足（30<50）→ 剔除（零暗示）。"""
    deliver = {"quests": [{"quest_id": "q_hidden"}]}
    ctx = _hidden_quest_ctx(codex=30, event_counts={"[事件:雨夜]": 2})
    assert available_quests(deliver, ctx) == []


def test_available_quests_npc_conditions_event_unmet_excluded() -> None:
    """D-05：事件未触发 → 剔除（零暗示）。"""
    deliver = {"quests": [{"quest_id": "q_hidden"}]}
    ctx = _hidden_quest_ctx(codex=60, event_counts={})
    assert available_quests(deliver, ctx) == []


def test_available_quests_no_npc_node_no_gate() -> None:
    """RN-08 兜底：quest 定义无 npc 节点 → 无发任务门槛（普通任务不受影响）。"""
    ctx = _hidden_quest_ctx()
    del ctx["quests"]["q_hidden"]["npc"]
    deliver = {"quests": [{"quest_id": "q_hidden"}]}
    assert [q["quest_id"] for q in available_quests(deliver, ctx)] == ["q_hidden"]


def test_available_quests_npc_conditions_empty_list_offered() -> None:
    """npc.conditions 空数组 = 全与恒真（无门槛）。"""
    ctx = _hidden_quest_ctx(codex=10, event_counts={})
    ctx["quests"]["q_hidden"]["npc"]["conditions"] = []
    deliver = {"quests": [{"quest_id": "q_hidden"}]}
    assert [q["quest_id"] for q in available_quests(deliver, ctx)] == ["q_hidden"]


def test_available_quests_quest_definition_missing_no_gate() -> None:
    """quest 定义缺失（无 quests 映射）→ resolve 失败 → 无门槛（既有行为保持）。"""
    deliver = {"quests": [{"quest_id": "q_plain"}]}
    assert [q["quest_id"] for q in available_quests(deliver, {"quest_active": {}})] == [
        "q_plain",
    ]


def test_available_quests_dual_gate_candidate_and_npc_conditions() -> None:
    """候选 condition 与 quest.npc.conditions 双条件叠加，逐条全过才发。"""
    deliver = {"quests": [
        {"quest_id": "q_hidden", "condition": {"var": "level", "op": "ge", "value": 30}},
    ]}
    # 候选条件不满足（level=10）→ 剔除
    ctx = _met_ctx()
    ctx["level"] = 10
    assert available_quests(deliver, ctx) == []
    # 双条件全满足 → 发
    ctx2 = _met_ctx()
    ctx2["level"] = 40
    assert [q["quest_id"] for q in available_quests(deliver, ctx2)] == ["q_hidden"]


def test_action_quest_npc_conditions_unmet_zero_hint() -> None:
    """D-05 零暗示：quest.npc.conditions 不满足 → 不发（ok=False/no_available_quest/
    data None，普通对话分支无任务 id）。"""
    ctx = _hidden_quest_ctx(codex=30, event_counts={})
    entry = {"action": "quest", "quests": [{"quest_id": "q_hidden"}]}
    res = dispatch_action(entry, ctx, None, "npc1")
    assert res["ok"] is False
    assert res["reason"] == "no_available_quest"
    assert res.get("data") is None


def test_action_quest_npc_conditions_met_offers() -> None:
    """D-05：quest.npc.conditions 满足 → 主动发任务（data.quest_id 命中）。"""
    ctx = _met_ctx()
    entry = {"action": "quest", "quests": [{"quest_id": "q_hidden"}]}
    res = dispatch_action(entry, ctx, None, "npc1")
    assert res["ok"] is True
    assert res["data"]["quest_id"] == "q_hidden"


# ---------------------------------------------------------------------------
# hunt 对接 BOSS 战（3f R-12 / F-08）
# ---------------------------------------------------------------------------

def _hunt_result(**over: Any) -> dict:
    """兄弟路引擎 hunt 信号形态（kind=hunt + boss_ref）。"""
    r: dict = {"kind": KIND_HUNT, "text": "你察觉到了「moon_wolf」出没的迹象。",
               "boss_ref": "moon_wolf"}
    r.update(over)
    return r


def test_launch_hunt_battle_with_callable_battle_engine() -> None:
    """F-08：ctx 注入 callable battle_engine → 发起 BOSS 战（started + 正确 boss_ref）。"""
    calls: list = []

    def fake_engine(c: MutableMapping[str, Any], ref: str) -> dict:
        calls.append((c, ref))
        return {"ok": True, "battle": "BE", "message": "BOSS 战开始"}

    ctx: MutableMapping[str, Any] = {"battle_engine": fake_engine}
    launch = launch_hunt_battle(ctx, _hunt_result())
    assert launch is not None and launch["started"] is True
    assert launch["boss_ref"] == "moon_wolf"
    assert launch["battle"] == "BE"
    assert calls == [(ctx, "moon_wolf")]


def test_launch_hunt_battle_with_engine_object_method() -> None:
    """F-08：battle_engine 对象带 start_battle 方法 → 发起。"""
    calls: list = []

    class FakeEngine:
        def start_battle(self, c: MutableMapping[str, Any], ref: str) -> dict:
            calls.append((c, ref))
            return {"ok": True, "message": "开战"}

    ctx: MutableMapping[str, Any] = {"battle_engine": FakeEngine()}
    launch = launch_hunt_battle(ctx, _hunt_result())
    assert launch is not None and launch["started"] is True
    assert launch["boss_ref"] == "moon_wolf"
    assert calls == [(ctx, "moon_wolf")]


def test_launch_hunt_battle_start_battle_hook_priority() -> None:
    """start_battle hook 优先于 battle_engine（装配层注入形态）。"""
    calls: list = []
    ctx: MutableMapping[str, Any] = {
        "start_battle": lambda c, ref: (calls.append((c, ref)) or {"ok": True}),  # type: ignore[func-returns-value]
        "battle_engine": lambda c, ref: {"ok": False},  # 不应被调用
    }
    launch = launch_hunt_battle(ctx, _hunt_result())
    assert launch is not None and launch["started"] is True
    assert calls == [(ctx, "moon_wolf")]


def test_launch_hunt_battle_no_capability_returns_none() -> None:
    """无 battle 发起能力 → None（保持信号文本，最小侵入）。"""
    assert launch_hunt_battle({}, _hunt_result()) is None
    assert launch_hunt_battle({"battle_engine": None}, _hunt_result()) is None


def test_launch_hunt_battle_non_hunt_returns_none() -> None:
    """非 hunt（彩蛋等）→ 不发起 BOSS 战。"""
    ctx: MutableMapping[str, Any] = {
        "battle_engine": lambda c, ref: {"ok": True, "message": "战"},
    }
    assert launch_hunt_battle(ctx, {"kind": "egg", "text": "彩蛋"}) is None


def test_launch_hunt_battle_no_boss_ref_returns_none() -> None:
    """hunt 但无 boss_ref（引擎未给）→ 无发起目标 → None。"""
    ctx: MutableMapping[str, Any] = {
        "battle_engine": lambda c, ref: {"ok": True, "message": "战"},
    }
    assert launch_hunt_battle(ctx, {"kind": KIND_HUNT, "text": "x"}) is None


def test_launch_hunt_battle_failure_returns_none() -> None:
    """发起返回 ok=False → 视为失败 → None（回退信号文本）。"""
    ctx: MutableMapping[str, Any] = {
        "battle_engine": lambda c, ref: {"ok": False, "message": "不能开战"},
    }
    assert launch_hunt_battle(ctx, _hunt_result()) is None


def test_launch_hunt_battle_launcher_exception_returns_none() -> None:
    """发起抛异常 → None（fail-safe，不崩）。"""
    ctx: MutableMapping[str, Any] = {
        "battle_engine": lambda c, ref: (_ for _ in ()).throw(RuntimeError("boom")),
    }
    assert launch_hunt_battle(ctx, _hunt_result()) is None


# ---------------------------------------------------------------------------
# /调查 全链路：hunt 信号接真实 BOSS 战（F-08）
# ---------------------------------------------------------------------------

def _hunt_ctx(**over: Any) -> MutableMapping[str, Any]:
    """可蹲点（秋 + window 命中 moon_wolf）的 /调查 ctx。"""
    fog: dict = {
        "id": "fog_marsh", "name": "雾沼",
        "monsters": [
            {"enemy": "moon_wolf", "name": "蚀月之狼",
             "window": {"var": "season", "param": "秋"}},
        ],
    }
    ctx: MutableMapping[str, Any] = {
        "map_def": fog,
        "season": "秋",
        "persistent_state": {"investigate_quota": {}, "investigate_revealed": []},
        "event_counts": {}, "longline_counters": {},
        "maps": [fog],
        "monsters": {"moon_wolf": {"name": "蚀月之狼"}},
    }
    ctx.update(over)
    return ctx


def test_cmd_investigate_hunt_with_battle_engine_launches() -> None:
    """/调查 蹲点命中 + battle_engine 注入 → 发起 BOSS 战（回复含发起消息 + 记录 boss_ref）。"""
    calls: list = []
    ctx = _hunt_ctx(battle_engine=lambda c, ref: (
        calls.append((c, ref)) or {"ok": True, "message": "蚀月之狼已现身，战斗开始！"}))  # type: ignore[func-returns-value]
    reply = cmd_investigate(parse_command("/调查"), ctx)
    assert "蚀月之狼已现身，战斗开始！" in reply
    assert calls == [(ctx, "moon_wolf")]


def test_cmd_investigate_hunt_without_battle_engine_signal_text() -> None:
    """/调查 蹲点命中但无 battle 能力 → 保持既有信号文本（不发起）。"""
    ctx = _hunt_ctx()
    reply = cmd_investigate(parse_command("/调查"), ctx)
    assert "【发现】" in reply  # 蹲点仪式感保留（演出 + 卡片 + 信号）
    assert "战斗即将开始" in reply
    assert "蚀月之狼已现身" not in reply  # 无发起消息