# 审查报告：M6 实现层批4（内容包冒烟）· j-space 静态审查

> 审查对象：`scripts/e2e_m6_smoke.py`、`scripts/verify/verify_m0.py`、`tests/unit/test_e2e_m6_smoke.py`、
> `tests/unit/test_pack_fixtures_matrix.py`、`content/demo_blank`（五档包抽查）、`docs/verify/m6_smoke.md`
> 参考契约：`docs/细化/细化_M6_内容包冒烟.md`（D4）§一~§五 + TC-SMK/TC-PCK
> 审查方式：**纯静态代码审查**（本环境无 bash 沙箱，禁止运行命令/脚本/验证）；所有运行行为结论均标【静态推导】。
> 结论分级：P0（契约核心破坏/假绿空断言）｜P1（契约规则未落地/真实缺陷）｜P2（弱断言/工程改进）。

---

## 〇、审查维度覆盖总览

| 维度 | 结论 | 说明 |
|---|---|---|
| ① D4 契约落地 | ⚠ 大体落地、两处核心偏斜 | 冒烟脚本形态（Smoke 收集器/零 NoneBot/固定 now+seed/两次重放逐字一致/退出码）齐；**攻击步「一轮一条合并」为死断言（P0）**；**missing_mod Y-6 断言静默缺失（P1）**；PCK-10 五档包装配战斗无落地（P1） |
| ② 代码质量（bug/边界/断言可回溯/确定性/引擎调用正确性） | ⚠ 见 P0/P1/P2 | 断言可回溯基本达标（check_eq 带期望/实际）；确定性摘要可靠；**dispatch_round 调用两处 API 错用**（BattlePipeline 缺 sender + report 传 dict） |
| ③ 遗漏（TC 未覆盖/规则未实现/与 e2e_m4、verify_m0、content 接缝） | ⚠ 见 P1/P2 | verify_m0 修正真实有效；归档为模板延期 D8（契约允许）；五档包目录/模块集/registry 递增断言齐 |

**总体**：批4 主体（四步矩阵 3/4 步真实、validator 矩阵、verify_m0 修正、五档包结构、pytest 包装、归档模板）质量良好；
核心问题集中在冒烟脚本自身的两处「静默弱化」（攻击合并断言、missing_mod Y-6），正是本批契约反复强调要消灭的空断言形态。

---

## 一、P0（1 项）

### P0-1　攻击步「一轮一条合并」是死断言：异常全吞 + API 双错用 → 恒真假绿

- **位置**：`scripts/e2e_m6_smoke.py` L206-214（step_attack）；关联 `qbot_rpg/commands/battle_commands.py` L501-512（BattlePipeline.__init__）、L630-637（dispatch_round 签名）、L691（`report.ended` 直取属性）。
- **契约**：D4 §二 2.1 攻击行 + SMK-10 + TC-SMK-06「一轮行动+反击合并一条消息（dispatch_round 恰 1 次 send，对齐 verify_m5 ④b）」；§一 SMK-12「禁止空断言」。
- **静态推导的缺陷链**（三处叠加，任一处即致命，实际全部叠加）：
  1. `pipeline = BattlePipeline()`（L208）缺必填位置参数 `sender`（battle_commands.py L501-503 `__init__(self, sender, ...)`）→ 立即 `TypeError: missing 1 required positional argument`。**从未执行到 dispatch_round。**
  2. 即便构造成功，`dispatch_round(eng, eng.battle_state(), ...)`（L209）把 `battle_state()` **dict** 传给形参 `report`，而 dispatch_round 要求 TurnReport（L691 `if report.ended:` 对 dict 直取属性 → 必 `AttributeError`；L658/L670 的 getattr 走缺省后也在 L691 崩）。
  3. 外层 `except Exception: sends = []`（L212-213）把上述任何异常**静默吞掉** → `len(sends) <= 2`（L214）以 **0 条** 恒真通过。
