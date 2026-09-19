"""批37 · X12 战后恢复（`post_battle_recovery`）单测：纯函数 + 校验 + 端到端 + 边界。

覆盖：
  · 引擎纯函数 `core/post_battle_recovery.py`：段归一（缺省关）/ 比例计算（封顶、只增不减）/
    ctx 落点（dict 与 Player frozen 两形态）；确定性（同参同值，无随机）。
  · 校验器 `content/validator.py::_check_post_battle_recovery`：结构红拦 / enabled 类型 /
    ratio 越界 V5 红拦 / >0.5 V9 黄提示。
  · 端到端（**临时内容根**：真实 `build_pack` 装载探针包 → 真实 `BattleEngine` + 真实
    `_run_battle_action`）：贴 HP/MP 前后数值 + 恢复行（模板表）。
  · 回归对拍：不配置该字段 / enabled=false → 与现状逐字段一致（玩家档全字段 + 发送段）。
  · 边界：满血满蓝 / 失败不恢复 / 不减血（cur>max）/ 同场重复派发只应用一次 /
    恢复后再次战斗起始值正确。

依据：docs/战后恢复_实现口径.md；【框架】L294/L298-300；3h §4.2/L232/L234。
铁律：测试只写临时目录/临时内容根，绝不写仓库 content/。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.commands import battle_commands as bc
from qbot_rpg.commands.sender import Sender
from qbot_rpg.content.loader import PackLoadError, build_pack
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.post_battle_recovery import (
    DEFAULT_HEAL_RATIO,
    DEFAULT_SAFE_ZONE_HEAL,
    compute_recovery,
    parse_config,
    recover_after_battle,
)
from qbot_rpg.data.player import Player

# ---------------------------------------------------------------------------
# 临时内容根：探针包（真实装载 + 校验；不动仓库 content/）
# ---------------------------------------------------------------------------
_SETTINGS = {"post_battle_recovery": {"enabled": True, "heal_ratio": 0.2}}
_ENEMIES = [{"id": "slime", "name": "史莱姆"}]
_MAPS = [{"id": "m_field", "name": "野草地",
          "monsters": [{"enemy": "slime", "count": 1, "respawn_minutes": 5}],
          "exits": {}}]


def _write_pack(root: Path, settings: Dict[str, Any]) -> Path:
    pack = root / "content" / "pbrprobe"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "manifest.json").write_text(json.dumps(
        {"name": "战后恢复探针包", "version": "1.0.0", "schema_version": 1,
         "modules": ["maps", "enemies", "settings"]}, ensure_ascii=False), encoding="utf-8")
    (pack / "enemies.json").write_text(json.dumps(_ENEMIES, ensure_ascii=False), encoding="utf-8")
    (pack / "maps.json").write_text(json.dumps(_MAPS, ensure_ascii=False), encoding="utf-8")
    (pack / "settings.json").write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    return pack


def _load_settings(tmp_path: Path, settings: Dict[str, Any]) -> Dict[str, Any]:
    pack_dir = _write_pack(tmp_path, settings)
    try:
        built, _ = build_pack(pack_dir)
    except PackLoadError as exc:  # pragma: no cover - 探针包应零红拦
        raise AssertionError(f"探针包应零红拦：{exc.report.errors}") from exc
    assert built.report.ok, built.report.errors
    return built.registry.modules_raw["settings"]


# ---------------------------------------------------------------------------
# 战斗夹具（真实引擎；一击必杀弱怪 → 本拍终局）
# ---------------------------------------------------------------------------
PLAYER = {"name": "阿伟", "hp": 50, "mp": 10, "max_hp": 500, "max_mp": 100,
          "atk": 100, "dfn": 50, "mag": 50, "spd": 50, "foc": 100, "con": 50,
          "str": 100, "int": 80, "agi": 50, "spr": 50, "lck": 50,
          "elem_atk": 0}
WEAK_ENEMY = {"name": "史莱姆", "hp": 30, "max_hp": 30, "atk": 80, "dfn": 40,
              "mag": 30, "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30,
              "agi": 40, "spr": 40, "lck": 10, "elem_atk": 0}


class RecordingSender(Sender):
    """记录型统一出口（收集实际发送段；对齐 test_battle_wiring.RecordingSender）。"""

    def __init__(self) -> None:
        super().__init__(send_text=self._record)
        self.calls: list = []

    def _record(self, text: str, to=None) -> None:
        self.calls.append(text)


def _make_ctx(settings: Any, *, player: Dict[str, Any] | None = None) -> Dict[str, Any]:
    sender = RecordingSender()
    engine = BattleEngine().start(dict(player or PLAYER), dict(WEAK_ENEMY), random_seed=42)
    return {
        "battle_engine": engine,
        "sender": sender,
        "to": "group1",
        "channel": "group",
        "level": 35,
        "name": "阿伟",
        "prefix_settings": {"enabled": False},
        "skills": {},
        "items": {},
        "player": dict(player or PLAYER),
        "settings": settings,
    }


# ===========================================================================
# 一、引擎纯函数
# ===========================================================================
def test_parse_config_defaults_and_disabled() -> None:
    """段缺失 / 非对象 / enabled 非 True → 关闭（定稿 L299 默认关）。"""
    assert parse_config({}) == parse_config({"other": 1})
    assert parse_config(None).enabled is False
    assert parse_config({"post_battle_recovery": "x"}).enabled is False
    assert parse_config({"post_battle_recovery": {"enabled": False}}).enabled is False
    assert parse_config({"post_battle_recovery": {"heal_ratio": 0.5}}).enabled is False
    # 缺省比例 = 3h §4.2（无定稿依据，D1）
    cfg = parse_config({"post_battle_recovery": {"enabled": True}})
    assert cfg.enabled is True
    assert cfg.heal_ratio == DEFAULT_HEAL_RATIO
    assert cfg.safe_zone_heal == DEFAULT_SAFE_ZONE_HEAL


def test_parse_config_clamps_ratio() -> None:
    """越界/非法比例 → clamp 到 [0,1]（防御降级；校验器另有红拦）。"""
    def _ratio(raw: Any) -> float:
        return parse_config({"post_battle_recovery": {"enabled": True,
                                                      "heal_ratio": raw}}).heal_ratio

    assert _ratio(5) == 1.0
    assert _ratio(-1) == 0.0
    assert _ratio("x") == DEFAULT_HEAL_RATIO


def test_compute_recovery_ratio_and_cap() -> None:
    """比例恢复：heal=int(max×ratio)，加到当前值后封顶 max。"""
    assert compute_recovery(50, 200, 0.2) == (90, 40)
    assert compute_recovery(50, 200, 1.0) == (200, 150)
    assert compute_recovery(190, 200, 0.2) == (200, 10)     # 封顶
    assert compute_recovery(200, 200, 0.2) == (200, 0)      # 满值零操作
    assert compute_recovery(50, 200, 0) == (50, 0)
    assert compute_recovery(50, 0, 0.2) == (50, 0)          # max 非正 → 零操作


def test_compute_recovery_never_reduces() -> None:
    """cur > max（升级回满后旧快照 max 偏小）→ 不减血、不恢复。"""
    assert compute_recovery(210, 200, 0.2) == (210, 0)


def test_recover_after_battle_dict_and_player_forms() -> None:
    """ctx 落点：dict 就地写 / Player frozen 重建写回；均返回恢复明细。"""
    settings = {"post_battle_recovery": {"enabled": True, "heal_ratio": 0.2}}
    snap = {"player": {"max_hp": 500, "max_mp": 100}}
    # dict 形态
    ctx: Dict[str, Any] = {"player": {"hp": 50, "mp": 10}}
    info = recover_after_battle(ctx, snap, settings)
    assert info == {"hp_before": 50, "hp": 150, "hp_max": 500, "hp_healed": 100,
                    "mp_before": 10, "mp": 30, "mp_max": 100, "mp_healed": 20}
    assert ctx["player"] == {"hp": 150, "mp": 30}
    # Player frozen 形态
    ctx2: Dict[str, Any] = {"player": Player(qid="u1", name="阿伟", hp=50, mp=10)}
    recover_after_battle(ctx2, snap, settings)
    assert isinstance(ctx2["player"], Player)
    assert (ctx2["player"].hp, ctx2["player"].mp) == (150, 30)


def test_recover_after_battle_disabled_and_no_change() -> None:
    """未开启 / 满血满蓝 → None（不写回、不出提示）。"""
    snap = {"player": {"max_hp": 500, "max_mp": 100}}
    assert recover_after_battle({"player": {"hp": 50, "mp": 10}}, snap, {}) is None
    assert recover_after_battle(
        {"player": {"hp": 50, "mp": 10}}, snap,
        {"post_battle_recovery": {"enabled": True, "heal_ratio": 0}}) is None
    full = {"player": {"hp": 500, "mp": 100}}
    assert recover_after_battle(
        full, snap, {"post_battle_recovery": {"enabled": True, "heal_ratio": 0.2}}) is None
    assert full["player"] == {"hp": 500, "mp": 100}


# ===========================================================================
# 二、校验器（settings.post_battle_recovery）
# ===========================================================================
def _errors(settings: Any) -> list:
    rep = check_pack({"settings": settings})
    return [(e.field, e.detail.get("rule")) for e in rep.errors]


def _warnings(settings: Any) -> list:
    rep = check_pack({"settings": settings})
    return [(w.field, w.detail.get("rule")) for w in rep.warnings]


def test_validator_absent_and_valid_clean() -> None:
    assert _errors({"level_cap": 45}) == []
    assert _errors({"post_battle_recovery": {"enabled": True, "heal_ratio": 0.2,
                                             "safe_zone_heal": 0.1}}) == []


@pytest.mark.parametrize("bad", [None, 3, "x", []])
def test_validator_structure_red(bad: Any) -> None:
    errs = _errors({"post_battle_recovery": bad})
    assert any(rule == "section_structure" for _, rule in errs), errs


def test_validator_enabled_type_red() -> None:
    assert ("settings.post_battle_recovery.enabled", "type") in _errors(
        {"post_battle_recovery": {"enabled": 1}})


@pytest.mark.parametrize("ratio", [-0.1, 1.5, 2, -3])
def test_validator_ratio_range_red(ratio: Any) -> None:
    """V5（3h L234）：ratio ∉ [0,1] → 红拦。"""
    assert ("settings.post_battle_recovery.heal_ratio", "ratio_out_of_range") in _errors(
        {"post_battle_recovery": {"heal_ratio": ratio}})


def test_validator_ratio_type_red() -> None:
    assert ("settings.post_battle_recovery.heal_ratio", "type") in _errors(
        {"post_battle_recovery": {"heal_ratio": "0.2"}})
    assert ("settings.post_battle_recovery.safe_zone_heal", "type") in _errors(
        {"post_battle_recovery": {"safe_zone_heal": True}})


def test_validator_ratio_high_yellow() -> None:
    """V9（3h L234/L510）：ratio > 0.5 → 黄提示（不阻断）。"""
    warn = _warnings({"post_battle_recovery": {"heal_ratio": 0.6}})
    assert ("settings.post_battle_recovery.heal_ratio", "recovery_ratio_high") in warn
    assert _errors({"post_battle_recovery": {"heal_ratio": 0.6}}) == []


# ===========================================================================
# 三、端到端（临时内容根 + 真实战斗）
# ===========================================================================
def _run(settings: Any, *, player: Dict[str, Any] | None = None) -> Dict[str, Any]:
    ctx = _make_ctx(settings, player=player)
    before = dict(ctx["player"])
    res = bc._run_battle_action(ctx, {"type": "normal"})
    return {"ctx": ctx, "before": before, "after": dict(ctx["player"]),
            "sent": ctx["sender"].calls, "res": res,
            "engine_hp": ctx["battle_engine"].battle_state()["player"]["hp"]}


def test_e2e_recovery_applies_on_win(tmp_path: Path) -> None:
    """E2E：临时内容根装载配置 → 战斗胜利 → 按比例恢复（贴 HP/MP 前后数值）。"""
    settings = _load_settings(tmp_path, _SETTINGS)
    out = _run(settings)
    # 前 50/10 → 后 150/30（max 500/100 × 0.2 = +100/+20）
    assert (out["before"]["hp"], out["before"]["mp"]) == (50, 10)
    assert (out["after"]["hp"], out["after"]["mp"]) == (150, 30)
    assert any("战后恢复" in seg and "150/500" in seg and "30/100" in seg
               for seg in out["sent"]), out["sent"]
    # 只写玩家档、不改引擎快照（战斗内数值零影响）
    assert out["engine_hp"] == 50
    assert out["res"]["ok"] is True


def test_e2e_no_config_matches_current_behaviour(tmp_path: Path) -> None:
    """回归对拍：不配置该字段 / enabled=false → 战后行为逐字段一致（无恢复行、HP/MP 不变）。"""
    absent = _run(_load_settings(tmp_path / "a", {}))
    disabled = _run(_load_settings(tmp_path / "b", {"post_battle_recovery": {"enabled": False}}))
    # 玩家档逐字段一致 + 发送段逐段一致（模板/文案零变化）
    assert absent["after"] == disabled["after"] == absent["before"]
    assert absent["sent"] == disabled["sent"]
    assert all("战后恢复" not in seg for seg in absent["sent"])


def test_e2e_full_vitals_no_line(tmp_path: Path) -> None:
    """边界：满血满蓝 → 无恢复行、数值不变（不溢出）。"""
    settings = _load_settings(tmp_path, _SETTINGS)
    full = dict(PLAYER, hp=500, mp=100)
    out = _run(settings, player=full)
    assert (out["after"]["hp"], out["after"]["mp"]) == (500, 100)
    assert all("战后恢复" not in seg for seg in out["sent"])


def test_e2e_recovery_once_then_next_battle(tmp_path: Path) -> None:
    """边界：同场重复派发只恢复一次；恢复后再次战斗起始值正确（不重复结算）。"""
    settings = _load_settings(tmp_path, _SETTINGS)
    out = _run(settings)
    ctx = out["ctx"]
    # 同 engine 再次调用恢复入口 → 只应用一次（P-4）
    assert bc._apply_post_battle_recovery(ctx, ctx["battle_engine"]) is None
    assert ctx["player"]["hp"] == 150
    # 恢复后再次战斗：新战斗从恢复后的 150 起算，再恢复 +100 → 250
    second = _run(settings, player=dict(ctx["player"]))
    assert (second["before"]["hp"], second["before"]["mp"]) == (150, 30)
    assert (second["after"]["hp"], second["after"]["mp"]) == (250, 50)


def test_e2e_lose_does_not_recover() -> None:
    """边界：失败不恢复（定稿 L298 只写「胜利后」）。"""
    # 玩家弱到必败：hp=1，敌人强
    weak_player = dict(PLAYER, hp=1, mp=1, max_hp=5, max_mp=5, atk=1, str=1)
    ctx = _make_ctx({"post_battle_recovery": {"enabled": True, "heal_ratio": 0.5}},
                    player=weak_player)
    ctx["battle_engine"] = BattleEngine().start(
        dict(weak_player), dict(WEAK_ENEMY, atk=9999, hp=500, max_hp=500), random_seed=7)
    bc._run_battle_action(ctx, {"type": "normal"})
    assert ctx["battle_engine"].battle_state().get("status") == "lose"
    assert ctx["player"]["hp"] == 0
    assert all("战后恢复" not in seg for seg in ctx["sender"].calls)
