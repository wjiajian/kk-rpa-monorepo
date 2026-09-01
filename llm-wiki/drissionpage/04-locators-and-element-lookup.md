# 定位语法与元素查找

官方来源：

- [查找元素概述](https://drissionpage.cn/browser_control/get_elements/intro)
- [定位语法](https://drissionpage.cn/browser_control/get_elements/syntax)
- [页面或元素内查找](https://drissionpage.cn/browser_control/get_elements/find_in_object)
- [相对定位](https://drissionpage.cn/browser_control/get_elements/relative)
- [行为模式](https://drissionpage.cn/browser_control/get_elements/behavior)
- [语法速查表](https://drissionpage.cn/browser_control/get_elements/sheet)

## 基本查找

页面、元素、iframe 和 shadow root 都可以在自己的范围内查找。

```python
element = tab.ele(locator, index=1, timeout=None)
elements = tab.eles(locator, timeout=None)
```

- `ele()` 返回指定序号的一个元素，序号从 1 开始，负数表示倒数；
- `eles()` 返回所有匹配元素组成的列表；
- 浏览器查找自带等待，默认跟随页面基础超时，官方默认 10 秒；
- 单次 `timeout` 不会修改页面默认设置；
- 找不到单个元素默认返回布尔值为 `False` 的 `NoneElement`；
- 对 `NoneElement` 调用实际功能会抛出 `ElementNotFoundError`；
- 查找多个元素失败时返回空列表。

框架适配器必须把 `NoneElement` 转换为明确的 `ElementLookupError` 或 `exists=False`，不能泄漏给应用。

## 定位语法

### 属性与文本

| 写法 | 含义 | 示例 |
| --- | --- | --- |
| `@name=value` | 单属性精确匹配 | `@name=keyword` |
| `@@a=1@@b=2` | 多条件“与” | `@@role=button@@text()=提交` |
| `@|a=1@|b=2` | 多条件“或” | `@|id=first@|id=second` |
| `@!name=value` | 否定条件 | `@!disabled` |
| `@tag()=div` | 标签名 | `@tag()=button` |
| `@text()=文本` | 组合条件中的文本 | `@@class=item@@text()=确认` |

匹配模式：

| 符号 | 行为 | 示例 |
| --- | --- | --- |
| `=` | 精确匹配 | `@id=row1` |
| `:` | 包含 | `@id:row` |
| `^` | 以指定内容开头 | `@id^row` |
| `$` | 以指定内容结尾 | `@id$1` |

### 简写

| 写法 | 含义 |
| --- | --- |
| `#value` | ID 精确匹配 |
| `.value` | class 字符串精确匹配 |
| `text=value` | 文本精确匹配 |
| `text:value` 或直接写文本 | 文本包含匹配 |
| `tag:div` 或 `t:div` | 标签匹配 |
| `xpath://...` 或 `x://...` | XPath |
| `css:...` 或 `c:...` | CSS selector |

DrissionPage 将完整 class 属性当作普通字符串处理，不采用 Selenium 中把空格替换成点的习惯。

## 相对定位

| 方法 | 查找范围 |
| --- | --- |
| `parent()` | 指定层级或符合定位符的祖先元素 |
| `child()` / `children()` | 直接子节点 |
| `next()` / `nexts()` | 后续兄弟节点 |
| `prev()` / `prevs()` | 前序兄弟节点 |
| `after()` / `afters()` | 整个 DOM 中位于当前元素之后的节点 |
| `before()` / `befores()` | 整个 DOM 中位于当前元素之前的节点 |

这些方法通常接受定位符、结果序号、超时和 `ele_only`。`ele_only=False` 时可能返回文本或注释节点。相对定位不能跨越 iframe 文档。

## 项目定位器规则

定位优先级：

1. 稳定且唯一的 ID；
2. 稳定的 `data-*`、`name`、role 或业务语义属性；
3. 页面组件范围内的组合定位；
4. 稳定文本；
5. 经真实页面验证的 CSS 或 XPath。

禁止：

- 应用源码中散落字符串定位器；
- 直接复制浏览器开发工具生成的绝对 XPath；
- 依赖随机 class、临时哈希或深层 `nth-child`；
- 从截图猜测 XPath/CSS；
- 跨步骤缓存 `ChromiumElement`。

所有定位器必须进入 `ElementSpec`，并在真实授权测试中验证唯一性、显示、可点击和刷新稳定性。
