# LLM 旁路契约

## 边界

LLM 只允许解释、总结、比较和诊断。它不参与选股、评分、分层、仓位、
价格区间或任何业务表写入。模型失败不得阻断日报、Evaluation、邮件和对账。

## 三层结构

1. `analysis.llm_fact_pack`：从规范视图读取事实，生成
   `llm_fact_pack_v1`。每个事实包具有内容哈希、成熟状态、证据引用和限制项。
2. `analysis.llm_adapter`：供应商无关的模型接口。输出必须符合
   `llm_interpretation_v1`，每条判断必须引用事实包中存在的证据。
   `compare`任务必须同时提供两份完整事实包，不能用日报文本替代第二份证据。
3. `analysis.llm_governance`：校验内容哈希、限制项确认、越权文本、调用幂等和
   审计记录。该层是唯一允许调用模型适配器的入口。

## Evaluation 状态

- `pending`：目标交易日尚未到期，不是失败。
- `success`：已到期且收益值存在。
- `unavailable_price`：Evaluation 记录存在，但停牌或行情缺失导致收益不可用。
- `missing_record`：到期后仍没有规范 Evaluation 记录。
- `missing_value`：记录存在但收益与缺失原因均为空，需要检查。

## 数据粒度

- 信号粒度：`交易日 + 股票代码 + 策略`。
- 一只股票可以命中多个策略，因此股票数不能等同于信号数。
- 近期规范血缘通过 `signal_id` 连接信号、生成时快照与 Evaluation。

## 持久化

- `llm_fact_pack` 保存不可变事实包及 SHA-256。
- `llm_interpretation_run` 保存请求、响应、供应商、模型、Prompt版本、策略版本、
  状态、耗时和错误。
- 相同事实包、任务、供应商、模型与版本只允许一份成功结果；失败重试使用递增
  `attempt_no`。

## 启用条件

真实模型启用前必须满足：

1. 21项回归全部通过；
2. 行为等价审计 `gate_status=pass`；
3. 事实包状态不是 `blocked`；
4. 供应商实现只能接入 `LLMProvider`，不得从日报渲染器直接调用HTTP；
5. 先以不发邮件、不写日报的旁路方式观察输出。
