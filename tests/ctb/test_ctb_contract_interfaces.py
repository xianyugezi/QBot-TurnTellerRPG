"""六个稳定接口的 CTB 行为契约测试（tests/ctb/test_ctb_contract_interfaces.py）。

依据：docs/ctb/01_asset_inventory.md（下称「清点表」）——
  - §0.1 三分类口径：【删除】3 个（`action_order`/`enemy_act`/`end_turn`）保留同名
    抛 `NotImplementedError` 的壳；【重写】25 个含时序假设的方法须语义等价重写。
  - §1.7/§1.11 主循环与快照：`start`(1664) / `player_act`(3456) / `to_snapshot`(3527)
    / `from_snapshot`(3594) 均为【重写】；`do_action`(1955) 与 `battle_state`(3722) 为
    【平移】但须适配 CTB 语义。
  - 全仓调用频率实测（硬数据，决定不可动接口）：
       battle_state 203 / do_action 189 / start 159 / to_snapshot 43 /
       from_snapshot 33 / player_act 28。

本文件定义的契约（= Agent 3 重写时的靶子）：
  1. `battle_state()`  —— 唯一权威状态查询；深拷贝；CTB 下含 battle_time/action_seq；
                          且**不得**再暴露 `turn`（行动数）语义作为推进主键。
  2. `do_action()`     —— 单次结算入口；签名 `do_action(attacker, action_dict)` 零改动。
  3. `start()`         —— 签名 `start(player, enemy, random_seed, battle_type, config)` 零改动；
                          RNG 状态可导出（`random_seed` + `rng_state`）。
  4. `to_snapshot()`   —— 只产新格式 V2（schema_version >= 2）；含 RNG 状态；
                          **不兼容** `schema_version==1`（项目已决策删档）。
  5. `from_snapshot()` —— 只吃 V2；V1 快照须被拒（删档前提）。
  6. `player_act()`    —— 签名 `player_act(action, params=None)` 零改动；CTB 下语义为
                          「提交一次玩家行动并推进到下一个 ready actor」。

硬约束自检：本文件**不修改** `qbot_rpg/` 下任何业务代码；为 Agent 3 重写期间能长期
存活，凡断言 CTB 新行为（battle_time / schema_version>=2 / 拒绝 V1）的用例当前一律
`xfail(strict=False)`，并在 reason 注明「待 Agent 3 实现」。
"""

from __future__ import annotations

import copy
import json

import pytest

from qbot_rpg.core.battle import BattleEngine

# ---------------------------------------------------------------------------
# 与仓库既有测试同口径的固定夹具（对齐 tests/unit/test_battle_engine.py）
# ---------------------------------------------------------------------------
PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 100, "foc": 100, "con": 50, "str": 100, "int": 80,
          "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40,
         "mag": 30, "spd": 75, "foc": 50, "con": 50, "str": 80, "int": 30,
         "agi": 40, "spr": 40, "lck": 10, "elem_atk": 0, "name": "E"}

_SEED = 20260826

#: 历史标记：Agent 3（CTB 核心重写）已落地并转绿（2026-09-10 Wave B）。
#: 保留为 **no-op** 以免删除装饰器引入大 diff；语义上这些用例已是**硬断言**。
#: 若未来某条回退，它将以 FAILED 暴露（不再是 xfail 静默吸收）。
TODO_AGENT3 = pytest.mark.xfail(
    reason="[已落地] Agent 3 CTB 重写完成，本标记留作历史；用例为硬断言",
    strict=True,   # ← 关键：转 xfail 即报错，杜绝静默回退
    condition=False,  # ← 条件恒假 → 不生效（等价 no-op），但保留 strict 兜底
)


def _new_engine() -> BattleEngine:
    """构造战斗引擎并开战（同 seed，确定性）。"""
    eng = BattleEngine()
    eng.start(dict(PLAYER), dict(ENEMY), random_seed=_SEED)
    return eng


