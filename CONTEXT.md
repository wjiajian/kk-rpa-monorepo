# RPA Application Generation

一份业务需求形成一个可独立测试、配置和运行的 RPA 应用。

## Language

**Requirement Source**:
业务需求的原始来源及其读取版本。
_Avoid_: 随意补充的业务规则

**Requirement**:
开发者与 agent 共同维护的唯一需求基线。
_Avoid_: Requirement Spec、Requirement Memory、双份规范

**RPA Application**:
一份需求对应的独立交付单位，具有稳定身份和运行配置。
_Avoid_: 指令集合

**Program**:
一个应用按顺序完成的业务流程。
_Avoid_: 指令库

**Step**:
流程中的一个业务进展单位，具有实际动作和可观察的成功条件。
_Avoid_: 成功条件字符串

**Step Contract**:
一个业务步骤要求的输入、前置状态、产生的输出及可观察的成功条件。程序执行与 Agent 接管遵循同一契约。
_Avoid_: 动作清单、Agent 自行声明成功

**Element**:
应用页面目标的稳定身份，以及当前定位方式和特定阶段的匹配预期。定位方式变化不改变业务目标。
_Avoid_: 历史验证记录

**Element Catalog**:
一个应用正式流程依赖的页面目标集合。一次接管使用的临时辅助目标不必成为其中的永久条目。
_Avoid_: 整站元素清单、全局元素资产平台

**Browser Action**:
业务步骤和 Agent 接管使用的基础浏览器操作，承担页面交互及相应的等待、回读或下载处理。
_Avoid_: 指令编排、业务流程

**Successful Baseline**:
正常情况下必须被程序接受的测试场景。
_Avoid_: 默认成功

**Counterexample**:
故意违反已声明条件的测试场景，用于证明程序能够识别该条件失败。
_Avoid_: 任意异常

**Download Directory**:
应用指定的下载保存位置，可以由多个应用共用；保留既有文件，新下载重名时使用新文件名。
_Avoid_: 运行证据目录

**Evidence**:
记录一次运行过程与结论的日志、截图及结果记录。
_Avoid_: 成功的默认承诺

**Agent Resume**:
运行失败后，由 agent 判断并准备恢复位置，沿用原业务参数接着完成任务。
_Avoid_: 固定重试、无判断地跳过失败

**Agent Step Result**:
agent 临时完成失败步骤后提交的输出；满足原业务成功条件后才成为成功结果。
_Avoid_: agent 自行宣告成功

**Temporary Locator**:
仅为本次恢复任务替换的页面目标定位方式，不改变该目标的业务含义或成功条件。
_Avoid_: 永久修复、放宽验收条件

**Run Inputs**:
一次任务固定的业务参数，例如报表日期与品牌；续跑保持原值。
_Avoid_: 登录凭据、重新计算的今日参数

**Production Run**:
通过开发验收后，按照固定配置无人值守执行的运行。
_Avoid_: 每次人工批准的运行

**Preview Run**:
供开发检查使用的运行，支持预览的业务服务将拟写入内容保存在本地。
_Avoid_: 离线假浏览器测试
