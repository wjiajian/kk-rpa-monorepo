# 顶层 Python 指令源库

`instructions/` 保存经过真实验证、可独立复用的稳定能力。完整业务流程仍由应用的 `Program` 和 `Step` 编排。

## 目录与元数据

```text
instructions/<platform>/<product>/<capability>/
├── instruction.toml
└── instruction.py
```

```toml
schema_version = 1
kind = "instruction"
id = "example.web.open_login"
version = "1.0.0"
name = "打开登录页"
platform = "example"
product = "web"
status = "verified"
entrypoint = "instruction.py:OpenLogin"
dependencies = ["element:example.web.login.account"]
```

每条指令应明确四部分：

- 操作背景：平台、产品、页面和前置状态；
- 操作目标：依赖的稳定元素或服务；
- 操作动作：通过 `ExecutionContext` 执行的最小能力；
- 操作结果：声明输出和可观察的成功条件。

Python 实现继承 `rpa_core.instructions.Instruction`，公开 `InstructionSpec`，并实现 `execute()` 与 `verify()`。指令不得写 Step 检查点，也不得直接导入 DrissionPage、飞书、Excel 或数据库底层 SDK。

## 粒度

合适的公共指令示例：验证登录状态、打开模块、选择品牌、执行搜索、导出并验证下载。店铺专属规则、真实品牌、日期范围和应用输出策略应留在应用 Step 中。

如果一个能力还不能独立验证，应继续拆分；如果多个底层动作只有组合后才具有稳定业务含义，可以由一条指令封装，但每个输入、输出、前置条件和成功条件都必须机器可读。

## 候选与晋升

```text
应用内候选指令和候选元素
→ Fake Browser 测试
→ 开发人员授权真实浏览器验证
→ 逐条执行并验证结果
→ Preview 端到端通过
→ 提出回灌顶层库的独立 diff
→ 回归受影响应用
```

候选项不阻止离线测试，但阻止正常真实运行、审核和推送。顶层库更新不会改变已有应用；已有应用升级必须展示来源版本、哈希和文件 diff。