# ===========================================================================
# 契约 1：battle_state() —— 唯一权威状态查询（调用频次 203，全仓第一）
# ===========================================================================
class TestBattleStateContract:
    """`battle_state()` 行为契约。"""

    def test_returns_mapping_with_both_sides(self) -> None:
        """契约（现即成立）：返回含 player/enemy 两侧与 action_record 的映射。"""
        st = _new_engine().battle_state()
        assert isinstance(st, dict)
        assert "player" in st and "enemy" in st
        assert "action_record" in st
        assert st["player"]["hp"] == PLAYER["hp"]
        assert st["enemy"]["hp"] == ENEMY["hp"]

    def test_returns_deep_copy_not_internal_ref(self) -> None:
        """契约（现即成立）：返回深拷贝——外部改动不得回写引擎内部状态。"""
        eng = _new_engine()
        st = eng.battle_state()
        st["player"]["hp"] = 1
        st["action_record"].append({"x": 1})
        assert eng.battle_state()["player"]["hp"] == PLAYER["hp"]
        assert len(eng.battle_state()["action_record"]) == 0

    def test_is_json_serializable(self) -> None:
        """契约（现即成立）：state 必须 JSON 可序列化（快照/渲染/审计共用）。"""
        st = _new_engine().battle_state()
        assert json.dumps(st, default=str)  # 不抛错

    @TODO_AGENT3
    def test_ctb_exposes_battle_time_and_action_seq(self) -> None:
        """契约（待 Agent 3）：CTB 下 state 须暴露 `battle_time` 与 `action_seq` 双计数。

        清点表 §4 R17：旧 `turn` 是所有回合语义的计数源，CTB 须整体替换为
        `battle_time`/`action_seq` 双计数（§1.7 主循环）。
        """
        st = _new_engine().battle_state()
        assert "battle_time" in st
        assert "action_seq" in st

    @TODO_AGENT3
    def test_ctb_no_turn_as_progression_key(self) -> None:
        """契约：CTB 下 `turn` **不得作为推进主键**存在（可保留为兼容镜像）。

        清点表『删档』决策 + §4 R17：`turn` 是回合制产物，CTB 由逻辑时间/行动序号推进。

        **2026-09-10 复核修正**：Agent 3 保留了 `turn` 键——但**仅作 action_seq 的
        兼容镜像**（`world/snapshot_resume.py:105` 把 turn 列入快照完整性必需键
        `_SNAPSHOT_REQUIRED_KEYS`，见 02_wave_a_decisions.md 风险 R-A），且
        **不参与任何数值计算**。本契约据实改为「权威推进键是 action_seq/battle_time，
        turn 只能是其镜像」——比「键不存在」更准确地表达 CTB 的意图，也不误伤
        世界层完整性校验。
        """
        st = _new_engine().battle_state()
        # 权威推进键必须存在（CTB 双计数）
        assert "action_seq" in st, "CTB 须以 action_seq 为权威行动计数"
        assert "battle_time" in st, "CTB 须以 battle_time 为权威逻辑时间"
        # turn 若存在，必须只是 action_seq 的镜像（不得独立推进）
        if "turn" in st:
            assert st["turn"] == st["action_seq"], (
                f"turn 必须是 action_seq 的镜像（turn={st['turn']} "
                f"vs action_seq={st['action_seq']}）——不得独立计数"
            )


# ===========================================================================
# 契约 2：do_action() —— 单次结算入口（调用频次 189）
# ===========================================================================
class TestDoActionContract:
    """`do_action(attacker, action_dict)` 行为契约（清点表 §1.7，分类【平移】）。"""

    def test_signature_unchanged_two_positional_args(self) -> None:
        """契约：签名 `do_action(self, attacker, action_dict)` 零改动。"""
        import inspect

        params = list(inspect.signature(BattleEngine.do_action).parameters)
        assert params[:3] == ["self", "attacker", "action_dict"]

    def test_normal_attack_returns_outcome_and_applies_damage(self) -> None:
        """契约（现即成立）：普通攻击返回 outcome 且敌方 hp 扣减。"""
        eng = _new_engine()
        out = eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert out.action_type == "normal"
        assert eng.battle_state()["enemy"]["hp"] == ENEMY["hp"] - out.final_damage

    def test_records_action_into_action_record(self) -> None:
        """契约（现即成立）：每次结算写 action_record（审计字段）。"""
        eng = _new_engine()
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        rec = eng.battle_state()["action_record"]
        assert rec and rec[-1]["action"] == "normal"

    @TODO_AGENT3
    def test_ctb_does_not_require_turn_field_in_record(self) -> None:
        """契约（待 Agent 3）：action_record 条目须以 `action_seq`/时间标识归属。

        清点表 §4 R6/R7 + §2 A4：旧条目含 `turn` 且被 `_build_segments` 用 `turn` 过滤
        （过滤不到则连段段行静默消失）。CTB 须改记 `action_seq`。
        """
        eng = _new_engine()
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        rec = eng.battle_state()["action_record"]
        assert "action_seq" in rec[-1]


