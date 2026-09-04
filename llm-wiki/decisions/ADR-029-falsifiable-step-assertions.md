# ADR-029：以可证伪断言作为框架唯一的强制约束

- 状态：已接受
- 日期：2026-09-03

## 背景

V1 用 613 行 `AGENTS.md`、结构化门禁、快照哈希和审核留痕来保证质量。实际效果：

`StepSpec.success_conditions` 和 `InstructionSpec.success_conditions` 的类型是 `tuple[str, ...]` —— **自然语言字符串，永远不会被执行**。5 个 Step × 2 条成功条件 = 10 条断言，一条都不会跑。

真正执行的验证退化成了两类：

```python
# 假执行器：回显输入，不回读页面
def execute(...): return {"selected_brand": brand_value, "selection_visible": True}
def verify(...):  return bool(result["selected_brand"]) and bool(result["selection_visible"])

# 假验证器：断言一个页面上一直存在的东西
result_visible = browser.exists(filter_applied_marker)   # filter_applied_marker = "css:table tbody"
def verify(...): return bool(result["filter_applied"])
```

2026-09-03 的真实页面实测（只读探针）：

```
===== 搜索前（未做任何筛选） =====   css:table tbody -> 1,  tbody tr -> 21
===== 搜索后 =====                   css:table tbody -> 1,  tbody tr -> 21
```

结论：S003 恒真、S004 恒真，整条 S003 → S004 → S005 链路从未确认过品牌筛选生效，而应用状态是 `ready_for_push`。

根因不是 agent 不认真，是**激励结构装反了**：写一条假断言的成本是 0（填个字段），走完授权流程的成本很高。

## 决策

框架只保留一条强制约束，用它替代全部门禁、快照、审核和授权：

```python
def counterexamples(self) -> Iterable[Counterexample]: ...
```

`Counterexample` 携带一个**假浏览器状态**。`rpa-app test` 对每个 Step 的每个反例：

1. 在该状态下真的执行一次 `execute()`
2. 要求 `execute()` 抛错，或 `verify()` 返回 `False`
3. 若 `execute()` 正常返回且 `verify()` 返回 `True` —— 测试失败
4. Step 未提供任何反例 —— 测试失败

### 为什么反例必须是浏览器状态

如果反例只是一个直接喂给 `verify()` 的 `result` 字典，只能抓出假验证器，抓不出假执行器 —— 给上面的 S003 一个 `{"selection_visible": False}`，`verify()` 确实返回 `False`，测试通过，缺陷留下。

只有让反例是浏览器状态、并真的跑一遍 `execute()`，才能发现 `execute()` 根本没去页面上读。

### 配套：让真断言写得出来

V1 的 `BrowserActions` 只有 `exists()` 返回布尔、`text()` 返回单个字符串 —— **接口的贫乏直接导致了断言的贫乏**。V2 新增：

```python
def count(self, element) -> int: ...
def texts(self, element) -> list[str]: ...
```

## 结果

- 对 agent 有效的约束是会失败的测试，不是自然语言规矩 —— 后者它会满足字面要求然后继续
- 断言变真之后产生连锁收益：resume 不再需要预先声明前置动作，因为"当前状态还对不对"可以被真的检查
- 代价：写 Step 变贵了（必须构造反例）。这是有意的 —— 这正是"提高写错的成本"
- 风险：日后可能出现"这个 Step 造不出反例，先跳过"的压力。**造不出反例说明断言是恒真的，这时候要改的是断言，不是规则**

## 被否决方案

- **把 `success_conditions` 字符串交给 LLM 在运行时判定**：引入不确定性，且无法离线测试
- **只要求断言非平凡（静态检查）**：静态分析判定不了 `exists(某元素)` 是否恒真，那取决于页面
- **靠 code review 保证断言质量**：V1 已经有审核留痕机制，两条假断言照样通过了审核并被标记 `ready_for_push`
