# Generation Report — jushuitan.inventory.export_stock

> **0.4.0（2026-09-03）：V2 迁移。0.3.0 的"品牌筛选已验证"结论已被推翻。**

## 当前状态

| 项 | 值 |
| --- | --- |
| Application Version | 0.4.0 |
| Requirement Revision | 107 |
| Requirement Hash | `sha256:02de868803b5daf6eb76d4e66abfad385e20eddb9578a133a4285fc31cd30199` |
| Status | `ready_for_review` |
| Latest Review | 无。0.3.0 的审核记录保留为历史证据，不适用于 0.4.0 |
| 离线测试 | 285 项通过（应用 68、`rpa-core` 217） |
| 元素验证 | ✅ 已通过（`verify-elements-20260903T085838Z`，19 项 0 失效） |
| 真实 Preview | ✅ 已通过（`preview-20260903T090704Z`，S001–S005 全部完成） |

## 为什么 0.3.0 的结论不成立

0.3.0 的 README、Generation Report 和 Review Record 都写着"已验证 Brand Filter、Search"。代码不支持这个结论：

```python
# S003 —— 假执行器：回显输入，从不回读页面
def execute(...): return {"selected_brand": brand_value, "selection_visible": True}
def verify(...):  return bool(result["selected_brand"]) and bool(result["selection_visible"])

# S004 —— 假验证器：filter_applied_marker = "css:table tbody"
result_visible = browser.exists(filter_applied_marker, timeout=20.0)
def verify(...): return bool(result["filter_applied"])
```

2026-09-03 对真实页面做的只读探针（登录 → 库存 → 商品库存 → 搜索，只数匹配数，未点导出）：

```text
===== 搜索前（未做任何筛选） =====
  css:table tbody           -> 1
  css:table tbody tr (行数) -> 21
  //button[.='导出']        -> 1

===== 搜索后 =====
  css:table tbody           -> 1
  css:table tbody tr (行数) -> 21
```

结论：

- `table tbody` 在搜索之前就存在，`filter_applied` 在点搜索之前就是 `True`
- 搜索前后完全不可区分：搜索静默失败、请求被拒、筛选条件没传过去，S004 都返回成功
- S003 的 `selection_visible` 是硬编码 `True`，浏览器里发生了什么完全没查
- 因此 S003 → S004 → S005 整条链路**从未确认过品牌筛选生效**，S005 可能导出的是全量库存

同一次探针也纠正了一个猜测：业务 iframe 内 `导出` / `搜索` / `重置` 按钮**各只有 1 个**，不存在误点到同名按钮的问题。

## 0.4.0 的改动

### 断言改为回读页面状态

| Step | 0.3.0 的验证 | 0.4.0 的验证 |
| --- | --- | --- |
| S001 | `exists(module_marker)` | 不变（`module_marker` 带 `current___`，本来就有区分力） |
| S002 | `exists(page_marker)` | 不变（页签 active 状态，有区分力） |
| S003 | `bool(输入) and bool(True)` | **回读** `brand_selected_option`，选中集合必须恰好等于配置品牌 |
| S004 | `exists(table tbody)` | **结果行数 > 0** 且**搜索后回读的选中品牌仍恰好等于配置品牌** |
| S005 | 文件在 run 目录内、非空、哈希可复现 | 不变（本来就是真断言） |

S004 现在在**重新归一化之前**先回读一次平台留下的选中状态。0.3.0 的代码在搜索后直接重选品牌，把平台可能的重置盖掉了 —— 界面看起来对，结果表可能是未筛选的。

**这意味着 0.4.0 的 S004 有可能在真实运行中失败，而这个失败是正确的** —— 它暴露的是一直存在、但从未被检查的情况。

### 反例强制

每个 Step 提供至少一个假页面状态，`rpa-app test` 在该状态下真的跑一遍 `execute()`，要求它抛错或 `verify()` 返回 `False`。共 16 个反例。

`tests/test_falsifiable_assertions.py` 里有两条回归守卫，直接把 0.3.0 的 S003、S004 实现搬进来，断言它们**过不了**这套机制。

### 元素库

17 个分散的元素 TOML 合并为 `elements.toml`，每条带 `expect_count`（现在应成立的断言，不是历史记录）。新增：

- `product_stock.result_row`（`css:table tbody tr`，`expect_count = ">0"`）
- `product_stock.brand_selected_option`（回读选中集合的只读断言目标）
- `product_stock.filter_applied_marker`（`css:table tbody`，恒真）标记为 `weak`，任何 Step 都不得用它做断言

`shell.account_identity_surface`（`//body` 全文子串匹配）标记为 `assertion_strength = "weak"`。详见下方元素验证结果 —— 实测它匹配 9 个节点，比原先估计的更弱。

新增 `rpa-app verify-elements`：导航到各页面后逐条比对匹配数，报告失效条目和过弱断言。

### 框架侧

- `BrowserActions` 新增 `count()` 和 `texts()`。**接口的贫乏是断言贫乏的技术原因** —— 只有 `exists()` 返回布尔时，`verify()` 只能退化成 `bool(...)`
- 新增 `rpa_core.verification`（`Counterexample` / `FakeState` / 强制校验）和 `rpa_core.elements`（`elements.toml` 加载 + `expect_count` + 失效报告）
- 修复 `discovery.py` 端口检测的子串误报：`EXPORT_MENU` 里的 "ex**PORT**" 被判定为硬编码调试端口。已改为按标识符分词匹配，并附回归测试
- 修复 `test_authorization.py` 的时钟炸弹：`BASE_TIME` 是字面日期 + 10 分钟 TTL，这 3 个测试只在 2026-09-03 08:00–08:10 UTC 能通过

