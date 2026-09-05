# RPA 框架设计 V2

## 0. 这份文档要解决什么

V1 的问题不是没设计好，是**在只有一个样本时按 N 个样本设计**，并且**把一个为"不会写代码的人"设计的架构套在了"只会写代码的 agent"身上**。

结果是成本和价值装反了：

- 写一条假断言的成本是 0（填个 TOML 字段）
- 走完授权流程的成本很高（agent 的时间主要花在这里）

于是 agent 理性地选择了产出文书，而不是产出正确性。这不是 agent 的问题，是激励结构的问题。

V2 的全部设计都从一条判据推出来：

> **一个机制，要么降低 agent 写对的成本，要么提高 agent 写错的成本。两者都不满足的，是税。**

## 1. 设计原则

1. **使用者是 agent，不是人。** 对 agent 有效的约束是会失败的测试，不是自然语言规矩 —— 它会满足字面要求然后继续。
2. **抽象必须由第二个应用证明，不能预先设计。** 第二个应用用来证伪，第三个才用来抽象。
3. **断言必须可执行，且必须能被证伪。** 构造不出反例的断言等于没有断言。
4. **不重新发明 Python 已有的机制。** 模块、包、import、git 已经是最好的"指令库"。
5. **真正的安全边界在代码之外。** 代码里的守卫只能校验声明，而出错的恰恰是声明本身。

### 1.1 为什么 V1 的授权系统必须删

`authorization.py`(1504) + 测试(792) + Schema(560) = 2856 行。浏览器边界的全部检查是四条：

```python
if normalized_action not in self.scope.browser_actions: ...
if step_id not in self.scope.step_ids: ...
if element_id not in self.scope.element_ids: ...
if _origin_from_url(url) not in self.scope.allowed_origins: ...
```

而正常运行时的 scope 是：

```python
element_ids    = tuple(sorted(element_catalog()))   # 全部元素
browser_actions = tuple(BrowserAction)              # 全部动作
step_ids        = _PROGRAM_STEP_IDS                 # 全部步骤
```

四条检查恒为真 —— `BrowserActions` 的 API 本来就只接受目录里的 `ElementSpec`，只有那几个方法，只在登录的那个站点上。

更关键的是它**防不住它要防的东西**：危险藏在 `[locator]` 那行 `css:...` 里，而那行是 agent 自己写的。守卫校验的是"你做的和你说的一致吗"，而手滑的定义恰恰是"说的就是错的"。

### 1.2 为什么 V1 的 catalog / instruction 库必须降级

影刀这类商业 RPA 有元素库和指令库，是因为**它的用户不会写代码**：

| 影刀的机制 | 存在的理由 | agent 场景下的等价物 |
| --- | --- | --- |
| 元素库 + 拾取器 | 用户不会写 XPath | TOML + 验证命令 |
| 指令库 + 拖拽积木 | 用户不会写函数 | Python 函数 |
| 指令版本 / 依赖 / 注册表 | 没有 git，库就是它的模块系统 | git + uv |
| 跨应用共享库 | 无代码复用手段 | `git grep` + 复制 |

V1 用 TOML 声明 + 字符串 ID 查表 + 手写依赖闭包 + 手写版本，重新实现了一个 Python 模块系统，而且丢掉了 IDE 跳转、类型检查、重构和 `git grep`。

**但元素库有一样真价值，V2 要保留并加强**：页面改版时在一个地方修好，所有引用点跟着好。这个需求在 agent 场景下只强不弱 —— agent 写的 selector 更容易过时，而且它自己发现不了。

实现这个价值只需要 `elements.toml` + 一个 `verify-elements` 命令，不需要跨应用目录、内容哈希、快照锁和回灌工作流。

## 2. 三层结构

```
BrowserActions   隔离 DrissionPage，稳定的小接口
Element          定位器 + 期望匹配数，可单独验证和修复
Step             业务单元：execute + verify + counterexamples + checkpoint
```

没有 Instruction 层，没有 Program 层（Program 就是有序的 Step 列表）。

### 2.1 BrowserActions

V1 的接口只有 `exists` 返回布尔，`text` 返回单个字符串。**接口的贫乏直接导致了断言的贫乏** —— 所有 `assert` 只能退化成 `bool(...)`。V2 补两个返回结构化数据的方法：

