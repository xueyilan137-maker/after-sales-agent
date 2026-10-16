"""The prompt directory must track the exact filtered tool schemas."""
import unittest
from types import SimpleNamespace
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from after_sales.plugin import AfterSalesMiddleware


class ToolCatalogTests(unittest.TestCase):
    def test_directory_uses_only_bound_names_without_aliases(self):
        @tool('after-sales-demo_search_after_sales_knowledge')
        def search(query: str) -> str:
            """Read synthetic knowledge."""
            return '{}'

        @tool('after-sales-demo_approve_resolution')
        def approve() -> str:
            """Forbidden test fixture."""
            raise AssertionError('Never execute')

        request = ModelRequest(model=SimpleNamespace(), messages=[HumanMessage(content='只读查询')],
                               tools=[search, approve])
        result = AfterSalesMiddleware().transform(request)
        self.assertEqual([search], result.tools)
        self.assertIn('本次可调用工具完整名称：\nafter-sales-demo_search_after_sales_knowledge', result.system_message.content)
        self.assertNotIn('after-sales-demo_approve_resolution', result.system_message.content)
        self.assertNotIn('after-sales-demo-search_after_sales_knowledge', result.system_message.content)
        self.assertEqual([search, approve], request.tools)
