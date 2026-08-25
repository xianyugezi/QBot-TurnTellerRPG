# 审查_M0复查_data_types_20260824

> 审查者：QBot-TurnTellerRPG 代码审查 Agent（审查角色_初始化.md 固定人格）
> 批次：M0 复查 批1-路4 · 数据层领域类型
> 日期：2026-08-24（静态推导，本环境无 bash 沙箱，未运行任何命令/脚本/验证；全部结论标注「静态推导」）
>
> 审查文件（7）：`qbot_rpg/data/types.py`、`player.py`、`battle.py`、`status.py`、`item.py`、`world_state.py`、`__init__.py`
> 对照基准：
>   - `细化_3a_架构分层契约.md` §3（D-03 领域类型唯一落点 / frozen dataclass / D-06 群号非存档键）+ TC-06~08
>   - `细化_4a_存储层契约.md` §1.2 players 表字段级 schema（唯一数据源）/ §1.3 world_state/sessions 表
>   - 关联契约（溯源用）：`细化_3b`（属性三层/ADR-01/§4.4）、`细化_4b`（物品/装备/品质注册表）、`细化_1b`（效果/状态）、`细化_1g3/1g1c`（战斗快照）、`contract_deviations.md`
> 前置报告：`审查报告/审查_M0_coredata_20260818.md`（本批为复查，延续其 P2-8 formula_state 校验待办）

## 〇、结果总表

| 级别 | 数量 | 说明 |
|---|---|---|
| 🔴 拦截（P0 必改） | 0 | 无 M0 阻断项（零消费类型当前不破坏运行） |
| 🟡 注意（P1 应改） | 3 | 字段遗漏 / 状态实例类型与实际形态不兼容 / 战斗快照类型零消费且与实际快照双轨 |
| 🟡 建议（P2 建议） | 10 | 跨契约措辞不符、类型二义、文档引用幻觉、零消费无标注等 |

> 维度标注：①错误（bug/类型/字段/默认值）②缺漏（未实现/零消费）③幻觉（引用真实性/冒充定稿）。

---

## 一、P1（应改）明细

### P1-1 ①错误/字段遗漏：ItemInstance 缺 `stack_max`（4a §1.2 inventory 行格式字段）
- **文件:行号**：`qbot_rpg/data/item.py:28-36`（ItemInstance 字段集无 stack_max）；docstring `item.py:5` 自引 4a §1.2；消费端 `storage/repository.py:146-159`（`_item_from_dict` 对未知键「多忽略」MIG-1）
- **实际**：4a §1.2（L85）inventory JSON 行格式明文为 `{item_id, name, count, stack_max, bound, quality, traits...}`，`stack_max` 在列；ItemInstance 无此字段。若库内行含 stack_max（如旧包/4b 语义写入），读档被静默丢弃，堆叠上限约束（count ≤ stack_max）在数据层无承载。
- **应有/辨析**：4b ITM-07 将 stack_max 定义为 items.json 内容包定义级字段（默认 99），实例可不冗余——但 4a §1.2 行格式口径未同步，item.py 又自称以 4a §1.2 为唯一数据源，三处口径互斥，属跨契约未收敛 + 行格式字段遗漏。
- **修复建议（二选一，并登记 contract_deviations.md）**：① ItemInstance 增 `stack_max: int = 1`（随定义写入实例，MIG-1 缺补默认），或 ② 登记「stack_max 属 ItemDef(ITM-07) 定义级、实例不冗余」，并同步修订 4a §1.2 inventory 行格式说明，消除静默丢弃面。

