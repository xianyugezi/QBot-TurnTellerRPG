# M2 共享接口契约（怪物体系 · 多路并行依据）

> 本文件是 M2 怪物体系各并行子代理的**统一接口契约**。所有字段名/签名/形态以此为准，各路照此实现，跨路依赖零等待零冲突。
> 依据细化：1e（怪物八段 schema）/ 1f（AI 状态机）/ 1g4（战斗世界边界）。定稿在 /root/docs_archive/RPG框架项目/。
> 契约版本：v1（2026-08-26 主 agent 定，批次1 派工前）

---

## 一、enemies.json 八段字段表（1e §1.1 权威）

顶层 18 字段（旧 M0 简化口径 hp/atk/def/drop_rate 全部废弃，按八段重建）：

| 字段 | 类型 | 必填 | 默认 | 约束 |
|---|---|---|---|---|
| `id` | str | 必填 | — | 全文件唯一 |
| `name` | str | 必填 | — | 显示名 |
| `tier` | enum | 必填 | `normal` | `normal`/`elite`/`boss`/`training` |
| `type` | enum | 选 | 无 | `"dummy"` 标记（tier:training 或 type:dummy 任一=木桩） |
| `area` | str | 选 | 无 | 出没地图名 |
| `desc` | str | 选 | 无 | 一句话描述 |
| `stats` | obj | 必填(可漏键) | 模板补全 | 9 键 hp/mp/str/int/con/spr/foc/agi/luk |
| `weakness` | obj | 必填 | 空 | `{types:["斩"...], elements:{"fire":1.3}}` |
| `pv` | num | 必填(普通怪) | 档默认 10/75/300 | ≥0；木桩强制 0 |
| `pv_recover` | enum | 选 | `battle_end` | `battle_end`/`none` |
| `resistance` | obj | 选 | 空 | `{<effect_id>:0-100, immune:["poison"]}` |
| `actions` | array | 必填(普通怪) | 无 | 条目 {action, probability, weight, condition, cooldown, hungry} |
| `special_actions` | array | 选 | [] | 条目 {id, action, trigger, once, priority, trigger_cooldown, max_triggers, post_state, chain_ref} |
| `chains` | array | 选 | [] | 顶层连招表：{id, actions:[{action, chance, role, armor}]} |
| `drops` | obj | 必填(普通怪) | 三类 [] | `{battle:[], special:[], death:[]}` 条目 {item, chance, condition, count} |
| `lore` | array | 选 | [] | `{unlock:1-100递增, desc}` |
| `def_base` | num | 选(木桩向) | 无 | 防御基准≥0；配置=直读，未配=映射 stats.con |
| `elem_res` | obj | 选(木桩向) | 无 | 元素 ID ∈ 注册表；正=减伤/负=增伤 |

**AI 引擎依赖键（M2 审查 P2-2 补登记，2026-08-26）**：
- `ai`：`{states: {<state>: {enter_action, weight_mod, exclusive_actions}}, transitions: [{from, to, condition}]}`（行为态配置，monster_ai 消费）
- `phases`：阶段表（monster_phases 消费：threshold/actions/enter_action/broadcast；HP 阈值→阶段切换，驱动 phase_changed 联动）
- `basic_action`：兜底普攻行动 ID（L7 覆盖，缺省内置普攻）
- `chains[].cooldown`：链冷却回合数（断链登记，缺省 1）

### actions[] 条目（6 字段）
- `action`：引用 action.json 行动 ID（校验器硬拦悬空）
- `probability`：**默认 0**=锚点（只被链/条件/状态机触发）；1=入池；其他正值等价 1；数值不参与概率计算
- `weight`：≥0，随机池内归一化权重（默认兜底）
- `condition`：条件权重修正（如 pv_broken 时 ×2），默认 null
- `cooldown`：行动冷却回合数，默认 0
- `hungry`：连续 N 回合未选中强制选，默认 0=关

### special_actions[] 条目
- `id`：唯一标识（链引用目标，选填）
- `action`：引用 action.json 行动 ID（必填）
- `trigger`：`{type, value?, timing?, action?, chance?}`
  - type ∈ 15 类：`hp_below/pv_broken/get_up/battle_start/after_action/player_status/player_hp_below/turn_count/phase_changed/zone_changed/ally_dead/combo_broken/script` + `enemy_mark/player_mark`（印记扩展 2 类，2026-09-02 新增）+ `x_` 前缀自定义
  - 旧别名接受（兼容）：broken/revive/enter_phase → 归一 pv_broken/get_up/battle_start，黄提示迁移
  - timing ∈ `current_turn/next_turn/first_turn`；after_action 必带 action+chance(0-100)
- `once`：bool，一次性触发
- `priority`：条件行动优先级（降序，同级随机）
- `trigger_cooldown`：触发冷却回合数
- `max_triggers`：最大触发次数
- `post_state`：`{state, turns}` 触发后进入状态
- `chain_ref`：引用 chains 表 id（连招唯一载体）

