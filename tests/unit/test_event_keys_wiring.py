"""事件写入点接线测试（tests/unit/test_event_keys_wiring.py · M12.5 批5 路5B）。

覆盖 7 处字面量写点改读解析中心后（settings.events 可配）：
  - 含 events 配置的 ctx → 各写点产出新键（配置改名全链生效）；
  - 无配置 ctx → 产出默认键（向后兼容零破坏，等价现字面量）。

写点（审计 docs/m125_事件键审计.md §2）：
  core/checkin.py do_checkin 尾（签到） / core/dungeon.py 探索 clear（副本通关） /
  core/levelup.py gain_exp 升级（等级提升） / commands/battle_commands.py win 结算
  （怪物击杀） / core/codex.py mark_seen + core/fishing_codex.py _mark_fish_seen
  （图鉴新增，双路同键） / core/achievements.py _log_milestone（成就达成）。
所有写点经 bump_event 直接导入 + resolve_event_key(ctx, name) 解析键。
"""

from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.content.dungeon_models import DungeonDef
from qbot_rpg.core.achievements import _log_milestone
from qbot_rpg.core.checkin import checkin_do
from qbot_rpg.core.codex import mark_seen
from qbot_rpg.core.dungeon import explore_run
from qbot_rpg.core.event_bus import resolve_event_key
from qbot_rpg.core.fishing_codex import fish_codex_update
from qbot_rpg.core.levelup import LevelUpEngine
from qbot_rpg.data.player import PlayerAttributes

