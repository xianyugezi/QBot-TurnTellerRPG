"""M9 锻造·套装档位激活结算（qbot_rpg/core/forge_set_skills.py）——ACT-01~06 执行层。

文件名：qbot_rpg/core/forge_set_skills.py
创建时间：2026-09-14
作者：dsh（用户拍板 2026-09-14「套装档位这个功能要做」：补 forge_sets.py 边界声明中
  「套装技能激活/结算执行归后续」的 ACT-01~06 执行段；只做激活结算 + 指令渲染，
  编辑器套装页见 2c2d §1.6 另批）

功能描述：套装档位激活结算（2c2d §1.3 ACT-01~06 执行层，纯函数零副作用）：
  1) resolve_piece_counts(piece_counts)  档位集合归一：None → SET_PIECE_COUNTS 缺省
     {2,3,5}；传入 modules（含 settings）→ 读 settings.forge.set_piece_counts；传入
     int 列表 → 清洗去重升序。实现委托 forge_sets.resolve_piece_counts（F-8 单一来源）。
  2) family_piece_counts(player, sets)  族级件数（ACT-01）：set_tracker 优先（4b EQP-03），
     回退装配节点集 ∩ 同族 pieces 并集（VAR-03 α/β 混穿合并计数）——复用既有
     _set_tracker / _equipped_node_ids 口径，不得另造第二套。
  3) resolve_set_skills(player, sets, *, piece_counts=None)  技能 id → 等级（1/2/3）：
     ACT-02 取该 skill 全部档位中 piece_count ≤ N 的最大档 → 对应 level；
     N < min(配置档位集合) 不激活（forge_sets.min_activate_pieces，与 set_lookup.ready 同源）；
     ACT-03 无 4 件档（穿 4 件取 3 件档）；ACT-04 同套装多技能各自判定并行、同一 skill
     多档命中只取最高档不叠加。档位集合经 resolve_piece_counts（缺省 {2,3,5}）。
  4) recompute_set_tracker(player, sets)  穿/脱/换装重算（ACT-05）：重算族级件数写回
     player["set_tracker"]；返回重算结果。
  5) sync_set_skills(player, sets, *, piece_counts=None)  重算 + 结算一步到位：写
     player["set_tracker"] + player["set_skills"]（技能 id → 等级），返回技能等级表；
     该表经 skill_slots_battle 并入战斗可用技能集（生效接入唯一路径）。
  6) is_set_frozen(player)  战斗冻结判定（ACT-05 / 4b EQP-R06）：player["in_battle"]
     is True → 套装状态冻结。

【冻结点 · 必须写明】ACT-05（2c2d §1.3）：战斗内不可穿脱（4b EQP-R06，与珠「战前
  准备」同构）→ **战斗内套装状态冻结**。落地点：recompute_set_tracker 在
  player["in_battle"] is True 时**直接返回既有 set_tracker、不重算不写回**；sync_set_skills
  因此在战斗内返回冻结前的技能等级表（逐动一致）。战斗内穿脱入口（equipment.EquipmentEngine
  equip/unequip EQP-09）本身已拒绝，本层是第二道保险。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 P-x；不新增定稿外行为）：
  P-1  档位集合注入：resolve_set_skills 只接收显式 piece_counts（None → SET_PIECE_COUNTS
       {2,3,5}）；配置化由调用方传 modules Mapping 或 settings.forge.set_piece_counts
       序列（本模块 resolve_piece_counts 委托 forge_sets.resolve_piece_counts）。这样保持
       纯函数无 IO，同时满足「档位集合取 settings.forge.set_piece_counts」配置化要求。
  P-2  件数源口径：family_piece_counts 与既有 set_lookup / F-4 完全同源——player
       ["set_tracker"]（族 id→件数）优先，回退 equipped/equip_nodes/equip_snapshot 装配
       节点集 ∩ 同族全部记录 pieces 并集（α/β 混穿归族，VAR-03）。不做第二套统计。
  P-3  最低激活件数：N < min(配置档位集合) 恒不激活（ACT-02/ACT-03）；该值由
       forge_sets.min_activate_pieces(piece_counts) 派生，与 set_lookup.ready 同一实现，
       不写死常量；配置档位集合为空 → 无档位 → 不激活任何技能。
  P-4  档位有效性：只有 piece_count ∈ 配置档位集合的档位参与判定（档位集合外的档位按
       V3 属非法数据，结算层忽略，不误激活）；level 非法（非 int/≤0）的档位忽略。
  P-5  同 skill 跨族命中：结果以 skill id 为键；同族多档取最高档（ACT-04），跨族同 id
       取「件数更高者，件数相同取等级更高者」——不叠加、确定性。
  P-6  重算写回条件：recompute_set_tracker 仅当 player 出现装配节点键
       （equipped/equip_nodes/equip_snapshot 之一，哪怕空列表）时才重算，否则保留既有
       set_tracker（tracker-only 存档/测试态不被空装配误清）；sets 为空同样保留。
  P-7  占位技能（effect_ref 空，SK-04）：结算层不做效果接线过滤——占位技能的**激活登记**
       （进入 set_skills/可用技能集）与「只显示不结算」不矛盾（效果层无线接自然不产出
       效果）；/套装 渲染仍逐档展示。

依据：
  - docs/细化/细化_2c2d_锻造套装与客制.md §1.2（SET-01~08 / SK-01~04）、§1.3（ACT-01~06）、
    §1.4（VAR-01~03）、§1.5（/套装 指令样例）。
  - qbot_rpg/core/forge_sets.py（结构/校验/查询/契约；本模块复用其 _set_tracker /
    _equipped_node_ids / _configured_piece_counts / _coerce_set 口径）。
  - qbot_rpg/core/skill_slots_battle.py（战斗可用技能唯一权威：本模块产出的 set_skills
    经其并入可用技能集，不绕过）。
  - 4b EQP-03 set_tracker / INS-07 set_tag、EQP-R06 战斗内不可穿脱。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；零 IO（除按显式契约就地写
      player 的 set_tracker/set_skills 键）；零定时器/零睡眠；平台无关；不引入随机。
"""