```python
class BrowserActions(Protocol):
    def open(self, url: str, *, wait: str = "complete") -> None: ...
    def exists(self, el: ElementSpec, *, timeout: float = 5.0) -> bool: ...
    def click(self, el: ElementSpec) -> None: ...
    def input(self, el: ElementSpec, value: str) -> None: ...
    def select(self, el: ElementSpec, value: str) -> None: ...
    def text(self, el: ElementSpec) -> str: ...
    def download(self, el: ElementSpec, *, filename: str) -> DownloadRef: ...
    def screenshot(self, *, name: str) -> Path: ...

    # V2 新增 —— 没有这两个就写不出真断言
    def count(self, el: ElementSpec) -> int: ...
    def texts(self, el: ElementSpec) -> list[str]: ...

    # 点击后由浏览器级等待发现新标签页，并把后续动作绑定到新页
    def click_and_switch_to_new_tab(
        self, el: ElementSpec, *, timeout: float | None = None
    ) -> None: ...
```

DrissionPage 只允许出现在适配器 `rpa_core/drission_browser.py` 和生命周期管理器 `rpa_core/browser_manager.py`。业务代码只见 `ctx.browser`。

### 2.2 Element

一个应用一个 `elements.toml`，不再是 17 个文件：

```toml
[jushuitan.product_stock.export_menu]
locator      = "xpath://button[translate(normalize-space(.),' ','')='导出']"
frame        = "css:iframe[src*='/erp-scm-goods/stockInventoryManagement']"
expect_count = 1
check_at     = "S004"
note         = "列表右上角导出下拉入口"

[jushuitan.product_stock.result_row]
locator      = "css:table tbody tr"
frame        = "css:iframe[src*='/erp-scm-goods/stockInventoryManagement']"
expect_count = ">0"
check_at     = "S004"
note         = "结果行；行数用于筛选断言"
```

`expect_count` 是关键新增，也是 V2 与 V1 `[verification]` 块的本质区别：

- V1 的 `[verification]` 记录**过去某一时刻的事实**（`match_count = 1`、`refresh_stable = true`），今天什么也不保证
- V2 的 `expect_count` 是**现在应该成立的断言**，`verify-elements` 拿它做判定

`check_at` 指定这条期望在哪个导航阶段成立：`login_page` / `session` / `S001` / `S002` / ...

**这是第一次真实运行逼出来的。** 不带阶段、在某个任意时刻统一检查，19 条里有 7 条报"失效"而实际什么都没坏 —— 登录框在已登录页面本来就是 0 个，"模块已激活"标识在导航更深之后本来就不再匹配。没有阶段的期望不是断言，只是把歧义搬进了报告。


删掉 `[verification]` 整块、`status`、`version`、`dependencies`、`schema_version`。元素的版本历史交给 git。

### 2.3 Step

沿用现有的 `execute` / `verify` 命名，只新增第三个方法：

```python
class Step(ABC):
    spec: StepSpec

    def execute(self, ctx: ExecutionContext) -> Mapping[str, object]: ...

    def verify(self, ctx: ExecutionContext, result) -> bool:
        """必须是可执行代码，必须能被 counterexamples 证伪。"""

    def counterexamples(self) -> Iterable[Counterexample]:
        """至少一个。每个都必须让这个 Step 失败。"""
```

```python
@dataclass(frozen=True)
class FakeState:
    """反例需要的页面状态，声明式，与具体应用的 fake fixture 解耦。"""
    hidden: tuple[str, ...] = ()                 # 必须不存在的元素 ID
    counts: Mapping[str, int] = ...              # count() 的返回值
    texts: Mapping[str, tuple[str, ...]] = ...   # texts() 的返回值
    downloads_available: bool = True
    new_tabs_available: bool = True              # 点击后是否出现预期新标签页

@dataclass(frozen=True)
class Counterexample:
    label: str                                   # 人读的场景名
    state: FakeState = FakeState()
    metadata: Mapping[str, object] = ...         # 可选的上下文覆盖
```

框架强制（在 `rpa-app test` 里）：

1. 每个 Step 至少提供 1 个 counterexample，否则测试失败
2. 每个 counterexample 下，`execute()` 抛错**或** `verify()` 返回 `False`，二者必居其一；
   如果 `execute()` 正常返回且 `verify()` 返回 `True`，测试失败

### 为什么反例必须是浏览器状态，而不是直接构造 result

反例如果只是一个 `result` 字典直接喂给 `verify()`，只能抓出**假验证器**，抓不出**假执行器**。

V1 的 S003 恰恰是后者：

```python
def execute(...): return {"selected_brand": brand_value, "selection_visible": True}  # 硬编码
def verify(...):  return bool(result["selected_brand"]) and bool(result["selection_visible"])
```

给它一个 `{"selection_visible": False}` 的 result，`verify()` 确实返回 False —— 测试会通过，缺陷照样留下。

只有让反例是**浏览器状态**、并且真的跑一遍 `execute()`，才能发现 `execute()` 根本没去页面上读。

**这是整个框架唯一的强制约束，它替代掉 V1 里所有的门禁、快照、审核和授权。**

在这条规则下，V1 的两个假断言根本写不出来：