### P1-2 ②缺漏+①错误：StatusInstance/Duration 全库零消费，且字段形态与 effects.py 实际 status_state dict 不兼容
- **文件:行号**：`qbot_rpg/data/status.py:17-38`（Duration/StatusInstance 定义）；实际形态 `core/effects.py:646-658`（`_new_instance` 构造 status_state 实例 dict）+ `effects.py:253-255`（`status_instances -> List[Dict]`）
- **实际**：
  - `StatusInstance{status_id, name, level, stacks, duration{Duration(turns,charges)}, decay: float, source}` **全库无任何构造/消费**（除 data/__init__ 转发）。
  - effects.py 实际状态实例是 **dict**：`{status_id, name, level, stacks, turns, charges, decay(str 枚举 halve/decrement/trigger/none), decay_subject, value, source, category...}`。
  - 差异点：① `decay` 语义错位——StatusInstance.decay:float「衰减值」vs 实际 decay 为**字符串衰减类型** + 独立 `decay_subject`/`value` 键（halve/decrement 形态无法用 float 表达）；② `duration` 嵌套 Duration 对象 vs 实际扁平 turns/charges；③ 实际多 `value`/`decay_subject`/`category` 键。
  - 引用错位：status.py:37 称 decay「细化_3b §1.2」——3b §1.2 实为「层优先级与覆盖规则」（3b L68），与状态衰减无关；衰减/持续语义应溯源 细化_1b §1.4/§4。
- **应有**：3a §3.2/TC-06 将 StatusInstance 定为唯一落点，M1 效果系统接入时须能与 effects.py status_state 互转（4a TC-17 往返精神）。
- **修复建议**：以 effects.py 实际形态（或 细化_1b §1.4 status_state 字段表）重构 StatusInstance 字段（decay 改 str 类型 + decay_subject + value；duration 扁平或保留 Duration 但补映射函数），并修正 3b §1.2 错引；若意图保持 spec-only，须在 data/status.py 显式标注「当前以 dict 形态落地（effects.py），StatusInstance 为契约 spec，M1 收敛」并登记。

### P1-3 ②缺漏：BattleSnapshot/CombatantSnapshot 全库零消费，实际战斗快照为 core/battle.py 可变 dict（U3 冻结保障未落地）
- **文件:行号**：`qbot_rpg/data/battle.py:20-58`（frozen 快照定义）；`core/battle.py:1564-1596`（`to_snapshot() -> Dict[str, Any]`）、`:855-876`（`self._snap` 可变 dict 初始化）、`:393/423/722/734`（原地改写 _snap）
- **实际**：
  - BattleSnapshot/CombatantSnapshot **全库无构造/消费**（仅 data/__init__ 转发；world/session.py 为 M1 占位，仅 docstring 提及）。
  - 实际快照是 `Dict`：字段集为 `schema_version/snapshot_at/context/units/ai_state/combo_state/turn/stats_collector/action_record/result/sides/status_state/marks_state/snapshot_cleaned...`（1g3 §1.2 形态），与 BattleSnapshot 的 `player/enemy(CombatantSnapshot)/turn/resist_table/effect_triggers/effect_cooldowns/formula_state` **字段结构不同**。
  - U3「快照 frozen 防战斗中被误改」对真实战斗快照**未生效**（_snap 为可变 dict，运行期原地改）。
- **应有**：3a §3.2 将 BattleSnapshot 列为唯一快照类型；M1 会话接线时若直接构造 dataclass 会与现有 dict 快照格式冲突（双轨已物化）。
- **修复建议**：M1 接线 session 时把 `to_snapshot` 收敛为 BattleSnapshot 构造（player/enemy 映射为 CombatantSnapshot、formula_state 注入 random_seed），或立即在 data/battle.py + contract_deviations.md 登记「战斗快照当前以 1g3 dict 格式落地（schema_version=1），BattleSnapshot 为契约 spec 待 M1 收敛」；同时延续前批 P2-8：formula_state「必含 random_seed」仍仅文档承诺，无构造期校验。

---

## 二、P2（建议）明细

### P2-1 ①错误/跨契约：4a §1.2 `stats` 列措辞与实际存储结构语义不符
- `repository.py:130` 写 `stats = asdict(PlayerAttributes)`（四层**管线输入** base/bonus/temp/cond）；4a §1.2 L87 描述为「属性当前值（stats.json 注册键 + 派生值，虚拟属性键空间查询）」。「派生值」从未持久化（派生属性运行时计算，ADR-03 只读不回写）。
- 修复：修订 4a §1.2 stats 列为「属性管线输入层（base/bonus/temp/cond）」，或若意图存派生值则补列。

