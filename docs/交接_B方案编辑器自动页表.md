# 交接：编辑器自动页表方案 B 实施

> 新对话任务。做完 B 方案（编辑器无 editor.json 包自动出全页）后，回原对话继续 veinborn 装备录入。

## 任务
读 `docs/m125_编辑器自动页表方案_B.md`（已提交 86e9c4a），按「六、实施顺序」执行：
1. editor_registry.py 加 `_MODULE_PAGE_CATALOG` + `auto_pages_from_modules` + 改 `load_editor_registry`
2. 单测更新（auto 场景 + 空 registry 语义）
3. 浏览器实测（宿主管 8125，veinborn 副本 /tmp/m12eq_ui）——重点验 npc/quest 页 meta 空表渲染
4. 全仓回归 + commit

## 仓库状态
- /root/QBot-TurnTellerRPG，main 分支，HEAD 86e9c4a（含：编辑器默认页表已加 equipment/item 两页、field_meta equipment_fields 已补 dfn/foc/hp/agi、B 方案文档）
- 工作区干净（仅 docs/veinborn_装备体系规划_v1.md 未跟踪——无关本任务）
- 全仓测试基线 10 failed（既有集合，不得新增红）

## 关键技术事实（勘察已完）
1. `load_editor_registry(registry)`（qbot_rpg/content/editor_registry.py L303）：modules_raw 无 "editor" 键 → `default_editor_pages()` 六页兜底
2. `default_editor_pages()` L244：返回 6 页（skill/job/monster/map/quest/shop）
3. **30 页母本** = content/test_demo/editor.json（page_id/title/icon/module_file/meta_source/validator/group/tabs/page_kind 全规格）——模块→页映射表来源
4. 模块发现源 = `registry.modules_raw`（loader 按 manifest.modules 加载：{模块名: 数据}）
5. 特殊页不自动生成：ai/hidden（extends 挂载页）、env_event/log_card（settings.json 子段页）
6. **当前 86e9c4a 已把默认兜底从 6 页扩到 8 页（+equipment/item）**——B 方案实施后此改动被 auto 函数取代（或保留为 auto 的 catalog 一部分），注意测试 test_editor_registry.py 已改 6→8 页断言，B 完成后断言要再改成 auto 语义
7. field_meta 覆盖：多数模块有 *_fields 表；npc/quest/shop/checkin/dungeon 等走专项 models 校验器（meta 宽松兜底已做，浏览器实测验证渲染）

## 编辑器宿主模板（浏览器实测用）
写 /tmp/*.py 再跑（内联大脚本被安全扫描拦）：
- 内容副本：`rm -rf /tmp/m12eq_ui && cp -r content/veinborn /tmp/m12eq_ui`
- 宿主脚本参考 /tmp/m12eq_host.py（上次已跑通）：`await load_pack(Path("/tmp/m12eq_ui"))`（load_pack 是 async 直接 await，别 to_thread 包）→ state=SimpleNamespace(auth_store=AuthStore("owner_test_qq"), registry=pack.registry, content_dir=Path("/tmp/m12eq_ui"), editor=None, permission_store=PermissionStore(), audit_store=AuditStore()) → create_app(state) → uvicorn 127.0.0.1:8125
  - AuthStore 在 qbot_rpg/web/auth.py（构造 AuthStore(owner_qq_id)）；PermissionStore/AuditStore 在 qbot_rpg/content/
- 登录流程：首次设密自动引导（428→setup→login 已修好）；密码内存态重启清空，可反复测首次设密
- **改 Python 代码必须重启宿主**（import 缓存）；editor.html 纯静态刷新即可
- 保存/删除后**必须读副本 JSON 断言落盘**（UI 提示会撒谎——M12 经验）

## 浏览器操作要点（agent-browser）
- snapshot -i 拿 refs → fill/click；点按钮弹 confirm 会 CDP 超时 → dialog status/accept 单独处理
- 每次导航/弹层后 refs 失效必须重新 snapshot

## 已知缺陷模式（M12 浏览器实测 6 类，同类必查）
1. 保存假成功真丢改（原始 JSON textarea 覆盖已收集字段）——改后必读盘验证
2. FastAPI HTTPException detail 包裹（前端读 j.errors undefined）
3. 枚举 select 静默清空（值不在枚举 → 保存丢字段）
4. 新建手填 id 被覆盖
5. 级联删除断链（删怪不删 maps/npc 引用）
6. 首次设密断链（已修，428 自动 setup）

## 完成标准（回原对话汇报）
- [ ] commit 落 main：`feat(M12.5): 编辑器默认页表自动发现……`
- [ ] veinborn 副本浏览器实测：全页出现（≥15 页含装备/物品/NPC/行动/效果）+ 装备新建保存磁盘断言通过
- [ ] test_demo（有 editor.json）30 页回归不变
- [ ] 全仓 pytest 无新增红
