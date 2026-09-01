# 连接浏览器与启动配置

官方来源：

- [连接浏览器](https://drissionpage.cn/browser_control/connect_browser)
- [浏览器启动设置](https://drissionpage.cn/browser_control/browser_options)

适用文档版本：DrissionPage `4.1.1.4`。

## Chromium 初始化

官方签名：

```python
Chromium(addr_or_opts=None, session_options=None)
```

`addr_or_opts` 可以是：

| 形式 | 行为 |
| --- | --- |
| `None` | 使用配置文件或内置配置启动或接管浏览器 |
| `int` | 连接指定本地端口；端口空闲时按默认配置启动 |
| `"ip:port"` | 连接指定地址 |
| WebSocket URL | 通过完整 ws/wss 地址连接 |
| `ChromiumOptions` | 按配置启动或连接浏览器 |

示例：

```python
from DrissionPage import Chromium

browser = Chromium(9333)
browser = Chromium("127.0.0.1:9333")
```

官方文档说明，同一 Python 进程中，同一个浏览器只对应一个 `Chromium` 对象；重复连接会取得同一对象。

## ChromiumOptions

初始化：

```python
ChromiumOptions(read_file=True, ini_path=None)
```

配置对象只在浏览器启动时生效。浏览器已经启动后再修改配置不会生效；接管已运行浏览器时，大多数启动配置也不会生效。

常用方法：

| 方法 | 参数要点 | 官方行为 |
| --- | --- | --- |
| `set_browser_path(path)` | 浏览器可执行文件路径 | 返回配置对象，可链式调用 |
| `set_local_port(port)` | 本地调试端口 | 与 `set_address()`、`auto_port()` 互斥 |
| `set_address(address)` | `ip:port` 或 ws 地址 | 与本地端口、自动端口互斥 |
| `set_user_data_path(path)` | Chromium User Data 路径 | 保存登录态和浏览器配置 |
| `set_cache_path(path)` | 缓存目录 | 返回配置对象 |
| `set_tmp_path(path)` | 临时文件默认路径 | 返回配置对象 |
| `existing_only(on_off=True)` | 只连接已存在浏览器 | 连接失败时不自动启动 |
| `set_argument(arg, value=None)` | Chromium 启动参数 | 可链式调用 |
| `remove_argument(arg)` | 删除启动参数 | 可链式调用 |
| `clear_arguments()` | 清空启动参数 | 可链式调用 |
| `auto_port(on_off=True, scope=None)` | 自动端口和临时用户目录 | 临时全新浏览器，不适合持久登录态 |

配置示例：

```python
from DrissionPage import Chromium, ChromiumOptions

options = (
    ChromiumOptions()
    .set_browser_path(browser_path)
    .set_local_port(debug_port)
    .set_user_data_path(profile_path)
)
browser = Chromium(options)
```

## 多浏览器规则

官方文档明确要求：同时控制多个浏览器时，每个浏览器都要使用独立端口和独立用户数据目录，二者缺一不可。

```python
first = ChromiumOptions().set_local_port(9111).set_user_data_path(profile_a)
second = ChromiumOptions().set_local_port(9222).set_user_data_path(profile_b)
```

项目进一步要求：

- 端口必须由 `PortPool` 动态租用，应用不得硬编码；
- Profile 必须由 `ProfileManager` 分配并加排他锁；
- 一个账号对应一个持久化 Profile；
- `auto_port()` 只用于无状态隔离测试，不用于需要复用登录态的正式账号；
- 多进程环境不能依赖 `auto_port()` 自身避免冲突，必须使用机器级端口租约；
- 不连接系统日常使用的默认 Chrome Profile。

## 浏览器退出行为

官方连接页提醒：一般情况下 Python 程序结束不会主动关闭浏览器进程，无头浏览器也可能继续在后台运行。

因此项目不能依赖进程退出隐式清理，必须由 `BrowserManager` 根据 `KEEP_OPEN`、`REUSE_UNTIL_IDLE` 或 `TERMINATE_ON_FINISH` 明确处理生命周期、锁和端口租约。
