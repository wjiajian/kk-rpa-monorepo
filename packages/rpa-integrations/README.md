# 外部系统接入

真实飞书、数据库适配器跟第一个实际写入应用落地。
应用通过 ApplicationDefinition.build_services(context) 提供服务实例，
业务步骤用 ctx.feishu / ctx.db / ctx.excel 调用。
工厂只构造服务，写入在步骤中发生；预览与事务由服务负责。
当前两个应用只有浏览器下载，不宣称已实现真实数据写入。
