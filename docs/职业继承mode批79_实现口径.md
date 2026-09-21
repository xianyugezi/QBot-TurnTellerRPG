# 职业继承 `mode`（替换/追加）· 批79 实现口径

> 目标：`docs/矛盾与待裁决登记.md` **X18** 销项（用户 2026-09-23 裁决）。
> 配套设计口径：`docs/进阶职业继承_设计口径.md` §5「用户裁决回填（Q1~Q4）」。
> 基线：main 最新 `930b858`（分支 `w-g40`）。

---

## 1. 用户裁决（照此实现，不自行加戏）

| 维度 | 裁决 | 本批动作 |
|---|---|---|
| ① 继承粒度 | **保持传递闭包**（A→B→C 时 C 继承 B 与 A） | **不改**（批35 现状即口径） |
| ② `skills` 白名单 | **保持**（空=全部；非空=只列出的） | **不改** |
| ③ `mode` | **新增**：`append`（默认=现状）与 `replace` | **本批实现** |
| ④ 技能等级继承 | **不做**（技能无等级维度；另立设计） | **不做**（仅文档注明） |

## 2. 字段形态（`jobs[].inherit`，进阶职一侧）

```jsonc
{
  "from":    "mage",                       // 母职（批35，必填）
  "skills":  ["mage_shield"],              // 可选白名单（批35；空/缺省 = 全部职业专属技能）
  "mode":    "replace",                    // 批79：append（缺省）/ replace
  "replace": { "mage_shield": "fire_ward" } // 批79：{母职技能id: 本职业技能id}；空 = 等价 append
}
```

- `mode="append"`（缺省） = 现状：母职继承技能 + 本职业自身技能**累加**；
- `mode="replace"` = 用本职业技能**替换**母职继承来的指定技能（`replace` 映射）；
- **只影响继承来的技能**：键未落在继承集 → 该项不生效；不动全局技能注册表；
- **未声明的技能照旧继承**；`replace` 空/缺省 = **等价 append**。

## 3. 引擎（`qbot_rpg/core/job_slots.py`）

- 常量：`INHERIT_MODE_KEY` / `INHERIT_REPLACE_KEY` / `INHERIT_MODE_APPEND` /
  `INHERIT_MODE_REPLACE` / `INHERIT_MODES`（`:106-118`）。
- `inherited_skill_ids`（`:162-207`）在批35 继承集之上调用 `_apply_inherit_replace`
  （`:210-241`）：
  - 键命中继承集 → 从结果移除；值（本职业替代技能 id）按声明顺序并入（去重）；
  - 键不在继承集 → 忽略。
- `_inherit_mode`（`:243-253`）：非 `"replace"` 一律 `"append"`（未知值黄提示在前，引擎取安全默认）。
- `_inherit_replace_map`（`:255-262`）：只收「两侧均非空字符串」的键值对（畸形项交校验器红拦）。
- **零行为变化**：`mode` 缺省/`append`/未知、`replace` 空 → 返回与批35 **逐字段一致**的元组
  （`_apply_inherit_replace` 首行短路）；`rearrange_job_slots`/`assemble_slots` 入口不变。

## 4. 校验（`qbot_rpg/content/job_validator_v58.py` V9，`:505-552`）

| 情形 | 判定 | 级别 |
|---|---|---|
| `mode` 为未知**字符串** | `inherit_mode_unknown` | **黄提示 Y-23**（不硬拦；引擎按 append） |
| `mode` 非字符串 | 泛型 `type=str` | 红拦 R-1（既有风格） |
| `replace` 非对象 | 泛型 `type=obj` | 红拦 R-1 |
| `replace` 键/值悬空 skills id | `replace_ref_missing`（detail 带 `role=key|value`） | 红拦 R-4 |
| `replace` 键/值非字符串 | `replace_not_str` | 红拦 R-1 |
| 缺 `inherit` / 缺 mode / 缺 replace | — | 零红零黄（既有数据零变化） |

`inherit.from` / `inherit.skills[]` 的 R-4 由既有泛型 field_meta 登记（批35）继续负责。

## 5. 字段元数据（两张表 + 编辑器）

- `qbot_rpg/content/field_meta.py:2578-2600`（编辑器权威表）：
  - `mode`：`type=str` + `editor=select` + `enum_options=("append","replace")`，
    label「继承模式」、help「追加=母职与本职业技能都装（默认）；替换=按下方映射换掉指定的继承技能。」
    （≤60 字；开放词汇不做泛型 enum 红拦）；
  - `replace`：`type=obj` + `editor=kvtable`（对象内联可编辑键值表）、label「继承技能替换」、
    help「替换模式下：键填母职技能 id，值填本职业替代技能 id；留空等同追加。」
- `qbot_rpg/content/job_models.py:387-394`（`jobs_fields()` 数据表）同步登记 mode/replace。
- 编辑器可见：`api.entry_detail` 的 `inherit.children` 含 `mode`（`control=select` +
  `enum_options`，前端 `objLeafInput` 按 `enum_options` 渲染下拉）与 `replace`
  （`control=kvtable`，前端 `objKvEdit` 内联编辑）；label/help 齐备。

## 6. 验收与证据

- 回归：`tests/unit/test_batch79_inherit_mode.py` **17 passed**
  （A 引擎三态/替换生效/未声明仍继承/零变化对拍；B 校验红黄；C 编辑器可见）。
- 既有断言同步：`test_batch35_job_inherit.py` / `test_job_models.py` /
  `test_m13_hard_counts.py`（inherit children 2 → 4、并集 41 → 43）。
- 全量：`pytest tests/ -q -o addopts=""` 0 failed；`ruff` 干净；`git status --porcelain` 空；
  `scripts/editor_verify_packs.py`（换包验收）全 PASS。
- 页脚批次串 →「批79 · 职业继承 mode」，全部批次串断言同步；
  迁移对拍基线重定（`scripts/compare_field_meta_migration.py` + 测试内 `BASELINE_REF`）。

## 7. 未完成 / 存疑

- **技能等级继承不做**（用户裁决 ④）：需先立「技能等级维度」系统级设计，本批不触碰。
- `replace` 的语义按用户给的建议形状落地（`{母职技能id: 本职业技能id}`）；设计口径文档
  原 §5 曾写「不实现 mode」，本批已按裁决回填 §5 与 §4，无冲突残留。
- 未在 `job_inherit_summary`（职业树只读卡片）新增 mode/replace 展示列——字段级编辑已可见，
  树卡片的最小展示维持批35 口径（避免顺手扩面）。