### P2-2 ①错误/生命周期：PlayerAttributes.temp/cond 随玩家存档持久化，违反 3b §4.4/L241「temp+cond 入战斗快照」
- `player.py:34-37` 四层全在 Player 内；`repository.py:130` 整体 asdict 落 players.stats（含 temp/cond）。
- 3b L241：「存档持久化：base + bonus 落玩家存档；temp + cond 入战斗快照」。当前战斗代码不写 Player.attributes.temp（buff 走战斗内 dict），风险潜伏；但一旦调用方写入并 save_player，战斗 buff 会残留进玩家存档，违背「战斗结束清除」边界。
- 修复：storage 序列化时剥离 temp/cond（仅 base+bonus 落 stats），或 data 层提供 splitter（存档层/快照层），并同步 4a §1.2 口径。

### P2-3 ①错误/类型二义：types.py `AttrID`(TypeAlias=str) 全库零消费，且 core 用 `StatKey as AttrID` 别名
- `types.py:35` `AttrID: TypeAlias = str`；`types.py:47` `StatKey = NewType("StatKey", str)` 语义重叠（同为 stats.json 键）。
- `data/__init__.py:11,38` 仅转发 AttrID；**无任何模块 import data.types.AttrID**；core 实际用 `core/player_attributes.py:33 from qbot_rpg.data.types import StatKey as AttrID` —— 同一名字 AttrID 在 data=str、在 core=NewType(StatKey)，类型语义漂移。
- 修复：AttrID 与 StatKey 合并为一（建议保留 NewType 语义并统一名称），或 core 改 import AttrID。

### P2-4 ②缺漏/接口声明失实：data/__init__ docstring「只 import 本包」与实际不符
- `__init__.py:3`「core/world/storage/content 只 import 本包」；但 `content/models.py:18` 直接 `from qbot_rpg.data.types import (...)`（需 PackID/StatKey 等 NewType，data/__init__ **未重导出** NewType 族）。
- 修复：data/__init__ 增补 NewType 族导出并改 content 引用，或修订 docstring 为「各层经 qbot_rpg.data 或 qbot_rpg.data.types 引用类型」。

### P2-5 ③幻觉：types.py 引用不存在的文档「共享接口契约（M0 data 层）」
- `types.py:8-9`「共享接口契约（M0 data 层）：PlayerQID / ItemID / … 全部 TypeAlias」——全库 .md（含审查报告）grep 该标题 **零命中**，无此文档。
- 被引用内容本身可在真实契约溯源（3a §3.2 / TC-06、4a §1.2），属「引用不存在文档/冒充接口定义」。
- 修复：改引「细化_3a §3.2 + TC-06」或标注「本工程内部约定（M0 跨组 import 纪律）」。

### P2-6 ③幻觉/轻度错配：battle.py 引用「4a §0.1/§5.1」措辞与 §5.1 实际内容不完全对应
- `battle.py:7-8`「细化_4a §0.1/§5.1（会话快照 ID+名称冗余存储，按旧配置结算，D-05）」。
- §0.1 术语表 L35 确有「会话快照 ID+名称冗余存储、按旧配置结算」✓；但 §5.1 是「会话管理器范围」（D-05 回收语义，storage 不自行决定结算），不含「按旧配置结算」。属挂错章节号（装饰性错配）。
- 修复：改引「4a §0.1 术语表 / §1.5 SCHEMA-5」。

### P2-7 ②缺漏：SlotID/RegistryKind 等 NewType 零消费且无里程碑标注
- `types.py:49-51` SlotID/RegistryKind 定义后全库无消费（registry.py:83 仅注释提及 RegistryKind 概念，未 import）；TaskID 有「M4 起消费」显式标注（好先例）。
- 修复：为 SlotID/RegistryKind 补消费里程碑标注（SlotID 属 M2 装备部位互斥图、RegistryKind 属 validator/registry），或删除直至消费。

### P2-8 ①错误/类型约束：ItemInstance.quality 裸 str，未在类型层约束四档枚举
- `item.py:31` `quality: str`，docstring 称「四档枚举」（3a §3.2）；无 Literal/Enum 约束。4b GRD-R02 规定配置/存档只认 normal/fine/epic/legendary 英文枚举、校验器硬拦。
- 修复：类型标注 `Literal["normal","fine","epic","legendary"]`（或 NewType+validator 兜底），与 GRD-R02 编码纪律呼应。