```python
# 写不出来：造不出让它返回 False 的状态
return bool(result["selected_brand"]) and bool(result["selection_visible"])  # selection_visible 硬编码 True

# 写不出来：table tbody 在搜索前就存在（实测 21 行，搜索前后不变）
return context.browser.exists(filter_applied_marker)
```

真断言长这样 —— 关键是**回读页面状态**，而不是回显输入：

```python
class SearchStep(Step):
    def execute(self, ctx):
        ctx.browser.click(E["jushuitan.erp.product_stock.search_button"])
        return {
            "rows":            ctx.browser.count(E["...product_stock.result_row"]),
            "selected_brands": ctx.browser.texts(E["...product_stock.brand_selector"]),
        }

    def verify(self, ctx, result):
        # 两条声明过的成功条件，现在都真的被检查
        return (
            result["rows"] > 0
            and set(result["selected_brands"]) == {store(ctx).brand_value}
        )

    def counterexamples(self):
        yield Counterexample("搜索后品牌被平台重置", FakeState(texts={BRAND_SELECTED: ()}))
        yield Counterexample("选中集合变成多个品牌", FakeState(texts={BRAND_SELECTED: ("甲", "乙")}))
        yield Counterexample("结果为空",             FakeState(counts={RESULT_ROW: 0}))
```

`brand_selector` 元素上早就定义了 `selected_option_locator`（读回真实选中集合），V1 定义了却从未用它验证过。V2 用它把"搜索后配置品牌仍被选中"这条**声明过但从未执行**的成功条件真正跑起来。

### 2.4 Checkpoint 与 Resume

`verify()` 通过后才写 checkpoint —— V1 这条设计是对的，保留。

Resume 简化为：**从头遍历所有 Step，已有 checkpoint 的先跑 `verify_recovery()`（回读页面），通过就跳过，不通过就重跑。**

删掉 V1 `program.py` 里那张硬编码的 `prerequisites` 表（S002 需要重放 open_module，S003 需要重放 open_module + open_product_stock……）。

这是一个连锁收益：**断言变真之后，"当前状态还对不对"可以被真的检查，resume 就不需要预先声明前置动作了。**

## 3. 目录结构

```
kk-rpa-monorepo/
├── AGENTS.md                          # ~80 行
├── docs/rpa-framework-design.md
├── packages/
│   ├── rpa-core/src/rpa_core/
│   │   ├── browser.py                 # BrowserActions 协议 + ElementSpec + 目录加载
│   │   ├── drission_browser.py        # DrissionPage 动作适配器
│   │   ├── browser_manager.py         # DrissionPage 浏览器构造与生命周期
│   │   ├── fake.py                    # FakeBrowser + FakeState
│   │   ├── step.py                    # Step 协议 + Runner + retry/checkpoint/resume
│   │   ├── run.py                     # run 目录 / 日志 / 截图 / 产物
│   │   └── cli.py                     # 全部命令实现
│   └── rpa_<platform>/                # 平台包，等第三个应用证明重复再建
└── apps/<slug>/
    ├── app.toml                       # id / name / entry
    ├── pyproject.toml, uv.lock, .python-version
    ├── requirement.md                 # 一份，人读 agent 也读
    ├── elements.toml
    ├── config/stores.example.toml
    ├── src/<pkg>/
    │   ├── cli.py                     # 3 行，转发 rpa_core.cli
    │   └── program.py                 # Step 定义，一个文件
    └── tests/test_program.py
```

**`cli.py` 必须进 core。** V1 应用里 `cli.py`(597) + `real_runtime.py`(1060) = **1657 行框架代码躺在应用里**，比 program + steps + models + validators + 全部 7 条指令加起来还多。不上提，第二个应用会原样复制。

删除：顶层 `elements/`、顶层 `instructions/`、`packages/rpa-platforms/`、`catalog.lock.json`、`requirement.spec.json`、`GENERATION_REPORT.md`、`reviews/`、`REQUIREMENT_MEMORY.md`（并入 `requirement.md`）。

生成报告和审核记录交给 git commit —— 它已经有作者、时间、diff 和不可篡改的历史。

## 4. 命令

从 V1 的 10+ 条降到 6 条：

```bash
uv run rpa-app doctor                 # Python / Chrome / 配置 / 依赖
uv run rpa-app test                   # 离线测试 + 反例强制（含原 check）
uv run rpa-app verify-elements --yes  # 真实浏览器，逐个元素报匹配数
uv run rpa-app run --yes              # 真实运行，外部写入转本地预览
uv run rpa-app run --live --yes       # 允许外部写入，二次确认
uv run rpa-app resume <run_id> --yes
```

删掉：`authorization request` / `authorization grant` / `login` / `verify-candidates` / `check`。

