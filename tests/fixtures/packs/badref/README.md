# 坏引用包 badref

依据：细化_5d §5.1（TC-5d-13）/ 细化_3e §2.1 红拦第 4 类 R-4（引用不存在）/ 细化_3e#TC-05 / 3a#TC-10
/ 细化_1e §⑤（enemies 八段 R1-R15，M2 A3 路）。

- 破坏点（红拦，整包必须抛 `PackLoadError`，registry 不被污染）：
  - `items.json` 的 `cursed_blade.effects[0] = "ghost_effect"` —— 引用一个**未注册**的 effect ID
    （R-4 ref_missing，细化_3e#TC-05 / 3a#TC-10 断言定位 `items.1.effects.0`）。
  - `enemies.json` 三只八段坏例怪，覆盖引用拦截 + 枚举拦截 + 参数拦截：
    - `bad_trigger`：trigger.type "hp_above"（非 13 类 → R2_trigger_type_invalid）+ lore unlock 非递增
      （10/50/40 → R6_unlock_increasing）。
    - `bad_ref`：actions.action "ghost_claw"（R1_action_ref）+ special_actions.action "ghost_roar"
      （R1_action_ref）+ chain_ref "ghost_chain"（R15_chain_ref_missing）+ drops.item "ghost_item"
      （R5_item_ref）+ weakness.elements "ice"（未注册元素 → R3_element_ref）。
    - `bad_enum`：tier "legendary"（R8_tier_enum）+ drops.chance 150（R5_chance_range）+
      drops.count [3,1]（R13_count_min_max）。
  - `action.json`（新增，供八段坏例引用基线）：claw_swipe / fireball 两个合法行动。
- 断言见 tests/unit/test_content.py::test_badref_pack_blocked（细化_3e#TC-05 / 3a#TC-10）
  与 tests/unit/test_enemies_schema.py::test_badref_8seg_red_blocks。
