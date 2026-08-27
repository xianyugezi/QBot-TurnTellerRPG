# 审查_M6实现_批6A（测试体系强化·SED 种子收敛 + FIX 参数读取器）— j-space 静态审查

> 方式：**纯静态代码审查**（j-space 门控 full 档；本环境无 bash 沙箱，未运行任何命令/脚本/验证）。
> 所有运行行为结论均标注【静态推导】，需实跑确认项单独列出。
> 依据契约：《细化_M6_测试体系强化.md》（D6）§二 SED-1~8 / F-SED-01~03 / TC-SED-01~05、
> §三 FIX-1~8 / F-FIX-01~27 / TC-FIX-01~06、§八 决策记录；《细化_1a_伤害公式数值.md》参数语义；
> 母契约【5d】TC-5d-04/05/14、【规则】L306-311/L330-331。

## 〇、结论摘要

| 级别 | 数量 | 摘要 |
|---|---|---|
| **P0** | **0** | 无阻断项 |
| **P1** | **1** | SED-3/SED-5 全仓规则残留（清单外约 10 文件 16 处）未迁移且未登记 |
| **P2** | **8** | 见 §三 明细（迁移⑥b 实跑确认项、FIX-3 残留、三处文档漂移、观察项等） |

## 一、维度① D6 契约落地（逐项核对）

### 1.1 seed / seeded_rng / formula_params 三 fixture（F-SED-01~03 / FIX-2）——✅ 确认

| 契约项 | 落点 | 核对 |
|---|---|---|
| F-SED-01 seed 默认 **20260826** | tests/conftest.py L41 `DEFAULT_SEED = 20260826`，L79-86 `seed` fixture | ✅ 与 D6 收敛值一致；注释声明 SED-6 一处生效 |
| F-SED-02 seeded_rng 返回 `random.Random(seed)` | conftest L89-101，L98-99 `_make(offset=0) → random.Random(seed + offset)` | ✅ 含 §2.5 派生形（offset），**派生种子确定性成立**【静态推导：同 seed 同 offset 恒同实例初态】 |
| F-SED-03 function 级作用域 | `@pytest.fixture` 默认 function 作用域（L79/L89） | ✅ 每用例独立实例，无跨用例 RNG 状态串扰 |
| FIX-2 formula_params 读取器 | conftest L109-191 `load_formula_params` + L194-202 fixture（session 级，frozen dataclass 只读安全） | ✅ 按 F-FIX-01~27 全映射关键字装配；frozen 子结构逐段实例化 |

### 1.2 formula.json F-FIX 参数（TC-FIX-01 / F-FIX-01~27 默认值对照）——✅ 确认

tests/fixtures/packs/legal/formula.json 与 D6 §3.2 表 + qbot_rpg/core/damage.py dataclass 默认值
三方逐字段静态对照：**27/27 项一致**（base_attack_mult=1.0 / rng=[0.9,1.1] / hit 1.0·10·95 /
crit 0.5·95·(2.2/1.7/1.3)·(1,3)·(0.05/0.10/0.15) / block 150·40·true·true / defense
"ratio"·100·{blunt:0.2} / weakness 1.3·1.3 / type_affinity true·0.2·0.05·0.05·true /
derived 1.5 / monster_def_rate 1.0 / elements 8 元素注册表）。
- FIX-1 保留 `damage_base`/`heal_rate` 两键 ✅（L2-3）；`damage` 段内 `schema_version`/
  `floor_mode`/`deep_floor` 属纯配置字段，读取器不消费（D6 §3.4 口径）✅。
- 参数语义（细化_1a）：`base_attack_mult` 已被引擎消费（battle.py L1387 `attack_value *= p.base_attack_mult`）✅；
  `monster_def_rate` 每怪可配、全局回退（battle.py L1395）✅；乱数闭区间经 `self._rng.random()`（battle.py L487）
  入 `total_damage` ✅。【静态推导】

### 1.3 SED-4 六处迁移清单逐项——✅ 五处严格等价 + 一处需实跑