## 元素验证结果（2026-09-03，run `verify-elements-20260903T085838Z`）

真实浏览器，只读：登录 → 库存 → 商品库存 → 选品牌 → 搜索。未点导出，无外部写入。

到达全部 6 个阶段，19 个元素 **0 失效**：

```text
--- login_page ---   account_input / password_input / agreement_checkbox
                     submit_button ✓          password_notice_confirm expect=0 ✓
--- session ---      authenticated_marker ✓   navigation.inventory_module ✓
                   ⚠ account_identity_surface  expect=>0  actual=9
--- S001 ---         module_marker ✓          product_stock_entry ✓
--- S002 ---         page_marker ✓  brand_selector ✓  reset_button ✓  search_button ✓
--- S003 ---       ✓ brand_selected_option    expect=>0  actual=1
--- S004 ---       ✓ result_row               expect=>0  actual=24
                   ⚠ filter_applied_marker    expect=1   actual=1
                     export_menu ✓            export_stock_option expect=0 ✓
```

**最关键的一行是 S003 的 `brand_selected_option = 1`** —— 替换掉硬编码 `True` 的回读断言，在真实页面上确实读到了选中的品牌。

两条 ⚠ 都是有意标记的过弱断言：

- `account_identity_surface`（`//body`）实测匹配 **9 个** —— 多 iframe 页面每个 frame 各有一个 body，`text()` 只取第一个。身份校验比原先估计的还弱，待捕获精确的账号显示元素后替换
- `filter_applied_marker`（`css:table tbody`）保留仅为满足遗留 `search` 指令的依赖，任何 Step 都不得用它做断言

## 验证过程中发现并修复的 4 个缺陷

1. **`count()` / `texts()` 不重试瞬时上下文丢失。** 业务 iframe 在 page_marker 出现后会重建，查询已解析的 frame 抛 `ContextLostError`。`_locate` 一直有重试，新加的多元素查询没有 —— 导致把健康的 `brand_selector` 报成失效。已改为每次重试都重新解析 scope，附回归测试。
2. **`expect_count` 缺少阶段。** 在某个任意时刻统一检查，19 条里 7 条误报失效。新增必填的 `check_at`，`verify-elements` 改为边导航边逐阶段检查。
3. **导航中断被静默吞掉。** 原实现 `except Exception: break`，只报告"未到达"却不说原因。现在输出 `navigation_failure`（step / phase / 异常类型 / error_code / 消息）。
4. **`verify_elements` 借用了 `verify-candidates` 的授权 operation**，而后者要求非空候选项。已新增独立的 `AuthorizationOperation.VERIFY_ELEMENTS`。

## 一次偶发失败（未修复，需要观察）

一次运行中 S003 的 `select(brand_selector)` 抛 `ElementActionError` / `browser_element_action_failed`，随后的运行全部通过。这是 V1 原样保留的调用（`click(reset)` + `select`），不是 V2 迁移引入的。品牌多选组件的时序值得继续观察；如果复现频率上升，需要在 `_ensure_exact_custom_selection` 里加等待或重试。

另有一处运行体验问题：`keep_open` 生命周期把 Chrome 留着占用 9301，下一次运行直接以 `browser_port_lease_failed` 失败，而不是等待或复用。

## 真实 Preview 结果（2026-09-03，run `preview-20260903T090704Z`）

S001–S005 全部完成，`external_business_writes_executed = false`。

Checkpoint 里每个 Step 从真实页面回读到的断言依据：

```json
S001  {"inventory_module_active": true}                                    attempts=1
S002  {"product_stock_active": true}                                       attempts=1
S003  {"requested_brand": "<品牌>", "selected_brands": ["<品牌>"]}          attempts=2
S004  {"brands_after_search": ["<品牌>"], "brands_normalized": ["<品牌>"],
       "requested_brand": "<品牌>", "row_count": 24}                        attempts=1
S005  {"download_path": "runs/<run>/downloads/inventory-export.xlsx",
       "sha256": "sha256:c949b8...5a8bc", "size_bytes": 218251}             attempts=1
```

**S004 的 `brands_after_search` 是重新归一化之前从 DOM 读回来的** —— 平台没有重置品牌选择。这条 V1 声明了却从未执行的成功条件，至此第一次被真正验证。

`row_count = 24` 是页面第一页的可见行数；导出文件含 1330 行，两者不矛盾（列表分页）。

### 导出文件交叉验证

导出的 xlsx 为 218,251 字节、1330 数据行 × 47 列，**不含品牌列**，因此无法从文件侧直接证明筛选。旁证：全部 1330 行的 `款式编码` 前缀 100% 与配置品牌一致。这是旁证不是证明 —— 不排除该店铺商品本来就都是这个前缀。

**决定性证据仍是 DOM 回读**（S003/S004 的 `selected_brands`），这正是 V2 断言存在的意义。

### S003 重试了 1 次

`attempts=2` —— 品牌多选组件的偶发失败在正式运行中也出现了，重试策略覆盖住了。与前述"一次偶发失败"是同一现象，值得继续观察。

## 未执行

- 任何 external business write（本应用没有，Live 始终关闭）
- Developer Review

## 下一步

由开发人员审核 0.4.0、Requirement Hash 和本次 Preview run。审核通过后 `latest_review` 和 `ready_for_push` 才有依据 —— AI 不得自行设置这两项。
