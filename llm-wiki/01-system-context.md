# 系统上下文与边界

## 目标

系统将一份带操作描述和截图的飞书 RPA 需求文档转换为一个独立、可测试、可审核、可恢复的 RPA 应用。

固定关系：

```text
一份飞书需求文档
= 一份 REQUIREMENT_MEMORY.md
= 一份 requirement.spec.json
= 一个稳定 app ID
= 一个独立应用目录
= 一个 RPA 程序入口
```

同一需求的后续 revision 更新原应用。只有业务目标实质变化时才创建新应用。

## 分层

```text
飞书需求与截图
  ↓
需求记忆与机器 Spec
  ↓
独立业务应用
  ↓ 只能通过 ExecutionContext
公共运行框架与 BrowserActions
  ↓
DrissionPage / Excel / 飞书 / 数据库适配器
  ↓
浏览器与外部系统
```

各层边界：

- `apps/<app_slug>/`：只表达步骤、条件、循环、输入、输出和成功条件。
- `packages/rpa-core/`：Program、Step、ExecutionContext、运行器、浏览器包装、检查点、日志、证据和授权门禁。
- `packages/rpa-platforms/`：按平台、站点、页面和组件组织的元素与页面知识。
- `packages/rpa-integrations/`：Excel、飞书、数据库和告警适配器。

## 强制不变量

- 每个应用拥有独立的 `pyproject.toml`、`uv.lock`、`.python-version` 和本地 `.venv/`。
- 应用通过本地 path dependency 引用公共包，不复制公共框架。
- 应用不得直接导入 DrissionPage、Excel 底层库、飞书 SDK 或数据库驱动。
- 步骤成功条件验证通过后才允许写检查点。
- Preview 只生成外部写入预览；Live 必须有单次、精确范围的授权。
- 任何未解决的待确认项或未解析元素都阻止审核、提交和推送。
- AI 不得自行把状态设置为 `approved` 或 `ready_for_push`。

## 当前非目标

- 调度中心和业务看板；
- 物理机故障漂移；
- 自动转换全部旧 RPA 程序；
- 用视觉模型替代正常 DOM 自动化；
- 自动绕过验证码、滑块、短信或平台风控；
- 未经授权操作真实浏览器或外部业务系统。