from __future__ import annotations

from typing import Dict, Mapping, MutableMapping, Sequence, Tuple, Union

from qbot_rpg.core.forge_sets import (
    _EQUIPPED_KEYS,
    _coerce_set,
    _equipped_node_ids,
    _set_tracker,
    min_activate_pieces,
    resolve_piece_counts as _resolve_piece_counts,
)

__all__ = [
    "SET_SKILLS_KEY",
    "SET_TRACKER_KEY",
    "PieceCountsInput",
    "resolve_piece_counts",
    "group_families",
    "equipped_piece_ids",
    "set_tracker_of",
    "family_piece_counts",
    "resolve_set_skills",
    "recompute_set_tracker",
    "sync_set_skills",
    "is_set_frozen",
]

# 玩家状态键（4b EQP-03 set_tracker / 本模块 set_skills 结算产物）
SET_TRACKER_KEY: str = "set_tracker"
SET_SKILLS_KEY: str = "set_skills"

# 档位集合入参（None=缺省 / int 序列 / modules Mapping 走 _configured_piece_counts）
PieceCountsInput = Union[None, Sequence[int], Mapping[str, object]]


def _is_int(value: object) -> bool:
    """非 bool 的 int 判定（件数/等级清洗，防 bool 混入）。"""
    return isinstance(value, int) and not isinstance(value, bool)


