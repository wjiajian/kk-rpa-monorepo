# 测试、反例与证据

## 反例强制是框架唯一的强制约束

```python
def counterexamples(self) -> Iterable[Counterexample]: ...
```

`Counterexample` 携带一个**假浏览器状态**。`rpa-app test` 对每个 Step 的每个反例：

1. 在该状态下真的执行一次 `execute()`
2. 要求 `execute()` 抛错，**或** `verify()` 返回 `False`
3. 若 `execute()` 正常返回且 `verify()` 返回 `True` —— 测试失败
4. Step 未提供任何反例 —— 测试失败

### 为什么反例必须是浏览器状态

如果反例只是一个直接喂给 `verify()` 的 result 字典，只能抓出**假验证器**，抓不出**假执行器**：

```python
# 假执行器：回显输入，从不读页面
def execute(...): return {"selected_brand": brand_value, "selection_visible": True}
def verify(...):  return bool(result["selected_brand"]) and bool(result["selection_visible"])
```

给它 `{"selection_visible": False}`，`verify()` 确实返回 `False`，测试通过，缺陷留下。只有让反例是浏览器状态、并真的跑一遍 `execute()`，才能发现它根本没去页面上读。

### 好反例的写法

反例要针对**这个 Step 声明的每一条成功条件**各造一个：

```python
def counterexamples(self):
    # 对应 "filtered inventory result marker is visible"
    yield Counterexample("结果为空", browser=fake(counts={ROW: 0}))
    # 对应 "the configured brand remains selected after search"
    yield Counterexample("搜索后品牌被平台重置", browser=fake(texts={BRAND: []}))
    yield Counterexample("筛选串了其他品牌",   browser=fake(texts={BRAND: ["其他品牌"]}))
```

**造不出反例说明断言是恒真的。这时候要改的是断言，不是规则。**

## 其他测试层次

### 1. 无副作用测试（默认自动执行）

- Step 顺序、分支、循环、重试和恢复
- Fake Browser / Fake Excel / Fake Feishu / Fake Database
- **反例强制**（上文）
- 默认模式的写入拦截与 `--live` 未确认时的拒绝
- 日志脱敏和检查点原子写入
- App / Step ID 唯一性
- `elements.toml` 可解析、ID 唯一、`expect_count` 合法

### 2. 架构测试

扫描应用源码，拒绝：

- 直接导入 DrissionPage、飞书 SDK、Excel 底层库或数据库驱动
- `page.ele(...).click()` 等绕开 `BrowserActions` 的调用
- 硬编码 Profile 路径、调试端口、凭据和本机绝对路径
- 误提交 `.env`、`stores.local.toml`、`profiles/`、`runs/`

### 3. DrissionPage 适配器契约测试

用 Fake Tab 或受控页面验证：

- 每个动作重新查找元素
- 等待和超时转换正确
- 底层异常映射为稳定错误码
- 输入内容不进入日志
- iframe 和标签页上下文退出后恢复
- 下载任务等待、超时和产物校验正确
- 应用层看不到 DrissionPage 类型

这类测试不等于真实 Chromium 集成。

### 4. 元素验证

```bash
uv run rpa-app verify-elements --account <alias> --yes
```

逐条检查匹配数是否符合 `expect_count`，并对 `//body`、`css:table tbody` 这类近乎恒真的定位器发出**断言过弱**警告。详见 [元素库与失效检测](04-elements-and-pages.md)。

### 5. 真实运行

默认模式允许页面读取、查询、筛选和下载；外部业务写入转本地预览。检查成功条件、下载文件、哈希、失败恢复和证据。Profile、端口和运行目录保持账号隔离。

`--live` 需要单独确认，完成后必须回读验证。

## 证据要求

每次运行至少关联：

- `run_id`、`app_id`、程序版本
- 账号脱敏别名、运行模式
- 步骤、尝试次数、耗时和验证结果
- 错误码和是否可重试
- 截图、下载、预览和日志引用
- 未执行的测试及原因

证据结论必须区分：

```text
框架代码完成
≠ 离线测试通过
≠ 元素验证通过
≠ 真实 Preview 通过
≠ Live 写入验证通过
≠ 业务验收通过
```

不得把预览成功写成真实写入成功，不得把自动测试通过写成业务验收通过。

## DrissionPage 升级回归

升级底层版本时至少回归：

- 浏览器连接和已有 Profile
- 元素查找、等待、输入与点击
- `count()` / `texts()` 的多元素语义
- iframe 和新标签页
- 下载任务、截图和失败证据
- 端口、锁和浏览器生命周期
- 所有引用公共浏览器适配器的应用

记录版本、日期、测试环境和受影响应用。**不得只以安装成功作为兼容性结论。**
