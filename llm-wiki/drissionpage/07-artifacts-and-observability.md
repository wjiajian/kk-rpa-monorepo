# 下载、截图、上传与监听

官方来源：

- [浏览器下载](https://drissionpage.cn/download/browser)
- [截图和录像](https://drissionpage.cn/browser_control/screen)
- [上传文件](https://drissionpage.cn/browser_control/upload)
- [监听网络数据](https://drissionpage.cn/browser_control/listener)
- [获取控制台信息](https://drissionpage.cn/browser_control/console)

## 下载

推荐入口：

```python
mission = element.click.to_download(
    save_path,
    rename=None,
    suffix=None,
    new_tab=False,
    by_js=False,
    timeout=None,
)
result = mission.wait(show=True, timeout=None, cancel_if_timeout=False)
```

`click.to_download()` 返回 `DownloadMission`。如果下载在新标签页触发，必须设置 `new_tab=True`。

其它等待：

| API | 行为 |
| --- | --- |
| `tab.wait.download_begin(...)` | 等待一个下载任务开始，成功返回任务对象 |
| `tab.wait.downloads_done(timeout=None, cancel_if_timeout=True)` | 等待当前 Tab 下载完成 |
| `browser.wait.downloads_done(...)` | 等待浏览器下载完成 |

官方文档提醒：下载完成前文件名可能是临时任务 ID，重命名在任务结束时完成，因此必须等待任务结束。

项目下载包装器必须：

- 固定到当前 `run_id/downloads/`；
- 设置有界超时；
- 验证最终文件存在、文件名、大小、哈希或业务内容；
- 把底层任务转换为 `DownloadRef`；
- 不把本机绝对路径写入可提交报告。

## 截图

页面截图：

```python
tab.get_screenshot(
    path=None,
    name=None,
    as_bytes=None,
    as_base64=None,
    full_page=False,
    left_top=None,
    right_bottom=None,
)
```

元素截图：

```python
element.get_screenshot(
    path=None,
    name=None,
    as_bytes=None,
    as_base64=None,
    scroll_to_center=True,
)
```

返回值依据参数可能是文件路径、图片字节或 Base64。官方参数优先级是 `as_bytes > as_base64 > path`。

项目默认保存文件证据并返回 `ArtifactRef`，失败截图进入当前运行目录。截图可能包含账号、姓名和业务数据，禁止提交 Git，进入报告前必须脱敏。

## 上传

自然交互方式：

```python
element.click.to_upload(file_paths, by_js=False)
```

`file_paths` 可以是单路径、路径列表或换行分隔的多路径。也可以先设置上传路径、点击按钮，再等待异步录入完成：

```python
tab.set.upload_files(paths)
button.click()
tab.wait.upload_paths_inputted()
```

跨域 iframe 中上传时，路径设置和等待必须在对应 `ChromiumFrame` 上执行。

上传属于外部副作用动作。Preview 默认拦截真实上传并生成文件清单预览；Live 必须限定目标页面、步骤、文件和运行 ID。

## 网络监听

每个 Tab 和 Frame 内置网络监听器。关键规则是先启动监听，再执行会产生请求的动作：

```python
tab.listen.start(targets, is_regex=False, method=("GET", "POST"))
button.click()
packet = tab.listen.wait(count=1, timeout=10)
```

主要能力：

- `listen.start(...)` 设置 URL 特征、正则、方法和资源类型；
- `listen.wait(...)` 等待并取得数据包；
- `listen.steps(...)` 逐个实时消费；
- 未在 `start()` 前发生的数据包不会被捕获。

网络包可能含 Cookie、Authorization、请求体和业务数据，默认只记录脱敏 URL、方法、状态、耗时和匹配结果。

## 控制台监听

```python
tab.console.start()
data = tab.console.wait(timeout=10)
tab.console.stop()
```

`ConsoleData` 可包含来源、级别、文本、解析后的 body、URL 和行列位置。不是所有 DevTools 控制台内容都能获取，官方说明主要捕获 `console.log()` 等输出。

控制台文本同样要经过敏感信息过滤后才能进入运行证据。
