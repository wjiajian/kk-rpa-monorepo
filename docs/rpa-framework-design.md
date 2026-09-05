# RPA 核心框架设计 V3

## 1. 两个应用确认的边界

2026-09-05 设计复查确认：
- 只有聚水潭库存导出和京麦商品明细导出两个测试应用，没有旧应用兼容要求。
- 下载验收是拿对报表并成功下载，不解析 Excel 核对业务数据。
- 导出失败允许从头重跑，也支持 agent 判断恢复位置后续跑；接受必要时重复生成同条件的平台报表。
- 下载路径可指定，目前程序共用同一个目录；新 run 前清空，resume 保留已有文件，不做目录并发协调。
- 后续支持飞书、数据库和平台操作。写入按业务提供的事务方式执行，不在框架内设计部分写入恢复、补偿或重复处理。
- 上线后无人值守，不逐次人工确认。

这些约定采用 agent 指定恢复点的续跑方式，替代旧的自动检查点恢复与逐次授权设计。

## 2. 核心结构

BrowserActions 隔离浏览器实现，Element 集中定位器，Step 描述有序业务进展。
CLI 统一配置加载、浏览器生命周期、下载目录准备、执行与测试。

程序依次调用每步 execute 和 verify。校验通过才记录成功；失败记录步骤、错误类型并结束。
run 从第一步开始。resume 读取原失败记录，沿用原业务参数和恢复点之前的成功结果；两者均创建新日志目录。
登录与身份检查也是普通 Step，不使用应用自定义 prepare / cleanup / verify_recovery 钩子。

## 3. 文件与配置

每个应用保留：
- app.toml：app_id、name、entrypoint。
- requirement.md：来源版本、业务流程、输入输出、未决问题、验收事实。
- elements.toml：定位器、expect_count、check_at。
- 独立依赖、锁文件、环境、应用代码与测试。
- config/stores.example.toml 和忽略的 stores.local.toml。

download_directory 相对于应用目录解析，也可指定绝对路径。
两个样本默认 ../../runs/downloads，指向同一个仓库下载目录。
浏览器下载和文件校验均使用此目录；新 run 与 verify-elements 前清空，resume 不清空。
应用源码和本次日志所在目录不能被当成下载目录清空。

日志、截图与 result.json 保存在各应用 runs/<run_id>。result.json 保存账号、模式、下载目录、业务输入、完成步骤、输出和失败诊断，每步更新；resume 用这些记录恢复业务上下文，原记录不覆盖。
下载检查目标匹配、传输完成、文件在指定目录且非空。
底层下载引用的校验码只作附加信息，不证明业务数据正确，不重复计算。

## 4. 测试先有正常场景

V2 把任意 execute 异常算作反例通过，导致两个下载步骤的 verify 改成恒真仍能通过。
京麦的正常测试与反例工厂中的弹窗文本表示也曾不一致。

每个应用只维护一个 build_test_context(step, case, temporary_root)：
- case 为 None：execute 必须成功且 verify 返回 True。
- 普通反例：execute 完成后，verify 必须返回 False。
- 动作失败：明确 expected_error，其他异常算测试故障。
- after_execute 可修改假页面或假文件，构造动作完成后结果错误的场景。
- 每步至少有一个结果反例，不能全部依靠动作异常过关。

这些测试证明所列条件被检查，不声称覆盖所有业务错误。
实际定位器仍需在授权真实页面用阶段化 verify-elements 验证。

## 5. 正式运行与业务服务

run 默认 live 模式，没有交互询问、授权记录、TTL、一次性凭证。
--preview 通过 context.mode 交给支持预览的业务服务；它不是离线测试，也不阻断所有网页操作。
开发验收时确认账号、目标、范围。agent 另行开展真实验证仍需用户授权。

ApplicationDefinition.build_services(context) 向同一运行注入具体服务，
业务通过 ctx.feishu / ctx.db / ctx.excel 调用。未配置服务直接报错，没有默认假后端。
工厂只构造服务，业务操作放在 Step；事务、连接资源和可选预览由服务负责。
框架不重试写入，不补偿部分写入。

当前两个应用仅使用浏览器。真实飞书、数据库适配跟第一个实际写入需求完成，
不提前猜目标表、字段映射或事务策略。

## 6. 命令

在各应用目录执行：

    uv run rpa-app doctor
    uv run rpa-app test
    uv run rpa-app verify-elements --account STORE_001
    uv run rpa-app run --account STORE_001
    uv run rpa-app run --preview --account STORE_001
    uv run rpa-app resume <run_id> --from-step S006

doctor、test 离线，不启动浏览器或清空真实下载目录。
verify-elements、run 都会真实运行并清空配置下载目录。
resume 会接管保留的浏览器并执行指定步骤，保留已有下载文件。
失败返回非零退出码及 run_id。调度由调用方负责；重新开始用 run，agent 续跑用 resume。
不保留旧 --yes、--live 入口。

## 7. Agent 续跑

agent 先读取失败日志与结果，检查当前页面，修复问题并准备恢复步骤需要的页面和文件，再明确指定 --from-step。可以选择失败步骤或更早的步骤；其前面的步骤必须有成功记录，不能静默跳过未完成步骤。

框架从选定步骤起重新 execute 和 verify，保留此前的成功输出，不重新验证已离开的历史页面。例如京麦完成报表导出后弹窗已关闭，下载续跑无需重新展示旧弹窗。

RuntimeOptions.inputs / ctx.inputs 只保存可序列化业务参数：京麦保存目标日期，聚水潭保存品牌和导出文件名。续跑使用原值，日期跨天或本地品牌配置变化不会改变原任务；凭据仍从本地配置加载。

浏览器失败后保留并记录接管信息，成功关闭；已有 BrowserManager 负责后续连接。若窗口或登录态已失效，agent 恢复页面或选择更早的步骤。框架不自动诊断、修复代码或决定恢复位置。

每次续跑生成新的 run_id，在 result.json 记录 resumed_from 和 from_step。若再次失败，agent 可以基于新的失败记录继续处理。旧版缺少 inputs 的记录不自动迁移。

## 8. 清理与演进

删除 V1 授权记录、catalog 快照、instruction 注册表、需求哈希及兼容层。
版本交给包和 Git，旧决定作为历史保留在 Git 和 ADR。
继续保留浏览器账号隔离、端口管理、页面等待、新标签页与下载完成判定。

每次新增应用用真实业务失败完善测试。
第三个实际应用证明重复后再抽取共享业务能力，不预建平台包。
