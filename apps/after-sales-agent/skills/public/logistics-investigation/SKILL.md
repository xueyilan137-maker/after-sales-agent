---
name: logistics-investigation
description: 查询合成物流轨迹，保留客户陈述与状态冲突，经人工审批登记演示调查并等待跟进。
---

# 物流异常调查

版本：0.3.0。全程为合成演示，不联系承运方。

1. 缺订单号时询问；否则查询 `after-sales-demo_get_demo_order` 与 `after-sales-demo_get_shipping_events`。已有工单先 `get_after_sales_ticket`，沿用其已知资料和 revision。
2. 用 `save_logistics_report` 保存本轮明确提供的异常描述和证据说明；省略其他字段以保留旧值。已有工单携带 expected_revision。不得编造物流轨迹。
3. 用 `search_after_sales_knowledge` 检索物流停滞、72 小时、签收冲突与调查审批，并传 ticket_id，按工单业务日期选政策。设计示例不作为资格或执行证据。
4. 信息完整时 `propose_after_sales_resolution`。运输中超过 72 小时无更新才能提出 carrier_inquiry。系统显示签收但客户说未收到时转人工。此场景不自动退款或补发。
5. awaiting_approval 时报告方案号、引用与工作台链接后结束回合。模型无审批、附件审核、记忆写入或跟进工具。
6. 用户要求继续时读取最新工单。仅 approved 时调用 `execute_approved_resolution`；登记后 awaiting_followup，等待人工在工作台记录合成结果。登记调查不能称为实际联系承运方、已送达或已解决。
7. 错误保留错误码，说明人工处理或刷新后再操作；不循环轮询、不盲目重试。
