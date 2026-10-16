"""Verification processes may use stdio/local sockets, never remote services."""
import sys


def deny_remote(event, args):
    if event != "socket.connect":
        return
    address = args[1]
    if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError("NON_MODEL_VERIFICATION: remote network access denied")


sys.addaudithook(deny_remote)
