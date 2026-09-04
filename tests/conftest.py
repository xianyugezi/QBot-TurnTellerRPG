"""测试共享夹具（细化_5d §3.2 幂等原则：SQLite 一律 :memory: 或 tmp_path；零 NoneBot）。

- PACKS_DIR / PATCH3F_DIR：fixtures 路径
- make_player()：构造带全字段的 Player，供 storage round-trip / panel 渲染复用
- seed() / seeded_rng()：固定随机种子收敛源（细化_M6 测试体系强化 D6 §二 SED-1~8 / F-SED-01~03）
- formula_params()：formula.json 段级参数 → DamageFormulaParams（D6 §三 FIX-2 / F-FIX-01~27）
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Callable

import pytest

from qbot_rpg.core.damage import DamageFormulaParams
from qbot_rpg.data import EquipmentSlot, ItemInstance, Player, PlayerAttributes

TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
PACKS_DIR = FIXTURES_DIR / "packs"
PATCH3F_DIR = FIXTURES_DIR / "m0_3f_patch"

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
# M12.5 需求1 批C：读取器已提生产侧（qbot_rpg/content/formula_loader.py），
# 本模块保留同名函数薄包装 + fixture（生产/测试同一装配源）。
# ---------------------------------------------------------------------------


def load_formula_params(path: Path) -> DamageFormulaParams:
    """formula.json 段级参数 → DamageFormulaParams（D6 FIX-2 读取器，F-FIX-01~27 映射）。

    生产侧装配源：qbot_rpg.content.formula_loader（同源同实现）；本包装保留
    既有测试调用形态（fixture formula_params 等零改动）。
    """
    from qbot_rpg.content.formula_loader import load_formula_params_from_path

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