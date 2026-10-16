---
name: damage-intake
description: 调查合成演示商品损坏请求，保存已知资料，引用政策并生成等待人工审批的业务方案。
---

# 商品损坏调查与处理

版本：0.3.4。适用：本地合成商品损坏申报；原订单使用真实时钟，独立场景使用明确标记的演示业务时钟。

## 步骤

1. 缺少订单号则先询问订单号。已有订单号调用 `after-sales-demo_get_demo_order`，使用工具事实核对归属、商品和签收状态。
2. 查询订单含 existing_ticket 时先 `after-sales-demo_get_after_sales_ticket`。客户偏好需要时查询 `get_customer_memory`，本次退款/补发仍需客户明确选择。
3. 用 `after-sales-demo_save_damage_report` 保存本轮明确给出的损坏描述、证据说明和偏好。补发传 requested_resolution="reship"，退款传 "refund"，不要传中文或其他同义词；未知字段省略，空字符串仅用于明确清空。已有工单编辑传最新 expected_revision；不要把截断的工单投影作为完整资料覆盖回去。
4. 保存成功且资料齐全后，调用 `after-sales-demo_propose_after_sales_resolution`；代码按首次业务申报日期选政策，返回方案、policy_basis条款正文及citations来源。引用这些确定性依据，不必再次检索相同政策。需要解释其他条款或设计示例时才调用 `after-sales-demo_search_after_sales_knowledge`，必须传 ticket_id，不与首报并行。期限、金额由后端校验，设计示例不是资格判断。
5. 若 awaiting_information 列出 missing_fields；若 manual_review 解释 reasons 并建议人工处理；若 awaiting_approval 提供方案与 [售后工作台](/api/after-sales/workbench)，结束当前回合。
6. 收到继续处理的请求后调用 `after-sales-demo_get_after_sales_ticket`。只有数据库状态 approved 时才调用 `after-sales-demo_execute_approved_resolution`。用户的聊天确认不能代替人工审批。
7. 执行工具会在事务提交后真实回读工单，返回readback；核对操作号与resolved状态。readback缺失时才单独读取工单，不重复查询已有回读。工具返回错误则结束当前回合，说明错误码与所需动作，不自动重试。

## 信息与输出

证据说明是客户陈述；图片可在工作台上传并由人工审核，模型不查看或判断图片。附件审核变化后需重新生成方案。业务工具不接受用户 ID、任意退款金额、地址或审批字段。

向用户简洁返回：合成数据标记、订单/工单号、已核实的订单事实、政策依据、当前状态、下一步。不要把等待审批描述为已退款/已发货。

审批拒绝或逾期后更新/补充业务资料再生成新方案，保留旧方案和审计记录。不能更改政策、绕过审批或删除历史记录。
