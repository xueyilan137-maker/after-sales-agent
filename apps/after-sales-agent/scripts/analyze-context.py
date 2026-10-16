"""Offline checkpoint projection audit; no model/client/database mutation.

Use the pinned Gateway Python with test sitecustomize on PYTHONPATH. Inputs are
private exported {run, messages} snapshots; output contains counts/hashes only.
Character deltas are not provider token or currency savings.
"""
import argparse
import hashlib
import json
from pathlib import Path

import sitecustomize  # remote socket guard from the project's test directory
from langchain_core.messages import AIMessage, messages_from_dict
from after_sales.plugin import AfterSalesMiddleware


def analyze(path):
    raw = path.read_bytes()
    data = json.loads(raw.decode('utf-8-sig'))
    messages = messages_from_dict([{'type': m['type'], 'data': m} for m in data['messages']])
    calls = []
    for i, message in enumerate(messages):
        if not isinstance(message, AIMessage) or not message.usage_metadata:
            continue
        prefix = messages[:i]
        before = [m.model_dump(mode='json') for m in prefix]
        projected = AfterSalesMiddleware.compact_model_messages(prefix)
        assert before == [m.model_dump(mode='json') for m in prefix], 'Source messages changed'
        original_chars = sum(len(json.dumps(m.content, ensure_ascii=False)) for m in prefix)
        projected_chars = sum(len(json.dumps(m.content, ensure_ascii=False)) for m in projected)
        calls.append({'checkpoint_index': i, 'original_content_chars': original_chars,
                      'projected_content_chars': projected_chars, 'provider_usage': message.usage_metadata})
    assert path.read_bytes() == raw, 'Checkpoint file changed'
    return {'snapshot': path.name, 'sha256': hashlib.sha256(raw).hexdigest(),
            'run_record': {k: data['run'].get(k) for k in ('total_input_tokens', 'total_output_tokens',
                'total_tokens', 'llm_call_count', 'stop_reason')},
            'calls': calls, 'scope': 'checkpoint prefixes, not captured provider request payloads'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshots', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps({'model_called': False, 'metric': 'message content characters, excludes tool schemas/system replacement',
                      'snapshots': [analyze(p) for p in args.snapshots]}, ensure_ascii=False, indent=2))
