"""Real private Unix IPC, real DeerMem, isolated state, no model or network."""
import asyncio
import json
import os
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

import sitecustomize
from after_sales import customer_memory as m, memory_rpc as rpc, store as s
from after_sales.identity import _signature


class MemoryRPCTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        m.close_memory()
        self.temp=tempfile.TemporaryDirectory(prefix='after-sales-ipc-')
        self.env=patch.dict(os.environ,{'AFTER_SALES_DATA_DIR':self.temp.name})
        self.env.start(); s.init_store()
        await asyncio.to_thread(m.manager)
        self.server=rpc.MemoryReadServer()
        await self.server.start()

    async def asyncTearDown(self):
        await self.server.stop()
        m.close_memory(); self.env.stop(); self.temp.cleanup()

    async def raw(self,request):
        reader,writer=await asyncio.open_unix_connection(str(rpc.socket_path()))
        writer.write(json.dumps(request).encode()+b'\n'); await writer.drain()
        response=json.loads(await reader.readline())
        writer.close(); await writer.wait_closed()
        return response

    async def test_scope_projection_and_live_corrections(self):
        first=m.save_preference('owner-a','resolution_preference','reship','private operator note')['preferences'][0]
        result=await asyncio.to_thread(rpc.read_memory_via_gateway,'owner-a')
        self.assertEqual('reship',result['preferences'][0]['value'])
        self.assertNotIn('source_note',result['preferences'][0])
        self.assertNotIn('fact_id',result['preferences'][0])
        self.assertEqual([], (await asyncio.to_thread(rpc.read_memory_via_gateway,'owner-b'))['preferences'])
        second=m.save_preference('owner-a','resolution_preference','refund','corrected',first['digest'])['preferences'][0]
        self.assertEqual('refund',(await asyncio.to_thread(rpc.read_memory_via_gateway,'owner-a'))['preferences'][0]['value'])
        m.forget_preference('owner-a',second['fact_id'],second['digest'])
        self.assertEqual([],(await asyncio.to_thread(rpc.read_memory_via_gateway,'owner-a'))['preferences'])

    async def test_signature_expiry_purpose_owner_and_shape(self):
        issued=str(int(time.time())); owner='owner-a'
        good={'owner':owner,'issued':issued,'signature':rpc.signature(owner,issued)}
        expired=str(int(issued)-61)
        for request in ({}, {**good,'signature':'bad'}, {**good,'owner':'owner-b'},
                        {**good,'issued':expired,'signature':rpc.signature(owner,expired)},
                        {**good,'signature':_signature(owner,issued)}, {**good,'command':'write'}):
            result=await self.raw(request)
            self.assertFalse(result['ok']); self.assertEqual('IDENTITY_REQUIRED',result['error']['code'])

    async def test_socket_private_and_missing_service_fails_without_fallback(self):
        self.assertEqual(0o600,stat.S_IMODE(rpc.socket_path().stat().st_mode))
        await self.server.stop()
        with self.assertRaises(s.BusinessError) as caught:
            await asyncio.to_thread(rpc.read_memory_via_gateway,'owner-a')
        self.assertEqual('MEMORY_UNAVAILABLE',caught.exception.code)

    async def test_start_preserves_non_socket_at_reserved_path(self):
        await self.server.stop()
        rpc.socket_path().write_text('preserve me')
        other=rpc.MemoryReadServer()
        with self.assertRaises(RuntimeError):await other.start()
        self.assertEqual('preserve me',rpc.socket_path().read_text())

    async def test_backend_failure_returns_structured_error(self):
        with patch.object(m,'manager',side_effect=RuntimeError('unavailable')):
            with self.assertRaises(s.BusinessError) as caught:
                await asyncio.to_thread(rpc.read_memory_via_gateway,'owner-a')
            self.assertEqual('MEMORY_UNAVAILABLE',caught.exception.code)