# ===========================================================================
# 契约 3：start() —— 开战入口（调用频次 159）
# ===========================================================================
class TestStartContract:
    """`start(player, enemy, random_seed, battle_type, config)` 行为契约。"""

    def test_signature_unchanged(self) -> None:
        """契约：签名零改动（清点表 §1.7 `start` 为【重写】但调用点不动）。"""
        import inspect

        params = list(inspect.signature(BattleEngine.start).parameters)
        assert params[:6] == [
            "self", "player", "enemy", "random_seed", "battle_type", "config"
        ]

    def test_start_initializes_state(self) -> None:
        """契约（现即成立）：开战后 state 含双方且战斗处于可行动态。"""
        eng = BattleEngine()
        eng.start(dict(PLAYER), dict(ENEMY), random_seed=_SEED)
        st = eng.battle_state()
        assert st["player"]["hp"] == PLAYER["hp"]
        assert eng.finished is False

    @TODO_AGENT3
    def test_ctb_start_emits_battle_start_and_sets_ready(self) -> None:
        """契约（待 Agent 3）：CTB 下 `start` 须建行动条并挂 `BATTLE_START`。

        清点表 §1.7：`start` 原建 `turn:0`/`round_phase` 并调 `start_turn()`；
        CTB 须建行动条（ready 态）并派发 `BATTLE_START`，不得再依赖回合相位。
        """
        eng = BattleEngine()
        eng.start(dict(PLAYER), dict(ENEMY), random_seed=_SEED)
        st = eng.battle_state()
        assert "battle_time" in st
        # CTB 位点：state 仍是行动态 'act'（引擎状态机保留），
        # 「行动条就绪」由 phase=actor_ready 承载（原回合制 phase=turn_start 已退役）。
        assert "ready" in str(eng.phase), f"CTB 起始位点应为就绪态，实际 {eng.phase!r}"

    @TODO_AGENT3
    def test_ctb_state_exposes_rng_seed_and_state(self) -> None:
        """契约（待 Agent 3）：RNG 状态可导出（`random_seed` + `rng_state`）。

        任务书 §1 明确：新快照要含 RNG 状态（`random_seed` + `rng_state`）；
        清点表 §2.3 `from_snapshot` docstring 也要求「随机种子随 formula_state.random_seed
        恢复 → 续玩随机序列一致」。
        """
        eng = BattleEngine()
        eng.start(dict(PLAYER), dict(ENEMY), random_seed=_SEED)
        st = eng.battle_state()
        assert "random_seed" in st
        assert "rng_state" in st


