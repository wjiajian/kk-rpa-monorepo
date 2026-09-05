# iframe、动作链与模式切换

官方来源：

- [iframe 操作](https://drissionpage.cn/browser_control/iframe)
- [动作链](https://drissionpage.cn/browser_control/actions)
- [模式切换](https://drissionpage.cn/browser_control/mode_change)

## iframe

DrissionPage 的 `ChromiumFrame` 同时具有元素和页面能力，无需 Selenium 风格的反复切入、切出。

```python
frame = tab.get_frame(loc_ind_ele, timeout=None)
frames = tab.get_frames(locator=None, timeout=None)
```

`get_frame()` 可以接收：

- 定位符；
- 从 1 开始的序号，负数表示倒数；
- 已有 `ChromiumFrame`；
- iframe 的 ID 或 name。

找不到时返回 `NoneElement`。嵌套 iframe 中按全局序号获取可能不准确，应优先使用稳定定位符。

同域 iframe 可以由页面对象跨层查找；跨域 iframe 必须先获得 `ChromiumFrame`，再在 frame 内部查找：

```python
frame = tab.get_frame("t:iframe")
element = frame.ele("text=目标")
```

项目统一包装为：

```python
with ctx.browser.frame(LoginPage.LOGIN_FRAME):
    ctx.browser.input(LoginPage.USERNAME, username)
```

应用不能持有 `ChromiumFrame`，也不能依赖底层同域跨层查找的隐式行为。

## 动作链

DrissionPage 动作链支持：

- `move_to()` 和相对移动；
- 左、中、右键点击及按住、释放；
- 鼠标滚轮；
- 键盘按下、释放、输入和逐字输入；
- 拖拽文件或文本；
- 链式等待。

动作链适用于悬停菜单、拖拽和组合键等普通元素方法无法稳定表达的场景。项目不向应用直接暴露动作链；应提供有业务语义、可记录和可验证的包装动作。

## d 模式与 s 模式

`MixTab` 和 `WebPage` 支持：

- `d` 模式：控制浏览器；
- `s` 模式：使用 Session/requests 收发请求。

```python
tab.change_mode(mode=None, go=True, copy_cookies=True)
```

切换时默认复制 Cookie，并跳转到原模式 URL；Headers 不会自动同步。`mode` 属性返回当前的 `"d"` 或 `"s"`。

项目初始实现只允许浏览器适配器使用 d 模式。s 模式会引入直接网络访问、Cookie 复制和另一套元素类型，必须作为单独集成能力设计，不能由业务应用用来绕过浏览器授权、网络审计或 `ExecutionContext`。

## 弹窗

页面提供 `handle_alert()` 和自动处理设置。业务需要处理弹窗时，在相应 Step 中按预期类型和文本决定动作，不能全局接受任意弹窗。生产流程按配置无人值守运行。
