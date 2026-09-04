# 系统上下文与边界

## 目标

系统将一份带操作描述和截图的需求文档，转换为一个独立、可测试、可恢复的 RPA 应用。

```text
一份 Requirement Source
= 一份 requirement.md
= 一个稳定 app ID
= 一个独立应用目录
= 一个 Program Entry Point
```

同一需求的后续 revision 更新原应用。只有业务目标实质变化时才创建新应用。

## 分层

```text
需求文档与截图
  ↓
apps/<slug>/requirement.md
  ↓
apps/<slug>/elements.toml          定位器 + expect_count
  ↓
apps/<slug>/src/<pkg>/steps.py     execute / verify / counterexamples
  ↓
rpa-core：Step Runner、Checkpoint、ExecutionContext、BrowserActions
  ↓
DrissionPage / Excel / 飞书 / 数据库适配器
  ↓
浏览器与外部系统
```

三层职责：

- **`BrowserActions`**：业务代码访问浏览器的唯一接口，隐藏 DrissionPage 类型。只有 `rpa_core` 的 DrissionPage 适配器可以 import DrissionPage。
- **`Element`**：UI 目标的稳定身份，携带定位器和**当前应成立的**匹配数（`expect_count`）。不保存实时 DOM 对象。
- **`Step`**：业务单元。`execute()` 操作页面并回读状态，`verify()` 判定成功，`counterexamples()` 提供必须失败的假浏览器状态。

没有 Instruction 层。跨应用复用的能力就是普通 Python 函数，按平台放进 `packages/rpa_<platform>/` —— 但在第三个应用真的重复同一段代码之前不建这个包。

## 强制不变量

- 每个应用拥有独立的 `pyproject.toml`、`uv.lock`、`.python-version` 和本地 `.venv/`
- 应用通过本地 path dependency 引用 `rpa-core`，不复制它
- 应用不得直接 import DrissionPage、Excel 底层库、飞书 SDK 或数据库驱动
- 每个 Step 必须提供至少一个 `Counterexample`，且在每个反例状态下 `execute()` 抛错或 `verify()` 返回 `False`
- `verify()` 必须回读页面状态，不得回显 `execute()` 的输入
- Step 验证通过后才允许写检查点
- 默认运行的外部业务写入只生成本地预览；`--live` 需要交互确认，写后必须回读验证
- AI 不得自行 commit、push 或部署

## 当前非目标

- 调度中心和业务看板
- 物理机故障漂移
- 自动转换全部旧 RPA 程序
- 用视觉模型替代正常 DOM 自动化
- 自动绕过验证码、滑块、短信或平台风控
- 未经确认操作真实浏览器或外部业务系统

## 已知的历史教训

V1 曾用 613 行 `AGENTS.md`、结构化门禁、快照哈希和审核留痕保证质量，结果是：

- `success_conditions` 是 `tuple[str, ...]`，永不执行；5 个 Step 共 10 条成功条件，一条都没跑过
- S003 是假执行器（`return {"selection_visible": True}`），S004 是假验证器（`exists("css:table tbody")`，实测搜索前后同为 21 行）
- 整条 S003 → S004 → S005 链路从未确认过品牌筛选生效，而应用状态是 `ready_for_push`
- 授权子系统 2856 行，其浏览器边界的四条检查在正常运行时恒为真

根因是激励结构：写假断言的成本是 0，走完授权流程的成本很高。V2 用反例强制把这个结构翻转过来。详见 [ADR-028](decisions/ADR-028-v2-structural-simplification.md) 和 [ADR-029](decisions/ADR-029-falsifiable-step-assertions.md)。
