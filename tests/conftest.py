"""测试共享夹具（细化_5d §3.2 幂等原则：SQLite 一律 :memory: 或 tmp_path；零 NoneBot）。

- PACKS_DIR / PATCH3F_DIR：fixtures 路径
- make_player()：构造带全字段的 Player，供 storage round-trip / panel 渲染复用
- seed() / seeded_rng()：固定随机种子收敛源（细化_M6 测试体系强化 D6 §二 SED-1~8 / F-SED-01~03）
- formula_params()：formula.json 段级参数 → DamageFormulaParams（D6 §三 FIX-2 / F-FIX-01~27）
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Callable, Tuple, cast

import pytest

from qbot_rpg.core.damage import (
    BlockParams,
    CritMultUp,
    CritParams,
    CritTiers,
    DamageFormulaParams,
    DefenseParams,
    DerivedParams,
    HitParams,
    TypeAffinityParams,
    WeaknessParams,
)
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
# ---------------------------------------------------------------------------


def load_formula_params(path: Path) -> DamageFormulaParams:
    """formula.json 段级参数 → DamageFormulaParams（D6 FIX-2 读取器，F-FIX-01~27 映射）。

    - 段缺省回退：formula.json 缺某段/键 → 用 dataclass 默认值不抛错（D6 §3.4 边界异常）；
    - 数组形态（rng/tier_p）→ tuple；扁平对象（tiers/crit_mult_up/pierce_types/elements）→
      对应 frozen 子结构；
    - floor_mode/deep_floor 等纯配置字段不在 DamageFormulaParams 内，读取器不消费（D6 §3.4）。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    dmg, hit_seg, crit_seg, block_seg = (
        data.get(k) or {} for k in ("damage", "hit", "crit", "block")
    )
    defense_seg = data.get("defense") or {}
    weakness_seg = data.get("weakness") or {}
    ta_seg = data.get("type_affinity") or {}
    derived_seg = data.get("derived") or {}
    base = DamageFormulaParams()  # 段缺省回退默认源（dataclass 默认 = F-FIX 表默认）

    def _f(seg: dict, key: str, default):
        v = seg.get(key)
        return default if v is None else v

    tiers = crit_seg.get("tiers") or {}
    mult_up = crit_seg.get("crit_mult_up") or {}
    return DamageFormulaParams(
        base_attack_mult=float(_f(dmg, "base_attack_mult", base.base_attack_mult)),  # F-FIX-01
        rng=cast(Tuple[float, float], tuple(float(x) for x in _f(dmg, "rng", base.rng))),  # F-FIX-02
        hit=HitParams(
            k=float(_f(hit_seg, "k", base.hit.k)),  # F-FIX-03
            cap_min=float(_f(hit_seg, "cap_min", base.hit.cap_min)),  # F-FIX-04
            cap_max=float(_f(hit_seg, "cap_max", base.hit.cap_max)),  # F-FIX-05
        ),
        crit=CritParams(
            p_coef=float(_f(crit_seg, "p_coef", base.crit.p_coef)),  # F-FIX-06
            cap=float(_f(crit_seg, "cap", base.crit.cap)),  # F-FIX-07
            tiers=CritTiers(
                high=float(_f(tiers, "high", base.crit.tiers.high)),  # F-FIX-08
                mid=float(_f(tiers, "mid", base.crit.tiers.mid)),
                low=float(_f(tiers, "low", base.crit.tiers.low)),
            ),
            tier_p=cast(Tuple[int, int], tuple(int(x) for x in _f(crit_seg, "tier_p", base.crit.tier_p))),  # F-FIX-09
            crit_mult_up=CritMultUp(
                lv1=float(_f(mult_up, "lv1", base.crit.crit_mult_up.lv1)),  # F-FIX-10
                lv2=float(_f(mult_up, "lv2", base.crit.crit_mult_up.lv2)),
                lv3=float(_f(mult_up, "lv3", base.crit.crit_mult_up.lv3)),
            ),
        ),
        block=BlockParams(
            k=float(_f(block_seg, "k", base.block.k)),  # F-FIX-11
            cap=float(_f(block_seg, "cap", base.block.cap)),  # F-FIX-12
            magic_ignores=bool(_f(block_seg, "magic_ignores", base.block.magic_ignores)),  # F-FIX-13
            halve_after_block=bool(  # F-FIX-14
                _f(block_seg, "halve_after_block", base.block.halve_after_block)
            ),
        ),
        defense=DefenseParams(
            mode=str(_f(defense_seg, "mode", base.defense.mode)),  # F-FIX-15
            k=float(_f(defense_seg, "k", base.defense.k)),  # F-FIX-16
            pierce_types=dict(  # F-FIX-17
                _f(defense_seg, "pierce_types", base.defense.pierce_types)
            ),
        ),
        weakness=WeaknessParams(
            type_mult=float(_f(weakness_seg, "type_mult", base.weakness.type_mult)),  # F-FIX-18
            element_mult=float(  # F-FIX-19
                _f(weakness_seg, "element_mult", base.weakness.element_mult)
            ),
        ),
        type_affinity=TypeAffinityParams(
            enabled=bool(_f(ta_seg, "enabled", base.type_affinity.enabled)),  # F-FIX-20
            blunt_pierce=float(_f(ta_seg, "blunt_pierce", base.type_affinity.blunt_pierce)),  # F-FIX-21
            thrust_hit=float(_f(ta_seg, "thrust_hit", base.type_affinity.thrust_hit)),  # F-FIX-22
            slash_crit=float(_f(ta_seg, "slash_crit", base.type_affinity.slash_crit)),  # F-FIX-23
            magic_ignore_block=bool(  # F-FIX-24
                _f(ta_seg, "magic_ignore_block", base.type_affinity.magic_ignore_block)
            ),
        ),
        derived=DerivedParams(  # F-FIX-25
            max_total_mult=float(_f(derived_seg, "max_total_mult", base.derived.max_total_mult))
        ),
        monster_def_rate=float(_f(data, "monster_def_rate", base.monster_def_rate)),  # F-FIX-26
        elements=dict(_f(data, "elements", base.elements)),  # F-FIX-27
    )


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