| # | D6 清单 | 实现落点 | 断言等价性核对【静态推导】 |
|---|---|---|---|
| ① | boundary L141 `Random(1)` → seeded_rng | test_battle_boundary.py L128 注入 fixture、L139 `rng=seeded_rng()` | ✅ 断言与种子无关：唯一非绑定候选、掉 1 件必掉「a」，任何种子结果相同 |
| ② | damage_gaps L79 `Random(42)` → 注入 | test_damage_gaps.py L74-82 `ctx(seeded_rng)` 缺省 `v.setdefault("rng", seeded_rng())` | ✅ assertions 由显式 `rng=1.0/0.9/1.1` 或 force/拦截短路驱动；拦截链无 proc 路径不消费 rng（effects.py L535/1376 仅 proc/status 路径） |
| ③ | effects_runtime L60 `Random(42)` → 注入 | test_effects_runtime.py L58-66 | ✅ 同上；L143 反射子 ctx 由 `is_reflect_damage=True` 短路 |
| ④ | effects_gaps L70 `Random(42)` → 注入 | test_effects_gaps.py L66-74 | ✅ 同上；d4 Mount 拦截先于命中 roll（reason=immune_mount 与 roll 无关） |
| ⑤ | monster_ai L190 `Random(20260826)` → seeded_rng | test_monster_ai.py L186-188 | ✅ **严格逐位等价**：原种子 == DEFAULT_SEED，20k 样本序列不变，容差断言无漂移 |
| ⑥a | battle_engine `random_seed=11..27` → seed fixture | test_battle_engine.py 全 20 用例 `def ...(seed: int)` + `random_seed=seed` | ✅ 决策序列不变：`make()` 先注入 QueueRNG，battle.py start() L875-876 `isinstance(self._rng, random.Random)` 守卫保留非 Random 实例；`_rng_seed` 仅作快照元数据（L921/L1771）不驱动决策 |
| ⑥b | wiring L115 `random_seed=42` → seed fixture | test_battle_wiring.py L115-121 `start_battle(seed)`，`random_seed=seed_` | ⚠️ **静态不可证**（见 P2-1）：真实 `Random(20260826)` 取代 `Random(42)`，命中/逃跑为概率分支，断言（"✅ 你攻击"/"❌ 逃跑失败"）依赖具体 roll 落点 |

六处文件内均无 `random.Random(N)` 字面量残留（grep 仅 docstring/注释提及）→ **TC-SED-02 ✅**。

### 1.4 禁裸随机（SED-7 / TC-SED-05）——✅ 确认

全仓 tests/ grep `random\.(random|uniform)\(`：**0 命中**（conftest 亦无）；七个文件内随机一律经
`seeded_rng()`/`ScriptedRng`/`QueueRNG`/`AlwaysZero/AlwaysHigh` 桩注入。TC-SED-01（fixture 可注入）
✅、TC-SED-04（property 用例复用 seeded_rng + formula_params，test_formula_property.py L272/301/356/429）
✅、TC-SED-03（一处生效：seed 唯一入口 = DEFAULT_SEED）✅ 结构性成立【静态推导】。

### 1.5 FIX 验收对照——✅ 主要项成立

- TC-FIX-01 ✅（27 键全落，值=表默认）；TC-FIX-02 ✅（test_damage.py L134-155
  `test_formula_params_fixture_matches_segments` 对照测试，抽样项 hit.k/crit.cap/block.k/defense.k/
  weakness.type_mult 全含，另覆盖 20+ 字段）；TC-FIX-04 ✅（`test_formula_params_defaults` 已删除，
  由对照测试承接）；TC-FIX-05 ✅（battle.py L326-331 FIX-6 登记注释在位）——⚠️ 文档同步缺口见 P2-3；
  TC-FIX-06 ✅ 结构上不阻塞（validator 对段级参数容器透传，L1493-1496 登记归 T01）——见 P2-6。

## 二、维度② 代码质量（审查通过项 + 观察项）

- **迁移只改注入形态不改断言值**：①⑤ 严格成立；②③④ 经 rng 消费点静态分析成立【静态推导】；
  ⑥a 成立（isinstance 守卫证据）。⑥b 需实跑（P2-1）。
