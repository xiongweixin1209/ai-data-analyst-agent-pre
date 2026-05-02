# Text-to-SQL 评估报告

> 生成时间：2026-05-02 10:48:49  
> 测试用例数：80  
> 数据库：Northwind (`data/northwind.db`)  
> 模型：qwen2.5-coder:7b (Ollama local)  

---

## 一、汇总指标对比

| 指标 | default（三层策略） | zero_shot_only | few_shot_top5 |
|---|---|---|---|
| LLM 调用成功率 | 100.0% | 100.0% | 100.0% |
| SQL 语法正确率 | 100.0% | 100.0% | 100.0% |
| 执行成功率 (EX) | 82.5% | 85.0% | 78.8% |
| 策略分类准确率 | 56.2% | 50.0% | 48.8% |
| 平均耗时 | 3556 ms | 3360 ms | 3419 ms |

> **策略分类准确率** 在 zero_shot_only / few_shot_top5 模式下意义有限（策略被强制指定），仅供参考。

---

## 二、各类别执行成功率（default 模式）

| 类别 | 用例数 | 语法正确 | 执行成功 | EX 成功率 |
|---|---|---|---|---|
| 单表查询 | 10 | 10 | 10 | 100.0% |
| 多表联结 | 15 | 15 | 12 | 80.0% |
| 聚合统计 | 15 | 15 | 14 | 93.3% |
| 时序查询 | 10 | 10 | 5 | 50.0% |
| 窗口函数 | 10 | 10 | 9 | 90.0% |
| 复杂嵌套 | 10 | 10 | 7 | 70.0% |
| DWS表查询 | 5 | 5 | 5 | 100.0% |
| 边界异常 | 5 | 5 | 4 | 80.0% |

---

## 三、按难度的执行成功率（default 模式）

| 难度 | 用例数 | 执行成功 | 成功率 |
|---|---|---|---|
| easy | 23 | 21 | 91.3% |
| medium | 22 | 18 | 81.8% |
| hard | 27 | 21 | 77.8% |
| expert | 8 | 6 | 75.0% |

---

## 四、执行失败用例（default 模式）

| ID | 查询 | 类别 | 策略 | 错误信息 |
|---|---|---|---|---|
| 15 | 查询来自美国的客户的订单及每笔订单金额 | 多表联结 | few_shot | no such column: od.UnitPrice |
| 18 | 查询包含海鲜类产品的订单编号和客户名称 | 多表联结 | few_shot | no such column: c.CompanyName |
| 22 | 查询没有下过任何订单的客户 | 多表联结 | few_shot | no such column: customer_id |
| 26 | 统计每个国家的客户数量并按数量降序排列 | 聚合统计 | few_shot | no such column: country |
| 42 | 查询2015年第三季度的订单 | 时序查询 | few_shot | no such column: order_date |
| 43 | 统计每年的订单数量和总运费变化趋势 | 时序查询 | few_shot | no such column: invoice_date |
| 47 | 查询2013年和2014年都有购买记录的客户数量 | 时序查询 | few_shot | no such column: customer_id |
| 49 | 查询2021年到2023年每年的总销售额 | 时序查询 | zero_shot | no such column: Total |
| 50 | 查询历史上订单量最多的前5个月份 | 时序查询 | few_shot | no such column: order_date |
| 55 | 按月统计销售额及与上月相比的增减金额（前24个月） | 窗口函数 | few_shot | near "24": syntax error |
| 63 | 查询销售额最高的前3个产品类别 | 复杂嵌套 | few_shot | near "Order": syntax error |
| 68 | 使用CTE统计每位员工的销售额及占总销售额的比例 | 复杂嵌套 | zero_shot | no such column: Total |
| 69 | 查询每个客户的最近购买时间、总订单数和购买产品种类数 | 复杂嵌套 | few_shot | no such column: o.customer_id |
| 77 | 查询尚未发货的订单 | 边界异常 | few_shot | no such column: shipped_date |

---

## 五、策略分类错误用例（default 模式）

| ID | 查询 | 期望策略 | 实际策略 | 类别 |
|---|---|---|---|---|
| 1 | 查询所有客户信息 | rule | zero_shot | 单表查询 |
| 3 | 查询单价超过50的产品 | few_shot | zero_shot | 单表查询 |
| 4 | 查询所有已停产的产品 | few_shot | zero_shot | 单表查询 |
| 5 | 查询运费超过200的订单 | few_shot | zero_shot | 单表查询 |
| 8 | 查询库存量超过50件的产品并按库存量降序排列 | few_shot | zero_shot | 单表查询 |
| 9 | 查询发往美国的前20条订单 | few_shot | zero_shot | 单表查询 |
| 15 | 查询来自美国的客户的订单及每笔订单金额 | zero_shot | few_shot | 多表联结 |
| 16 | 查询每个供应商提供的产品数量 | few_shot | zero_shot | 多表联结 |
| 17 | 查询向Andrew Fuller汇报的员工列表 | zero_shot | few_shot | 多表联结 |
| 18 | 查询包含海鲜类产品的订单编号和客户名称 | zero_shot | few_shot | 多表联结 |
| 20 | 查询订单明细中折扣金额最高的前10条记录 | zero_shot | few_shot | 多表联结 |
| 22 | 查询没有下过任何订单的客户 | zero_shot | few_shot | 多表联结 |
| 24 | 查询每个类别中单价最高的产品名称 | zero_shot | few_shot | 多表联结 |
| 25 | 查询每位员工的上级主管姓名 | zero_shot | few_shot | 多表联结 |
| 36 | 计算每个客户的平均订单金额前10名 | zero_shot | few_shot | 聚合统计 |
| 37 | 统计折扣总额超过1000的订单数量 | zero_shot | few_shot | 聚合统计 |
| 39 | 统计每位员工每年处理的订单数量 | zero_shot | few_shot | 聚合统计 |
| 40 | 计算全部订单折扣后的总销售额 | few_shot | zero_shot | 聚合统计 |
| 45 | 计算所有订单从下单到发货的平均天数 | zero_shot | few_shot | 时序查询 |
| 46 | 查询超过预期收货日期才发货的前20条订单 | few_shot | zero_shot | 时序查询 |

---

## 六、模式对比 — 各类别 EX 成功率

| 类别 | default（三层策略） | zero_shot_only | few_shot_top5 |
|---|---|---|---|
| 单表查询 | 100.0% | 100.0% | 100.0% |
| 多表联结 | 80.0% | 86.7% | 80.0% |
| 聚合统计 | 93.3% | 93.3% | 80.0% |
| 时序查询 | 50.0% | 70.0% | 60.0% |
| 窗口函数 | 90.0% | 70.0% | 80.0% |
| 复杂嵌套 | 70.0% | 70.0% | 50.0% |
| DWS表查询 | 100.0% | 100.0% | 100.0% |
| 边界异常 | 80.0% | 100.0% | 100.0% |

---

*报告由 `eval/evaluator.py` 自动生成*