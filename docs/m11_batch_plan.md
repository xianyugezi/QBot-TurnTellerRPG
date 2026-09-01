# M11 批次派工单（成就图鉴PVP · 每批 3 路并行）

> 依据：docs/m11_启动包.md（M11=4c 成就 + 4d 图鉴聚合 + 4e PVP 玩家互斗）
> 批次节奏：每批 3 路并行（≤3 合规）→ 主 agent 收口（lint+回归+提交）→ 下一批，不叠批
> 前置：批0 含 M10 钓鱼收尾（冒烟修复）作为 M11 开胃

## 批0 · M10 钓鱼收尾 + M11 摸底（3 路）

| 路 | 任务 | 交付 | 依赖 |
|---|---|---|---|
| 0A | verify_m10_smoke.py 冒烟修复（/进入 幽光林地 → 全链路跑通） | scripts/verify_m10_smoke.py 改 + /tmp/fishingflow.txt 全 PASS | 无 |
| 0B | 4c 成就系统摸底侦察（细化全文 + 接口盘点 + 契约摘要） | docs/m11_成就摸底.md | 无 |
| 0C | 4d 图鉴聚合摸底侦察（四册差距 + 加权 + lore 缺口） | docs/m11_图鉴摸底.md | 无 |

## 批1 · 4c 成就数据层（3 路）

| 路 | 任务 | 交付 |
|---|---|---|
| 1A | 成就引擎（条件四类映射 + reward 统一 + 称号联动 + 状态持久化 + 幂等） | core/achievements.py + test_achievements.py |
| 1B | 成就校验器 ACH-01~13 + loader/field_meta 登记 + fixtures | content/achievements_models.py + achievements.json + 测试 |
| 1C | 成就指令（/成就 /成就信息 /称号 查看 /称号 佩戴）+ 注册白名单 + 模板分区 | commands/achievement_commands.py + achievement_tpl.py + 测试 |

## 批2 · 4d 图鉴聚合（3 路）

| 路 | 任务 | 交付 |
|---|---|---|
| 2A | craft 册收敛 + 四册数据驱动归属 + 隐藏要素归册 | codex.py 扩展 + 测试 |
| 2B | 加权完成度 + 权重配置 + param 分册条件键 | codex.py 扩展 + 测试 |
| 2C | lore 情报解锁 + /图鉴 展示更新（总览进度条/分册/冠级/lore 行） | codex.py + codex_commands.py + 测试 |

## 批3 · 4e PVP + verify（3 路）

| 路 | 任务 | 交付 |
|---|---|---|
| 3A | PVP 引擎（/锁定玩家 /攻击玩家 + 偷袭战斗中玩家 + 结算 + 防刷） | core/pvp.py + 测试 |
| 3B | PVP 指令壳 + 注册白名单 + 模板 | commands/pvp_commands.py + 测试 |
| 3C | verify_m11.py 门禁（成就 22 TC + 图鉴 25 TC + DELAYED 复核） | scripts/verify/verify_m11.py |

## 批4 · 收口（主 agent，非并行批）

- 全仓回归 + ruff/mypy/G0/M43 + 硬计数断言同步
- dsh 审查（A1 成就 / A2 图鉴 / A3 PVP 分功能点）
- 部署实机验证（钓鱼 + 成就 + 图鉴 + PVP 链路）
- 记录.md 同步 + M11 收官

## 铁律（每路子 agent 必带）

1. 先读真实代码再写结论（契约建立在真实实现上）
2. 行号引用前验证在文件范围内（防编造）
3. 新文件 docstring 勿写定时器函数字面量（M43 探针）
4. emoji 纪律：仅 ✅/❌ 功能性标记 + 排版符号
5. 模板配置化：新增消息走 tpl_of 分区
6. 交付必过 lint（ruff/mypy）再交，自报不可信
7. 不 commit，交主 agent 收口统一提交
