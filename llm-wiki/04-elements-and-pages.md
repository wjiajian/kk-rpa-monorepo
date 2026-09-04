# 元素库与失效检测

## 一个应用一个 elements.toml

```text
apps/<slug>/elements.toml
```

没有顶层元素源库，没有快照，没有锁文件。跨应用复用元素在第三个应用真的需要同一个定位器之前不做 —— 到时候 `git grep` 抄一份。

## 格式

```toml
[jushuitan.erp.product_stock.export_menu]
locator      = "xpath://button[translate(normalize-space(.),' ','')='导出']"
frame        = "css:iframe[src*='/erp-scm-goods/stockInventoryManagement']"
expect_count = 1
check_at     = "S004"
note         = "列表右上角导出下拉入口"

[jushuitan.erp.product_stock.brand_selector]
locator                 = "css:input[placeholder='商品品牌']"
frame                   = "css:iframe[src*='/erp-scm-goods/stockInventoryManagement']"
expect_count            = 1
check_at                = "S002"
option_locator          = "css:div.j-item-text.ellipsis-1"
selected_option_locator = "css:label.goods-checkbox-wrapper-checked div.j-item-text.ellipsis-1"
popup_locator           = "css:div.goods-dropdown.j-selector-dropdown"
dismiss_locator         = "css:input[placeholder='商品编码']"
note                    = "多选品牌组件；selected_option_locator 用于回读真实选中集合"
```

## expect_count 是断言，不是记录

这是 V2 与 V1 `[verification]` 块的本质区别：

| | 含义 | 能发现失效吗 |
| --- | --- | --- |
| V1 `[verification] match_count = 1` | 2026-09-01 那一刻匹配了 1 个 | 否 |
| V2 `expect_count = 1` | **现在**必须匹配 1 个 | 是 |


`check_at` 指定这条期望在哪个导航阶段成立：`login_page` / `session` / `S001` / `S002` / ...

**这是第一次真实运行逼出来的。** 不带阶段、在某个任意时刻统一检查，19 条里有 7 条报"失效"而实际什么都没坏 —— 登录框在已登录页面本来就是 0 个，"模块已激活"标识在导航更深之后本来就不再匹配。没有阶段的期望不是断言，只是把歧义搬进了报告。

支持的写法：`1`、`">0"`、`">=2"`、`"0"`（用于断言某元素不应存在）。

`locator` 可以省略 —— 表示定位器尚未捕获。生产适配器调用 `require_locator()` 时 fail-closed，Fake Browser 按稳定 ID 测试完整业务编排。**不要编造未验证的 XPath/CSS**，也不要因为一个元素未知就只写半个流程。

## verify-elements

元素库的核心价值是**页面改版时在一个地方修好，所有引用点跟着好**。`verify-elements` 是兑现这个价值的命令：

```bash
uv run rpa-app verify-elements --account STORE_001 --yes
```

```text
jushuitan.erp.navigation.inventory_module      expect=1    actual=1    ✓
jushuitan.erp.product_stock.export_menu        expect=1    actual=1    ✓
jushuitan.erp.product_stock.result_row         expect>0    actual=21   ✓
jushuitan.erp.product_stock.row_brand          expect>0    actual=0    ✗ 失效
jushuitan.erp.shell.account_identity_surface   expect=1    actual=1    ⚠ 定位器为 //body，断言过弱
```

三类结论：

- **✓** 匹配数符合 `expect_count`
- **✗ 失效** 匹配数不符 —— 页面改版了，去修这一个条目
- **⚠ 断言过弱** 定位器是 `//body`、`css:table tbody` 这类几乎恒真的表达式。它们能"匹配成功"但区分不了任何状态，是假断言的温床

## 定位器优先级

1. 稳定且唯一的 `id`
2. 业务稳定的 `data-*` 属性
3. 稳定 `name`、角色或可访问名称
4. **页面组件范围内、带稳定锚点的相对定位**
5. 稳定文本
6. 经真实页面验证的 CSS 或 XPath

避免：绝对 XPath、深层 `nth-child`、随机 class、临时哈希属性、屏幕坐标、仅凭截图推断的定位器。

特别注意第 4 条。实测教训：`//button[normalize-space(.)='导出']` 这类**无祖先锚点的全局按钮文本**，在当前页面上恰好唯一，但换一个布局就可能匹配到另一个同名按钮。有稳定祖先时一定加上：

```
✓ //div[contains(@class,'ant-modal')]//button[normalize-space(.)='确 定']
✗ //button[normalize-space(.)='确 定']
```

## 逐步元素分析

获得真实浏览器确认后，按需求步骤逐个处理：

1. 记录 URL、标题、标签页、iframe 和登录状态
2. 只分析当前步骤的目标，不全量抓取无关 DOM
3. 生成按稳定性排序的候选定位
4. 用稳定锚点缩小作用域
5. **验证预期匹配数量**、可见、可用/可点击和页面身份
6. 刷新或重新进入页面复核
7. 执行一个原子动作
8. 用 URL、标题、状态元素、**回读的筛选值**或下载产物验证结果
9. 保存脱敏证据
10. 失败时停在当前步骤，把未解决元素写进 `requirement.md`，不猜测后续页面

第 8 条是重点：**验证要回读页面状态**。`brand_selector` 上的 `selected_option_locator` 就是为此存在的 —— V1 定义了它却从未用它验证，导致 S003/S004 恒真。

## 查找、等待和 iframe

- 元素操作前由适配器执行必要等待
- 可点击动作至少验证目标可点击
- 等待失败必须转换为稳定错误，不能把空对象传给业务步骤
- 每次动作重新解析 iframe，业务应用不保存 frame 对象
- 若 `BrowserActions` 契约确实不足，先提交独立的公共接口 diff 和 Fake 测试，不能让应用直接访问 DrissionPage
