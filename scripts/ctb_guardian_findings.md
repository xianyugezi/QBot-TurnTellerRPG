# CTB 契约守卫 · 发现清单（Agent 6）

> 产出 Agent：Agent 6 · 契约守卫（Guardian）
> 仓库基线：`9ef3ce2`（tag `pre-ctb-rewrite`）
> 硬约束遵守：**只在 `tests/` 与 `scripts/` 写文件**，未改 `qbot_rpg/` 任何业务代码。
> 关联测试：`tests/ctb/test_ctb_blackbox_sequences.py`

---

## F1【重要 · 待裁决】黑盒场景 2 `P→E→E→P` 口径歧义

### 事实

| 场景 | 参数 | 需求期望 | 实测（recovery=150 作总恢复值） |
|---|---|---|---|
| 基础 | P SPD=100 / E SPD=75 / 普攻 recovery=100 | `P→E→P→E→P` | ✅ **复现成功** |
| 慢技能 | 重技能 recovery=150 | `P→E→E→P` | ❌ 实得 `P→E→P→E` |

### 推演（speed_reference=100, min_speed=1, action_delay=0）

```
ready(P)      = 0   + 100*100/100 = 100.0
ready(E1)     = 0   + 100*100/75  = 133.333…
ready(E2)     = 133.333 + 133.333 = 266.667
场景2 P 用重技能后：ready(P2) = 100 + recovery * 100 / 100 = 100 + recovery
```

要形成 `E→E` 连动，须 `ready(P2) > ready(E2)`：

```
100 + recovery > 266.667  →  recovery > 166.667
```

- **recovery = 150（技能总恢复值直读）** → `ready(P2)=250 < 266.667` → 玩家抢先 → `P→E→P→E` —— 与需求不符。
- **重技能 = 基础 100 + 附加 150 = 250（加算解释）** → `ready(P2)=350 > 266.667` → `E→E` 连动 → `P→E→E→P` ✅。

### 结论

`recovery` 语义需在以下二者间拍板：

1. **总恢复值**：技能 recovery 直接替换基准 100。此解释下 `recovery=150` **无法**产出需求期望序列 → 需求文档的 150 数值或公式口径有误。
2. **基础之上附加**：`recovery = 普攻基准 100 + 技能附加 150 = 250`。此解释下 `P→E→E→P` 成立。

> 当前 `ctb_rules.recovery_for()` 的实现是**解释 1**（自带 `recovery` 键直接返回，不叠加基准）。
> 若定稿为解释 2，则 `recovery_for` / 内容包 `recovery` 键语义须同步调整（属 Agent 3/内容包范围）。

测试标记：`tests/ctb/test_ctb_blackbox_sequences.py::test_slow_skill_sequence_hard_indicator`
以 `xfail` 暴露该歧义；`test_slow_skill_additive_recovery_yields_expected_sequence` 证明解释 2 可行。

---

## F2【接口缺口 · 调度器】`CTBScheduler` 无法按 action 注入 recovery

### 事实

`qbot_rpg/core/ctb_scheduler.py:318-326` `_schedule()` 固定：

```python
action = {"recovery": self._rule.default_recovery}
view.next_ready = next_ready(base, action, view.effective_speed, self._rule)
```

- 仅使用 `default_recovery`，**无 per-action recovery 入参**。
- 公开 API（`push_actor` / `advance_to_next_ready` / `complete_player_action`）均无注入某次行动 recovery 的通道。

### 影响

- **场景 2 无法经调度器公开 API 产出**（慢技能的重 recovery 无处传入）。黑盒用例改在**规则层**用官方公式 `next_ready()` 复算，结论与公式一致。
- Agent 3 接引擎时，玩家/怪物技能 recovery 必然来自 action def；调度器需提供注入点（如 `complete_player_action(recovery=...)` / `resolve_action(actor_id, action=...)`）。

### 建议

给调度器补一个「按行动 recovery 重排」的公开入口，或在 `complete_player_action` 增加 `action` 参数；否则「行动恢复值可配」的设计无法落地。

---

## F3【基线漂移 · 良性】mypy 误差数下降

- `qa_ctb_baseline_mypy.txt`：**32 errors**（7 files）。
- 当前实测：**24 errors**（5 files）。

误差**只减不增**，减量来源是 Agent 2 新增的 `ctb_rules.py` / `ctb_scheduler.py` 无 mypy 误差，且 `battle.py` 部分历史误差计数变化。门禁脚本按「**只允许减少不允许新增**」比对，当前 PASS。

> 注：任务书给出基线 32，实际 24，属「减少」，符合门禁方向。若需对齐快照，重跑 `qa_ctb_baseline_mypy.txt` 即可（本次未覆盖快照文件，只读比对）。

---

## F4【回归 · 阻断全量单测】M43 零定时器扫描被 `ctb_scheduler.py` 击中

### 事实

`tests/unit/test_m43_regression.py::test_m43_zero_timer_repo_wide_scan` **FAIL**：

```
M43① 零定时器违反：{'qbot_rpg/core/ctb_scheduler.py': ['sched', 'schedule', 'threading', 'time.sleep']}
```

- 扫描规则（`test_m43_regression.py:53`）：
  `re.compile(r"time\.sleep|\bthreading\b|\bTimer\b|\bschedule\b|\bsched\b")`，扫描范围 `qbot_rpg/**`。
- 命中来源：`ctb_scheduler.py` 的 **docstring/注释** 出现 `time.sleep` / `threading`，
  且代码内大量使用 `sched` 变量与 `_schedule`/`re-schedule` 命名。
- 扫描范围仅 `qbot_rpg/**`，**不含 `tests/`、`scripts/`**——故 Agent 6 的新文件不触发本失败。

### 影响

- 任务书所述全量基线「6190 passed / 0 failed」**当前已不成立**：至少 1 failed。
- 该失败**先于 Agent 6 工作存在**（由 Agent 2 的 `ctb_scheduler.py` 引入），非本轮新增。

### 建议（不动业务代码，供 Agent 2/3 处置）

三选一：
1. 改写 `ctb_scheduler.py` 中的标识符（`sched` → `engine`/`scheduler` 会再命中？注意 `\bsched\b` 为词边界，`scheduler` 不含 `sched` 词；可用 `ctb` / `tick_source` 等）；并把注释里的 `time.sleep`/`threading` 改为中文描述（如「真实计时器」「线程」）。
2. 在 `test_m43_regression.py` 的 `_ALLOWED_TIMER_TOKENS` 允许清单中显式登记 `ctb_scheduler.py` 的**注释级**命中（需逐条自证非计时用途）。
3. 让 M43 扫描忽略 docstring/注释（较大改动，不推荐本轮做）。

> **优先级：高**——它阻断「全量单测绿」这一交付验收线。

---

## F5【观察】`battle_state()` 的 `turn` 键位置

当前 `battle_state()` 含 `turn`（回合数），且**不在** `units` 子结构下——是顶层键。CTB 契约要求去除 `turn` 并补 `battle_time`/`action_seq`（见 `test_ctb_contract_interfaces.py::TestBattleStateContract`）。已标 xfail 待 Agent 3。
