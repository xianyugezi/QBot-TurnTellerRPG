"""批83 · N2/N3/N5 收敛回归：`ItemInstance` 公共归一函数 + 两条链路共用。

依据 `/root/deliverables/手册剩余项_核清与口径.md` Q4（N2/N3 为**未被裁决接受**的真缺口）
与《手册·1》§3.1/§3.4：

  · N2 `/装备` dict→`ItemInstance` 归一丢 `effect_refs` 且写回背包；
  · N3 `stack_max` 在 runner / basic_commands **两条归一链路都丢**（回落默认 99）；
  · N5 两条内联归一（17/18 字段）与读档 codec（20/20）不一致。

修法 = 收敛为公共函数 `qbot_rpg/data/item.py::item_instance_from_mapping`（唯一源），
两条链路共用。本测试锁：① 公共函数 20/20 全字段无损；② `/装备` 适配层写回保留
`effect_refs` / `stack_max` / `cooldown_until`；③ 正常流程逐字段与读档 codec 一致。
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping

from qbot_rpg.commands.basic_commands import EquipmentEngineAdapter
from qbot_rpg.data.item import ItemInstance, item_instance_from_mapping
from qbot_rpg.storage.repository import _item_from_dict

# `ItemInstance` 全字段清单（新增字段必须同步进公共函数——本清单随之更新即可发现漏改）
_ALL_FIELDS = {f.name for f in dataclasses.fields(ItemInstance)}


class _FakeEngine:
    """只回绝的引擎替身：写回发生在 `equip()` 之前，故回绝也能验字段保留。"""

    def equip(self, player: Any, item: Any, slot: Any) -> dict:
        return {"ok": False, "reason": "fake-reject"}


def _full_instance() -> ItemInstance:
    return ItemInstance(
        item_id="hunter_blade", name="猎刃", count=1, quality="rare", bound=False,
        stack_max=1, slot="weapon", stats_bonus={"atk": 3.0, "hp": 5.0},
        traits=("sharp",), cooldown_until="2030-01-01T00:00:00Z", enhance_level=2,
        uid="u" * 32, affinities={"fire": 1.5}, set_affixes=("set_a",),
        passives=("p1",), quality_level=4, enhance_affixes=("ea1",), required_level=12,
        temper_alloc={"atk": 2}, effect_refs=("moon_bless", "frost_bite"),
    )


def _field(o: Any, key: str) -> Any:
    return o.get(key) if isinstance(o, Mapping) else getattr(o, key, None)


def test_common_normalize_roundtrip_all_fields() -> None:
    """公共归一函数：`asdict → normalize → asdict` **20/20 全字段**无损（N5 结构风险封堵）。"""
    inst = _full_instance()
    back = item_instance_from_mapping(dataclasses.asdict(inst))
    assert isinstance(back, ItemInstance)
    assert dataclasses.asdict(back) == dataclasses.asdict(inst)
    assert _ALL_FIELDS == set(dataclasses.asdict(back)), "字段清单漂移，请核对公共归一函数"


def test_common_normalize_matches_read_codec() -> None:
    """公共归一函数与读档 codec 对同一 dict 行**逐字段一致**（两条写链路 ≡ 读侧口径）。"""
    row = dataclasses.asdict(_full_instance())
    assert dataclasses.asdict(item_instance_from_mapping(row)) == \
        dataclasses.asdict(_item_from_dict(row))
    # 旧档缺键（最小行）→ 缺省口径一致
    legacy = {"item_id": "potion", "name": "药水", "count": 3,
              "quality": "normal", "bound": True, "uid": "u-legacy"}
    a = dataclasses.asdict(item_instance_from_mapping(legacy))
    b = dataclasses.asdict(_item_from_dict(legacy))
    assert a == b


def test_equip_path_preserves_effect_refs_and_stack_max() -> None:
    """N2/N3：dict 行经 `/装备` 适配层归一 + 写回背包后，`effect_refs` / `stack_max` 保留。"""
    row = dataclasses.asdict(ItemInstance(
        item_id="hunter_blade", name="猎刃", count=1, quality="rare", bound=False,
        stack_max=1, slot="weapon", effect_refs=("moon_bless", "frost_bite"),
        cooldown_until="2031-02-03T04:05:06Z"))
    ctx: dict = {"player": {"inventory": [row], "job_id": "warrior", "level": 10}}
    EquipmentEngineAdapter(engine=_FakeEngine()).equip_wear(1, ctx)
    after = ctx["player"]["inventory"][0]
    assert _field(after, "effect_refs") == ("moon_bless", "frost_bite")
    assert _field(after, "stack_max") == 1
    assert _field(after, "cooldown_until") == "2031-02-03T04:05:06Z"


def test_equip_path_normal_flow_unchanged() -> None:
    """零行为变化：无 `effect_refs`、`stack_max` 取默认的普通行，归一后与旧内联口径一致。"""
    row = {"item_id": "iron_sword", "name": "铁剑", "count": 1, "quality": "normal",
           "bound": False, "stack_max": 99, "slot": "weapon",
           "stats_bonus": {"atk": 2.0}, "traits": ["old"], "enhance_level": 1,
           "uid": "u" * 32, "affinities": {"ice": 1.0}, "set_affixes": ["s"],
           "passives": ["p"], "quality_level": 3, "enhance_affixes": ["e"],
           "required_level": 5, "temper_alloc": {"atk": 1}}
    expected = item_instance_from_mapping(row)
    ctx: dict = {"player": {"inventory": [dict(row)], "job_id": "warrior", "level": 10}}
    EquipmentEngineAdapter(engine=_FakeEngine()).equip_wear(1, ctx)
    after = ctx["player"]["inventory"][0]
    assert isinstance(after, ItemInstance)
    assert dataclasses.asdict(after) == dataclasses.asdict(expected)
