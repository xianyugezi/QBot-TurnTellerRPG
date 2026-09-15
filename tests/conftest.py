"""测试共享夹具（细化_5d §3.2 幂等原则：SQLite 一律 :memory: 或 tmp_path；零 NoneBot）。

- PACKS_DIR / PATCH3F_DIR：fixtures 路径
- make_player()：构造带全字段的 Player，供 storage round-trip / panel 渲染复用
- seed() / seeded_rng()：固定随机种子收敛源（细化_M6 测试体系强化 D6 §二 SED-1~8 / F-SED-01~03）
- formula_params()：formula.json 段级参数 → DamageFormulaParams（D6 §三 FIX-2 / F-FIX-01~27）
- content 防污染门禁（批19.1）：会话级 autouse 守卫，测试不得写真实内容包 content/
"""
from __future__ import annotations

import hashlib
import os
import random
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import pytest

from qbot_rpg.core.damage import DamageFormulaParams
from qbot_rpg.data import EquipmentSlot, ItemInstance, Player, PlayerAttributes

TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
PACKS_DIR = FIXTURES_DIR / "packs"
PATCH3F_DIR = FIXTURES_DIR / "m0_3f_patch"

# ===========================================================================
# 批19.1 · 内容包防污染门禁（会话级 autouse，默认禁止测试写真实 content/）
# ===========================================================================
# 背景：编辑器「启用模块 / 保存条目 / 回退」等写链路若误用仓库根内容根目录
# （`api.content_root(None)` 默认 = <仓库根>/content），会把真实内容包改脏，
# 并连带造成只读用例失败（批19 实测：veinborn manifest 多出 fishing/farming +
# 两个新数据文件）。本守卫在会话开始 / 结束各做一次内容快照，任何新增、删除、
# 内容变化都会让测试会话失败，并列出被改文件与疑似来源用例。
#
# 口径：
#   · 只对**仓库内真实 content/**（Path(__file__).parents[1] / "content"）生效；
#     tmp_path / 任意临时内容根一律不管（测试想在临时包里怎么写真都行）。
#   · 逐用例滚动快照用于定位「哪个测试写的」（mtime/size，便宜）；
#     会话首尾 sha256 快照用于权威判定（防 mtime 同秒 / 大小相同漏判）。
#   · 会话首快照在 pytest_sessionstart 采集，覆盖 collection/import 期的写盘。
#   · 显式豁免：环境变量 QBT_ALLOW_CONTENT_WRITES=1（整会话 opt-out，默认禁止）；
#     一经设置会在会话首打印醒目提示，且不参与判定。
#
# 迁移指引：需要「写包」的用例应把目标包 copytree 到 tmp_path，或把 root 指向
# 临时内容根（既有用例普遍如此）；不得对真实 content/ 落盘。
_CONTENT_ROOT = TESTS_DIR.parent / "content"
_GUARD_OPT_OUT_ENV = "QBT_ALLOW_CONTENT_WRITES"

_GUARD: Dict[str, object] = {
    "active": False,
    "start_sha": {},       # 相对路径 -> sha256（会话首，权威）
    "rolling_stat": {},    # 相对路径 -> (size, mtime_ns)（逐用例滚动，定位来源）
    "suspects": [],        # [(nodeid, [变化描述...])]
    "opt_out": False,
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _content_sha_snapshot() -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not _CONTENT_ROOT.is_dir():
        return out
    for p in sorted(_CONTENT_ROOT.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(_CONTENT_ROOT))] = _sha256_file(p)
    return out


def _content_stat_snapshot() -> Dict[str, Tuple[int, int]]:
    out: Dict[str, Tuple[int, int]] = {}
    if not _CONTENT_ROOT.is_dir():
        return out
    for p in _CONTENT_ROOT.rglob("*"):
        if p.is_file():
            try:
                st = p.stat()
            except OSError:  # 竞态删除：下次快照自然反映
                continue
            out[str(p.relative_to(_CONTENT_ROOT))] = (st.st_size, st.st_mtime_ns)
    return out


def _diff_snapshots(before: Dict[str, object], after: Dict[str, object]
                    ) -> Tuple[List[str], List[str], List[str]]:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return added, removed, changed


def _describe(before: Dict[str, object], after: Dict[str, object]) -> List[str]:
    added, removed, changed = _diff_snapshots(before, after)
    lines: List[str] = []
    lines += [f"+ content/{p}（新增）" for p in added]
    lines += [f"- content/{p}（删除）" for p in removed]
    lines += [f"~ content/{p}（内容变化）" for p in changed]
    return lines


