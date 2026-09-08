"""方位战斗系统 Step 5：battle_resources + 熟练度乘区验收测试。

依据：docs/方位战斗系统_框架改造草案.md（v0.6 技术定稿）：
  - §三.7 BattleResourceState（battle_resources.materials 冻结容器 +
    battle_alchemy_used 段内统一）
  - 修正 #8/#9（熟练度乘区 alchemy_proficiency_mult 走 settings
    战斗即时调合.proficiency_multiplier {min,max,curve}，勿硬编码 60-120；
    素材源=冻结容器，壳层 hook 绑容器不碰实时背包）
  - 附录 A Step 5：start() 冻结携带素材；count_item/remove_item hook 绑容器；
    alchemy_proficiency_mult settings 段（缺段=无乘区 1.0 零破坏）

铁律：零 NoneBot import；纯逻辑断言；确定性（QueueRNG + 固定 seed）。

验收覆盖：
  1. start() 冻结（config battle_materials → 快照容器深拷贝；缺省 {} 零变化；
     快照往返续战保持）
  2. 容器 hook（装配层闭包同构：count 查容器；remove 扣容器 + 同步扣背包防消耗丢失）
  3. 即时调合真实引擎链：carry_ok 读冻结容器；resolve 原子扣容器
  4. 熟练度乘区（缺段 1.0；{0.6,1.2} 线性：level0→0.6 / level3→0.9 / level6→1.2；
     非法配置防御；resolve 出参强度乘区生效）
  5. battle_alchemy_used 段内迁移（段内权威读优先、顶层兜底旧快照、写双落）
"""

from __future__ import annotations

from typing import Any, Dict, MutableMapping

import pytest

from qbot_rpg.core.alchemy_battle import BattleAlchemyEngine
from qbot_rpg.core.battle import BattleEngine

# 对齐 tests/unit/test_battle_engine.py 构造口径
PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80,
          "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40,
         "mag": 30, "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30,
         "agi": 40, "spr": 40, "lck": 10, "elem_atk": 0, "name": "E"}
SEQ = [0.5, 0.5, 0.5, 1.0]


class QueueRNG:
    """确定性随机源（对齐 test_battle_engine.QueueRNG）。"""

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def make(**kw) -> BattleEngine:
    eng = BattleEngine(**kw)
    eng._rng = QueueRNG(SEQ)  # type: ignore[assignment]  # 确定性随机源注入
    return eng


def _materials(eng: BattleEngine) -> dict:
    br = eng._snap.get("battle_resources") or {}
    m = br.get("materials")
    return m if isinstance(m, dict) else {}


# =====================================================================================
# 1. start() 冻结：config battle_materials → 快照容器（深拷贝/缺省/快照往返）
# =====================================================================================