# =====================================================================================
# 档位集合归一（P-1：配置化复用既有 _configured_piece_counts）
# =====================================================================================
def resolve_piece_counts(piece_counts: PieceCountsInput = None) -> Tuple[int, ...]:
    """档位集合归一 → 升序去重正整数元组（缺省 SET_PIECE_COUNTS {2,3,5}）。

    本函数**委托** forge_sets.resolve_piece_counts（F-8 唯一档位来源实现，不另写
    第二套）：入参 None/缺省 → SET_PIECE_COUNTS；Mapping（modules）→ 读
    settings.forge.set_piece_counts（键缺失/非法回落；显式空列表 → 空元组）；
    int 序列 → 清洗去重升序（显式空/全非法 → 空元组 = 无档位/不激活）。纯函数确定性。
    """
    return _resolve_piece_counts(piece_counts)


# =====================================================================================
# ACT-01：件数按实例归族（α/β 混穿合并；复用既有 tracker/装配节点口径，P-2）
# =====================================================================================
def group_families(sets: Sequence[object]) -> Dict[str, list]:
    """套装序列 → {族 id: ForgeSet 记录列表}（插入序 = 首次出现序）。

    归一 ForgeSet / raw dict 双形态（复用 forge_sets._coerce_set）；缺 id 记录跳过；
    同族 α/β 记录聚在一起（VAR-01/03 混穿归族）。
    """
    families: Dict[str, list] = {}
    for s in sets or ():
        fs = _coerce_set(s)
        if fs is None or not fs.id:
            continue
        families.setdefault(fs.id, []).append(fs)
    return families


def equipped_piece_ids(player: object) -> set:
    """装配节点 id 集（委托 forge_sets._equipped_node_ids，非 Mapping → 空集）。"""
    p: Mapping[str, object] = player if isinstance(player, Mapping) else {}
    return _equipped_node_ids(p)


def set_tracker_of(player: object) -> Dict[str, int]:
    """set_tracker 读取（委托 forge_sets._set_tracker，非 Mapping → {}）。"""
    p: Mapping[str, object] = player if isinstance(player, Mapping) else {}
    return _set_tracker(p)


def family_piece_counts(player: object, sets: Sequence[object]) -> Dict[str, int]:
    """族级件数（ACT-01）：{族 id: 件数}。

    源优先 player["set_tracker"]（4b EQP-03，族 id→件数）；否则装配节点集
    （equipped/equip_nodes/equip_snapshot）∩ 同族全部记录 pieces 并集（VAR-03 α/β
    混穿合并计数）。非 Mapping player → 空件数；纯函数确定性（不写 player）。
    """
    p: Mapping[str, object] = player if isinstance(player, Mapping) else {}
    tracker = _set_tracker(p)
    equipped = _equipped_node_ids(p)
    families = group_families(sets)
    out: Dict[str, int] = {}
    for fid, recs in families.items():
        if fid in tracker:
            out[fid] = tracker[fid]
            continue
        union: set = set()
        for fs in recs:
            union.update(fs.pieces)
        out[fid] = len(union & equipped)
    return out


