"""怪物连招链引擎（M2 怪物体系 · B2 路：chains 连招链 chain C 模型）。

依据：细化_1f_怪物AI状态机.md（② L4 连锁队列——「chain_queue 只由顶层 chains 表驱动 /
链节点 chance roll / 失败断链+冷却」；⑤ chains 连招链 5.1-5.5：chain C 模型（5.2 触发
roll 一次决定入队 / 入队后套内确定性执行 / roll 失败=断链+该链进入冷却）、套内稳定（5.3）、
打断=套完结（5.4）、接续概率 <60% 黄提示（5.5 / §八））+ docs/m2_shared_contract.md
第一节（chains[] 结构：id + actions[]{action, chance 0-1, role: chain|finisher, armor?}；
接续概率<60% 黄提示 / chain_ref→chains.id 悬空硬拦）+ 第五节（L4 / roll_chain 签名）+
第八节铁律。

纯规则引擎，零 NoneBot import（铁律 2）。chance 一律小数 fraction 0-1（铁律 5，与 1a
口径一致；chains schema chance 即 0-1 小数，A2 R15 硬拦越界）。随机一律走注入 rng
（铁律 6，可复现；不注入 → 抛 ValueError）。

校验规则登记（只登记不重复）：chain_ref → chains.id 悬空硬拦 + 节点接续概率 <60% 黄提示
已在 A2 校验器落地（qbot_rpg/content/validator.py R15_*，见 CHAIN_VALIDATION_RULES 登记表）。
本模块运行期防御性兜底（缺 chance 按 1.0 / 缺链按不入队），不替代校验器硬拦。

chain C 模型（1f ⑤5.2 / 核心规则2）：
  1. 链节点 chance：触发时 roll 一次决定是否入队（evaluate_chain 只 roll 链首节点，
     建议 ≥80%）；成功 → 整链入队（enqueue_chain），入队后套内确定性执行（中途不被条件打断）。
  2. roll 失败 = 断链（该链进入冷却；B1 monster_ai._produce False 分支 _break_chain 落账）。
  3. 打断 = 套完结（1f ⑤5.4 / 核心规则3）：on_chain_broken 清在途队列 + exec_state 回
     idle + 当前链进冷却（防同链立即重触发）；下一回合走随机流程 L6（不继续原套）。

ai_state 读取/写入键（contract §五快照）：chain_queue / chain_id / chain_pos / exec_state /
chain_cooldowns。本模块不改写除这些以外的键。
"""

from typing import Any, Dict, List, Mapping, Optional

__all__ = [
    "CHAIN_VALIDATION_RULES",
    "chain_validation_rules",
    "evaluate_chain",
    "enqueue_chain",
    "on_chain_broken",
    "node_chance",
]

# 校验规则登记表（A2 已在 validator.py 落地，本模块只登记不自实现——铁律 4「校验器走
# FieldMetaTable 泛化驱动」的 M2 新增规则归 A2；登记供审查/文档引用，避免跨路重复实现）。
CHAIN_VALIDATION_RULES: Dict[str, str] = {
    # chain_ref 悬空（special_actions[].chain_ref → chains[].id 引用存在，硬拦）
    "R15_chain_ref_missing": "chain_ref→chains.id 悬空 → 硬拦（validator.py "
                             "R15_chain_ref_missing，A2）",
    "R15_chain_ref_type": "chain_ref 非 str → 硬拦（validator.py R15_chain_ref_type，A2）",
    # 链节点 schema
    "R15_chain_id_required": "chains[].id 缺失/重复 → 硬拦（validator.py R15_chain_id_*，A2）",
    "R15_node_action_required": "节点 action 缺失/悬空引用 → 硬拦（validator.py "
                                "R15_node_action_required / _check_action_ref，A2）",
    "R15_node_chance_required": "节点 chance 缺失/非 0-1 小数 → 硬拦（validator.py "
                                "R15_node_chance_*，A2）",
    "R15_node_role_enum": "role ∉ {chain, finisher} → 硬拦（validator.py "
                          "R15_node_role_enum，A2）",
    # 接续概率 <60% 黄提示（1f ⑤5.5 / §八；本模块登记，A2 提示）
    "R15_chain_continuation_lt60": "节点接续概率 <60% → 黄提示（1f ⑤5.5；A2 校验器）",
    # 链成环 = 有意的循环连招，提示不拦截（1f ⑤5.1 / 细化_1e F14）
    "R15_chain_cycle": "链内 action 重复=环形链 → 提示不拦截（validator.py "
                       "R15_chain_cycle N-6，A2）",
}