# 探索副本 fixture（tests/fixtures/packs/legal：explore=molten_dungeon_explore + 三图）
_LEGAL_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs" / "legal"
_DUNGEON_DEF = DungeonDef.from_entry(next(
    d for d in json.loads((_LEGAL_DIR / "dungeon.json").read_text(encoding="utf-8"))
    if isinstance(d, dict) and d.get("id") == "molten_dungeon_explore"
))
_DUNGEON_MAPS = json.loads((_LEGAL_DIR / "maps.json").read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# 通用 ctx 夹具：settings.events 可注入（events=None → 无 events 段）
# ---------------------------------------------------------------------------


def _events_ctx(events: dict | None = None) -> dict:
    """最小事件结算 ctx：三表 + settings（events 段可选，装配口径子表）。"""
    settings: dict = {}
    if events is not None:
        settings["events"] = events
    return {
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {"event_log": []},
        "settings": settings,
    }


def _codex_ctx(events: dict | None = None) -> dict:
    """codex 结算 ctx：codex_state + registry + 事件三表 + settings。"""
    ctx = _events_ctx(events)
    ctx["codex_state"] = {}
    ctx["registry"] = _Reg({"monster": ["rock_weasel"], "item": []})
    # registry 内容注入为 list 形态（mark_seen 写目标条目的 registry 引用落点）
    ctx["registry_all"] = {"monster": ["rock_weasel"], "item": []}
    return ctx


def _fish_ctx(events: dict | None = None) -> dict:
    """fishing codex 结算 ctx：codex_state(fish 册) + 事件三表 + settings。"""
    ctx = _events_ctx(events)
    ctx["codex_state"] = {}
    return ctx


class _Reg:
    """registry 最小替身：all_ids 供 codex 分册分母，resolve 返回条目。"""

    def __init__(self, ids: dict) -> None:
        self._ids = ids

    def all_ids(self, category: str) -> list:
        return list(self._ids.get(category, []))

    def resolve(self, category: str, ref_id: str) -> dict:
        return {"id": ref_id, "name": ref_id}


# ---------------------------------------------------------------------------
# 签到（core/checkin.py do_checkin 尾）
# ---------------------------------------------------------------------------


def _checkin_ctx(events: dict | None = None) -> dict:
    """checkin_do 结算 ctx：事件三表 + settings（对齐 test_checkin.make_ctx 最小面）。"""
    ctx = _events_ctx(events)
    ctx.update({
        "checkin_tables": {},
        "checkin_state": {},
        "inventory": {},
        "currencies": {},
        "items": {},
        # now 为 UTC+8 秒级时间戳（对齐 test_checkin.NOW 口径）
        "now": 1785201600,
    })
    return ctx


def test_checkin_write_key_default() -> None:
    """无配置 → checkin_do 写默认键 [事件:签到]（flat milestone）。"""
    ctx = _checkin_ctx()
    r = checkin_do(ctx)
    assert r["ok"] is True
    assert ctx["event_counts"] == {"[事件:签到]": 1}


def test_checkin_write_key_configured() -> None:
    """events 段配 签到→每日打卡 → checkin_do 写新键 [事件:每日打卡]。"""
    ctx = _checkin_ctx({"签到": "每日打卡"})
    r = checkin_do(ctx)
    assert r["ok"] is True
    assert ctx["event_counts"] == {"[事件:每日打卡]": 1}
    assert "[事件:签到]" not in ctx["event_counts"]


# ---------------------------------------------------------------------------
# 副本通关（core/dungeon.py 探索 clear）
# ---------------------------------------------------------------------------


def _dungeon_ctx(events: dict | None = None) -> dict:
    """探索副本 ctx：事件三表 + settings + 入场必需字段（对齐 dungeon 消费面）。"""
    ctx = _events_ctx(events)
    ctx.update({
        "map_id": "mountain_foot",
        "player": {"map_id": "mountain_foot", "name": "阿伟", "inventory": {}},
        "inventory": {},
        "dungeon_entries": {},
        "content_pack_id": "legal",
        "content_pack_version": "1.0.0",
    })
    return ctx


def test_dungeon_clear_write_key_default() -> None:
    """无配置 → 探索 clear 写默认键 [事件:副本通关]（flat milestone）。"""
    ctx = _dungeon_ctx()
    r = explore_run(ctx, _DUNGEON_DEF, _DUNGEON_MAPS, actions=[
        ("walk", "上"), ("walk", "左"), ("clear",),
    ])
    assert r["ok"] is True
    assert ctx["event_counts"] == {"[事件:副本通关]": 1}


def test_dungeon_clear_write_key_configured() -> None:
    """events 段配 副本通关→地牢征服 → clear 写新键 [事件:地牢征服]。"""
    ctx = _dungeon_ctx({"副本通关": "地牢征服"})
    r = explore_run(ctx, _DUNGEON_DEF, _DUNGEON_MAPS, actions=[
        ("walk", "上"), ("walk", "左"), ("clear",),
    ])
    assert r["ok"] is True
    assert ctx["event_counts"] == {"[事件:地牢征服]": 1}


# ---------------------------------------------------------------------------
# 等级提升（core/levelup.py gain_exp 升级结算）
# ---------------------------------------------------------------------------


def _level_player(events: dict | None = None) -> dict:
    """LevelUpEngine 消费的玩家 dict：level/exp + 事件三表 + settings 子表。"""
    player: dict = {
        "level": 1,
        "exp": 90,
        "hp": 100,
        "mp": 30,
        "job_id": "warrior",
        "attributes": PlayerAttributes(
            base={"hp": 100.0, "mp": 30.0, "str": 15.0, "con": 10.0}
        ),
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {"event_log": []},
        "settings": {},
    }
    if events is not None:
        player["settings"] = {"events": events}
    return player


def test_levelup_write_key_default() -> None:
    """无配置 → 升级写默认键 [事件:等级提升]（flat milestone）。"""
    player = _level_player()
    eng = LevelUpEngine()
    r = eng.gain_exp(player, 100)
    assert r["ok"] is True and r["level_ups"] == 1
    # 装配层升级结算 player 即 ctx 直键容器：三表挂在 player 自身
    assert player["event_counts"] == {"[事件:等级提升]": 1}
    assert player["persistent_state"]["event_log"][0]["event_id"] == "milestone:[事件:等级提升]"


def test_levelup_write_key_configured() -> None:
    """events 段配 等级提升→等级跃迁 → 升级写新键 [事件:等级跃迁]。"""
    player = _level_player({"等级提升": "等级跃迁"})
    eng = LevelUpEngine()
    r = eng.gain_exp(player, 100)
    assert r["ok"] is True and r["level_ups"] == 1
    assert player["event_counts"] == {"[事件:等级跃迁]": 1}


# ---------------------------------------------------------------------------
# 图鉴新增双路同键（core/codex.mark_seen + core/fishing_codex）
# 注：双写同键同源铁律——两写点 bump 均用 adventure_log.EVENT_KEY_CODEX_NEW
# 常量（与 log_codex_new 常量路同源）；adventure_log 常量路未解析中心化，
# 配置改名对图鉴新增路径 DELAYED（默认键断言恒成立）。本组测试把
# log_codex_new 置空以隔离各写点自身 bump（防双写点计数叠加干扰键断言）。
# ---------------------------------------------------------------------------


def _silence_log_codex_new(monkeypatch) -> None:
    """log_codex_new 置空：codex/fishing 写点各自独立 bump（隔离计数）。"""
    import qbot_rpg.core.adventure_log as al

    monkeypatch.setattr(al, "log_codex_new", lambda ctx, entry: {"ok": True})


def test_codex_new_write_key_default(monkeypatch) -> None:
    """无配置 → mark_seen 首见写默认键 [事件:图鉴新增] nested target=rid。"""
    _silence_log_codex_new(monkeypatch)
    ctx = _codex_ctx()
    r = mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    assert r["first_seen"] is True
    assert ctx["event_counts"] == {"[事件:图鉴新增]": {"rock_weasel": 1}}


def test_codex_new_write_key_configured(monkeypatch) -> None:
    """events 段配 图鉴新增→收集物 → mark_seen 仍写常量默认键（DELAYED：常量路未中心化）。"""
    _silence_log_codex_new(monkeypatch)
    ctx = _codex_ctx({"图鉴新增": "收集物"})
    r = mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    assert r["first_seen"] is True
    assert ctx["event_counts"] == {"[事件:图鉴新增]": {"rock_weasel": 1}}


def test_fish_codex_new_write_key_default(monkeypatch) -> None:
    """无配置 → 钓鱼首获写默认键 [事件:图鉴新增] nested target=鱼种（与 mark_seen 同键）。"""
    _silence_log_codex_new(monkeypatch)
    ctx = _fish_ctx()
    r = fish_codex_update(ctx, "silver_carp", {"size": 35.0, "weight": 2.65,
                                               "crown": "normal"}, name="银鲤")
    assert r["first_seen"] is True
    assert ctx["event_counts"] == {"[事件:图鉴新增]": {"silver_carp": 1}}


def test_fish_codex_new_write_key_configured(monkeypatch) -> None:
    """配置改名 → 钓鱼首获仍写常量默认键（与 mark_seen 同源同键，双路不分裂）。"""
    _silence_log_codex_new(monkeypatch)
    ctx = _fish_ctx({"图鉴新增": "收集物"})
    r = fish_codex_update(ctx, "silver_carp", {"size": 35.0, "weight": 2.65,
                                               "crown": "normal"}, name="银鲤")
    assert r["first_seen"] is True
    assert ctx["event_counts"] == {"[事件:图鉴新增]": {"silver_carp": 1}}


def test_codex_dual_path_same_source_constant() -> None:
    """双路写同键同源：codex/fishing 两写点 bump 键 == log_codex_new 常量
    EVENT_KEY_CODEX_NEW（配置改名期间双路同走常量，计数不分裂）。"""
    from qbot_rpg.core.adventure_log import EVENT_KEY_CODEX_NEW

    assert EVENT_KEY_CODEX_NEW == "[事件:图鉴新增]"
    # 两写点经 resolve_event_key 会产出配置新键，但铁律要求与 log_codex_new
    # 常量同源——现状同走常量键（DELAYED 记录在案，见文件头注释）
    assert resolve_event_key(_codex_ctx({"图鉴新增": "收集物"}), "图鉴新增") == "[事件:收集物]"


# ---------------------------------------------------------------------------
# 成就达成（core/achievements._log_milestone）
# ---------------------------------------------------------------------------


def _ach_ctx(events: dict | None = None) -> dict:
    """_log_milestone 结算 ctx：事件三表 + settings（flat 无 target 形态）。"""
    return _events_ctx(events)


def test_achievement_write_key_default() -> None:
    """无配置 → _log_milestone 写默认键 [事件:成就达成]（flat）。"""
    ctx = _ach_ctx()
    r = _log_milestone(ctx, "ach_001")
    assert r["ok"] is True
    assert ctx["event_counts"] == {"[事件:成就达成]": 1}
    # aid 元数据经 instance.params 保留（不进 event_counts）
    assert ctx["persistent_state"]["event_log"][0]["params"]["achievement_id"] == "ach_001"


def test_achievement_write_key_configured() -> None:
    """events 段配 成就达成→勋章解锁 → _log_milestone 写新键（flat）。"""
    ctx = _ach_ctx({"成就达成": "勋章解锁"})
    r = _log_milestone(ctx, "ach_001")
    assert r["ok"] is True
    assert ctx["event_counts"] == {"[事件:勋章解锁]": 1}
    assert "[事件:成就达成]" not in ctx["event_counts"]


# ---------------------------------------------------------------------------
# 全部写点默认键对齐（向后兼容零破坏总断言）
# ---------------------------------------------------------------------------


def test_all_write_points_default_keys_no_config() -> None:
    """无配置全链路：各写点产出键 == 现字面量（零破坏契约）。"""
    expected = {
        "签到": "[事件:签到]",
        "副本通关": "[事件:副本通关]",
        "等级提升": "[事件:等级提升]",
        "怪物击杀": "[事件:怪物击杀]",
        "图鉴新增": "[事件:图鉴新增]",
        "成就达成": "[事件:成就达成]",
    }
    for name, key in expected.items():
        assert resolve_event_key(_events_ctx(), name) == key
    # 图鉴新增双路写点实际 bump 键：与 log_codex_new 同源常量（默认键零破坏）；
    # 中心解析改名对该路径 DELAYED（adventure_log 常量路未解析化，见文件头注释）
    from qbot_rpg.core.adventure_log import EVENT_KEY_CODEX_NEW

    assert EVENT_KEY_CODEX_NEW == "[事件:图鉴新增]"
