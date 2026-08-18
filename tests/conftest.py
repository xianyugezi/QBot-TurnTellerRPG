"""测试共享夹具（细化_5d §3.2 幂等原则：SQLite 一律 :memory: 或 tmp_path；零 NoneBot）。

- PACKS_DIR / PATCH3F_DIR：fixtures 路径
- make_player()：构造带全字段的 Player，供 storage round-trip / panel 渲染复用
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qbot_rpg.data import EquipmentSlot, ItemInstance, Player, PlayerAttributes

TESTS_DIR = Path(__file__).parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
PACKS_DIR = FIXTURES_DIR / "packs"
PATCH3F_DIR = FIXTURES_DIR / "m0_3f_patch"

# 细化_5d TC-5d-13：packs/ 有且仅有四件套
REQUIRED_PACKS: tuple[str, ...] = ("legal", "badref", "missing_mod", "old_schema")


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
