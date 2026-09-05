# 测试、反例与证据

当前契约见 [verification.py](../packages/rpa-core/src/rpa_core/verification.py)。每个应用的 `build_test_context(step, case, temporary_root)` 同时供 CLI 和应用测试使用；`case=None` 是正常场景。

框架对每一步先验证正常场景能执行成功且 `verify` 返回 True，再跑全部反例：

- 动作本来就应失败的反例显式声明 `expected_error`，其他执行异常属于测试错误。
- 结果错误的反例要求执行成功，然后 `verify` 返回 False；校验器自身抛错不能算拦截成功。
- 每一步至少有一个由 `verify` 拒绝的结果反例。
- `after_execute(context, result)` 可在动作后修改假页面或测试文件，例如将已下载文件清空；不直接伪造一份结果字典替代执行。

```python
def counterexamples(self):
    yield Counterexample("选中了其他品牌", FakeState(texts={BRAND: ("OTHER",)}))
    yield Counterexample("搜索按钮缺失", FakeState(hidden=(SEARCH,)),
                         expected_error=ElementLookupError)
```

这会拦住恒真验证器、没有正常成功场景的恒假验证器，以及忽略错误页面状态的执行器。反例质量仍取决于是否覆盖真实成功条件；框架不能证明任意业务实现都正确。

`rpa-app test` 先执行上述契约，再运行应用 pytest。关注正常业务顺序、错误账号或条件、下载失败与空文件、失败后重新从头执行，以及 agent 指定恢复步骤续跑。

底层假 Tab 测试覆盖浏览器定位、等待、iframe、新标签页、选择、下载目录及生命周期。它们不等于真实浏览器测试。

运行的 `events.jsonl` 记录步骤与状态，`result.json` 持续记录原业务参数、完成步骤、结果和失败诊断，截图位于 `evidence`。保留每次结果，所有命令保留已有下载文件，同名下载改名。

续跑回归覆盖跨日仍用原日期、本地配置变化仍用原品牌、旧弹窗消失不阻断下载、选择更早的恢复点、原记录保留和无效恢复点在浏览器启动前报错。

报告明确区分离线测试、真实元素验证、真实运行和业务验收。本次框架迁移的真实运行仍等待授权。
