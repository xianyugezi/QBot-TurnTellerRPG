# veinborn 开发期 · 框架引擎缺口登记与修复（2026-09-02）

> 性质：veinborn 精简验证包开发期发现的三处框架引擎缺口（非 veinborn 数据问题），
> 用户拍板「可以，那处理吧」→ 三路子 agent 并行修复中。
> 状态：G1/G2/G3 各自子 agent 实施中；完成后本文件回填 diff 摘要 + 回归结果。

## 背景

veinborn content 包 build_pack 零红拦、数据全对，但完整玩法被三处引擎缺口挡住：

| # | 缺口 | 现象 | 根因 | 影响 |
|---|---|---|---|---|
| G1 | 派生技结算不跟随 | 破脉核链派生成功但伤害 12（源技能 0.6×）非 200（破技 2.0×），core_broken 不挂 | battle.py `_resolve_combo_action`：form_id 替换只改 `ca["skill_id"]`，sd/mult/effects 不重解析（L1910 开头解析一次） | 部位破坏派生链无法工作（veinborn 核心机制） |
| G2 | consume_marks 无运行时 | 破技 consume_marks {break_vein_core:120} 从不执行 | 全库无消费方（仅 content 访问器+校验器 V-3） | 破坏值不清零、破技可无限放；test_demo heavens_smash 同受影响 |
| G3 | 实机无开战入口 | /调查 只出文本、/攻击 报无战斗、/锁定 是 stub | ctx["start_battle"]/["battle_engine"] 从未注入（context.py L1154 硬编码 None）；无任何代码调 session_mgr.acquire("battle") | 实机无法从指令发起任何 PvE 战（demo 包同样） |

## 契约/拍板依据

- **G2 语义**：contract_deviations.md §六 S-01（用户 2026-08-23 拍板）——
  consume_marks「无印被拒」副作用 = **完全免费**：不耗 MP、不耗行动、连段保留
  （符合 P1-5「被拒不耗回合不改连段」先例延伸）。测试断言「拒了=啥也没发生」。
- **G3 设计**：每指令 make_context 重建 ctx → BattleEngine 需跨指令存活，
  走 session_mgr acquire("battle") + battle.py to_snapshot()/from_snapshot() 快照续战
  （M11 PVP 持久化遗留同款方案）。

## 修复方案（子 agent 实施中）

### G1 · battle.py 派生后重解析
派生替换分支（form_id 替换处）后补：sd 重新 resolve 派生技 + mult 重折算
（未显式给定则新 power/100）+ ca["effects"] 换派生技 effects。非派生路径零变化。

### G2 · consume_marks 运行时消费
技能施放成功时读 sd.consume_marks（{mark_id: count}），检查并扣除目标侧印记；
不足 → 免费被拒（S-01）。无 consume_marks 技能零变化。

### G3 · 实机战斗发起
context.py：注入 ctx["start_battle"]（创建 battle session + BattleEngine.start 落
session_mgr）+ 每指令从活跃 battle session 恢复引擎注入 ctx["battle_engine"]。
router_setup.py：/锁定 stub → 真实开战指令（当前地图第一只活动怪物）。

## 回归门禁

- 每个子 agent：先跑基线 → 最小改动 → 新测试 → 全仓 `pytest tests/unit -q`（5500+）零破坏
- 完成后主 agent：全仓回归 + ruff/mypy + veinborn 冒烟全链 + 实机 e2e

## 回填区（子 agent 完成后填）

- [ ] G1 diff 摘要 + 测试 + 回归
- [ ] G2 diff 摘要 + 测试 + 回归
- [ ] G3 diff 摘要 + 测试 + 回归
- [ ] contract_deviations 登记