### P2-9 ②缺漏（延续前批 P2-8 未闭合）：battle.py formula_state「必含 random_seed」无构造期校验
- `battle.py:44-45,58` 仅 docstring/注释承诺（4a TC-17 随机序列往返）；构造期不校验。
- 修复：提供构造/校验函数兜底（如 `BattleSnapshot(...)` 入口断言 formula_state["random_seed"] 存在）。

### P2-10 ①确认项（已登记偏差，无新增）：job_id 无独立存储列，折入 persistent_state
- 4a §1.2 players 宽表无 job_id 列；`repository.py:61-63,118-119,227` 折入 `persistent_state["job_id"]`（写回时弹出，往返一致）。
- 复查确认：已登记 `contract_deviations.md` D-1（含「与系统自有 persistent_state.job_id 键冲突」风险标注），**登记完备，无新增动作**；仅提示 M1+ 若出现 job 键冲突需改独立列（D-1 已注明）。

---

## 三、通过项（核对确认，静态推导）

1. **D-03/U1 唯一落点**：Player/PlayerAttributes/EquipmentSlot/ItemInstance/StatusInstance/Duration/CombatantSnapshot/BattleSnapshot/WorldState 全仓 grep **仅 data/ 各定义一次**；core/world/storage 无同名类定义 ✓
2. **frozen（U3）**：9 个 dataclass 全部 `@dataclass(frozen=True)` ✓；Tuple/不可变容器用于实例字段（inventory/gems/traits/achievement_state）✓
3. **D-06 群号非存档键**：Player.qid=QQ 全局键、`last_seen_group: Optional[str]` 仅来源记录、WorldState key=全局（world_state.py:23）✓
4. **4a §1.2 逐字段映射**（player↔players 行）：player_qid↔qid ✓、nickname↔name（storage 映射）✓、level/exp(默认1/0) ✓、hp/mp ✓、currencies ✓、equipment→EquipmentSlot{item_id,name,slot_level,locked,gems} 与 4a §1.2 **逐字段匹配** ✓、persistent_state/longline_counters/reputation_state/codex_state/achievement_state(tuple↔[]) /title_state/content_pack_id/content_pack_version/schema_version(默认4=当前5兼容)/last_seen_group/created_at/last_active_at 全部一一对应 ✓（inventory 缺 stack_max 见 P1-1）
5. **world_state §1.3**：map_boss/world_stock/spawn_timers/dummy_override + last_spawn_time（3a §3.2 有据、4a「等」覆盖）✓
6. **版本/类型纪律**：Python 3.9 兼容写法（Optional/List/Dict/Tuple，无 `|` 新语法）✓；`typing_extensions` 兜底已落地（前批 M0_storage P2-13 已闭合，types.py:20-23）✓
7. **引用行号核验**：3a L141 types.py ✓、3a §3.2 字段要点 ✓、3b ADR-01（temp_flat 扩展）✓、4a §1.2/§1.3/TX-1 ✓、细化_2a1d / 1g1c / 1b 均存在 ✓、Player 注释「4a RW-3/TX-1」准确 ✓

---

## 四、结论（静态推导）

**可合入（P0=0）**。数据层 7 文件对 3a §3（D-03 唯一落点、全 frozen、D-06 群号非存档键）与 4a §1.2/§1.3 字段映射的主体落地正确、引用行号基本真实，前批 P2-13 已闭合。

**P1=3 须在 M1 接线前处理**：P1-1 ItemInstance 缺 stack_max（4a §1.2 行格式字段遗漏 + 读档静默丢弃，需补字段或登记偏差）；P1-2 StatusInstance/Duration 零消费且字段与 effects.py 实际状态 dict 不兼容（decay 语义错位，M1 效果系统接线必撞）；P1-3 BattleSnapshot/CombatantSnapshot 零消费、实际战斗快照为 core/battle.py 可变 dict（U3 frozen 保障未落地、字段双轨已物化）。三条共同根因：**「唯一落点类型」与「实际运行形态」未绑定**——建议在 contract_deviations.md 统一登记三类 spec-only 状态的收敛口径。

**P2=10** 均为跨契约措辞/类型二义/引用幻觉/零消费标注类，重点为 P2-5（引用不存在的「共享接口契约」文档）、P2-1/2-2（stats 列语义与 temp/cond 生命周期）、P2-3（AttrID/StatKey 同名两义）。