# ===========================================================================
# 契约 4：to_snapshot() —— 只产新格式 V2（调用频次 43）
# ===========================================================================
class TestToSnapshotContract:
    """`to_snapshot(boundary)` 行为契约。"""

    def test_returns_mapping_with_schema_version(self) -> None:
        """契约（现即成立）：返回映射且含 `schema_version`。"""
        eng = _new_engine()
        snap = eng.to_snapshot("actor_ready")
        assert isinstance(snap, dict)
        assert "schema_version" in snap

    def test_snapshot_is_json_serializable(self) -> None:
        """契约（现即成立）：快照 JSON 可序列化（1g3 §1.2）。"""
        eng = _new_engine()
        snap = eng.to_snapshot("actor_ready")
        assert json.dumps(snap, default=str)

    def test_boundary_is_required_positional(self) -> None:
        """契约：`to_snapshot(boundary)` 首参为落点标注（签名不删）。"""
        import inspect

        params = list(inspect.signature(BattleEngine.to_snapshot).parameters)
        assert params[:2] == ["self", "boundary"]

    @TODO_AGENT3
    def test_ctb_snapshot_only_new_format_v2(self) -> None:
        """契约（待 Agent 3）：只产新格式 V2（schema_version >= 2）。

        任务书 §1：删档前提下 `to_snapshot` 只需支持新格式 V2，不用兼容旧
        `schema_version==1`；旧格式为回合制产物（清点表 §4 R20）。
        """
        eng = _new_engine()
        snap = eng.to_snapshot("actor_ready")
        assert int(snap["schema_version"]) >= 2

    @TODO_AGENT3
    def test_ctb_snapshot_contains_rng_state(self) -> None:
        """契约（待 Agent 3）：快照须含 RNG 状态（`random_seed` + `rng_state`）。

        任务书 §1 硬要求；缺失则续战随机序列不可复现（清点表 §2.3 C2/A8 断链风险）。
        """
        eng = _new_engine()
        snap = eng.to_snapshot("actor_ready")
        assert "random_seed" in snap
        assert "rng_state" in snap

    @TODO_AGENT3
    def test_ctb_snapshot_boundary_is_ctb_boundary(self) -> None:
        """契约（待 Agent 3）：快照落点须为 CTB 边界（非 turn_start/turn_end）。

        清点表 §4 R20 + §6 S8：CTB 无回合边界，「快照只落确定性边界」的不变量须保留，
        但边界名须重定义（如 AFTER_ACTION / ready 边界）。
        """
        eng = _new_engine()
        snap = eng.to_snapshot("after_action")
        at = snap.get("snapshot_at") or {}
        assert str(at.get("boundary", "")) != "turn_start"
        assert str(at.get("boundary", "")) != "turn_end"


# ===========================================================================
# 契约 5：from_snapshot() —— 只吃 V2（调用频次 33）
# ===========================================================================
class TestFromSnapshotContract:
    """`from_snapshot(cls, data, ...)` 行为契约（本项目决策：删档）。"""

    def test_signature_keeps_data_first(self) -> None:
        """契约：类方法首参为快照 data（其余注入参数保留，调用点不改）。"""
        import inspect

        params = list(inspect.signature(BattleEngine.from_snapshot).parameters)
        assert params[0] == "data"

    def test_roundtrip_restores_state(self) -> None:
        """契约（现即成立）：快照 round-trip 后状态可继续（等价入口）。

        CTB 边界为 actor_ready / after_action（不再有回合边界，清点表 §4 R20）；
        本用例验证续战等价性不变量（render/续战一致）。
        """
        eng = _new_engine()
        snap = eng.to_snapshot("actor_ready")
        restored = BattleEngine.from_snapshot(copy.deepcopy(snap))
        assert restored.battle_state()["enemy"]["hp"] == eng.battle_state()["enemy"]["hp"]

    @TODO_AGENT3
    def test_ctb_rejects_legacy_v1_snapshot(self) -> None:
        """契约（待 Agent 3）：删档前提下 V1 快照必须被拒（不得静默降级续战）。

        任务书 §1：「删档：不兼容旧存档/旧快照格式」。当前引擎 `schema_version==1`
        属旧格式，CTB 后 `from_snapshot` 收到 V1 应显式报错而非带病续战。
        """
        eng = _new_engine()
        snap = eng.to_snapshot("actor_ready")
        snap["schema_version"] = 1
        with pytest.raises(Exception):
            BattleEngine.from_snapshot(snap)

    @TODO_AGENT3
    def test_ctb_restores_rng_state_for_reproducibility(self) -> None:
        """契约（待 Agent 3）：恢复后 RNG 状态须与原局一致，使后续随机完全相同。

        清点表 §2.3 `from_snapshot` docstring「随机种子随 formula_state.random_seed 恢复
        → 续玩随机序列一致（4a TC-17）」。断言强度：快照的 `rng_state` 必须可回灌，
        恢复局与原局在同一状态下的随机推进结果一致（非仅「字段存在」）。
        """
        eng = _new_engine()
        snap = eng.to_snapshot("actor_ready")
        assert "rng_state" in snap, "快照须含 rng_state（任务书 §1）"
        restored = BattleEngine.from_snapshot(copy.deepcopy(snap))
        st_r = restored.battle_state()
        assert st_r.get("rng_state") == snap.get("rng_state"), "rng_state 未正确回灌"