class TestFreeze:
    def test_start_freezes_materials_from_config(self) -> None:
        """start(config battle_materials) → 快照容器冻结副本。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11,
                           config={"battle_materials": {"herb": 3, "iron": 5}})
        assert _materials(eng) == {"herb": 3, "iron": 5}

    def test_frozen_copy_immune_to_external_mutation(self) -> None:
        """深拷贝冻结：外部源后续改动不侵快照（快照=唯一权威）。"""
        src = {"herb": 3}
        eng = make().start(PLAYER, ENEMY, random_seed=11,
                           config={"battle_materials": src})
        src["herb"] = 99
        assert _materials(eng) == {"herb": 3}

    def test_no_config_empty_zero_change(self) -> None:
        """无 battle_materials 配置 → 容器空（既有战斗零变化）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        assert _materials(eng) == {}

    def test_snapshot_roundtrip_keeps_materials(self) -> None:
        """快照往返（中断续战）：to_snapshot → from_snapshot 素材容器保持（不重冻）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11,
                           config={"battle_materials": {"herb": 3, "iron": 5}})
        snap = eng.to_snapshot()
        eng2 = BattleEngine.from_snapshot(snap)
        assert _materials(eng2) == {"herb": 3, "iron": 5}


# =====================================================================================
# 2. 容器 hook（装配层闭包同构：count 查容器；remove 扣容器 + 同步扣背包）
# =====================================================================================


class TestContainerHooks:
    def _wiring(self, eng: BattleEngine, bag: MutableMapping[str, int]):
        """context.py 战斗接线闭包同构（独立复刻：读容器/扣容器+背包同步）。"""
        mat = _materials(eng)

        def orig_remove(iid: str, cnt: int = 1) -> bool:
            cur = int(bag.get(iid, 0))
            if cur < cnt:
                return False
            if cur == cnt:
                bag.pop(iid, None)
            else:
                bag[iid] = cur - cnt
            return True

        def count(iid: str) -> int:
            return max(0, int(mat.get(str(iid), 0)))

        def remove(iid: str, cnt: int = 1) -> bool:
            cur = count(iid)
            if cur < cnt:
                return False
            key = str(iid)
            if cur == cnt:
                mat.pop(key, None)
            else:
                mat[key] = cur - cnt
            return orig_remove(key, cnt)

        return count, remove

    def test_count_reads_container_only(self) -> None:
        """count_item 查冻结容器（非携带素材=0——携带集由冻结时定）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11,
                           config={"battle_materials": {"herb": 3}})
        count, _ = self._wiring(eng, {})
        assert count("herb") == 3
        assert count("iron") == 0

    def test_remove_deducts_container_and_bag(self) -> None:
        """扣减：容器（权威）扣 + 实时背包同步扣（防消耗丢失，账实一致）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11,
                           config={"battle_materials": {"herb": 3}})
        bag: MutableMapping[str, int] = {"herb": 3}
        _, remove = self._wiring(eng, bag)
        assert remove("herb", 2) is True
        assert _materials(eng) == {"herb": 1}
        assert bag == {"herb": 1}
        assert remove("herb", 5) is False      # 超量拒（容器只剩 1）
        assert _materials(eng) == {"herb": 1}  # 零副作用

    def test_battle_ctx_engine_snapshot_is_authority(self) -> None:
        """装配层接入点：ctx 战斗引擎恢复后 _snap.battle_resources.materials 即容器。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11,
                           config={"battle_materials": {"herb": 2}})
        # 模拟战斗 ctx 装配（context.py 接线）：ctx["battle_snapshot"] = 引擎 _snap
        ctx: Dict[str, Any] = {"battle_snapshot": eng._snap}
        assert ctx["battle_snapshot"]["battle_resources"]["materials"]["herb"] == 2


# =====================================================================================
# 3. 即时调合真实引擎链：carry 读冻结容器 / resolve 原子扣容器
# =====================================================================================

RECIPE_FLAME = {"id": "flame_bomb", "name": "火焰弹", "skill": 50, "cooldown": 3,
                "materials": [{"id": "ember_crystal", "count": 1}]}


def _alchemy_ctx(eng: BattleEngine, bag: MutableMapping[str, int],
                 settings: Any = None, player: Any = None) -> dict:
    """战斗 ctx 鸭子（容器 hook 绑 battle_resources.materials；背包=bag 兜底）。"""
    mat = _materials(eng)

    def count(iid: str) -> int:
        return max(0, int(mat.get(str(iid), 0)))

    def remove(iid: str, cnt: int = 1) -> bool:
        cur = count(iid)
        if cur < cnt:
            return False
        key = str(iid)
        if cur == cnt:
            mat.pop(key, None)
        else:
            mat[key] = cur - cnt
        bcur = int(bag.get(key, 0))
        if bcur >= cnt:
            if bcur == cnt:
                bag.pop(key, None)
            else:
                bag[key] = bcur - cnt
        return True

    p = player if player is not None else {
        "proficiency": {"alchemy": {"level": 4, "exp": 0}}}

    def add(iid: str, cnt: int = 1, bound: bool = False, **kw: Any) -> dict:
        return {"ok": True, "added": cnt}

    return {"count_item": count, "remove_item": remove,
            "add_item": add,
            "currencies": {"gem": 10}, "player": p,
            "battle_snapshot": eng._snap}


