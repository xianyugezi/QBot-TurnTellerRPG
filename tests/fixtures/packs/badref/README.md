# 坏引用包 badref

依据：细化_5d §5.1（TC-5d-13）/ 细化_3e §2.1 红拦第 4 类 R-4（引用不存在）/ 细化_3e#TC-05 / 3a#TC-10。

- 破坏点：`items.json` 的 `cursed_blade.effects[0] = "ghost_effect"` —— 引用一个**未注册**的 effect ID，
  整包被红拦 R-4（ref_missing），必须抛 `PackLoadError`，registry 不被污染。
- 除该条悬空引用外其余数据全部合法（heal_small/statuses/slime 正确），保证红拦**只**由一根坏引用触发，
  便于断言错误定位 `items.1.effects.0`。
- 断言见 tests/unit/test_content.py::test_badref_pack_blocked（细化_3e#TC-05 / 3a#TC-10）。