- `login` 删掉 —— `run` 自己处理会话（开页 → 查登录标记 → 没登录就登 → 校验身份）
- `check` 并入 `test`
- `verify-candidates` 并入 `verify-elements`

`verify-elements` 的输出是元素库真正的价值所在：

```
jushuitan.product_stock.export_menu     expect=1    actual=1    ✓
jushuitan.product_stock.result_row      expect>0    actual=21   ✓
jushuitan.product_stock.row_brand       expect>0    actual=0    ✗ 失效
jushuitan.shell.account_surface         expect=1    actual=1    ⚠ locator 是 //body，断言过弱
```

## 5. 安全边界

按**实际有效性**排序，不按仪式感排序：

### 5.1 只读子账号（唯一真正的边界）

每接入一个新平台，**第一件事是申请只读/导出权限的子账号**。这是唯一在你的代码之外的边界 —— 它连你的代码写错了都拦得住，且零维护成本。

拿不到只读账号的平台，在 `app.toml` 里显式标记，并在该应用的 `requirement.md` 里写明风险由谁承担。

### 5.2 `--live` 二分 + 交互确认

- 默认（不带 `--live`）：浏览器读取、筛选、下载可以执行；外部业务写入（飞书 / 数据库 / 正式 Excel / NAS）转本地预览
- `--live`：允许已声明的外部写入，启动前展示账号、目标、预计记录数，要求一次 `y/N`
- 非交互环境不自动确认

### 5.3 外部写入回读

Live 写入完成后必须独立查回来，比对记录数和内容摘要。V1 这条设计是对的，保留，只在 live 用。

删除：`AuthorizationScope` / `AuthorizationRecord` / `AuthorizationClaim` / receipt / scope digest / TTL / single-use / profile fingerprint / element scope 检查 / `authorization-record.schema.json`。

### 5.4 保留的硬规矩

这几条留在 AGENTS.md，因为它们要么是法律/合规问题，要么无法用测试表达：

- CAPTCHA / 滑块 / 短信验证只检测、留证据、转人工，不绕过
- `.env`、`stores.local.toml`、`profiles/`、`runs/` 不提交
- 可提交文件里不出现真实店铺名、账号、Cookie、Token、本机路径
- agent 默认不建分支、不 commit、不 push

## 6. 框架如何"逐步完善"

这是 V1 失控的地方 —— 每次迭代只变大不变强，因为新经验一律被写成新的流程规矩，而流程规矩对 agent 无效。

V2 的迭代规则：

> **每完成一个应用，问一次：这次踩的坑，能不能变成一条会失败的测试？**
>
> - 能 → 加进 `rpa-core`，并附一条证明它会失败的测试
> - 不能，但能变成一个命令（如 `verify-elements`）→ 加进 CLI
> - 都不能 → **不加**。写进 AGENTS.md 的规矩，agent 只会用生成文书来满足它

配套一条抽象纪律：

> **任何"跨应用共享"的机制，在第三个应用真的重复了同一段代码之前，不许建。**
> 第二个应用只用来证伪，不用来抽象。

已知的第一条应用示例：这次踩的坑是"假断言" → 变成 `counterexamples` 强制机制。✓

## 7. 迁移路径

不做大爆炸重写。按**收益/成本**排序：

1. ~~**给现有 5 个 Step 补 `verify()` + `counterexamples`。**~~（已完成 2026-09-03）
   最便宜，且立刻产生价值 —— 它会当场暴露 S003（`bool(True)`）和 S004（`exists(table tbody)`，实测搜索前后同为 21 行）是假断言，以及 S003→S004→S005 整条链路从未确认过品牌筛选生效。
2. ~~**给 `BrowserActions` 加 `count()` 和 `texts()`。**~~（已完成）没有它们，第 1 步写不出真断言。
3. ~~**把 `real_runtime.py` + `cli.py` 的通用部分上提到 `rpa_core.cli`。**~~（已完成 2026-09-04）
   聚水潭和京麦均使用共享 CLI；框架统一执行反例、doctor、元素验证、运行、恢复和浏览器生命周期。
4. ~~**元素合并为 `elements.toml`，加 `expect_count`，实现 `verify-elements`。**~~（已完成；共享 CLI 调用应用阶段导航并逐项报告）
5. ~~**第二个应用（非聚水潭）用新结构写。**~~（2026-09-04 已完成京麦商品明细报表导出应用；登录、筛选、导出、查看与下载链路已在真实页面验证）
6. ~~**按实际使用情况删。**~~（应用运行路径已完成 2026-09-04）聚水潭已移除应用内运行时、授权流程、instruction 快照和双份 requirement 调用；旧核心合同仅作仓库兼容层，不进入新应用。

**让证据决定删什么。** 第 6 步不要提前做。
