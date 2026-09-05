# 元素与页面阶段检查

每个应用的 `elements.toml` 是该应用定位器的唯一来源。没有顶层元素库、应用快照或同步机制。

条目包含稳定元素 ID、`locator`、可选 `frame`、`expect_count`、`check_at` 和说明；复杂下拉可声明选项、选中项、浮层与关闭目标的定位器。具体字段见 [elements.py](../packages/rpa-core/src/rpa_core/elements.py)。

`expect_count` 表示检查阶段现在应成立的数量，不是历史测量结果。例如导出菜单尚未展开时，菜单选项的期望数量可以是 0。

`verify-elements` 通过应用的 `verify_element_stages` 到达各声明阶段后检查；已有会话时登录页阶段可以跳过。未到达的阶段会报告为未验证。

未知定位器保持缺省，在 `requirement.md` 记录待确认项。真实运行在启动浏览器前报告未解析元素；假浏览器可以按稳定 ID 验证完整业务流程。

截图只说明业务意图，不能推导 CSS、XPath 或唯一性。真实捕获与验证仍需开发期授权。页面阶段检查通过，也不代替 Step 对账号、筛选条件和报表的业务回读。