def _pollution_message() -> str:
    start = _GUARD["start_sha"]
    assert isinstance(start, dict)
    final = _content_sha_snapshot()
    added, removed, changed = _diff_snapshots(start, final)
    lines = [
        "",
        "=" * 78,
        "[防污染门禁] 测试会话改动了真实内容包 content/ —— 判定失败。",
        "测试不得写真实内容包：请在 tmp_path 副本 / 临时内容根上操作，"
        "禁止对 content/ 落盘。",
        f"  新增 {len(added)} / 删除 {len(removed)} / 修改 {len(changed)}",
    ]
    lines += [f"    + content/{p}" for p in added]
    lines += [f"    - content/{p}" for p in removed]
    lines += [f"    ~ content/{p}" for p in changed]
    suspects = _GUARD["suspects"]
    if suspects:
        lines.append("疑似来源（逐用例滚动快照定位）：")
        for nodeid, descs in suspects:  # type: ignore[misc]
            lines.append(f"    · {nodeid}")
            lines += [f"        {d}" for d in descs]
    else:
        lines.append("疑似来源：未能逐用例定位"
                     "（可能发生在 collection/import 期或最后一个用例的 teardown）。")
    lines.append("如确需写真实内容包：设置 QBT_ALLOW_CONTENT_WRITES=1 显式豁免"
                 "（默认禁止，且需在批次报告说明）。")
    lines.append("=" * 78)
    return "\n".join(lines)


def pytest_sessionstart(session: pytest.Session) -> None:  # noqa: ARG001
    """会话首采集内容快照（早于 collection / import，覆盖 import 期写盘）。"""
    if os.environ.get(_GUARD_OPT_OUT_ENV):
        _GUARD["opt_out"] = True
        print(f"\n[防污染门禁] 已通过 {_GUARD_OPT_OUT_ENV} 显式豁免"
              "（默认禁止测试写真实内容包）。")
        return
    _GUARD["start_sha"] = _content_sha_snapshot()
    _GUARD["rolling_stat"] = _content_stat_snapshot()
    _GUARD["active"] = True


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """逐用例滚动比对（定位来源；不判定失败，判定归会话级守卫）。

    在 `call` 阶段后立即比对（此刻用例主体已执行、会话级 fixture 尚未收尾，
    能拿到正确的 nodeid）；`teardown` 阶段再补一次以覆盖 fixture 收尾写盘。
    """
    if not _GUARD["active"] or report.when not in ("call", "teardown"):
        return
    before = _GUARD["rolling_stat"]
    assert isinstance(before, dict)
    after = _content_stat_snapshot()
    descs = _describe(before, after)
    if descs:
        suspects = _GUARD["suspects"]
        assert isinstance(suspects, list)
        suspects.append((report.nodeid, descs))
        _GUARD["rolling_stat"] = after


@pytest.fixture(scope="session", autouse=True)
def _content_pollution_guard() -> object:
    """会话级 autouse 守卫：会话结束比对 content/ 快照，被改则判定失败。"""
    yield
    if not _GUARD["active"]:
        return
    start = _GUARD["start_sha"]
    assert isinstance(start, dict)
    final = _content_sha_snapshot()
    added, removed, changed = _diff_snapshots(start, final)
    if added or removed or changed:
        pytest.fail(_pollution_message(), pytrace=False)

# 细化_5d TC-5d-13：packs/ 有且仅有四件套
REQUIRED_PACKS: tuple[str, ...] = ("legal", "badref", "missing_mod", "old_schema")

# D6 F-SED-01【工程补白】收敛值：全仓测试随机种子唯一收敛源（对齐 test_monster_ai
# 现用 20260826，迁移后原数值不漂移）；变更种子只改此处（D6 SED-6 一处生效）。
DEFAULT_SEED = 20260826


@pytest.fixture(scope="session")
def packs_dir() -> Path:
    return PACKS_DIR


@pytest.fixture(scope="session")
def legal_pack_dir() -> Path:
    return PACKS_DIR / "legal"


@pytest.fixture(scope="session")
def badref_pack_dir() -> Path:
    return PACKS_DIR / "badref"


@pytest.fixture(scope="session")
def missing_mod_pack_dir() -> Path:
    return PACKS_DIR / "missing_mod"


@pytest.fixture(scope="session")
def old_schema_pack_dir() -> Path:
    return PACKS_DIR / "old_schema"


@pytest.fixture(scope="session")
def patch3f_dir() -> Path:
    return PATCH3F_DIR


