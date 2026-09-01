"""tests/unit/test_ctx_injection.py — M13 批13 路13A：ctx["skills"]/ctx["jobs"] 注入单测。

依据：docs/m13_启动包.md §2.4 装配接线（ctx["skills"]/ctx["jobs"] 注入——现恒空，
/攻击 <技能> 无法解析）+ §四 关键接口 + docs/m13_6a摸底.md（A11：ctx['skills'] 注入
context.py:1279 _table_from_registry kind='skill'）+ docs/m13_6b摸底.md（⑧：ctx["jobs"]
从未注入，批5 接线）。

覆盖：
  - 注册态 + 未注册态两态下 ctx["skills"]/ctx["jobs"] 均注入且为 Mapping；
  - test_demo 真实内容包（22 技能 / 4 职业）经 load_pack → make_context 注入非空、
    含预期 id、Def→raw dict 契约（Mapping.get("name") 可用）；
  - /攻击 <技能> 解析链路（battle_commands._resolve_skill：id/名称/序号 三形态）；
  - 注册默认职业链路（register_commands.resolve_job/default_job：显示名匹配 /
    job_id 直配 / recommended_newbie 兜底链）；
  - 技能展示 skill_rows 与 PVP 技能解析（pvp_commands._resolve_skill）消费；
  - 未注册态注册流程可用（default_job 未注册玩家可取默认职业）；
  - 无 skills/jobs 模块兜底 {}（不硬崩装配）。

零 NoneBot import；平台无关（铁律）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qbot_rpg.assembly.context import AssemblyDeps, make_context
from qbot_rpg.commands import battle_commands, basic_commands, pvp_commands
from qbot_rpg.commands import register_commands
from qbot_rpg.content.registry import Registry
from qbot_rpg.data import ItemInstance, Player, PlayerAttributes

REPO = Path(__file__).resolve().parents[2]
TEST_DEMO = REPO / "content" / "test_demo"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _player(qid: str = "10001") -> Player:
    """已注册玩家（warrior 职业；skills/jobs 表消费与职业 id 无关）。"""
    return Player(
        qid=qid,
        name="阿伟",
        job_id="warrior",
        level=35,
        exp=1200,
        hp=220,
        mp=60,
        currencies={"gold": 350, "gem": 8},
        inventory=(
            ItemInstance(item_id="potion", name="药水", count=2, quality="normal", bound=False),
        ),
        equipment={},
        attributes=PlayerAttributes(
            base={"hp": 100.0, "mp": 50.0, "str": 15.0}, bonus={"flat": {}, "pct": {}}
        ),
        title_state={"current": ""},
        persistent_state={"location": "town_center"},
        longline_counters={},
        codex_state={},
    )


class _FakeRepo:
    """鸭子 Repository：async load_player（test_demo 注册表探针无 DB 依赖）。"""

    def __init__(self, player: object) -> None:
        self._player = player

    async def load_player(self, qid: str):  # noqa: ANN001
        p = self._player
        if p is not None and getattr(p, "qid", None) == str(qid):
            return p
        return None


class _StubWorld:
    """最小 GameWorld 鸭式（make_context 兜底读，均返回安全值）。"""

    def get_map(self, map_id: str):  # noqa: ANN001
        return None

    def monster_pool(self, map_id: str):  # noqa: ANN001
        return []

    def get_npcs(self, map_id: str):  # noqa: ANN001
        return []


class _StubSession:
    def get_active(self, qid: str):  # noqa: ANN001
        return None


def _registry_with(skills: object, jobs: object) -> Registry:
    """手工 Registry：skill/job 表（SimpleNamespace Def + raw dict 双形态）。"""
    tables: dict = {}
    names: dict = {}
    if isinstance(skills, dict):
        tables["skill"] = {
            k: SimpleNamespace(id=k, name=v.get("name", k), raw=dict(v)) for k, v in skills.items()
        }
        names.update({k: v.get("name", k) for k, v in skills.items()})
    if isinstance(jobs, dict):
        tables["job"] = {
            k: SimpleNamespace(id=k, name=v.get("name", k), raw=dict(v)) for k, v in jobs.items()
        }
        names.update({k: v.get("name", k) for k, v in jobs.items()})
    return Registry(pack_id="t", generation=1, tables=tables, names=names, modules_raw={})


def _deps(registry: Registry, player: object = None) -> AssemblyDeps:
    return AssemblyDeps(
        repo=_FakeRepo(player),
        game_world=_StubWorld(),
        registry=registry,
        settings={"default_map": "town_center", "default_job_id": "novice"},
        session_mgr=_StubSession(),
    )


def _event(**over: object) -> dict:
    e: dict = {"group_id": "123456", "user_id": "10001", "message": "/状态", "channel": "qq"}
    e.update(over)
    return e


@pytest.fixture(scope="module")
def demo_registry() -> Registry:
    """test_demo 真实内容包注册表（22 技能 / 4 职业，批1/批4 已落盘）。"""
    from qbot_rpg.content.loader import build_pack

    pack, _ = build_pack(TEST_DEMO)
    assert pack.report.ok, f"test_demo 不应红拦：{pack.report.errors}"
    return pack.registry


@pytest.fixture(scope="module")
def demo_ctx(demo_registry: Registry) -> dict:
    """test_demo 注册表 + 已注册玩家 → make_context 全量 ctx。"""
    return _make_ctx(demo_registry, _player())


def _make_ctx(registry: Registry, player: object = None) -> dict:
    import asyncio

    return asyncio.run(make_context(_event(), _deps(registry, player)))


# ---------------------------------------------------------------------------
# 1. make_context 注入核对（注册态）
# ---------------------------------------------------------------------------
def test_skills_injected_registered(demo_ctx: dict) -> None:
    """已注册态：ctx["skills"] 注入且为 Mapping（非 None / 非恒空）。"""
    skills = demo_ctx.get("skills")
    assert isinstance(skills, dict)
    assert len(skills) > 0


def test_skills_contains_test_demo_ids(demo_ctx: dict) -> None:
    """已注册态：test_demo 12 技能族（22 条含 4 类时机）id 可查。"""
    skills = demo_ctx["skills"]
    for sid in (
        "basic_attack",
        "power_strike",
        "healing_light",
        "fireball",
        "stone_guard",
        "flame_burst",
        "fury_slash",
        "rage_burst",
    ):
        assert sid in skills, f"ctx[skills] 缺 test_demo 技能: {sid}"


def test_skills_def_raw_dict_contract(demo_ctx: dict) -> None:
    """ctx["skills"] 值为 raw dict（Def→dict 转换，Mapping.get 契约成立）。"""
    d = demo_ctx["skills"]["power_strike"]
    assert isinstance(d, dict)
    assert d.get("name") == "强力斩击"
    assert d.get("type") == "active"


def test_jobs_injected_registered(demo_ctx: dict) -> None:
    """已注册态：ctx["jobs"] 注入且为 Mapping（新注入，6b 摸底 ⑧ 缺口修复）。"""
    jobs = demo_ctx.get("jobs")
    assert isinstance(jobs, dict)
    assert len(jobs) > 0


def test_jobs_contains_test_demo_jobs(demo_ctx: dict) -> None:
    """已注册态：test_demo 4 职业全量可查（狂战士/炼金术士/铁匠/渔夫）。"""
    jobs = demo_ctx["jobs"]
    for jid in ("berserker", "alchemy", "forge", "fishing"):
        assert jid in jobs, f"ctx[jobs] 缺 test_demo 职业: {jid}"


def test_jobs_def_raw_dict_contract(demo_ctx: dict) -> None:
    """ctx["jobs"] 值为 raw dict（Def→dict 转换；recommended_newbie 可读）。"""
    d = demo_ctx["jobs"]["berserker"]
    assert isinstance(d, dict)
    assert d.get("name") == "狂战士"
    assert d.get("recommended_newbie") is False
    assert demo_ctx["jobs"]["alchemy"].get("recommended_newbie") is True


# ---------------------------------------------------------------------------
# 2. make_context 注入核对（未注册态）
# ---------------------------------------------------------------------------
def test_skills_jobs_injected_unregistered(demo_registry: Registry) -> None:
    """未注册态：skills/jobs 仍注入非空（注册流程消费，注册态无关）。"""
    ctx = _make_ctx(demo_registry, None)
    assert isinstance(ctx.get("skills"), dict)
    assert len(ctx["skills"]) == 22
    assert isinstance(ctx.get("jobs"), dict)
    assert len(ctx["jobs"]) == 4


def test_missing_modules_fallback_empty() -> None:
    """无 skills/jobs 模块 → {} 兜底（不硬崩装配；消费方 fail-safe）。"""
    reg = _registry_with({}, {})
    ctx = _make_ctx(reg, _player())
    assert ctx["skills"] == {}
    assert ctx["jobs"] == {}


# ---------------------------------------------------------------------------
# 3. /攻击 <技能> 解析链路（battle_commands._resolve_skill）
# ---------------------------------------------------------------------------
def test_resolve_skill_by_id(demo_ctx: dict) -> None:
    """技能 id 直配：/攻击 power_strike → power_strike。"""
    assert battle_commands._resolve_skill(demo_ctx, "power_strike") == "power_strike"


def test_resolve_skill_by_name(demo_ctx: dict) -> None:
    """技能中文名匹配：/攻击 火球术 → fireball。"""
    assert battle_commands._resolve_skill(demo_ctx, "火球术") == "fireball"


def test_resolve_skill_by_index(demo_ctx: dict) -> None:
    """数字序号（配置序 1 起）：/攻击 2 → 第 2 个技能 id。"""
    skills = demo_ctx["skills"]
    sid = battle_commands._resolve_skill(demo_ctx, "2")
    assert sid == list(skills.keys())[1]
    assert battle_commands._resolve_skill(demo_ctx, "1") == list(skills.keys())[0]


def test_resolve_skill_unknown_returns_none(demo_ctx: dict) -> None:
    """查无（不存在的 id/名称/越界序号）→ None（不抛异常）。"""
    assert battle_commands._resolve_skill(demo_ctx, "不存在的技能") is None
    assert battle_commands._resolve_skill(demo_ctx, "9999") is None
    assert battle_commands._resolve_skill(demo_ctx, "") is None


# ---------------------------------------------------------------------------
# 4. 注册默认职业链路（register_commands.resolve_job / default_job）
# ---------------------------------------------------------------------------
def test_resolve_job_by_display_name(demo_ctx: dict) -> None:
    """RUL-03 显示名精确匹配：resolve_job(ctx, "炼金术士") → alchemy。"""
    d = register_commands.resolve_job(demo_ctx, "炼金术士")
    assert d is not None
    assert d["id"] == "alchemy"


def test_resolve_job_by_id_fallback(demo_ctx: dict) -> None:
    """job_id 直配兜底：resolve_job(ctx, "berserker") → berserker。"""
    d = register_commands.resolve_job(demo_ctx, "berserker")
    assert d is not None
    assert d["id"] == "berserker"
    assert d["name"] == "狂战士"


def test_resolve_job_unknown_none(demo_ctx: dict) -> None:
    """查无 → None（调用方兜底「?」）。"""
    assert register_commands.resolve_job(demo_ctx, "不存在职业") is None
    assert register_commands.resolve_job(demo_ctx, "") is None


def test_default_job_recommended_newbie(demo_ctx: dict) -> None:
    """default_job 兜底链：settings.default_job_id 无效 → 首个 recommended_newbie。"""
    d = register_commands.default_job(demo_ctx)
    assert d is not None
    assert d["id"] == "alchemy"  # test_demo: alchemy/forge/fishing 均推荐，首者为 alchemy
    assert d.get("recommended_newbie") is True


def test_default_job_settings_override(demo_registry: Registry) -> None:
    """default_job 兜底链①：settings.default_job_id 有效 → 直配（B7/REG-04）。"""
    deps = _deps(demo_registry, _player())
    deps.settings = {"default_map": "town_center", "default_job_id": "forge"}
    ctx = _make_ctx(demo_registry, _player())
    ctx["settings"] = {"default_map": "town_center", "default_job_id": "forge"}
    d = register_commands.default_job(ctx)
    assert d is not None and d["id"] == "forge"


def test_default_job_unregistered_player(demo_registry: Registry) -> None:
    """未注册玩家（注册流程中）：default_job 仍可用（jobs 注册态无关注入）。"""
    ctx = _make_ctx(demo_registry, None)
    d = register_commands.default_job(ctx)
    assert d is not None
    assert d["id"] == "alchemy"


def test_default_job_missing_jobs_none() -> None:
    """无 jobs 表 → default_job None（调用方兜底「?」，不抛）。"""
    reg = _registry_with({}, {})
    ctx = _make_ctx(reg, None)
    assert register_commands.default_job(ctx) is None
    assert register_commands.resolve_job(ctx, "warrior") is None


# ---------------------------------------------------------------------------
# 5. 展示 / PVP 消费（回归）
# ---------------------------------------------------------------------------
def test_skill_rows_uses_ctx_skills(demo_ctx: dict) -> None:
    """/技能 列表 skill_rows：从 ctx["skills"] 生成（含 basic 普攻第 1 位）。"""
    rows = basic_commands.skill_rows(demo_ctx)
    assert isinstance(rows, list)
    assert rows, "skill_rows 应非空"
    assert rows[0] == "basic_attack"  # 6a §1.5 普攻固定第 1 位
    assert "power_strike" in rows


def test_pvp_resolve_skill_uses_ctx_skills(demo_ctx: dict) -> None:
    """/攻击玩家 技能序号：pvp_commands._resolve_skill 从 ctx["skills"] 解析。"""
    assert pvp_commands._resolve_skill(demo_ctx, "火球术") == "fireball"
    assert pvp_commands._resolve_skill(demo_ctx, "1") == list(demo_ctx["skills"].keys())[0]
    assert pvp_commands._resolve_skill(demo_ctx, "无此技能") is None


def test_core_pvp_skill_action(demo_ctx: dict) -> None:
    """core.pvp._resolve_skill_action：技能 id 命中 → skill 行动（非普攻兜底）。"""
    from qbot_rpg.core import pvp as core_pvp

    act = core_pvp._resolve_skill_action(demo_ctx, "power_strike", {})
    assert act == {"action": "skill", "skill_id": "power_strike", "target": "enemy"}
    act2 = core_pvp._resolve_skill_action(demo_ctx, "不存在", {})
    assert act2 == "normal"
