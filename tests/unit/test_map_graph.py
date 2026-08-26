"""M3 批次3·路J：M02 双向通道判定 + M03 单向拦截 + M04 捷径/追击路径计算测试。

依据：
  - 细化_2a1a_地图schema字段.md §2（exits 6 字段：direction/target/mode/shortcut/hidden/lore）
  - 细化_2a1b_通道规则与刷怪.md §一（R2 未配置方向=死路 / R3 双向 / R4 单向反方向拒绝 /
    R5 捷径=单向边+绕回边布线 / R6-R7 隐藏条件打开 / R10 熟悉直追不熟绕路）
  - m3_shared_contract §2.4（can_move / bidirectional_consistent / path_exists 签名与语义；
    MoveResult={ok,to,mode,hidden_ok,blocked_reason?}；双向不对称黄提示 ④）

测试目标：qbot_rpg.content.map_graph（纯逻辑零 NoneBot；数据 = legal/maps.json 深拷贝 +
内联构造的单向门/捷径回环用例，对齐 test_maps_schema 的 _base_maps 风格）。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from qbot_rpg.content.map_graph import (
    BLOCKED_NO_CHANNEL,
    BLOCKED_NO_PASSAGE,
    RULE_BIDIRECTIONAL_ASYMMETRY,
    bidirectional_consistent,
    can_move,
    path_exists,
)

LEGAL_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs" / "legal"


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _legal_maps() -> list:
    """legal/maps.json 深拷贝（3 图：rubble_field/crag_den/lava_tunnel，含双向/单向/隐藏）。"""
    data = json.loads((LEGAL_DIR / "maps.json").read_text(encoding="utf-8"))
    assert isinstance(data, list) and len(data) == 3
    return copy.deepcopy(data)


def _ctx(maps: list, conditions=None) -> dict:
    """标准 ctx：{maps, conditions?}；conditions 未注入 = 隐藏条件不满足。"""
    ctx: dict = {"maps": maps}
    if conditions is not None:
        ctx["conditions"] = conditions
    return ctx


def _always(flag: bool):
    """测试用条件求值器：任何表达式 → 固定布尔。"""
    return lambda cond: flag


def _one_side_gate() -> list:
    """单向门只声明源端（2a1b R4 / TC-02 反向拒绝）：A.down→B one_way，B 无回 A 的边。"""
    return [
        {"id": "A", "name": "入口", "exits": {"down": {"to": "B", "mode": "one_way"}}},
        {"id": "B", "name": "坑道", "exits": {"right": {"to": "C", "mode": "bidirectional"}}},
        {"id": "C", "name": "矿洞", "exits": {"left": {"to": "B", "mode": "bidirectional"}}},
    ]


def _shortcut_loop() -> list:
    """捷径回环四图（2a1b R5 布线样例）：A→B 单向门 + B→C→A 绕回；D 孤立无通道。"""
    return [
        {"id": "A", "name": "入口区", "exits": {"right": {"to": "B", "mode": "one_way"}}},
        {"id": "B", "name": "坑道", "exits": {"left": {"to": "C", "mode": "bidirectional"}}},
        {"id": "C", "name": "矿洞", "exits": {"left": {"to": "A", "mode": "bidirectional"}}},
        {"id": "D", "name": "孤岛", "exits": {}},
    ]


def _hidden_only() -> list:
    """仅隐藏通道连通 X→Y（R6/R7）：条件满足才有路。"""
    return [
        {"id": "X", "name": "外厅", "exits": {
            "right": {"to": "Y", "mode": "hidden",
                      "condition": {"var": "subquest_done", "op": "eq", "param": "learn_mechanic"}}}},
        {"id": "Y", "name": "密室", "exits": {}},
    ]


# ---------------------------------------------------------------------------
# M02 can_move：双向通道（R3）
# ---------------------------------------------------------------------------
def test_can_move_bidirectional_forward() -> None:
    """双向通道直接可走：ok=True + 目标图 id + mode=bidirectional + 无拦截原因（R3 / TC-01）。"""
    maps = _legal_maps()
    r = can_move("rubble_field", "up", _ctx(maps))
    assert r["ok"] is True
    assert r["to"] == "crag_den"
    assert r["mode"] == "bidirectional"
    assert r["hidden_ok"] is False
    assert r["blocked_reason"] is None


def test_can_move_bidirectional_return_trip() -> None:
    """双向往返：crag_den.down→rubble_field、crag_den.left→lava_tunnel、lava_tunnel.right→crag_den。"""
    maps = _legal_maps()
    r1 = can_move("crag_den", "down", _ctx(maps))
    assert r1["ok"] is True and r1["to"] == "rubble_field" and r1["mode"] == "bidirectional"
    r2 = can_move("crag_den", "left", _ctx(maps))
    assert r2["ok"] is True and r2["to"] == "lava_tunnel"
    r3 = can_move("lava_tunnel", "right", _ctx(maps))
    assert r3["ok"] is True and r3["to"] == "crag_den" and r3["blocked_reason"] is None


def test_can_move_to_name_for_prompt() -> None:
    """to_name = 目标图 maps.name（供 /进入 提示，工程补白 2）。"""
    maps = _legal_maps()
    r = can_move("rubble_field", "up", _ctx(maps))
    assert r["to_name"] == "石甲蜥巢穴"
    r2 = can_move("rubble_field", "down", _ctx(maps))
    assert r2["to_name"] == "熔岩坑道"


def test_can_move_lore_returned() -> None:
    """通道 lore（细化_2a1a §2.6）透传供指令层途经文本；无 lore 为 None。"""
    maps = [
        {"id": "M1", "exits": {"up": {"to": "M2", "mode": "bidirectional",
                                      "lore": "顺着灼热气流向上，通往熔岩坑道（捷径，单向）。"}}},
        {"id": "M2", "exits": {"down": {"to": "M1", "mode": "bidirectional"}}},
    ]
    r = can_move("M1", "up", _ctx(maps))
    assert r["ok"] is True and r["lore"] == "顺着灼热气流向上，通往熔岩坑道（捷径，单向）。"
    r2 = can_move("M2", "down", _ctx(maps))
    assert r2["ok"] is True and r2["lore"] is None


# ---------------------------------------------------------------------------
# M03 can_move：单向通道（R4 前向可走 / 反方向拦截）
# ---------------------------------------------------------------------------
def test_can_move_one_way_forward_allowed() -> None:
    """单向门前向通行：rubble_field.down→lava_tunnel、lava_tunnel.up→rubble_field（均声明端可走）。"""
    maps = _legal_maps()
    r1 = can_move("rubble_field", "down", _ctx(maps))
    assert r1["ok"] is True and r1["to"] == "lava_tunnel" and r1["mode"] == "one_way"
    r2 = can_move("lava_tunnel", "up", _ctx(maps))
    assert r2["ok"] is True and r2["to"] == "rubble_field" and r2["mode"] == "one_way"


def test_can_move_one_way_reverse_blocked() -> None:
    """单向反方向（目标图回本图无该方向/无对应边）：ok=False 拦截"此路不通"（R4 / TC-02）。"""
    maps = _one_side_gate()  # A.down→B 单向；B 无回 A 的边
    r = can_move("B", "up", _ctx(maps))  # 玩家位于单向门目标端，试图反向回 A
    assert r["ok"] is False
    assert r["to"] is None
    assert r["blocked_reason"] == BLOCKED_NO_PASSAGE
    r2 = can_move("B", "down", _ctx(maps))
    assert r2["ok"] is False and r2["blocked_reason"] == BLOCKED_NO_PASSAGE
    # 同图中 B→C 双向仍可走（拦截只针对无回边方向）
    r3 = can_move("B", "right", _ctx(maps))
    assert r3["ok"] is True and r3["to"] == "C"


# ---------------------------------------------------------------------------
# M02 can_move：隐藏通道（R6/R7 条件打开）
# ---------------------------------------------------------------------------
def test_can_move_hidden_condition_satisfied() -> None:
    """隐藏通道条件满足 → ok=True + hidden_ok=True + 目标图（TC-06）。"""
    maps = _legal_maps()
    r = can_move("rubble_field", "right", _ctx(maps, conditions=_always(True)))
    assert r["ok"] is True
    assert r["to"] == "lava_tunnel"
    assert r["mode"] == "hidden"
    assert r["hidden_ok"] is True
    assert r["blocked_reason"] is None


def test_can_move_hidden_condition_not_satisfied() -> None:
    """隐藏通道条件不满足 → ok=False + blocked_reason="此处无通道"（R7 / TC-05 双层拒绝）。"""
    maps = _legal_maps()
    r = can_move("rubble_field", "right", _ctx(maps, conditions=_always(False)))
    assert r["ok"] is False
    assert r["to"] == "lava_tunnel"  # 通道存在但锁定，mode 仍透出 hidden
    assert r["mode"] == "hidden"
    assert r["hidden_ok"] is False
    assert r["blocked_reason"] == BLOCKED_NO_CHANNEL


def test_can_move_hidden_no_conditions_injected() -> None:
    """ctx 未注入 conditions（未注入=条件不满足）→ "此处无通道"（工程补白 3）。"""
    maps = _legal_maps()
    r = can_move("rubble_field", "right", _ctx(maps))
    assert r["ok"] is False and r["blocked_reason"] == BLOCKED_NO_CHANNEL and r["hidden_ok"] is False


def test_can_move_hidden_evaluator_raises() -> None:
    """求值器抛异常 → 防御性视为不满足（工程补白 3）。"""

    def _boom(cond) -> bool:
        raise RuntimeError("条件引擎不可用")

    maps = _legal_maps()
    r = can_move("rubble_field", "right", _ctx(maps, conditions=_boom))
    assert r["ok"] is False and r["blocked_reason"] == BLOCKED_NO_CHANNEL


# ---------------------------------------------------------------------------
# M02 can_move：方向缺失 = 死路（R2）
# ---------------------------------------------------------------------------
def test_can_move_dead_end_direction_missing() -> None:
    """/进入 未配置方向 → "此路不通"（R2 / TC-03）：left 未配、lava_tunnel.down 未配。"""
    maps = _legal_maps()
    r1 = can_move("rubble_field", "left", _ctx(maps))
    assert r1["ok"] is False and r1["blocked_reason"] == BLOCKED_NO_PASSAGE and r1["to"] is None
    r2 = can_move("lava_tunnel", "down", _ctx(maps))
    assert r2["ok"] is False and r2["blocked_reason"] == BLOCKED_NO_PASSAGE
    r3 = can_move("crag_den", "up", _ctx(maps))
    assert r3["ok"] is False and r3["blocked_reason"] == BLOCKED_NO_PASSAGE


def test_can_move_unknown_map_or_direction() -> None:
    """防御性：未知地图 / 非法方向 → ok=False"此路不通"。"""
    maps = _legal_maps()
    r1 = can_move("no_such_map", "up", _ctx(maps))
    assert r1["ok"] is False and r1["blocked_reason"] == BLOCKED_NO_PASSAGE
    r2 = can_move("rubble_field", "north", _ctx(maps))
    assert r2["ok"] is False and r2["blocked_reason"] == BLOCKED_NO_PASSAGE
    r3 = can_move("rubble_field", "up", _ctx([]))  # maps 未注入/空
    assert r3["ok"] is False and r3["blocked_reason"] == BLOCKED_NO_PASSAGE


# ---------------------------------------------------------------------------
# M02 bidirectional_consistent：双向不对称黄提示（契约 §2.2 ④）
# ---------------------------------------------------------------------------
def test_bidirectional_consistent_symmetric_legal() -> None:
    """对称双向（双向↔双向）→ 零黄提示；legal 全包零黄（对齐 test_maps_schema 零黄基线）。"""
    assert bidirectional_consistent(_legal_maps()) == []


def test_bidirectional_consistent_symmetric_inline() -> None:
    """内联对称双向（A↔B 两侧 bidirectional）→ 零黄提示。"""
    maps = [
        {"id": "A", "exits": {"up": {"to": "B", "mode": "bidirectional"}}},
        {"id": "B", "exits": {"down": {"to": "A", "mode": "bidirectional"}}},
    ]
    assert bidirectional_consistent(maps) == []


def test_bidirectional_consistent_back_missing() -> None:
    """A→B 双向而 B 无回边 → 黄提示 back_missing=True。"""
    maps = [
        {"id": "A", "exits": {"up": {"to": "B", "mode": "bidirectional"}}},
        {"id": "B", "exits": {}},
    ]
    warns = bidirectional_consistent(maps)
    assert len(warns) == 1
    w = warns[0]
    assert w["rule"] == RULE_BIDIRECTIONAL_ASYMMETRY
    assert w["map_id"] == "A" and w["direction"] == "up" and w["to"] == "B"
    assert w["back_missing"] is True


def test_bidirectional_consistent_back_one_way() -> None:
    """A→B 双向而 B→A 单向 → 黄提示 back_missing=False + back_mode="one_way"（契约 §2.2 ④ 原文）。"""
    maps = [
        {"id": "A", "exits": {"up": {"to": "B", "mode": "bidirectional"}}},
        {"id": "B", "exits": {"down": {"to": "A", "mode": "one_way"}}},
    ]
    warns = bidirectional_consistent(maps)
    assert len(warns) == 1
    w = warns[0]
    assert w["back_missing"] is False
    assert w["back_direction"] == "down" and w["back_mode"] == "one_way"


def test_bidirectional_consistent_back_hidden_warns() -> None:
    """A→B 双向而 B→A 为隐藏（非双向）→ 黄提示（隐藏不可随时通行，不算对称）。"""
    maps = [
        {"id": "A", "exits": {"up": {"to": "B", "mode": "bidirectional"}}},
        {"id": "B", "exits": {"down": {"to": "A", "mode": "hidden",
                                       "condition": {"var": "season", "op": "eq", "param": "summer"}}}},
    ]
    warns = bidirectional_consistent(maps)
    assert len(warns) == 1 and warns[0]["back_mode"] == "hidden"


def test_bidirectional_consistent_ignores_non_bidirectional_src() -> None:
    """源端非双向（one_way）不触发检查；双向边全对称的捷径布线（单向门+绕回）零误报。"""
    maps = [
        {"id": "A", "exits": {"right": {"to": "B", "mode": "one_way"},   # 单向门（R5 布线）
                              "up": {"to": "C", "mode": "bidirectional"}}},
        {"id": "B", "exits": {"left": {"to": "C", "mode": "bidirectional"}}},
        {"id": "C", "exits": {"left": {"to": "A", "mode": "bidirectional"},
                              "right": {"to": "B", "mode": "bidirectional"}}},
    ]
    # 双向边：A↔C（up/left）、B↔C（left/right）全对称 → 零黄提示；A→B 单向不触发检查
    assert bidirectional_consistent(maps) == []


def test_bidirectional_consistent_dangling_to_skipped() -> None:
    """to 悬空（目标不在 maps，validate_maps R-4 已红拦）→ 跳过不重复噪音。"""
    maps = [
        {"id": "A", "exits": {"up": {"to": "ghost_map", "mode": "bidirectional"}}},
    ]
    assert bidirectional_consistent(maps) == []


# ---------------------------------------------------------------------------
# M04 path_exists：直连 / 捷径回环 / 隐藏条件 / 不可达（BFS）
# ---------------------------------------------------------------------------
def test_path_exists_direct_edges() -> None:
    """直连可达：双向直连、单向前向直连（R3/R4 前向）。"""
    maps = _legal_maps()
    assert path_exists("rubble_field", "crag_den", maps, _ctx(maps)) is True
    assert path_exists("crag_den", "rubble_field", maps, _ctx(maps)) is True
    assert path_exists("rubble_field", "lava_tunnel", maps, _ctx(maps)) is True  # 单向门直入
    assert path_exists("lava_tunnel", "rubble_field", maps, _ctx(maps)) is True  # 坑道 up 回程


def test_path_exists_shortcut_loop() -> None:
    """捷径=单向门回环场景（R5 / TC-04）：A→B 单向直达，B→A 经 C 绕回可达。"""
    maps = _shortcut_loop()
    assert path_exists("A", "B", maps, _ctx(maps)) is True  # 单向门前向
    assert path_exists("B", "A", maps, _ctx(maps)) is True  # B→C→A 绕回（闭环）
    assert path_exists("A", "C", maps, _ctx(maps)) is True  # A→B→C
    assert path_exists("C", "B", maps, _ctx(maps)) is True  # C→A→B
    assert path_exists("C", "A", maps, _ctx(maps)) is True  # 直连绕回
    assert path_exists("B", "C", maps, _ctx(maps)) is True


def test_path_exists_start_equals_goal() -> None:
    """from == to（已在原地）→ True，含无通道孤立节点。"""
    maps = _shortcut_loop()
    assert path_exists("A", "A", maps, _ctx(maps)) is True
    assert path_exists("D", "D", maps, _ctx(maps)) is True


def test_path_exists_unreachable() -> None:
    """不可达：孤立节点 D（R2 全方向死路）与主图互不可达。"""
    maps = _shortcut_loop()
    assert path_exists("A", "D", maps, _ctx(maps)) is False
    assert path_exists("D", "A", maps, _ctx(maps)) is False


def test_path_exists_hidden_condition_gates() -> None:
    """仅隐藏通道连通：条件满足→可达；不满足/未注入→不可达（R7 双层拒绝）。"""
    maps = _hidden_only()
    assert path_exists("X", "Y", maps, _ctx(maps, conditions=_always(True))) is True
    assert path_exists("X", "Y", maps, _ctx(maps, conditions=_always(False))) is False
    assert path_exists("X", "Y", maps, _ctx(maps)) is False  # 未注入 = 不满足


def test_path_exists_hidden_not_required_if_alternative() -> None:
    """隐藏通道被锁时不影响其他通道：legal 中 rubble_field→lava_tunnel 走单向门仍可达。"""
    maps = _legal_maps()
    assert path_exists("rubble_field", "lava_tunnel", maps, _ctx(maps)) is True


def test_path_exists_unknown_ids() -> None:
    """未知地图 id → False（不抛异常）。"""
    maps = _legal_maps()
    assert path_exists("no_such", "crag_den", maps, _ctx(maps)) is False
    assert path_exists("crag_den", "no_such", maps, _ctx(maps)) is False
    assert path_exists("no_such", "no_such", maps, _ctx(maps)) is False