- **影响**：SMK-10/TC-SMK-06 的「恰 1 次 send」断言从未真实执行；冒烟报告全绿（green=True）而该断言是空断言。这正是本批契约（承接批2B P0-1「四步零断言」、SMK-12「禁止空断言」）要消灭的形态，属契约核心破坏。
- **另**：断言阈值为 `<= 2`（含 0、2），与契约「恰 1」不符，即使修复管道也需改为 `== 1`。
- **修复建议**：直接复用 verify_m5 ④b 既有范本（verify_m5.py L497-513）：
  ```python
  eng2 = BattleEngine(); eng2._rng = _FixedRng()
  eng2.start(dict(SMOKE_PLAYER), _enemy_combatant(), random_seed=SEED)
  report = eng2.player_act("normal")                     # TurnReport（含玩家行动+怪物反击）
  mock = unittest.mock.Mock(); mock.send.return_value = []
  pipeline = BattlePipeline(mock, level=1, name="冒烟侠", to="smoke")
  ctx = {"battle_engine": eng2, "sender": mock, "battle_status_changes": ()}
  sent = dispatch_round(eng2, report, pipeline, ctx)
  s.check_eq(mock.send.call_count, 1, "攻击·一轮行动+反击合并恰 1 次 send")
  ```
  并**删除吞异常分支**（或 except 分支改 `s.check(False, ...)` 使失败显式化，绝不静默置空）。

---

## 二、P1（2 项）

### P1-1　validator 矩阵 missing_mod 的 Y-6 断言被静默丢弃（dead variable）

- **位置**：`scripts/e2e_m6_smoke.py` L261-268（validator_matrix）；`y6` 计算于 L264，**从未被 `s.check(...)` 消费**。
- **契约**：D4 §三 SMK-12/13 + TC-SMK-10「missing_mod 软放行 = 加载成功 + **warnings 含 Y-6(statuses)** + 未声明不加载」。
- **静态推导**：L264 算出 `y6`（含 Y-6/statuses 判定），L265-266 却只断言 `mp.report.ok` 与 `len(warnings) > 0`（任意黄即可过）。missing_mod 的签名断言（Y-6 statuses）在冒烟内**静默缺失**；该变量成为无消费者死代码，属于「已写断言意图、未落断言」的典型缺陷。
- **影响**：冒烟 validator 矩阵对 missing_mod 的覆盖弱化为「能加载且有任意黄提示」，SMK-13 的核心签名（Y-6 statuses）在冒烟内不生效（外部 verify_m0 / test_pack_fixtures_matrix / test_content 仍有覆盖，故非 P0）。
- **修复建议**：L266 后补一行 `s.check(y6, "validator·missing_mod 含 Y-6(statuses) 黄提示")`（或并入 L266 的条件）。

### P1-2　PCK-10「五档包数据装配战斗」无任何落地

- **位置**：全批4 文件；`tests/unit/test_pack_fixtures_matrix.py`（PCK 组）、`scripts/e2e_m6_smoke.py`。
- **契约**：D4 §五 PCK-10「至少 demo_lv15 档数据装配可战斗怪 → BattleEngine 模拟一局（锁定→攻击→结算）通过」；TC-PCK 系列。
- **静态推导**：冒烟脚本的战斗只装配 `tests/fixtures/packs/legal` 的 rock_weasel（e2e_m6_smoke.py L107-117）；test_pack_fixtures_matrix 对五档包只做 `build_pack`/registry 断言（test_pck02/pck05/pck06/pck11），**无任何 content/demo_* 数据进入 BattleEngine**。PCK-10 规则无测试/脚本承接。
- **影响**：五档包「至少 demo_lv15 起可装配真实战斗」的契约断言缺失（demo_lv15/enemies.json 已含 rock_weasel+training_dummy，数据在但无人驱动引擎）。
- **修复建议**：test_pack_fixtures_matrix 增补用例——读 `content/demo_lv15/enemies.json` 的 rock_weasel → 装配 `BattleEngine.start(player, enemy_combatant, random_seed)` → 断言 do_action 后 enemy.hp 差分、终局 round-trip（对齐冒烟结算步）；或让 e2e_m6_smoke 的 `_enemy_combatant` 改从 demo_lv15 取数（替代 legal），一处覆盖 SMK-10 + PCK-10。

