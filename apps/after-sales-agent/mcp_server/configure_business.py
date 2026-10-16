"""Operator command: activate own profile, preserving secrets/model settings."""

import json
import argparse
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

config_path = Path("/app/project/config.yaml")
extensions_path = Path("/app/project/extensions_config.json")
suffix = datetime.now(timezone.utc).strftime(".before-business-%Y%m%dT%H%M%S%f")
parser = argparse.ArgumentParser(description="Activate or restore the operator-owned business configuration.")
parser.add_argument("--restore-suffix")
arguments = parser.parse_args()
if arguments.restore_suffix:
    if not re.fullmatch(r"\.before-business-[0-9]{8}T[0-9]{12}", arguments.restore_suffix):
        raise ValueError("Use the complete saved .before-business timestamp suffix, without a path.")
    sources = [path.with_name(path.name + arguments.restore_suffix) for path in (config_path, extensions_path)]
    restored_config = yaml.safe_load(sources[0].read_text(encoding="utf-8"))
    json.loads(sources[1].read_text(encoding="utf-8"))
    if restored_config.get("config_version") != 45:
        raise ValueError("The selected backup does not belong to pinned configuration schema 45.")
    for path in (config_path, extensions_path):
        shutil.copy2(path, path.with_name(path.name + suffix))
    try:
        for source, destination in zip(sources, (config_path, extensions_path)):
            shutil.copy2(source, destination)
    except OSError:
        for path in (config_path, extensions_path):
            shutil.copy2(path.with_name(path.name + suffix), path)
        raise
    print("Restored the selected configuration pair; previous files were backed up. RestartGateway is required.")
    raise SystemExit(0)
config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
extensions = json.loads(extensions_path.read_text(encoding="utf-8"))
if config.get("config_version") != 45:
    raise RuntimeError("Expected the pinned config schema 45; no files changed.")
plugin = {"name": "after-sales", "use": "after_sales.plugin:install", "enabled": True, "required": True}
others = [item for item in config.get("plugins", []) if item.get("name") != "after-sales"]
config["plugins"] = others + [plugin]
config["skills"] = {**config.get("skills", {}), "path": "/app/after-sales-skills",
                    "container_path": "/mnt/skills", "deferred_discovery": False}
config["tools"] = [{"name": "read_file", "group": "file:read", "use": "deerflow.sandbox.tools:read_file_tool"}]
config["tool_groups"] = [{"name": "file:read"}]
config["tool_search"] = {**config.get("tool_search", {}), "enabled": False}
# Graph-node budget, not token/provider budget. Pinned 26-hook chain exceeds
# 50 steps before a four-response budget stop reaches its end hook.
config['recursion_limit'] = 100
config['max_recursion_limit'] = 100
interceptors = extensions.get("mcpInterceptors", []) or []
if isinstance(interceptors, str):
    interceptors = [interceptors]
identity_hook = "after_sales.identity:build_identity_interceptor"
extensions["mcpInterceptors"] = [item for item in interceptors if item != identity_hook] + [identity_hook]
middleware_hook = "after_sales.plugin:AfterSalesMiddleware"
middlewares = extensions.get("middlewares", []) or []
if isinstance(middlewares, str):
    middlewares = [middlewares]
extensions["middlewares"] = [item for item in middlewares if item != middleware_hook] + [middleware_hook]
server = extensions["mcpServers"]["after-sales-demo"]
server["env"] = {**server.get("env", {}), "PYTHONIOENCODING": "utf-8",
                 "PYTHONPATH": "/app/backend", "AFTER_SALES_DATA_DIR": "/app/after-sales-data"}
server["description"] = "Synthetic after-sales tools; approval is human-only in the authenticated workbench."
prepared = ((config_path, yaml.safe_dump(config, allow_unicode=True, sort_keys=False)),
            (extensions_path, json.dumps(extensions, ensure_ascii=False, indent=2) + "\n"))
if any(path.read_text(encoding="utf-8") != contents for path, contents in prepared):
    # Always retain a complete configuration pair, even when only one changed.
    for path, contents in prepared:
        shutil.copy2(path, path.with_name(path.name + suffix))
    try:
        for path, contents in prepared:
            path.write_text(contents, encoding="utf-8")
    except OSError:
        for path, contents in prepared:
            shutil.copy2(path.with_name(path.name + suffix), path)
        raise
print("Activated after-sales profile (graph-node limit 100). Prior configuration pair retained beside ignored local files.")
print("Model endpoint, key references and token budget were preserved. RestartGateway is required.")
