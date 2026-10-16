"""Request-only projection: facts survive; historical policy prose is deferred."""
import json
import unittest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from after_sales.plugin import AfterSalesMiddleware


class ContextProjectionTests(unittest.TestCase):
    def test_unnamed_or_denied_tool_error_stops_before_provider(self):
        from types import SimpleNamespace
        from deerflow.config.token_budget_config import TokenBudgetConfig
        mw = AfterSalesMiddleware(TokenBudgetConfig(enabled=True,max_tokens=20000))
        for name in (None, 'after-sales-demo-search_after_sales_knowledge'):
            error = ToolMessage(name=name, tool_call_id='bad-name', status='error', content='工具被拒绝')
            request = SimpleNamespace(messages=[error],state={'messages':[error]})
            response = mw.tool_failure_response(request)
            self.assertIsNotNone(response)
            self.assertEqual('TOOL_ERROR', response.result[0].additional_kwargs['after_sales_non_model_stop'])

    def test_only_historical_policy_prose_is_deferred(self):
        payload={'status':'awaiting_approval','revision':1,'proposal':{'status':'pending','citations':[{'source':'/policy#DAMAGE-01','version':'1.0.0'}],'policy_basis':[{'text':'完整政策正文'}]}}
        old=ToolMessage(name='after-sales-demo_propose_after_sales_resolution',tool_call_id='old',content=json.dumps(payload))
        current=ToolMessage(name=old.name,tool_call_id='current',content=json.dumps(payload))
        messages=[HumanMessage(content='首轮'),old,HumanMessage(content='继续'),current,HumanMessage(content='host warning',name='budget_warning')]
        result=AfterSalesMiddleware.compact_model_messages(messages)
        historical=json.loads(result[1].content)
        self.assertNotIn('policy_basis',historical['proposal'])
        self.assertTrue(historical['proposal']['policy_basis_deferred_to_sources'])
        self.assertEqual(payload['proposal']['citations'],historical['proposal']['citations'])
        self.assertEqual(1,historical['revision'])
        self.assertEqual(payload,json.loads(result[3].content))
        self.assertEqual(payload,json.loads(old.content))
    def test_nested_data_citations_and_metadata_survive(self):
        payload = {'ok':True, 'revision':2, 'evidence_note':'裂纹\n客户明确陈述', 'citations':[{'version':'1.0.0','source':'/policy#DAMAGE-01'}], 'amount_minor':4900}
        original = ToolMessage(name='after-sales-demo_get_after_sales_ticket', id='tool-row', tool_call_id='call-a',
            status='success', additional_kwargs={'audit':'retained'},
            content=[{'type':'text','text':json.dumps(payload,ensure_ascii=False,indent=2),'id':'block-id'}])
        before = original.model_dump()
        result = AfterSalesMiddleware.compact_model_messages([HumanMessage(content='已知资料'), original])
        projected = result[1]
        self.assertEqual(payload, json.loads(projected.content[0]['text']))
        self.assertEqual('block-id', projected.content[0]['id'])
        self.assertEqual(original.tool_call_id, projected.tool_call_id)
        self.assertEqual(original.additional_kwargs, projected.additional_kwargs)
        self.assertEqual(before, original.model_dump())
        self.assertLess(len(projected.content[0]['text']), len(original.content[0]['text']))

    def test_non_json_skill_images_and_user_messages_unchanged(self):
        messages = [HumanMessage(content='原始用户资料'), AIMessage(content='助手历史'),
            ToolMessage(name='read_file',tool_call_id='skill',content='Skill全文'),
            ToolMessage(name='after-sales-demo_get_demo_order',tool_call_id='text',content='非JSON文字'),
            ToolMessage(name='after-sales-demo_get_demo_order',tool_call_id='image',content=[{'type':'image','data':'fixture'}])]
        result = AfterSalesMiddleware.compact_model_messages(messages)
        self.assertEqual([m.model_dump() for m in messages], [m.model_dump() for m in result])

    def test_execution_boundary_requires_operation_readback(self):
        from types import SimpleNamespace
        from deerflow.config.token_budget_config import TokenBudgetConfig
        mw = AfterSalesMiddleware(TokenBudgetConfig(enabled=True,max_tokens=20000))
        payload = {'data_kind':'synthetic_demo_data','operation_id':'OP-FIXTURE','readback':{
            'operation_ids':['OP-FIXTURE'],'ticket_id':'TKT-FIXTURE','status':'resolved','revision':1}}
        request = SimpleNamespace(messages=[ToolMessage(name='after-sales-demo_execute_approved_resolution',tool_call_id='execute',content=json.dumps(payload))])
        response = mw.business_boundary_response(request)
        self.assertEqual('resolved', response.result[0].additional_kwargs['after_sales_non_model_terminal'])
        payload['readback']['operation_ids'] = []
        request.messages[0].content=json.dumps(payload)
        self.assertIsNone(mw.business_boundary_response(request))

    def test_request_warning_cannot_hide_completed_tool_error(self):
        from types import SimpleNamespace
        from deerflow.config.token_budget_config import TokenBudgetConfig
        mw = AfterSalesMiddleware(TokenBudgetConfig(enabled=True,max_tokens=20000))
        error = ToolMessage(name='after-sales-demo_get_demo_order',tool_call_id='error',content='{"ok":false,"error":{"code":"ORDER_NOT_FOUND"}}')
        request = SimpleNamespace(messages=[error,HumanMessage(content='预算提醒',name='budget_warning')],state={'messages':[error]})
        self.assertEqual('ORDER_NOT_FOUND',mw.tool_failure_response(request).result[0].additional_kwargs['after_sales_non_model_stop'])
