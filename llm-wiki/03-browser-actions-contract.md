# BrowserActions 契约

业务通过 `ctx.browser` 访问浏览器，接口定义以 [browser.py](../packages/rpa-core/src/rpa_core/browser.py) 为准。底层适配在 [drission_browser.py](../packages/rpa-core/src/rpa_core/drission_browser.py)。

当前接口包括导航、存在与匹配数检查、点击、输入、单个或多个文本回读、选择、点击并切换新标签页、下载、截图。

这些是普通操作 API，不承担指令注册或流程解释。新增方法应对应真实遇到的等待、交互、结果回读或错误处理问题；不逐个包装底层库的全部方法。条件、循环和数据处理使用 Python，品牌筛选或报表日期选择等业务组合保留为应用内函数。

`count()` 和 `texts()` 让“结果为空”“选中品牌不符”等状态可以被业务明确判断。不能用页面始终存在的容器代替筛选结果。

每次操作重新定位元素及 iframe。适配器负责等待、短暂页面上下文丢失后的重新定位、底层错误转换、新标签页切换和下载超时。业务不接触 DrissionPage 对象。

`SecretValue` 在字符串和调试表示中隐藏内容。输入值只在适配器最终调用时取出。

`DownloadRef` 返回路径、状态、字节数及一次计算的摘要。两个应用只按正确报表和非空下载验收，不反复计算摘要或解析工作簿。

下载使用运行配置传入的 `download_dir`；截图使用每次独立的 `run_dir/evidence`。默认使用系统下载文件夹；所有命令保留已有文件，同名下载自动改名，返回实际下载路径。

`FakeBrowserActions` 只读写测试临时目录、不访问网络。它支持元素可见性、匹配数、文本、下载和新标签页场景；应用测试统一使用各自的 `build_test_context`。