---

## 三、P2（约 10 项，均不阻断）

### 冒烟脚本（e2e_m6_smoke.py）

1. **L250-254 legal 弱断言**：`len(changed) >= 5` 是「registry 全量注册且 ID 唯一」的弱代理；矩阵 §3.1 要求 ID 唯一未断言。外部（verify_m0 L126-129 / test_smk08）已覆盖，冒烟内可补 `all_ids("enemy")` 精确集。
2. **L256-260 badref 弱断言**：只断言抛 PackLoadError，缺「红拦 5 类之一（如 R-4）」「registry 未被污染」。外部已覆盖（verify_m0 L102-113 / test_smk09）。
3. **L269-274 old_schema 弱断言**：只断言 `report.ok`，缺「缺补默认 hp=None」「多忽略 x_future_field 放行」。外部已覆盖（verify_m0 L146-155 / test_smk11）。
4. **L217-244 结算步缺 victory 文案与掉落断言**：SMK-11/TC-SMK-07 列出的「victory 文案（BREP-16~24）+ 掉落」未实现；docstring（L218）自称含 victory/掉落属**过度声明**。回合数偏离声明（L232「win 模板不含『回合数 N』」）经核对 battle_render.py L184/L204 属实（win 无 BREP-24 汇总行，lose/draw 才有）——冒烟处理正确，但 D4 契约 §2.1 引用 BREP-24「回合数 N」对 win 不成立（文档内部不准，非实现缺陷）。快照 round-trip 只比 turn/hp/action_record 3 字段非「完全一致」（L235-244 有注释声明）。建议：结算步至少断言 `state["result"]["flag"] == "win"` 或渲染含「您击败了」（battle_render L824）；docstring 与实际断言对齐。
5. **L172-189 锁定步 start 后只断言 enemy 名称**：契约「双方 combatant 数值来自 legal 包」未断言数值（如 enemy hp==120）。建议补 `bs["enemy"]["hp"] == 120`。
6. **L154-169 注册后放行只回归 cmd_view 一个指令**：TC-SMK-04「注册后 registered=True → 指令放行」应对 4 指令统一断言（现仅 /角色）。
7. **L294-307 重放不一致时无诊断**：`a != b` 时只打印 a 的 failures（可能为空），不打印两次摘要差异。建议打印 `a`、`b` 差异。
8. **SMK-05「分路径断言计数」未实现**：Smoke 收集器无 per-path 计数，summary 只有 total；F-03 归档的 N/M/K/J 无法由冒烟自身产出（依赖 D8）。属规则项未全落地。

### verify_m0.py

9. **L107-113 badref「registry 未污染」断言机制与标签不符**：实为「badref 红拦后 legal 重载成功」；因 build_pack 每次构建独立 registry（loader.py L294 `_build_registry`），该断言**恒真**、无法检测任何污染（与 test_smk09 L54-56 同构）。语义在 per-pack registry 下天然成立（非错误结果），但标签声称验证了「原子快照替换」不成立。建议：注释声明该语义（或注入共享 registry 断言），避免误导。

### 归档 / 接入

10. **docs/verify/m6_smoke.md 仅为模板（F-01~05 定义），无真实运行数据**：批4 范围内无写入者；契约 ADR-D4-03 双轨允许（写入归 D8 verify_m6）。TC-SMK-14 在批4 只验证模板段存在（test_smk14_archive_template_sections）。属声明内延期，非缺陷。SMK-17 run_all_tests L4 e2e 接入同理归 D8（MILESTONES["m6"]=None 未置位）；两个新测试文件落在 tests/unit/，verify_m0 unit 段会自动拾取（有益副作用）。

---

## 四、无问题维度确认（正面结论）