- **RNG 状态串扰**：无。function 级 fixture + 每次调用全新实例；无模块级共享 Random。
- **派生种子确定性**：`Random(seed + offset)`；test_formula_property 以 offset=1/2/3/8 与工厂
  交互一致 ✅【静态推导】。
- **formula_params 缺段回退**：`_f` 对缺失段/缺失键/显式 null 一律回 dataclass 默认，不抛错
  （D6 §3.4）✅。观察项：rng/tier_p 数组长度不校验（单元素数组静默成 1-tuple，后续下游 unpack
  才暴露；契约未要求，validator T01 承接）；`bool("false")` 字符串陷阱（fixture 包用真布尔，无实害）。
- **死导入**：test_effects_runtime.py L9 `import random` 已无使用（P2-7）。

## 三、维度③ 遗漏与接缝（问题明细 P1/P2）

### P1-1｜SED-3/SED-5 全仓规则残留：清单外 ~10 文件 16 处未迁移、且无登记承接
D6 SED-3「禁止在用例体内新建 `random.Random(N)` 字面量」与 SED-5「battle
`start(random_seed=N)` 的 N 一律来自 seed fixture」为**规则表级全仓约束**（非仅六处清单），
本批仅覆盖 2.2 清单六处，以下残留既未迁移也未在 D6 §八/批文档登记后续批次（孤儿项风险，
【总纲】TC-M6-12）：
- `random.Random(N)` 字面量：tests/unit/test_npc.py L181/191/202/326/327/530
  （12345/7/1/9/9/0）、test_shop.py L168（42）、test_m1_review_fixes.py L51/114（42/i）；
- `random_seed=` 魔法数（battle start 类）：test_snapshot_resume.py L272（42）、
  test_m43_regression.py L179（42）、test_marks.py L105/113/122（9）、test_combo.py L133/144（1/2）、
  test_monster_ai_battle.py L321/332（9/7；L154 已用 seed，同文件新旧并存）、
  test_battle_snapshot_generation.py L29/36/42/48/57/74（11~15）、test_m2_review_fixes.py L217（1）；
  （test_storage.py L180/182/266 为存档行 random_seed 数据语义，非 start()，不在此列。）
- **修复建议**：① 后续批次（批6B）按「派生子种子」逐文件迁移（test_monster_ai_battle L154 已有
  先例），或 ② 立即在 D6 §八 追加登记「清单外残留待批6B 承接」，否则规则悬空且 grep 型验收
  （TC-SED-02 文本）长期与规则背离。

### P2-1｜迁移⑥b（test_battle_wiring）断言种子敏感性【静态推导，需实跑】
种子 42→20260826 改变真实 RNG 序列，而 wiring 断言落在概率分支上：攻击命中率 ≈71.4%
（foc/spd，K=1）、miss 将改写"✅ 你攻击"行（P2-8 同类：逃跑失败分支 9.1%）。SED-4「断言值
不变」对⑥b 仅靠**一次实跑**成立（TC-SED-03 / verify_m5 ④b）。本环境禁运行，无法静态证明。
**修复建议**：跑一次 `pytest tests/unit/test_battle_wiring.py + test_battle_engine.py` 全绿即闭合；
若红，将 wiring 用例改为注入确定性桩 rng（QueueRNG 模式）或改用 `seed` 派生种子复查。

### P2-2｜FIX-3 残留：部分测试仍硬编码公式参数字面量（TC-FIX-03 未闭环）
- test_damage_gaps.py L145 `pierce_pct("blunt") == 0.2`（断言生产函数内置默认 0.2，性质同
  FIX-4 已删的默认断言一类）；L257/259 会心 `2.2` 字面量（=crit.tiers.high 默认）；
- test_battle_engine.py L54 crit 倍率 `1.3` 字面量（=crit.tiers.low 默认）。
当前 fixture 值==默认值故行为等值，但违反 FIX-3「参数一律经 formula_params 注入」与 TC-FIX-03
全仓清零目标。
**修复建议**：后续批统一改为 `P.crit.tiers.high` / `p.type_affinity.blunt_pierce` 引用，或逐处登记豁免。

