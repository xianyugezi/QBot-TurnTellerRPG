# QBot-TurnTellerRPG

QQ 回合制 RPG 框架 = 平台无关核心包 `qbot_rpg`（core/world/storage/content/data 零 NoneBot）+ 壳层 `commands`（唯一适配器）+ `web`（编辑器外壳）。

## 目录
- `qbot_rpg/` — 平台无关核心包（细化_3a §2.1 七层）
- `tests/` — 测试金字塔（unit/integration/contract/e2e/fault）
- `scripts/verify/` — 里程碑验收脚本 verify_m0~m6
- 实现依据：仓库内 `细化_*.md`（72 份契约）+ `/root/docs_archive/RPG框架项目/`（39 份定稿）

## 快速起步
```
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # 全量单测
python scripts/run_all_tests.py --only m0   # M0 里程碑验收
```