def chain_validation_rules() -> Dict[str, str]:
    """校验规则登记查询（返回拷贝，防外部修改登记表）。"""
    return dict(CHAIN_VALIDATION_RULES)


def node_chance(chain_def: Mapping[str, Any], index: int = 0) -> float:
    """节点 chance 归一 0-1 小数（铁律 5；chains schema chance 即 0-1 小数）。
    缺 chance → 1.0（运行期防御性兜底；A2 R15 已硬拦缺失，此处仅兜底防 None）。"""
    nodes = chain_def.get("actions") or []
    if not nodes or index >= len(nodes) or not isinstance(nodes[index], Mapping):
        return 0.0
    c = nodes[index].get("chance")
    if c is None:
        return 1.0
    return max(0.0, min(1.0, float(c)))


def evaluate_chain(
    chain_id: str,
    chain_def: Mapping[str, Any],
    ai_state: Mapping[str, Any],
    rng: Any,
) -> bool:
    """chain C 模型：链首节点 chance roll（入队 true / 断链 false，contract §五 roll_chain）。

    - 链在冷却（chain_cooldowns[chain_id] > 0）→ False（冷却过滤，不 roll）。
    - 链定义缺 actions / 链首节点缺失 / chance<=0 → False。
    - roll：rng.random() < 首节点 chance → True；否则 False。
    - 纯判定不写状态：True 后由调用方 enqueue_chain 入队；False 后由调用方登记链冷却
      （B1 monster_ai._produce 已接：True→_enqueue_chain，False→_break_chain 断链+冷却，
      主 agent 接线时沿用既有路径，本函数不重复落账）。
    """
    if not isinstance(chain_def, Mapping):
        return False
    cds = ai_state.get("chain_cooldowns") or {}
    if int(cds.get(chain_id, 0)) > 0:
        return False  # 链冷却中 → 不入队
    chance = node_chance(chain_def, 0)
    if chance <= 0.0:
        return False
    if rng is None:
        raise ValueError("monster_chains: evaluate_chain 需注入 rng（铁律 6，可复现）")
    return float(rng.random()) < chance


def enqueue_chain(
    chain_id: str,
    chain_def: Mapping[str, Any],
    ai_state: Dict[str, Any],
) -> None:
    """连招链入队（evaluate_chain True 后调用）：chain_queue = 链节点 action id 序列。

    入队 = 全链序列（套内确定性执行）；触发行动 = 链首节点——由调用方在入队后弹出队首并
    本次执行（对齐 B1 monster_ai._produce L499-502「触发行动=链首节点，余下待 L0」）。
    链定义缺 actions 或全节点无 action → 不入队（空队列防御）。
    """
    if not isinstance(chain_def, Mapping):
        return
    nodes = chain_def.get("actions") or []
    actions: List[str] = []
    for n in nodes:
        if isinstance(n, Mapping) and n.get("action"):
            actions.append(str(n["action"]))
    if not actions:
        return
    ai_state["chain_queue"] = actions
    ai_state["chain_id"] = chain_id
    ai_state["chain_pos"] = 0
    ai_state["exec_state"] = "in_chain"


def on_chain_broken(ai_state: Dict[str, Any]) -> None:
    """打断 = 套完结（1f ⑤5.4 / 核心规则3）：清在途队列 + exec_state 回 idle + 链进冷却。

    - 打断（玩家 interrupt 命中，contract §六）由 C1/battle 侧调用；
    - 清 chain_queue / chain_pos=0 / chain_id=None / exec_state="idle"（下一回合走随机流程 L6）；
    - 当前链进冷却（chain_cooldowns[chain_id] 缺省 1 回合，防同链立即重触发；打断≠roll 断链，
      语义是套完结，核心=不继续原套）。
    """
    cid = ai_state.get("chain_id")
    ai_state["chain_queue"] = []
    ai_state["chain_pos"] = 0
    ai_state["chain_id"] = None
    ai_state["exec_state"] = "idle"
    if cid:
        cds = ai_state.setdefault("chain_cooldowns", {})
        cds[cid] = int(cds.get(cid, 0)) or 1  # 既有冷却更高则保留，0 → 缺省 1