### P2-3｜文档漂移：battle.py FIX-6 注释引用落空
battle.py L330「文档口径由 D6 §八 登记承接」，但 D6 §八（L361-367）仍为「默认采纳 FIX-5」，
**无 FIX-6 已采纳的追加登记**——实现选了 FIX-6，契约文档未同步（违反 D6 变更纪律「禁止静默
改语义」的登记要求）。
**修复建议**：D6 §八 补一行：批6A 采纳 FIX-6，段级参数当前仅默认值，生产装配归实现层 T01。

### P2-4｜test_formula_property.py 头注失实（路A 落盘后未清理）
L29-33 仍声明「本地 fixture 暂驻」「formula.json 当前仅 damage_base/heal_rate 两键」——实际
本地 fixture 段已删除（用例直接消费 conftest 三 fixture，无遮蔽、无双源，功能无害），且
formula.json 已全段落位（本批所为）。失实注记会误导后续诊断。
**修复建议**：删除/改写头注 L29-33 为「路A 已落盘，fixture 来自 conftest」。

### P2-5｜脚本侧种子双源（SED-8 精神未全量）
e2e_m6_smoke.py L54 `SEED = 20260826` 值已同步 ✅；但 verify_m5.py L505 仍 `random_seed=42`
（与 test_battle_wiring 迁移后 20260826 同场景双源）、verify_m1.py L66-67/97/196/207/219-222、
verify_m2.py L142/181/203、e2e_m4_smoke.py L239、e2e_m3_smoke.py L457/462 各自内联常量。
D6 SED-8 要求脚本侧读同一常量源，防双源漂移。
**修复建议**：verify 脚本侧统一引用 `tests.conftest.DEFAULT_SEED`（或登记豁免为验收入口固定值）。

### P2-6｜FIX-8 段参数红黄校验未实现（登记已存在，观察项）
validator.py L1493-1496 对段级参数容器「透传不红拦」，hit 0.05-1 / cap 10-100 等 15 条段参数
红黄校验明确登记归实现层 T01。本批不阻塞（legal 包可全绿），但 FIX-8 验收依赖 T01 批次落地，
建议 D6 §八 同步一笔转归。

### P2-7｜死导入
test_effects_runtime.py L9 `import random` 已无符号使用（迁移后遗留）。

### P2-8｜effects.py 生产侧裸随机回退（观察项，不在本批范围）
effects.py L536/L1377 在 ctx 无 rng 注入时回退 `random.random()`。测试路径已全部注入
（TC-SED-05 不受影响）；生产兜底属引擎契约外，登记观察，建议后续批次改为引擎 `_rng` 注入。

## 四、无问题维度确认

- ✅ D6 契约落地：SED 三 fixture、F-FIX-01~27 三方一致（文档表 vs formula.json vs damage.py 默认）、
  六处迁移 ①~⑥a 断言等价（静态推导）、TC-SED-01/02/04/05、TC-FIX-01/02/04/05 全部成立；
- ✅ 代码质量：RNG 状态隔离（function 级+新实例）、派生种子确定性、缺段回退语义、frozen 共享安全；
- ✅ 既有测试接缝：test_damage.py 默认断言已删并替换为对照测试；property 用例消费 conftest
  三 fixture（无本地遮蔽）；QueueRNG 注入与 start() 的 isinstance 守卫兼容（battle.py L875-876）；
  base_attack_mult/monster_def_rate 生产消费点存在（battle.py L1387/L1395）。

## 五、Top 3（并收录批 6A 复核清单）

1. **P1-1** 清单外 SED 残留（10 文件 16 处）未迁移未登记——立即登记承接或批6B 迁移；
2. **P2-1** 迁移⑥b wiring 种子变更后断言未实跑验证【静态推导：命中 71.4%/逃跑失败 9.1% 分支敏感】——
   一次 `pytest tests/unit/test_battle_wiring.py` 全绿即闭合；
3. **P2-3/4** 文档漂移三连（D6 §八 无 FIX-6 登记、battle.py 注释引用落空、property 头注失实）——
   随批 6A 收尾一并更新。