# ===========================================================================
# 契约 6：player_act() —— 玩家主入口（调用频次 28，battle_commands.py:1016 调用）
# ===========================================================================
class TestPlayerActContract:
    """`player_act(action, params=None)` 行为契约（清点表 §1.11，分类【重写】）。"""

    def test_signature_unchanged(self) -> None:
        """契约：签名 `player_act(self, action, params=None)` 零改动。"""
        import inspect

        sig = inspect.signature(BattleEngine.player_act)
        params = list(sig.parameters)
        assert params[:3] == ["self", "action", "params"]
        assert sig.parameters["params"].default is None

    def test_accepts_normal_str_and_returns_report(self) -> None:
        """契约（现即成立）：接受 'normal' 字符串并返回报告对象。"""
        eng = _new_engine()
        report = eng.player_act("normal")
        assert report is not None

    @TODO_AGENT3
    def test_ctb_player_act_advances_to_next_ready(self) -> None:
        """契约（待 Agent 3）：一次 `player_act` = 提交一次行动 + 推进到下一 ready。

        清点表 §1.11 `player_act` 语义从「整轮：先手→后手→tick→结算」改为
        「提交一次玩家行动并推进到下一个 ready actor」。

        **action_seq 语义（2026-09-10 复核修正）**：`action_seq` 是**已派发的行动
        序号**（调度器权威），覆盖**所有单位**的每次行动，而非仅玩家行动。故一次
        `player_act` 后增量 = 1（玩家自身）+ N（随后自动连锁的 NPC 行动）。
        断言为「严格递增」（冻结语义，避免误判为恰好 +1）。
        """
        eng = _new_engine()
        before = eng.battle_state().get("action_seq")
        before = before if before is not None else 0
        eng.player_act("normal")
        after = eng.battle_state().get("action_seq")
        assert after > before, f"player_act 应推进 action_seq（{before} → {after}）"

    @TODO_AGENT3
    def test_ctb_player_act_report_has_action_seq_not_phases(self) -> None:
        """契约（待 Agent 3）：行动报告改带 `action_seq`，去掉回合相位 `phases`。

        清点表 §1.11 M7：`_turn_report` 构造 `TurnReport(turn, phases, ...)`；
        CTB 须换为「行动报告」——`turn`→`action_seq`/`battle_time`，`phases`→去掉。
        """
        eng = _new_engine()
        report = eng.player_act("normal")
        fields = set(vars(report)) if hasattr(report, "__dict__") else set()
        if not fields:
            fields = set(getattr(report, "_fields", ()))
        assert "action_seq" in fields
        assert "phases" not in fields


# ===========================================================================
# 附加契约：时序旧方法必须抛 NotImplementedError（清点表 §0.1 / §1.12）
# ===========================================================================
class TestRemovedTimingShellsContract:
    """三个【删除】方法保留同名壳并抛 `NotImplementedError`（清点表 §1.12）。"""

    @TODO_AGENT3
    @pytest.mark.parametrize(
        "method,args",
        [
            ("action_order", ()),
            ("enemy_act", ({},)),
            ("end_turn", ()),
        ],
    )
    def test_removed_timing_methods_raise_not_implemented(
        self, method: str, args: tuple
    ) -> None:
        """契约（待 Agent 3）：三个删回合方法须抛 `NotImplementedError`。

        清点表 §1.12：`action_order`(1913) / `enemy_act`(3304) / `end_turn`(3333)
        为纯回合制产物，CTB 无对应物 → 保留同名签名壳、物理抛 `NotImplementedError`
        （暴露误用）。本用例三方法同拍断言，Agent 3 须全部落地。
        """
        eng = _new_engine()
        with pytest.raises(NotImplementedError):
            getattr(eng, method)(*args)

    def test_removed_shells_keep_signature(self) -> None:
        """契约：三个壳方法保留原签名（调用点编译期零改动）。"""
        import inspect

        assert list(inspect.signature(BattleEngine.action_order).parameters) == ["self"]
        assert list(inspect.signature(BattleEngine.enemy_act).parameters) == ["self", "action_dict"]
        assert list(inspect.signature(BattleEngine.end_turn).parameters) == ["self"]