### chains[] 条目（连招唯一载体）
- `id`：链唯一标识（chain_ref 引用目标）
- `actions[]`：`{action, chance 0-1, role: chain|finisher, armor?}`
- 接续概率 <60% 黄提示；chain_ref → chains.id 悬空硬拦；链成环=有意的循环连招，提示不拦截

### drops[] 条目（三类容器 battle/special/death）
- `item`：物品 ID，引用存在（硬拦）
- `chance`：0-100 整数（硬拦越界）
- `condition`：`pv_broken`/`no_damage`/`after_action:<action_id>`（special 类专用；**与 trigger.type 是两套独立枚举**，不得复用 trigger 校验器）
- `count`：num 或 [min,max] 闭区间，min≤max 非负

## 二、难度模板默认值（1e §②）

| 模板 | tier | stats 缺省补全 | PV 默认 | 行动表规模 | 特殊行动数 |
|---|---|---|---|---|---|
| 低 | normal | 全部 1×（同玩家同级） | 10 | 1-2 招 | 0 |
| 中 | elite | HP×2.5 / 攻击×1.2 / 防御×1.3 | 75 | 2-4 招 | 1 |
| 高 | boss | HP×10+ / 攻击×1.3 / 防御×1.5 | 300 | 4-6 招 | 2-4 |

模板只作用于 stats 漏配键与 pv 缺省；行动表/掉落/lore 无模板默认。木桩不套模板。

## 三、木桩特例（tier:training / type:dummy 任一命中）

- **忽略项（配置了也忽略+黄提示）**：drops（无掉落无金币无经验不计击杀任务）、lore（不入图鉴）、pv（强制 0）、actions/special_actions（不可反击，忽略 AI）
- **可配项**：stats.hp 极大、def_base、elem_res、weakness（豁免 ≥1 弱点约束）
- 运行期：与普通战斗共用引擎；战败=无损退出（可配 0=按普通战败）；/撤退 随时退出；不在地图内

## 四、action.json 行动字段（T24-T26 ActionCore + AI 字段）

- **基础（ActionCore ≤7 字段）**：`id/name/kind/power/attack_type/element/effects`
  - kind：basic/active/...（技能=怪物行动同构，同一执行器）
  - power：倍率；attack_type：斩/打/突/魔；element：元素 ID；effects：效果引用数组
- **AI 字段（怪物侧扩展，T26）**：`weight/probability/intent/cooldown/condition/hungry/chain(历史写法,兼容解析)/charge_*蓄力字段/preview/preview_chain/reveal_condition/armor/interrupt/tags`
- 校验：kind 枚举、intent 枚举（伤害/防御/蓄力/治疗/控制/buff/debuff/印记/功能）、AI 字段缺省兜底不报错、probability 漏配默认 0

## 五、AI 引擎接口（core/monster_ai.py 新建）

```python
# 行为态枚举
NORMAL, ENRAGED, DYING = "normal", "enraged", "dying"
# 执行态枚举
IDLE, IN_CHAIN, CHARGING, DOWNED = "idle", "in_chain", "charging", "downed"

class MonsterAI:
    """怪物 AI 决策引擎（无状态，状态以 battle 快照 ai_state 为权威）。"""
    def __init__(self, enemy_def, action_lib, rng):
        """enemy_def=enemies.json 条目 raw dict；action_lib=action 解析器（id→行动定义）；rng=确定性随机源（可注入）"""

    def decide(self, battle_state: dict) -> dict:
        """怪物行动阶段主入口：产出行动 action_dict（交给 battle._do_action/enemy_act 执行）。
        内部走：L0 套内门 → L1-L7 套间评估；同步更新 ai_state。"""

    def evaluate_transitions(self, battle_state: dict) -> None:
        """L1 行为态切换（transitions 条件表达式求值，套间调用）"""

    def evaluate_conditions(self, battle_state: dict) -> list:
        """L3 条件行动匹配（13 类触发 + priority 降序同级随机；once/max_triggers/trigger_cooldown 过滤）"""

    def roll_chain(self, chain_id: str, battle_state: dict) -> bool:
        """chain C 模型：节点 chance roll（入队 true / 断链+冷却 false）"""

    def intent_for(self, action_id: str, battle_state: dict) -> dict:
        """意图预告：{level, category, action_id, name_revealed, chain_preview, progress}"""
```

