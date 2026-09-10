"""QBot-TurnTellerRPG 平台无关核心包。

分层（细化_3a_架构分层契约 §2.1）：
  core/     纯规则引擎 + message_format 纯字符串渲染
  world/    全局世界状态与并发互斥
  storage/  SQLite 持久化（事务/迁移/幂等）
  content/  内容包 loader/validator/registry/hot_reload
  data/     领域模型唯一落点（最底层，仅标准库）
  commands/ 壳层适配器（唯一 NoneBot 接触点，M4 起接入）
  web/      Web 编辑器外壳（FastAPI，零 NoneBot）
"""
__version__ = "0.1.0"