# =====================================================================================
# ACT-02/03/04：档位判定（≤N 最大档 → level；无 4 档；同级取高不叠加）
# =====================================================================================
def resolve_set_skills(
    player: object,
    sets: Sequence[object],
    *,
    piece_counts: PieceCountsInput = None,
) -> Dict[str, int]:
    """套装技能档位判定（ACT-02~04）→ {技能 id: 等级 1/2/3}。

    入参 player: 玩家状态（set_tracker 优先，回退装配节点集；非 Mapping → 空装配）；
              sets: 套装记录序列（ForgeSet / raw dict 双形态）；
              piece_counts: 档位集合（None/序列/modules，见 resolve_piece_counts）。
    出参 dict: 已激活技能 id → 等级。规则：
      ACT-01  件数按族归并（family_piece_counts，α/β 混穿合并）；
      ACT-02  族件数 N：取该 skill 档位中 piece_count ≤ N 的最大档 → 该行 level
              （等级以数据 level 为准不硬编码）；N < min(配置档位集合) 不激活（P-3）；
      ACT-03  无 4 件档：穿 4 件命中的仍是 ≤4 的最大档（即 3 件档 level=2）；
      ACT-04  同套装多技能各自判定并行；同 skill 多档命中只取最高档不叠加（P-5）。
    档位集合外的 piece_count 视为非法数据忽略（P-4）。技能 id 非空、level 合法才登记。
    出参按技能 id 升序，纯函数确定性。
    """
    allowed = resolve_piece_counts(piece_counts)
    min_pieces = min_activate_pieces(piece_counts)
    if min_pieces is None:
        return {}  # 无档位（集合为空）→ 不激活
    counts = family_piece_counts(player, sets)
    families = group_families(sets)

    best: Dict[str, Tuple[int, int]] = {}
    for fid, recs in families.items():
        n = counts.get(fid, 0)
        if n < min_pieces:
            continue  # ACT-02/03：N < min(配置档位集合) 不激活
        for fs in recs:
            for sk in fs.skill_defs():
                sid = sk.skill
                pc = sk.piece_count
                lv = sk.level
                if not isinstance(sid, str) or not sid:
                    continue
                if not _is_int(pc) or pc not in allowed:
                    continue
                if not _is_int(lv) or lv < 1:
                    continue
                if pc > n:
                    continue
                prev = best.get(sid)
                if prev is None or pc > prev[0] or (pc == prev[0] and lv > prev[1]):
                    best[sid] = (pc, lv)
    return {sid: best[sid][1] for sid in sorted(best)}


# =====================================================================================
# ACT-05：穿/脱/换装重算 + 战斗内冻结
# =====================================================================================
def is_set_frozen(player: object) -> bool:
    """套装状态是否冻结（ACT-05 / 4b EQP-R06）：player["in_battle"] is True → 冻结。"""
    return isinstance(player, Mapping) and player.get("in_battle") is True


def recompute_set_tracker(player: object, sets: Sequence[object]) -> Dict[str, int]:
    """穿/脱/换装重算 set_tracker（ACT-05）→ 重算后的 {族 id: 件数}。

    入参 player: 玩家状态（MutableMapping 才可写回；非 Mapping → {}）；
              sets: 套装记录序列（双形态）。
    行为：件数源与 family_piece_counts 同源（P-2）；重算结果写回
      player["set_tracker"]（4b EQP-03）。**冻结点**：player["in_battle"] is True 时
      直接返回既有 set_tracker、不重算不写回（战斗内套装状态冻结，EQP-R06）。
      仅在 player 出现装配节点键（equipped/equip_nodes/equip_snapshot 之一）或 sets
      非空可算时才写回；均不可得 → 保留既有（P-6）。纯函数确定性（除契约写回）。
    """
    if not isinstance(player, MutableMapping):
        return {}
    existing = _set_tracker(player)
    if is_set_frozen(player):
        return dict(existing)  # 冻结点：战斗内不重算（ACT-05/EQP-R06）
    families = group_families(sets)
    if not families:
        return dict(existing)
    if not any(key in player for key in _EQUIPPED_KEYS):
        return dict(existing)  # 无装配节点信息源 → 不空写（P-6）
    out = family_piece_counts(player, sets)
    player[SET_TRACKER_KEY] = out
    return out


def sync_set_skills(
    player: object,
    sets: Sequence[object],
    *,
    piece_counts: PieceCountsInput = None,
) -> Dict[str, int]:
    """重算 + 结算一步到位（ACT-05 接线入口）→ {技能 id: 等级}。

    行为：recompute_set_tracker（穿/脱/换装重算，战斗内冻结）→ resolve_set_skills
    （ACT-02~04 判定）→ 写回 player["set_skills"]（生效接入键）。返回技能等级表。
    非 Mapping player → {}（不写）。纯函数确定性（除契约写回）。
    """
    recompute_set_tracker(player, sets)
    skills = resolve_set_skills(player, sets, piece_counts=piece_counts)
    if isinstance(player, MutableMapping):
        player[SET_SKILLS_KEY] = dict(skills)
    return skills