class TestInstantWithContainer:
    def test_carry_ok_reads_frozen_container(self) -> None:
        """carry_ok（GU-53）：配方素材查询走冻结容器——容器有则过、无则全拒+差异。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11,
                           config={"battle_materials": {"ember_crystal": 2}})
        aeng = BattleAlchemyEngine(settings={})
        ok = aeng.carry_ok(_alchemy_ctx(eng, {"ember_crystal": 2}), RECIPE_FLAME)
        assert ok.get("ok") is True
        eng2 = make().start(PLAYER, ENEMY, random_seed=11)
        bad = aeng.carry_ok(_alchemy_ctx(eng2, {}), RECIPE_FLAME)
        assert bad.get("ok") is False and bad.get("reason") == "materials_insufficient"

    def test_resolve_deducts_container_not_bag_source(self) -> None:
        """resolve 原子扣减走容器 hook（扣容器 + 背包同步）；背包源不被二次扣。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11,
                           config={"battle_materials": {"ember_crystal": 2}})
        bag: MutableMapping[str, int] = {"ember_crystal": 2}
        aeng = BattleAlchemyEngine(settings={})
        r = aeng.resolve(_alchemy_ctx(eng, bag), RECIPE_FLAME,
                         battle_alchemy_used=0, cooldown=3, use_fn=None)
        assert r.get("ok") is True
        assert _materials(eng) == {"ember_crystal": 1}   # 容器扣 1（权威）
        assert bag == {"ember_crystal": 1}               # 背包同步扣 1（不二次）
        assert r["produced"]["item_id"] == "flame_bomb"

    def test_used_written_to_section_and_top(self) -> None:
        """resolve 后 battle_alchemy_used 落段内（权威）+ 顶层同步镜像。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11,
                           config={"battle_materials": {"ember_crystal": 2}})
        aeng = BattleAlchemyEngine(settings={})
        r = aeng.resolve(_alchemy_ctx(eng, {"ember_crystal": 2}), RECIPE_FLAME,
                         battle_alchemy_used=0, cooldown=3, use_fn=None)
        assert r.get("battle_alchemy_used") == 1
        assert eng._snap["battle_resources"]["battle_alchemy_used"] == 1
        assert eng._snap["battle_alchemy_used"] == 1      # 顶层镜像


# =====================================================================================
# 4. 熟练度乘区（缺段 1.0 零破坏；{min,max} 线性；非法防御）
# =====================================================================================

PM_DEFAULT = {"min": 0.6, "max": 1.2, "curve": "linear"}


def _player_lv(lv: int) -> dict:
    return {"proficiency": {"alchemy": {"level": lv, "exp": 0}}}


class TestProficiencyMult:
    def _eng(self, pm: Any = None) -> BattleAlchemyEngine:
        ba: Dict[str, Any] = {"auto_use": True, "per_battle_limit": 1}
        if pm is not None:
            ba["proficiency_multiplier"] = pm
        return BattleAlchemyEngine(settings={"alchemy": {"战斗即时调合": ba}})

    def test_no_config_mult_one(self) -> None:
        """settings 无 proficiency_multiplier 段 → 乘区 1.0（现状零破坏）。"""
        eng = BattleAlchemyEngine(settings={})
        assert eng.proficiency_mult(_player_lv(4)) == 1.0

    def test_linear_bounds(self) -> None:
        """{0.6,1.2} 线性：level0→0.6（下限）、level6→1.2（上限，王）。"""
        eng = self._eng(PM_DEFAULT)
        assert eng.proficiency_mult(_player_lv(0)) == pytest.approx(0.6)
        assert eng.proficiency_mult(_player_lv(6)) == pytest.approx(1.2)
        assert eng.proficiency_mult(_player_lv(3)) == pytest.approx(0.9)
        assert eng.proficiency_mult(_player_lv(7)) == pytest.approx(1.2)  # 封顶

    def test_invalid_config_mult_one(self) -> None:
        """非法配置（min>max/非数值/非对象）→ 1.0 防御。"""
        eng = self._eng({"min": 1.5, "max": 0.5, "curve": "linear"})
        assert eng.proficiency_mult(_player_lv(4)) == 1.0
        eng2 = self._eng({"min": "x", "max": 1.2})
        assert eng2.proficiency_mult(_player_lv(4)) == 1.0
        eng3 = self._eng("bogus")
        assert eng3.proficiency_mult(_player_lv(4)) == 1.0

    def test_unknown_curve_falls_back_linear(self) -> None:
        """未知 curve → 回退 linear（N2 扩展曲线形态时改）。"""
        eng = self._eng({"min": 0.6, "max": 1.2, "curve": "sigmoid"})
        assert eng.proficiency_mult(_player_lv(3)) == pytest.approx(0.9)

    def test_resolve_intensity_applies_mult(self) -> None:
        """resolve 出参强度 = 公式强度 × 乘区（缺段不变、配置后生效）。"""
        # 无配置 → 110（零破坏）
        eng1 = make().start(PLAYER, ENEMY, random_seed=11,
                            config={"battle_materials": {"ember_crystal": 2}})
        a1 = BattleAlchemyEngine(settings={})
        r1 = a1.resolve(_alchemy_ctx(eng1, {"ember_crystal": 2}), RECIPE_FLAME,
                        battle_alchemy_used=0, cooldown=3, use_fn=None)
        assert r1["intensity"] == pytest.approx(50 * (1 + 0.4 * 3))  # 110.0
        # {0.6,1.2} + level 3（档 3/6 → 0.9）→ 99.0（独立引擎/容器防素材串扰）
        eng2 = make().start(PLAYER, ENEMY, random_seed=11,
                            config={"battle_materials": {"ember_crystal": 2}})
        a2 = self._eng(PM_DEFAULT)
        r2 = a2.resolve(_alchemy_ctx(eng2, {"ember_crystal": 2},
                                     player=_player_lv(3)), RECIPE_FLAME,
                        battle_alchemy_used=0, cooldown=3, use_fn=None)
        assert r2["intensity"] == pytest.approx(110.0 * 0.9)
        # 王级（level 6 → 1.2）→ 132.0
        eng3 = make().start(PLAYER, ENEMY, random_seed=11,
                            config={"battle_materials": {"ember_crystal": 2}})
        r3 = a2.resolve(_alchemy_ctx(eng3, {"ember_crystal": 2},
                                     player=_player_lv(6)), RECIPE_FLAME,
                        battle_alchemy_used=0, cooldown=3, use_fn=None)
        assert r3.get("ok") is True
        assert r3["intensity"] == pytest.approx(110.0 * 1.2)


# =====================================================================================
# 5. battle_alchemy_used 段内迁移（段内权威读优先 / 顶层兜底旧快照 / 双落写）
# =====================================================================================


class TestUsedMigration:
    def test_read_used_section_priority_then_top(self) -> None:
        """read_used：段内权威优先；旧快照（仅顶层）兜底。"""
        aeng = BattleAlchemyEngine(settings={})
        snap = {"battle_resources": {"battle_alchemy_used": 2}, "battle_alchemy_used": 5}
        assert aeng.read_used(snap) == 2
        old = {"battle_alchemy_used": 5}          # 旧快照 M8 形态
        assert aeng.read_used(old) == 5
        assert aeng.read_used({}) == 0

    def test_write_used_writes_both(self) -> None:
        """write_used：段内权威 + 顶层同步镜像。"""
        aeng = BattleAlchemyEngine(settings={})
        snap: MutableMapping[str, Any] = {}
        aeng.write_used(snap, 3)
        assert snap["battle_resources"]["battle_alchemy_used"] == 3
        assert snap["battle_alchemy_used"] == 3
        aeng.write_used(snap, 1)
        assert snap["battle_resources"]["battle_alchemy_used"] == 1
        assert snap["battle_alchemy_used"] == 1

    def test_engine_record_alchemy_used_section_authority(self) -> None:
        """BattleEngine.record_alchemy_used：段内权威 + 顶层镜像。"""
        eng = make().start(PLAYER, ENEMY, random_seed=11)
        assert eng.record_alchemy_used(1) == 1
        assert eng._snap["battle_resources"]["battle_alchemy_used"] == 1
        assert eng._snap["battle_alchemy_used"] == 1
        # 段内被外部改（旧快照顶层残留不一致场景）→ 段内优先累计
        eng._snap["battle_resources"]["battle_alchemy_used"] = 4
        eng._snap["battle_alchemy_used"] = 9
        assert eng.record_alchemy_used(1) == 5
