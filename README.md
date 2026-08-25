# QBot-TurnTellerRPG

QQ 回合制 RPG 框架 = 平台无关核心包 `qbot_rpg`（core/world/storage/content/data 零 NoneBot）+ 壳层 `commands`（唯一适配器）+ `web`（编辑器外壳）。

## 目录结构

```
qbot_rpg/          平台无关核心包（细化_3a §2.1 七层：core/world/storage/content/data + commands/web）
tests/             测试金字塔（unit/contract/e2e；每模块配套 test_模块名.py）
scripts/           里程碑验收脚本 verify_m0~m6 + 架构门禁 check_architecture
docs/
  细化/            实现契约 76 份（细化_1a~6c）
  规划/            实现规划 21 份（规划_路1~3）+ 实现层规划文档
  审查/            幻觉审查 72 + 覆盖审计 8 + 总结论
  审查报告/        里程碑复查报告 31 份（M0/M1 复查，dsh 审查）
  仲裁/            仲裁决议汇总 + 差距清单
  实现层启动手册.md   → 新手入口（先读这个）
  细化规划总索引.md    → 文档总索引
contract_deviations.md   契约偏差登记（M0 未实现/收敛/跨文档冲突）
记录.md            通用规则①：已完成/下一步/未完成工作记录
```

## 快速起步
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 依赖锁定（规则⑧）
pytest            # 全量单测
python scripts/run_all_tests.py   # 全量回归 + M0 门禁
```

## 文档入口
- 新接手先读 `docs/实现层启动手册.md`，再按 `docs/细化规划总索引.md` 定位细化契约
- 实现依据：`docs/细化/`（76 份契约）+ `/root/docs_archive/RPG框架项目/`（39 份定稿）
