# veinborn G1 派生结算缺口修复（veinborn_G1派生结算修复）

- 日期：2026-09-02
- 范围：`qbot_rpg/core/battle.py` `_resolve_combo_action` 派生分支（唯一改动文件）
- 关联：docs 引擎缺口登记 G1（f979850）——破脉核派生链 `chain_core_break`
  （`rb_core_strike`→`vb_core_breaker`，mode=replace，condition
  target_marks break_vein_core min:120）

## 一、缺陷现象（修复前）

派生（form_id 替换）成功后，**伤害/效果按源技能 def 结算**：

| 观察项 | 修复前 | 期望 |
| --- | --- | --- |
| 伤害 | 12 ≈ 源 `rb_core_strike` power 60 → mult 0.6× | `vb_core_breaker` power 200 → 2.0× |
| effects | 源 `mark_add break_vein_core 20` **重复执行**（core_broken 永不挂） | 派生技 `mark_add core_broken 1` |

combo_state 侧派生已真实命中（chain 激活、step_index=0），说明缺口在
battle 层结算管道而非 combo 引擎。

## 二、根因

`qbot_rpg/core/battle.py _resolve_combo_action`（改前 L1961-1968）：

- L1910 `sd = resolve_skill(ca.skill_id)` 在函数**开头**以源技能解析一次；
- L1913-1914 `ca['effects']` 合并源技能 effects；
- L1918-1922 `mult` 按 `sd.power/100` 折算（60/100=0.6）；
- L1961-1968 派生替换：`ca['skill_id']=result.form_id; ca['_derived']=...`
  ——只改 skill_id，**sd/mult/effects 不重新解析**；
- 后续 effects 执行段（L2077-2098 用 `ca['effects']`）+ 伤害结算
  `_resolve_damage_action`（用 `ca['mult']`）全部停留在源技能 def。

## 三、修复方案（改动最小、局部）

派生替换分支（`if result.form_id and result.form_id != ca.get("skill_id"):`）
内、skill_id 覆写之后，补一段**按派生技 def 的重解析同步**：

```python
_fsd = self.combo_engine().resolve_skill(str(result.form_id or "")) or {}
_f_power = float(_fsd.get("power", 0) or 0)
if _f_power > 0 and not _action_had_mult:      # 显式 mult 保持优先
    ca["mult"] = _f_power / 100.0
if "effects" not in action:                    # 显式 effects 保持优先
    ca["effects"] = list(_fsd.get("effects") or [])
if not action.get("tag"):
    ca["tag"] = str(_fsd.get("tag", "") or "")
if not action.get("armor"):
    ca["armor"] = bool(_fsd.get("armor", False))
_f_hits = int(_fsd.get("hits", 1) or 1)
if _f_hits > 1 and "segments" not in ca:
    ca["segments"] = [{"hit": True, "mult": 1.0} for _ in range(_f_hits)]
```

口径说明（与既有非派生路径完全一致）：

1. **显式优先**：`_action_had_mult`/`"effects" not in action`/`action.get("tag")`
   等判据与函数开头 D4/power 折算分支同一套——action 显式给定 → 不被覆写；
   仅当 action 未显式给出时才跟随派生技 def。非派生路径不进入该分支，零变化。
2. **派生技 def 缺失**（无 form 技能配置）→ `_fsd={}` → 各 setdefault 等价
   无操作（mult 维持折算值/缺省、effects 维持源合并），安全降级不崩。
3. **tag/armor/hits 同步**：派生步 tag 为空时继承派生技 tag；armor 取派生技
   def；hits>1 且 action 未显式 segments 时按派生技展开多段（与函数开头
   M13 批14 同一展开口径）。
4. **刻意不动**：mp_cost/energy/combo_table/transform 门禁仍以源技能为准
   （保守——破坏技派生不额外收费的既有语义不因本修复改变；G2
   consume_marks 为另一登记缺口，不在本修复范围）。

## 四、测试

新文件 `tests/unit/test_veinborn_derived_settle.py`（6 用例，构造与 veinborn
同构的最小 defs，零 content 依赖）：

1. `test_derived_damage_uses_derived_power` —— 破坏值 120 预置后第 7 下
   派生：伤害 >120（2.0×≈200），非 0.6×≈60；
2. `test_derived_effects_use_derived_def` —— core_broken 印记挂 1、
   break_vein_core 不再重复 +20；
3. `test_non_derived_path_unchanged` —— 未达条件直接施放源技能：0.6× +
   源 effects +20、core_broken=0；派生技直接施放（cast to 路径 a，条件满足）
   也跟派生技 def（2.0×）；
4. `test_unconditional_replace_chain_derives` —— 无条件 replace 链同样跟随
   派生技（2.0× + core_broken）；
5. `test_explicit_mult_effects_keep_priority` —— 显式 mult 0.5/显式 effects
   不被派生技 def 覆写；
6. `test_mult0_derived_skill_still_resolves` —— mult=0 派生零伤害但 effects
   照常执行（core_broken 挂 1）。

修复前该文件 4 用例红（伤害/effects/无条件/显式全覆盖），修复后全绿——
新测试确实捕获缺陷（stash 验证）。

## 五、回归结果

- 新测试：6 passed
- 基线四文件 + 新测试：55 passed
- 全仓 `pytest tests/unit -q -p no:cacheprovider`：见下方全仓回归结果
  （约 5500+ 测试，需确认零失败）

## 六、产出清单

- 修改：`qbot_rpg/core/battle.py`（仅 `_resolve_combo_action` 派生分支 +23 行）
- 新增：`tests/unit/test_veinborn_derived_settle.py`
- 未改：content 配置、combo.py、其余引擎文件（铁律遵守）