- **冒烟形态对齐 e2e_m4**：Smoke.check/check_eq 收集器（L75-95）、固定 now（L53 FIXED_NOW=2026-08-01 12:00 UTC+8）、固定种子（L54 SEED=20260826）、两次 run_smoke 摘要逐字一致（L296-300）、退出码 0=全绿 + 全绿行（L55/L306）——**全部符合 SMK-01/03/05**。【静态推导】摘要只含 passed/failed/failures/green，不涉 uuid/时间戳，确定性可靠。
- **零 NoneBot 铁律（SMK-02）**：脚本仅 import qbot_rpg.* + 标准库，无 nonebot；pytest 包装 ast 扫描（test_e2e_m6_smoke.py L59-70）覆盖 Import/ImportFrom。✓
- **pytest 包装形态（SMK-01 / TC-SMK-01~03）**：子进程 exit0+全绿行、run_smoke green、确定性重放、断言数下限（MIN_TOTAL_ASSERTIONS=25，实计 28 条）四断言齐全，对齐 test_e2e_m4_smoke。✓
- **verify_m0 修正（SMK-13 / TC-SMK-12）**：`_validate_fixtures`（verify_m0.py L61-160）missing_mod 分支为真实断言（Y-6(statuses) + npc.villager 未注册 + items.potion 挂载），docstring 已由「必须被红拦」改正为「软放行」；old_schema 断言 hp=None。修复真实有效。【静态推导】
- **四件套矩阵（SMK-12 / TC-SMK-08~11）**：test_pack_fixtures_matrix 四包断言齐全（legal 全绿+ID 集、badref R-4+重载、missing_mod Y-6+未声明不加载+挂载、old_schema hp=None+old_potion），fixtures 已在 tests/conftest.py 注册。✓
- **五档包（PCK-01~09/11/12）**：目录齐全（blank/lv15/lv30/lv45/full，F-08 命名）；demo_blank manifest 5 模块与磁盘 JSON 一一对应、无 enemies → 只装配不战斗（PCK-06）【静态推导】；lv15/lv30/lv45/full 模块集 11/12/16/16 单调递增（PCK-05）【静态推导】；registry enemy 集逐档递增与测试断言一致【静态推导】；demo_full=legal 基线（PCK-11）enemy 集一致【静态推导】；四件套分离（PCK-07）成立。✓
- **战斗引擎调用正确性（除 P0-1 外）**：try_acquire_lock(None, qid, now, battle_ref) 四参签名与 battle_boundary.py L645-650 一致；`eng._rng = _FixedRng()` 注入不被 start 覆盖（battle.py L869 尊重非 random.Random 注入）；`_rng.random()` 是引擎唯一随机调用（L481）故 `_FixedRng.random()` 足够；hit 判定 `_roll() <= hr` 且 hit_rate cap_min=10%（damage.py L338-362）→ 恒 0.1 必命中【静态推导】；legal rock_weasel 九项 stats 键齐全（luk→lck 映射成立）。✓
- **确定性重放（SMK-03 / TC-SMK-03）**：同参两跑摘要逐字一致成立（见上）。✓
- **存档/生产 IO**：冒烟与测试零生产存档触碰，全部只读 fixtures + content。✓

---

## 五、修复优先级建议

1. **P0-1**：仿 verify_m5 ④b 重写 step_attack 合并断言（删 try/except 吞异常、BattlePipeline 注入 mock sender、dispatch_round 传 TurnReport、阈值改 `==1`）。
2. **P1-1**：missing_mod 补 `s.check(y6, ...)` 一行。
3. **P1-2**：test_pack_fixtures_matrix 增补 demo_lv15→BattleEngine 一局，或在冒烟 `_enemy_combatant` 改读 demo_lv15 数据。
4. P2 各项按「结算 victory/掉落 + 锁定数值 + 注册四指令」优先补强，其余记录在案。

---

*审查方式：纯静态（无运行）。带【静态推导】的结论以源码交叉核对为基础（battle.py/battle_commands.py/battle_boundary.py/basic_commands.py/register_commands.py/content/loader.py/registry.py/models.py/battle_render.py/damage.py/parsers.py 已逐一核对签名与行为）。*