# ---------------------------------------------------------------------------
# SED：固定随机种子 fixture（细化_M6 测试体系强化 D6 §二 SED-1 / F-SED-01~03）
# ---------------------------------------------------------------------------


@pytest.fixture
def seed() -> int:
    """统一收敛默认随机种子（D6 F-SED-01：默认 20260826）。

    变更随机种子的唯一入口 = 改 DEFAULT_SEED（或用例参数化 seed 值），全仓同步换种
    （D6 SED-6 一处生效）。
    """
    return DEFAULT_SEED


@pytest.fixture
def seeded_rng(seed: int) -> Callable[[int], random.Random]:
    """可复现 RNG 工厂（D6 F-SED-02/03 + §2.5 派生种子边界）。

    seeded_rng() → random.Random(seed)；seeded_rng(offset) → random.Random(seed + offset)
    （同一用例多独立 RNG 时派生形，保持同 seed 可复现）。function 级作用域，
    每调用独立实例（防跨用例 RNG 状态串扰，D6 F-SED-03）。
    """

    def _make(offset: int = 0) -> random.Random:
        return random.Random(seed + offset)

    return _make


# ---------------------------------------------------------------------------
# FIX：formula.json 段级参数 → DamageFormulaParams 读取器（D6 §三 FIX-2 / F-FIX-01~27）
# M12.5 需求1 批C：读取器已提生产侧（qbot_rpg/core/formula_loader.py），
# 本模块保留同名函数薄包装 + fixture（生产/测试同一装配源）。
# ---------------------------------------------------------------------------


def load_formula_params(path: Path) -> DamageFormulaParams:
    """formula.json 段级参数 → DamageFormulaParams（D6 FIX-2 读取器，F-FIX-01~27 映射）。

    生产侧装配源：qbot_rpg.core.formula_loader（同源同实现）；本包装保留
    既有测试调用形态（fixture formula_params 等零改动）。
    """
    from qbot_rpg.core.formula_loader import load_formula_params_from_path

    return load_formula_params_from_path(path)


@pytest.fixture(scope="session")
def formula_params(legal_pack_dir: Path) -> DamageFormulaParams:
    """formula.json 段级参数 → DamageFormulaParams（D6 FIX-2 读取器注入）。

    测试公式参数（hit/crit/block/defense/weakness/derived/rng/monster_def_rate）一律经
    本 fixture 注入（D6 FIX-3 / 细化_5d TC-5d-05：禁测试内硬编码生产参数；
    本读取器是唯一允许的参数常量落点）。frozen dataclass → session 级安全。
    """
    return load_formula_params(legal_pack_dir / "formula.json")


def make_player(qid: str = "123456789", name: str = "阿伟") -> Player:
    """全字段 Player（细化_4a#TC-12 round-trip / 细化_3d panel 渲染基准）。"""
    attrs = PlayerAttributes(
        base={"hp": 100.0, "mp": 50.0, "str": 15.0, "lck": 10.0},
        bonus={"flat": {"str": 5.0}, "pct": {"hp": 10.0}},
        temp={"pct": {"atk": 20.0}, "flat": {"atk": 3.0}},
        cond={"str": 2.0},
    )
    inv = (
        ItemInstance(item_id="potion", name="药水", count=5, quality="normal", bound=False),
        ItemInstance(item_id="iron_sword", name="铁剑", count=1, quality="rare",
                     bound=True, slot="weapon", stats_bonus={"atk": 5.0},
                     traits=("锋利",), cooldown_until=None),
    )
    return Player(
        qid=qid,
        name=name,
        job_id="warrior",
        level=35,
        exp=1200,
        hp=220,
        mp=60,
        currencies={"gold": 350, "gem": 8},
        inventory=inv,
        equipment={
            "weapon": EquipmentSlot(
                item_id="iron_sword", name="铁剑", slot_level=3, locked=True, gems=("ruby",),
            )
        },
        attributes=attrs,
        achievement_state=("ach_first_blood",),
        title_state={"current": "斩龙者"},
        persistent_state={"checkin_count": 3},
        longline_counters={"battle_wins": 12},
        reputation_state={"commercial": 2},
        codex_state={"monster": {"slime": {"unlocked": True}}},
        content_pack_id="legal",
        content_pack_version="1.0.0",
        schema_version=4,
        last_seen_group="10001",
        created_at="2026-08-01T00:00:00Z",
        last_active_at="2026-08-18T12:00:00Z",
    )


@pytest.fixture
def player() -> Player:
    return make_player()