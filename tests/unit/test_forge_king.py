"""M9 锻造·批3·路3C：铸造王单元测试（tests/unit/test_forge_king.py）。

文件名：test_forge_king.py
创建时间：2026-08-30
作者：Hermes 子agent-3C（M9 锻造实现组批3·路3C：并发同仓，仅新建本文件 +
qbot_rpg/core/forge_king.py；不改动批0~批2 既有文件、不改 fixtures）

依据：docs/细化/细化_2c2d_锻造套装与客制.md §3.3（KF-01~03：图鉴全亮→铸造王 +
专属配方 king_only 节点 + 称号加成 + 群内展示；N-16 king_only 节点扩展）+
docs/细化/细化_2c5a_职业等级与SP.md §四 TTL-01~08（王称号按职业独立授予、与等级
解耦）+ docs/细化/细化_2c2b_锻造流程契约.md §4.4（查询口径=派生树全部节点 ∈
玩家已锻造集合）+ docs/m9_接口摸底.md §三/§四（codex weapon 分册 = equipment kind；
grant_king_title 铸造王称号已有引擎支持）。
测试目标：qbot_rpg.core.forge_king 全部 6 功能 + 与真实 forge.json 兼容。

覆盖矩阵：
  A codex_all_lit：全节点已锻→all_lit True（总数/已亮数）/ 缺一→False / 未锻→False /
    空树→total0 / codex weapon 分册旁路统计（无 registry → 各 0）
  B king_eligible：图鉴全亮→eligible；与等级解耦——等级到王但图鉴未亮→False；
    高等级+未亮→不授予（TC-20 反例同构）；has_title 回读
  C grant_forge_king：图鉴全亮→即时授「铸造王」（title id="forge"）；幂等；未全亮→
    reason codex_incomplete；与其他王并行（KF-03，TTL-01 不唯一）
  D king_only_nodes：合成树 king_only 节点列表（文件序）；真实 forge.json 无 king_only→[]
  E forge_king_eligible_check：king_only 节点无称号→拒绝 king_title_required（文案
    「未获铸造王」）；已获称号→放行；非 king_only→守卫不适用；三形态 node（id str/
    raw dict/ForgeNode）；未解析 id→不适用

铁律：零 NoneBot import；纯函数确定性；不写定时器/睡眠调用；不引入随机。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, Optional, cast

from qbot_rpg.content.forge_models import ForgeNode
from qbot_rpg.core.forge_king import (
    KING_TITLE_ID,
    codex_all_lit,
    forge_king_eligible_check,
    grant_forge_king,
    king_bonus,
    king_eligible,
    king_only_nodes,
)
from qbot_rpg.core.forge_tree import FORGE_JOB_ID, ForgeTreeEngine
from qbot_rpg.core.proficiency import ProficiencyEngine

# 仓库根 = tests/unit/test_forge_king.py 上溯两级
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORGE_JSON = _REPO_ROOT / "content" / "test_demo" / "forge.json"

# 真实 forge.json 武器树 9 节点（文件序）
_ALL_NODES = [
    "node_iron_sword", "node_iron_sword_1", "node_iron_sword_2",
    "node_flame_sword", "node_flame_sword_2", "node_flame_sword_3",
    "node_flame_king_sword", "node_ice_sword", "node_lightning_sword",
]

# 合成树：含 2 个 king_only 节点（KF-02 ① 专属配方示例）
_SYNTH_FORGE = {
    "trees": [
        {
            "id": "tree_king_test",
            "name": "铸造王测试树",
            "type": "weapon",
            "roots": ["n_root"],
            "nodes": [
                {"id": "n_root", "name": "基础剑", "level": 1, "parent": None},
                {"id": "n_adv", "name": "进阶剑", "level": 3, "parent": "n_root"},
                {"id": "n_king_a", "name": "王剑甲", "level": 7,
                 "parent": "n_adv", "king_only": True},
                {"id": "n_king_b", "name": "王剑乙", "level": 8,
                 "parent": "n_adv", "king_only": True},
                {"id": "n_common", "name": "普通剑", "level": 4, "parent": "n_root"},
            ],
        }
    ]
}


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _engine() -> ForgeTreeEngine:
    """真实 forge.json → ForgeTreeEngine（fixtures 只读消费，不改动）。"""
    forge = cast(Mapping, _load_json(_FORGE_JSON))
    return ForgeTreeEngine(forge=forge, items={}, settings={})


def _synth_engine() -> ForgeTreeEngine:
    """合成树 → ForgeTreeEngine（含 king_only 节点）。"""
    return ForgeTreeEngine(forge=cast(Mapping, _SYNTH_FORGE), items={}, settings={})


def _player(*, forged: object = None, forge_level: int = 0,
            owned: Optional[object] = None) -> Dict[str, object]:
    """构造玩家 dict（proficiency.forge.level + forged + title_state.owned 可配）。"""
    prof = {FORGE_JOB_ID: {"level": forge_level, "exp": 0}}
    p: Dict[str, object] = {"proficiency": prof, "forged": forged if forged is not None else []}
    if owned is not None:
        owned_list = list(owned) if isinstance(owned, (list, tuple, set)) else []
        p["title_state"] = {"owned": owned_list, "equipped": None}
    return p


def _ctx(*, player: object = None, engine: object = None,
         forge: object = None) -> Dict[str, object]:
    """构造 ctx（forge_tree 优先，回退 forge raw）。"""
    ctx: Dict[str, object] = {}
    if engine is not None:
        ctx["forge_tree"] = engine
    elif forge is not None:
        ctx["forge"] = forge
    if player is not None:
        ctx["player"] = player
    return ctx


def _owned(player: Mapping[str, object]) -> List[str]:
    """读取 title_state.owned 列表（Dict[str,object] 形态安全访问）。"""
    ts = player.get("title_state")
    if isinstance(ts, Mapping):
        owned = ts.get("owned")
        if isinstance(owned, (list, tuple, set)):
            return [str(x) for x in owned]
    return []


# ---------------------------------------------------------------------------
# A codex_all_lit：图鉴全亮判定（KF-01 / 2c2b §4.4）
# ---------------------------------------------------------------------------
def test_codex_all_lit_all_forged() -> None:
    """正例：全部派生树节点已锻 → all_lit True，lit_count==total==9。"""
    p = _player(forged=list(_ALL_NODES))
    r = codex_all_lit(_ctx(player=p, engine=_engine()))
    assert r["all_lit"] is True
    assert r["lit_count"] == 9
    assert r["total"] == 9
    for key in ("all_lit", "lit_count", "total", "codex"):
        assert key in r


def test_codex_all_lit_missing_one() -> None:
    """负例：缺一节点（雷剑）→ all_lit False，lit_count=8。"""
    p = _player(forged=[n for n in _ALL_NODES if n != "node_lightning_sword"])
    r = codex_all_lit(_ctx(player=p, engine=_engine()))
    assert r["all_lit"] is False
    assert r["lit_count"] == 8
    assert r["total"] == 9


def test_codex_all_lit_none_forged() -> None:
    """负例：未锻造任何节点 → all_lit False，lit_count=0。"""
    r = codex_all_lit(_ctx(player=_player(forged=[]), engine=_engine()))
    assert r["all_lit"] is False
    assert r["lit_count"] == 0
    assert r["total"] == 9


def test_codex_all_lit_no_tree() -> None:
    """fail-safe：ctx 无派生树 → total=0、all_lit False（codex 补白同构）。"""
    r = codex_all_lit(_ctx(player=_player(forged=list(_ALL_NODES))))
    assert r["all_lit"] is False
    assert r["total"] == 0
    assert r["lit_count"] == 0


def test_codex_all_lit_no_registry_codex_fail_safe() -> None:
    """codex weapon 分册旁路：无 registry → codex 各 0；forged 主判定不受影响。"""
    p = _player(forged=list(_ALL_NODES))
    r = codex_all_lit(_ctx(player=p, engine=_engine()))
    assert r["all_lit"] is True
    assert r["codex"] == {"total": 0, "seen": 0, "killed": 0, "pct": 0.0}


# ---------------------------------------------------------------------------
# B king_eligible：资格判定（KF-01 图鉴全亮 → eligible；与等级解耦）
# ---------------------------------------------------------------------------
def test_king_eligible_all_lit() -> None:
    """正例：图鉴全亮 → eligible True；has_title 初始 False。"""
    p = _player(forged=list(_ALL_NODES))
    r = king_eligible(p, _ctx(engine=_engine()))
    assert r["eligible"] is True
    assert r["all_lit"] is True
    assert r["has_title"] is False
    assert r["reason"] is None
    for key in ("eligible", "all_lit", "lit_count", "total", "has_title", "reason"):
        assert key in r


def test_king_eligible_incomplete() -> None:
    """负例：图鉴未全亮 → eligible False，reason codex_incomplete。"""
    p = _player(forged=[])
    r = king_eligible(p, _ctx(engine=_engine()))
    assert r["eligible"] is False
    assert r["reason"] == "codex_incomplete"


def test_king_eligible_decoupled_from_level() -> None:
    """等级解耦：等级到王（高等级）但图鉴未亮 → 不 eligible（KF-01/TTL-01，TC-20 反例
    同构）；等级低但图鉴全亮 → eligible。"""
    # 高等级 + 未全亮 → 不授（等级到王但图鉴未亮不授予）
    high = _player(forged=[], forge_level=60)
    assert king_eligible(high, _ctx(engine=_engine()))["eligible"] is False
    # 低等级 + 全亮 → 授（图鉴全亮与等级区间解耦）
    low = _player(forged=list(_ALL_NODES), forge_level=1)
    assert king_eligible(low, _ctx(engine=_engine()))["eligible"] is True


# ---------------------------------------------------------------------------
# C grant_forge_king：即时结算（KF-01 / TTL-01~03）
# ---------------------------------------------------------------------------
def test_grant_forge_king_grants() -> None:
    """正例：图鉴全亮 → 即时授予「铸造王」（title id=forge），进入可佩戴列表。"""
    p = _player(forged=list(_ALL_NODES))
    r = grant_forge_king(p, _ctx(engine=_engine()))
    assert r["ok"] is True
    assert r["granted"] is True
    assert r["title_id"] == KING_TITLE_ID == "forge"
    assert r["reason"] is None
    assert "forge" in _owned(p)
    for key in ("ok", "granted", "title_id", "reason", "all_lit", "lit_count", "total"):
        assert key in r


def test_grant_forge_king_idempotent() -> None:
    """幂等：已拥有铸造王 → 重复授予 granted=False，owned 不重复。"""
    p = _player(forged=list(_ALL_NODES))
    r1 = grant_forge_king(p, _ctx(engine=_engine()))
    assert r1["granted"] is True
    r2 = grant_forge_king(p, _ctx(engine=_engine()))
    assert r2["ok"] is True
    assert r2["granted"] is False
    assert _owned(p) == ["forge"]


def test_grant_forge_king_incomplete_reject() -> None:
    """负例：图鉴未全亮 → ok False，reason codex_incomplete，不落账。"""
    p = _player(forged=[])
    r = grant_forge_king(p, _ctx(engine=_engine()))
    assert r["ok"] is False
    assert r["reason"] == "codex_incomplete"
    assert "title_state" not in p


def test_grant_forge_king_parallel_with_other_king() -> None:
    """并行不唯一（KF-03/TTL-01）：先授炼金王，再授铸造王 → 并存互不覆盖。"""
    p = _player(forged=list(_ALL_NODES))
    # 其他王（炼金王）先行落账
    eng = ProficiencyEngine()
    assert eng.grant_king_title(p, "alchemy", codex_all_lit=True)["granted"] is True
    # 铸造王再授
    r = grant_forge_king(p, _ctx(engine=_engine()))
    assert r["granted"] is True
    assert set(_owned(p)) == {"alchemy", "forge"}


# ---------------------------------------------------------------------------
# D king_only_nodes：专属配方节点列表（KF-02 ① / N-16）
# ---------------------------------------------------------------------------
def test_king_only_nodes_synth() -> None:
    """正例：合成树 2 个 king_only 节点（文件序）；非 king_only 节点不返回。"""
    # ForgeTreeEngine 形态
    assert king_only_nodes(_synth_engine()) == ["n_king_a", "n_king_b"]
    # forge raw dict 形态
    assert king_only_nodes(_SYNTH_FORGE) == ["n_king_a", "n_king_b"]


def test_king_only_nodes_real_fixture_empty() -> None:
    """真实 forge.json 无 king_only 节点 → []（合法；守卫只在配置 king_only 时生效）。"""
    assert king_only_nodes(_engine()) == []


def test_king_only_nodes_empty() -> None:
    """入参 None / 空 dict → []（确定性兜底）。"""
    assert king_only_nodes(None) == []
    assert king_only_nodes({}) == []


# ---------------------------------------------------------------------------
# E forge_king_eligible_check：king_only 节点锻造守卫（KF-02 ①）
# ---------------------------------------------------------------------------
def test_guard_king_only_reject_without_title() -> None:
    """负例：锻造 king_only 节点但未获铸造王 → 拒绝 king_title_required，
    文案「未获铸造王」。"""
    p = _player()
    r = forge_king_eligible_check(p, _ctx(engine=_synth_engine()), "n_king_a")
    assert r["ok"] is False
    assert r["reason"] == "king_title_required"
    assert r["message"] == "未获铸造王"
    assert r["king_only"] is True
    assert r["has_title"] is False
    assert r["node_id"] == "n_king_a"


def test_guard_king_only_pass_with_title() -> None:
    """正例：已获铸造王 → 锻造 king_only 节点放行。"""
    p = _player(forged=list(_ALL_NODES), owned=["forge"])
    r = forge_king_eligible_check(p, _ctx(engine=_synth_engine()), "n_king_b")
    assert r["ok"] is True
    assert r["king_only"] is True
    assert r["has_title"] is True
    assert r["reason"] is None


def test_guard_non_king_only_pass() -> None:
    """非 king_only 节点 → 守卫不适用直接放行（无论是否有称号）。"""
    p_no_title = _player()
    r1 = forge_king_eligible_check(p_no_title, _ctx(engine=_synth_engine()), "n_root")
    assert r1["ok"] is True
    assert r1["king_only"] is False
    # 有称号同样放行
    p_has = _player(owned=["forge"])
    r2 = forge_king_eligible_check(p_has, _ctx(engine=_synth_engine()), "n_common")
    assert r2["ok"] is True
    assert r2["king_only"] is False


def test_guard_node_three_forms() -> None:
    """node 三形态：id str / raw dict / ForgeNode 判定一致（F-7）。"""
    p = _player()
    ctx = _ctx(engine=_synth_engine())
    # id str
    assert forge_king_eligible_check(p, ctx, "n_king_a")["ok"] is False
    # raw dict
    raw = _SYNTH_FORGE["trees"][0]["nodes"][2]  # n_king_a
    assert forge_king_eligible_check(p, ctx, raw)["ok"] is False
    # ForgeNode
    node = _synth_engine().node("n_king_a")
    assert isinstance(node, ForgeNode)
    assert forge_king_eligible_check(p, ctx, node)["ok"] is False
    # 非 king_only 三形态一致放行
    raw_common = _SYNTH_FORGE["trees"][0]["nodes"][4]  # n_common
    assert forge_king_eligible_check(p, ctx, "n_common")["ok"] is True
    assert forge_king_eligible_check(p, ctx, raw_common)["ok"] is True
    assert forge_king_eligible_check(p, ctx, _synth_engine().node("n_common"))["ok"] is True


def test_guard_unresolved_id_pass() -> None:
    """未解析节点 id（树中不存在）→ 守卫不适用放行（存在性由 forge_guard GU-03 另判）。"""
    p = _player()
    r = forge_king_eligible_check(p, _ctx(engine=_synth_engine()), "node_nonexistent")
    assert r["ok"] is True
    assert r["king_only"] is False


# ---------------------------------------------------------------------------
# F king_bonus：称号加成（KF-02 ② 全属性+X% 可配；进 4b 加成层 pct）
# ---------------------------------------------------------------------------
def test_king_bonus_default() -> None:
    """缺省：settings 无配置 → 全属性+5%（percent=5、pct=0.05、enabled）。"""
    r = king_bonus({})
    assert r["percent"] == 5.0
    assert r["pct"] == 0.05
    assert r["enabled"] is True
    assert r["key"] == "king_bonus_pct"


def test_king_bonus_configured() -> None:
    """可配：settings.forge.king_bonus_pct=10 → percent=10、pct=0.10。"""
    r = king_bonus({"forge": {"king_bonus_pct": 10}})
    assert r["percent"] == 10.0
    assert r["pct"] == 0.10
    # forge 段本身形态
    r2 = king_bonus({"king_bonus_pct": 7})
    assert r2["percent"] == 7.0
    assert r2["pct"] == 0.07


def test_king_bonus_invalid_and_zero() -> None:
    """非法/负数 → 兜底与钳制：字符串数字解析；负数钳 0（enabled False）；None → 缺省。"""
    assert king_bonus({"forge": {"king_bonus_pct": "3"}})["percent"] == 3.0
    assert king_bonus({"forge": {"king_bonus_pct": 0}})["enabled"] is False
    assert king_bonus({"forge": {"king_bonus_pct": -2}})["pct"] == 0.0
    assert king_bonus({"forge": {"king_bonus_pct": None}})["percent"] == 5.0
    assert king_bonus(None)["percent"] == 5.0
