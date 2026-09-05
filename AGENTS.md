# 全局工作约定

目标：在合理的情况下以最小范围、最少改动和最少必要验证，高效完成用户明确要求。避免过度设计、过度防御、过度测试、无关探索和流程性输出

核心原则：只解决真实需求和真实风险，不处理想象中的需求和风险。

本文件的编写原则：**能变成测试的不写进规矩；写进规矩的必须是测试表达不了的。** 完整设计见 `docs/rpa-framework-design.md`。

# RPA 应用生成规则

## 1. 目标

一份需求文档 = 一个应用目录 = 一个程序入口。同一需求的后续变更更新原应用。

## 2. 核对外部接口

涉及 DrissionPage、uv、飞书 API 或任何库、SDK、CLI 时，先通过 Context7 或官方文档核对当前版本，不凭记忆编造接口。

## 3. 目录结构

```text
apps/<slug>/
├── app.toml              # id / name / entry
├── pyproject.toml, uv.lock, .python-version
├── requirement.md        # 需求基线，人读 agent 也读
├── elements.toml         # 本应用全部定位器
├── config/stores.example.toml
├── src/<pkg>/
│   ├── cli.py            # 转发 rpa_core.cli
│   └── program.py        # Step 定义
└── tests/test_program.py
```

每个应用有自己的 `pyproject.toml`、`uv.lock`、`.venv/`。不共用根虚拟环境。

## 4. 代码边界

- 只有 `rpa_core/drission_browser.py` 和 `rpa_core/browser_manager.py` 可以 import DrissionPage
- 业务代码只通过 `ctx.browser` / `ctx.excel` / `ctx.feishu` / `ctx.db` 访问外部系统
- 通用能力放 `rpa-core` 或平台包，不留在应用里

## 5. Step 契约（唯一的强制约束）

每个 Step 必须提供：

```python
def execute(self, ctx) -> Mapping[str, object]: ...
def verify(self, ctx, result) -> bool: ...              # 可执行代码，不是字符串
def counterexamples(self) -> Iterable[Counterexample]: ...  # 至少 1 个
```

`Counterexample` 携带一个**假浏览器状态**。`rpa-app test` 在每个反例状态下真的跑一遍 `execute()`，要求它抛错或 `verify()` 返回 `False`。

**构造不出反例的断言 = 没有断言。** 两类写法过不了：

- 假验证器：`return bool(True)`、`return exists(页面上一直存在的元素)`
- 假执行器：`execute()` 回显输入而不回读页面，例如 `return {"selected": True}`

`verify()` 必须**回读页面状态**。筛选生效的证据是回读到的选中品牌等于配置品牌，不是"表格存在"。

## 6. 元素

`elements.toml` 每个元素声明 `locator`、可选 `frame`、`expect_count`、`note`。

`expect_count` 是**现在应该成立的断言**，不是历史记录。`rpa-app verify-elements` 用它判定失效。

不确定的定位器不要编。写进 `requirement.md` 的待确认清单，流程照样写完整，不要因为一个元素未知就只写半个程序。

## 7. 抽象纪律

**任何"跨应用共享"的机制，在第三个应用真的重复了同一段代码之前，不许建。**

第二个应用用来证伪，不用来抽象。不要预先建注册表、版本、依赖闭包、快照锁。

## 8. 框架演进

每完成一个应用，问：这次踩的坑能不能变成一条会失败的测试？

- 能 → 加进 `rpa-core`，附一条证明它会失败的测试
- 能变成一个命令 → 加进 CLI
- 都不能 → **不加**

## 9. 真实运行

新平台接入的第一件事：**申请只读 / 导出权限的子账号**。这是唯一在代码之外、真正拦得住误操作的边界。拿不到的，在 `app.toml` 显式标记。

- 默认运行：读取、筛选、下载可执行；外部业务写入转本地预览
- `--live`：允许已声明的外部写入，启动前展示账号、目标、预计记录数，要一次 `y/N`；非交互环境不自动确认
- Live 写入后必须独立回读，比对记录数和内容摘要
- CAPTCHA / 滑块 / 短信验证：只检测、留证据、转人工，**不绕过**

未经明确授权，不打开真实浏览器、不登录业务平台、不写飞书 / 数据库 / 正式 Excel。未授权的真实测试在报告中标记"等待授权"，不得宣称通过。

## 10. 脱敏

真实店铺名、账号、手机号、Cookie、Token、本机路径只允许存在于 `.env`、`config/stores.local.toml`、`profiles/`、`runs/`。这四项不提交。

可提交文件用稳定别名（`STORE_001`）和占位符。

## 11. 提交

默认不建分支、不 commit、不 push、不部署。

需要提交时先展示文件清单、测试结果、提交信息和目标分支，得到明确确认后执行。只提交当前应用和已确认的公共包改动。

## 12. 沟通

需要澄清时一次只问一个问题。

以下情况停下来问：需求有歧义且不同解读会导致不同实现、需要真实浏览器或外部写入授权、现有代码的修改方案未确认、测试失败。

说明：发生了什么、影响哪些文件或步骤、已完成什么、下一步需要确认什么。
