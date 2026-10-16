"""Private, signed read-only IPC to the Gateway's already-warm DeerMem.

No public HTTP route, model construction, write command or remote fallback.
"""
import asyncio
import hashlib
import hmac
import json
import os
import socket
import stat
import time

from .store import BusinessError, _owner, state_dir

MAX_RESPONSE = 65536


def socket_path():
    return state_dir() / '.customer-memory.sock'


def signature(owner: str, issued: str) -> str:
    key = (state_dir() / '.identity-key').read_bytes()
    return hmac.new(key, f'memory-read-v1\n{owner}\n{issued}'.encode(), hashlib.sha256).hexdigest()


def verify_request(request) -> str:
    try:
        if not isinstance(request, dict) or set(request) != {'owner', 'issued', 'signature'}:
            raise ValueError('Invalid request shape')
        owner, issued, supplied = request['owner'], request['issued'], request['signature']
        _owner(owner)
        age = time.time() - int(issued)
        if not isinstance(issued, str) or not isinstance(supplied, str) or not -5 <= age <= 60 or not hmac.compare_digest(supplied, signature(owner, issued)):
            raise ValueError('Invalid signature')
        return owner
    except (BusinessError, ValueError, TypeError, OSError, KeyError) as exc:
        raise BusinessError('IDENTITY_REQUIRED', '本地记忆读取缺少有效签名身份。', 401) from exc


def model_memory(owner: str) -> dict:
    from .customer_memory import get_customer_memory
    result = get_customer_memory(owner)
    result['preferences'] = [{key: item[key] for key in ('key', 'value', 'confirmed_at', 'source_kind')}
                             for item in result['preferences']]
    return result


class MemoryReadServer:
    def __init__(self):
        self.server = None
        self.bound_identity = None
        self.path = socket_path()

    async def start(self):
        # A preserved volume can contain an old socket after a container exits.
        # Never unlink a regular file, symlink, or a different user's socket.
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise RuntimeError('Unexpected file at private memory socket path')
            self.path.unlink()
        self.server = await asyncio.start_unix_server(self.handle, path=str(self.path), limit=4096, start_serving=False)
        self.path.chmod(0o600)
        info = self.path.stat()
        self.bound_identity = (info.st_dev, info.st_ino)
        await self.server.start_serving()

    async def stop(self):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        try:
            info = self.path.lstat()
            if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == self.bound_identity:
                self.path.unlink()
        except FileNotFoundError:
            pass

    async def handle(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=2)
            owner = verify_request(json.loads(line))
            result = {'ok': True, 'data': await asyncio.to_thread(model_memory, owner)}
        except BusinessError as exc:
            result = {'ok': False, 'error': {'code': exc.code, 'message': exc.message, 'status': exc.status}}
        except Exception:
            result = {'ok': False, 'error': {'code': 'MEMORY_UNAVAILABLE', 'message': '本地记忆读取未完成。', 'status': 503}}
        try:
            encoded = json.dumps(result, ensure_ascii=False).encode() + b'\n'
            if len(encoded) > MAX_RESPONSE:
                encoded = b'{"ok":false,"error":{"code":"MEMORY_UNAVAILABLE","message":"Memory response too large","status":503}}\n'
            writer.write(encoded)
            await asyncio.wait_for(writer.drain(), timeout=2)
        except (OSError, TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


def read_memory_via_gateway(owner: str) -> dict:
    _owner(owner)
    issued = str(int(time.time()))
    try:
        request = {'owner': owner, 'issued': issued, 'signature': signature(owner, issued)}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(str(socket_path()))
            connection.sendall(json.dumps(request).encode() + b'\n')
            with connection.makefile('rb') as stream:
                line = stream.readline(MAX_RESPONSE + 1)
            if len(line) > MAX_RESPONSE or not line.endswith(b'\n'):
                raise ValueError('Invalid response size')
            result = json.loads(line)
            if not isinstance(result, dict):
                raise ValueError('Invalid memory response')
            if result.get('ok') is not True:
                error = result.get('error', {})
                raise BusinessError(error.get('code', 'MEMORY_UNAVAILABLE'), error.get('message', '记忆暂不可读。'), error.get('status', 503))
            if not isinstance(result.get('data'), dict):
                raise ValueError('Invalid memory result')
            return result['data']
    except BusinessError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise BusinessError('MEMORY_UNAVAILABLE', '本地记忆服务暂不可读，请使用本轮已提供信息。', 503) from exc