### ai_state 快照形态（battle._snap["ai_state"]，跨模块契约）
```python
{
  "state": "normal",           # 行为态
  "exec_state": "idle",        # 执行态（idle/in_chain/charging/downed）
  "phase": 1,                  # phases 阶段（BOSS：1/2/3）
  "chain_pos": 0,              # 连招链位置
  "chain_queue": [],           # 在途链（action id 序列）
  "chain_id": None,            # 当前链 id
  "chain_cooldowns": {},       # 链冷却 {chain_id: 剩余回合}
  "charge": None,              # 蓄力 {action_id, remaining_turns, armor}
  "trigger_cooldowns": {},     # 条件行动冷却 {special_action_id: 剩余}
  "action_cooldowns": {},      # 行动冷却 {action_id: 剩余}
  "hungry_count": {},          # 饥饿计数 {action_id: 连续未选回合}
  "intent": {},                # 意图预告 {level, category, action_id, name_revealed, chain_preview, progress}
  "forced_queue": [],          # 强制队列（开场技/脚本/enter_action）
  "boss_phase": 1,             # 兼容旧键（battle.py L487 已读此键）
}
```
注意：battle.py L487 现有 `boss_phase` 键（读 `(self._snap.get("ai_state") or {}).get("boss_phase", 1)`）——新形态保留 `boss_phase` 键，`phase` 与 `boss_phase` 同值（冗余兼容，后续收敛）。

### L0-L7 决策管线（1f §② 权威）
- **L0 套内门**：chain_queue 非空 ∨ charging → 只走链推进/蓄力结算，跳过 L1-L7
- **L1 状态机切换**：transitions 条件求值 → 切行为态；enter_action 入强制队列；weight_mod 生效（**套间先切**）
- **L2 强制队列**：队首行动执行；引链则入 chain_queue
- **L3 条件行动**：13 类触发匹配（priority 降序同级随机）；单次锚点或 chain_ref 链入队
- **L4 连锁队列**：chain_queue 非空 → 节点 roll 入队确定性执行；失败断链+冷却
- **L5 状态专属行动**：exclusive_actions 白名单
- **L6 随机行动表**：probability=1 池，P=weight×condition×state_mod 归一化；hungry 先查；cooldown 过滤
- **L7 兜底普攻**：L0-L6 均无产出

优先级总则：L0 闸门最高；L2-L7 逐级短路；**L1 例外**（L1 产出流入 L2 强制队列不停止）。打断=套完结（combo 被打断 → 下一回合随机流程）。状态切换一律走 phase_changed 联动（hp_below 直接阈值=演示写法提示迁移，TC-04）。

## 六、battle.py 挂接点（C1 路）

- `enemy_act(action_dict=None)`（battle.py L1455，M1 已预留）：action_dict=None 时用 **MonsterAI.decide()** 产出行动，再走既有 `_do_action`/`_resolve_damage_action` 执行；返回 ActionOutcome
- `_snap["ai_state"]` 读写：决策后回灌快照（吸收返回）
- 怪物行动执行复用玩家侧同一伤害通道（T24 同构双库语义：技能=怪物行动=一次出手）
- 打断接线：玩家 interrupt 命中怪物 → combo 引擎断链 + ai_state 置套完结（chain_queue 清空、下一回合走随机流程 L6）
- 换区/开场技（battle_start）触发留给 C2/M3，接口预留

## 七、1g4 世界边界（C2 路，逻辑层+接口预留）

- **丢失挂起**：`battle_snapshot.lost_pending = {target_ref:{id,name}, map_id, pending_since}`（F-08）
- **脱战回血**：野图 BOSS 三事件源（解除锁定/离开地图/战斗失败）→ HP 回满+锁释放（原子事务 CAS）；副本 BOSS 不恢复（J-01）
- **死亡惩罚**：settings `death_penalty` 段 `{weak_duration_sec:60, drop_currency:[], drop_exp:{enabled,percent}, drop_items:{enabled,count}}`（F-01~F-04）
- **跨群锁**：`world_state.wild_lock:<monster_key>` = `{holder_qid, since, battle_ref}`（F-07，原子 CAS）
- 校验器：F-02 货币引用存在 / F-02/F-04 数值合法 / F-05/F-06 引用存在 / 任何"战斗超时"键不识别
- 依赖 M3 spawn / M4 指令的部分：只做数据结构+逻辑函数+接口预留，不做完整接线

## 八、铁律（所有路遵守）

0. **属性键桥接（M2 审查 P2-6 登记）**：敌人 stats 九键 `luk`（1e S09）与玩家属性键 `lck`（3b/玩家侧）同名不同键——M3 战斗层消费敌人属性时需桥接 `enemy.luk → player.lck`（幸运），其余 8 键同名单向映射。契约层已知接缝，实现侧勿混用。
1. 每功能可追溯：文件头/docstring 标注「依据：细化_1e/1f/1g4 §X」
2. 平台无关：world/content/data 零 NoneBot import
3. 拦截链必须接线：新函数查调用方（禁止孤岛）
4. 校验器走 FieldMetaTable 泛化驱动（新字段=元数据加行，红拦封闭清单 R-1~R-5 + 本 M2 新增 R 规则）
5. 概率输出一律小数 fraction（与 1a 口径一致）
6. 确定性：AI 随机全部走注入 rng（可复现测试），禁止裸 random
7. 数据表非空：fixtures 的 enemies.json 必须非空且八段合法（防空表空转）
8. 命令格式：技能名/行动名禁空格
9. 提交：写完自测（/tmp smoke exit 0）→ 报告落盘路径 → 主 agent 收口核对
10. 引用行号先验证在文件范围内（行号编造教训）
