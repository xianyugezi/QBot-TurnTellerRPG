# M6 内容包冒烟归档（docs/verify/m6_smoke.md）

> 归档物模板（D4《细化_M6_内容包冒烟》§四 SMK-16 + ADR-10：归档路径统一 docs/verify/）。
> 本文件 = **归档物结构定义**（F-01~05 五段内容物），写入者 = verify_m6（D8 统一归档）或冒烟脚本自身
> （独立可运行时不依赖 verify_m6，ADR-D4-03 双轨）。本批（M6 批4·路B）只定义内容物与目录，
> 实际写入由 D8 verify_m6 落实。
> 零 NoneBot；确定性重放口径见 F-06（FIXED_NOW / SEED，D4 §六 6.2）。

---

## F-01 · 归档文件说明

- 路径：`docs/verify/m6_smoke.md`
- 写入者：verify_m6（D8 统一归档）或冒烟脚本自身（ADR-D4-03 双轨）
- 触发：M6 内容包冒烟（`scripts/e2e_m6_smoke.py` / verify_m6 段一「冒烟闭环」）跑完一次即覆盖写入
- 每次运行全量覆盖（保留最近一次确定性结果）

---

## F-02 · 归档段① validator 报告

> 语义：四件套逐包 + 五档包逐档的红/黄/绿计数与失败清单（SMK-12/16 / PCK-04）。
> 写入者产出：

```text
[validator 报告]
-- 四件套（tests/fixtures/packs）--
legal        : 0 红 / 0 黄 / 绿
badref       : PackLoadError（R-1/R-2/R-4/R-5）· registry 未污染
missing_mod  : 0 红 / 1 黄（Y-6 statuses）/ 绿（软放行）
old_schema   : 0 红 / 0 黄 / 绿（容忍加载）
-- 五档包（content/*）--
demo_blank   : 0 红 / 0 黄 / 绿（仅装配不战斗）
demo_lv15    : 0 红 / 0 黄 / 绿
demo_lv30    : 0 红 / 0 黄 / 绿
demo_lv45    : 0 红 / 0 黄 / 绿
demo_full    : 0 红 / 0 黄 / 绿
-- 失败清单 --
（无失败时填「无」）
```

---

## F-03 · 归档段② 断言计数

> 语义：SMK 各路径断言数 + 运行级断言数 + 总数（SMK-05/16）。
> 写入者产出（冒烟脚本按 Smoke.check/check_eq 收集器实计）：

```text
[断言计数]
SMK 四步路径（注册/锁定/攻击/结算）：N / M / K / J
validator 矩阵（四件套 + 五档包）  ：N
运行级确定性断言                    ：N
总断言数                          ：T（= 上述合计）
```

---

## F-04 · 归档段③ 确定性重放结果

> 语义：两次运行摘要逐字一致（一致/不一致）（SMK-03/16）。
> 写入者产出：

```text
[确定性重放]
FIXED_NOW: 2026-08-01 12:00 UTC+8
SEED     : 20260826
第一次摘要: <sha256 或摘要前 64 字符>
第二次摘要: <sha256 或摘要前 64 字符>
结果     : replay_identical=True（两次逐字一致）/ 或 False + 差异定位
```

---

## F-05 · 归档段④ 五档包明细

> 语义：每档模块集 / 黄提示记录 / 是否模拟一局（PCK-04/05/06/10 / SMK-16）。
> 写入者产出（模块集以 content/*/manifest.json 为准动态扫描）：

```text
[五档包明细]
demo_blank（空白）  : 模块集={settings,stats,formula,effects,items} · 黄提示=无 · 模拟一局=否（无怪只装配 PCK-06）
demo_lv15（新手 1-15）: 模块集={...11 模块} · 黄提示=无 · 模拟一局=是（rock_weasel）
demo_lv30（成长 1-30）: 模块集={...12 模块} · 黄提示=无 · 模拟一局=是
demo_lv45（进阶 1-45）: 模块集={...16 模块} · 黄提示=无 · 模拟一局=是
demo_full（完整）   : 模块集={...16 模块} · 黄提示=无 · 模拟一局=是（含 ember_drake boss）
```

---

## F-06 · 冒烟确定性常量（D4 §六 6.2，【工程补白】）

- `FIXED_NOW = 2026-08-01 12:00 UTC+8`
- `SEED = 20260826`

---

*模板结束：以上 F-01~05 为归档物五段内容物定义；实际数据由 D8 verify_m6 / 冒烟脚本写入。*
