# kk-rpa-monorepo

需求文档驱动的 RPA 应用框架。它把一份需求转换为一个可测试、可恢复、可独立运行的 Python RPA 应用，浏览器底层为 DrissionPage。

```text
一份 Requirement Source
= 一个稳定 Application ID
= 一个独立 Application Directory
= 一个 Program Entry Point
```

## 设计判据

框架里的每一个机制，要么降低 agent 写对的成本，要么提高 agent 写错的成本。两者都不满足的，是税。

完整推导见 [`docs/rpa-framework-design.md`](docs/rpa-framework-design.md)，决策记录见 [ADR-028](llm-wiki/decisions/ADR-028-v2-structural-simplification.md) 和 [ADR-029](llm-wiki/decisions/ADR-029-falsifiable-step-assertions.md)。

## 三层结构

```text
BrowserActions   隔离 DrissionPage，稳定的小接口
Element          定位器 + 期望匹配数，可单独验证和修复
Step             业务单元：execute + verify + counterexamples + checkpoint
```

没有 Instruction 层，没有独立的 Program 层 —— Program 就是有序的 Step 列表。

## 唯一的强制约束

```python
def execute(self, ctx) -> Mapping[str, object]: ...
def verify(self, ctx, result) -> bool: ...
def counterexamples(self) -> Iterable[Counterexample]: ...   # 至少 1 个
```

`Counterexample` 携带一个**假浏览器状态**。`rpa-app test` 在每个反例状态下真的跑一遍 `execute()`，要求它抛错或 `verify()` 返回 `False`。

**构造不出反例的断言 = 没有断言。** 这一条替代了 V1 的门禁、快照、审核留痕和授权记录。

反例必须是浏览器状态而不是直接构造的 result —— 否则只能抓出假验证器，抓不出"`execute()` 回显输入、根本没读页面"的假执行器。

## 元素库

一个应用一个 `elements.toml`：

```toml
[jushuitan.erp.product_stock.export_menu]
locator      = "xpath://button[translate(normalize-space(.),' ','')='导出']"
frame        = "css:iframe[src*='/erp-scm-goods/stockInventoryManagement']"
expect_count = 1
check_at     = "S004"
note         = "列表右上角导出下拉入口"
```

`expect_count` 是**现在应该成立的断言**，不是历史记录 —— 这是它能发现失效的原因。`check_at` 指定它在哪个导航阶段成立：不带阶段统一检查时，19 条里有 7 条会误报失效（登录框在已登录页面本来就是 0 个）。

```bash
uv run rpa-app verify-elements --yes
```

2026-09-03 在真实页面上的实际输出（节选）：

```text
--- S003 ---
 ✓ jushuitan.erp.product_stock.brand_selected_option  expect=>0  actual=1
--- S004 ---
 ✓ jushuitan.erp.product_stock.result_row             expect=>0  actual=24
 ⚠ jushuitan.erp.product_stock.filter_applied_marker  expect=1   actual=1
 ✓ jushuitan.erp.product_stock.export_menu            expect=1   actual=1
```

页面改版时在一个地方修好，所有引用点跟着好 —— 这是元素库的核心价值，也是保留它的唯一理由。

## 仓库结构

```text
kk-rpa-monorepo/
├── AGENTS.md                       # 生成、测试和真实运行规则
├── docs/rpa-framework-design.md
├── llm-wiki/                       # 项目采用方式 + DrissionPage 4.1.1.4 笔记
├── packages/
│   ├── rpa-core/                   # BrowserActions / Element / Step / Runner
│   └── rpa-integrations/           # 外部系统适配器
└── apps/
    ├── inventory_jushuitan_export_stock/
    └── report_jingmai_export_product_detail/
```

## 快速开始

前置条件：Python 3.12、[uv](https://docs.astral.sh/uv/getting-started/installation/)。真实运行还需要本机 Chrome、应用本地配置和一次明确确认。

```bash
cd apps/report_jingmai_export_product_detail
uv sync --locked
uv run --locked rpa-app doctor
uv run --locked rpa-app test
```

以上只做环境检查和无副作用测试，不启动真实浏览器。

```bash
uv run --locked rpa-app verify-elements --account STORE_001 --yes   # 检查元素是否失效
uv run --locked rpa-app run --account STORE_001 --yes               # 真实运行，写入转本地预览
uv run --locked rpa-app run --account STORE_001 --live --yes        # 允许已声明的外部写入
uv run --locked rpa-app resume <run_id> --account STORE_001 --yes
```

真实运行前按应用 README 准备 Git 忽略的 `.env`、`config/stores.local.toml` 和独立 Profile。

## 安全边界

按**实际有效性**排序：

1. **只读子账号（平台侧）** —— 每接入一个新平台，第一件事是申请只有查询/导出权限的子账号。这是唯一在代码之外、连你的代码写错了都拦得住的边界。
2. **`--live` 二分 + 交互确认** —— 默认读取、筛选、下载可执行，外部业务写入转本地预览；`--live` 启动前展示账号、目标、预计记录数，要一次 `y/N`；非交互环境不自动确认。
3. **写后回读** —— Live 写入完成后独立查回来，比对记录数和内容摘要。

CAPTCHA、滑块、短信验证只检测、留证据、转人工，不绕过。

`.env`、`config/stores.local.toml`、`profiles/`、`runs/` 不提交。

结论必须始终区分：

```text
框架代码完成
≠ 离线测试通过
≠ 元素验证通过
≠ 真实 Preview 通过
≠ Live 写入验证通过
≠ 业务验收通过
```

## 框架如何演进

每完成一个应用，问一次：**这次踩的坑，能不能变成一条会失败的测试？**

- 能 → 加进 `rpa-core`，附一条证明它会失败的测试
- 能变成一个命令（如 `verify-elements`）→ 加进 CLI
- 都不能 → **不加**。写进 AGENTS.md 的规矩，agent 只会用生成文书来满足它

配套纪律：**任何"跨应用共享"的机制，在第三个应用真的重复了同一段代码之前，不许建。** 第二个应用只用来证伪，不用来抽象。

## 当前状态（2026-09-04）

- 首个应用 `apps/inventory_jushuitan_export_stock/` 已按 V2 迁移：5 个 Step 全部改为可证伪断言并配套反例
- `verify-elements` 已在真实浏览器上跑通：6 个阶段全部到达，19 个元素 0 失效，2 条标记为断言过弱
- 真实 Preview 已通过：S001–S005 全部完成，S003/S004 从 DOM 回读到的选中品牌恰好等于配置品牌，无外部业务写入
- 第二个应用 `apps/report_jingmai_export_product_detail/` 已按精简结构完成实际开发：6 个 Step、26 个真实定位器、离线反例和仓库发现门禁均通过
- 京麦完整链路已用全新隔离 Profile 验证：从专用稳定入口完成密码登录并回读目标身份，再打开报表、选择跨月日期、导出、查看报表和下载；`STORE_001` 账号边界已确认，26 个真实定位器均有页面或动作证据，下载包内容及 SHA-256 已核验
- 第二个应用证明新应用不需要 catalog/instruction 快照和应用内运行时；公共 CLI 已进入 `rpa-core`，发现器已兼容精简应用，并修复了点击后新标签页被 SSO 替换时的切换竞态
- 旧授权、catalog、instruction、双份 requirement 等模块仍被首个应用引用，暂不删除；先迁移真实调用方，再由测试证明可删
