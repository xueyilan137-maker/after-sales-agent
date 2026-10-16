"""Deterministic old-result pointers for model requests, never persisted state."""
import hashlib
import json
from collections import Counter

from langchain_core.messages import AIMessage, ToolMessage


SNAPSHOT_TOOLS = {'after-sales-demo_' + name for name in (
    'get_demo_order', 'get_after_sales_ticket', 'save_damage_report',
    'save_logistics_report', 'propose_after_sales_resolution')}


def historical_pointers(messages, latest_user):
    """Return replacements only for unique, earlier, correctly paired results.

    A malformed/duplicate/unpaired/mixed/failed result is left for the existing
    lossless JSON compactor. Keep all calls, results and messages in place.
    """
    calls = Counter(call.get('id') for m in messages if isinstance(m, AIMessage) for call in m.tool_calls)
    returns = Counter(m.tool_call_id for m in messages if isinstance(m, ToolMessage))
    preceding = {}
    citation_sources = {}
    result = {}
    for index, message in enumerate(messages):
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                preceding[call.get('id')] = call.get('name')
            continue
        if not isinstance(message, ToolMessage) or index >= latest_user:
            continue
        call_id = message.tool_call_id
        if (message.name not in SNAPSHOT_TOOLS or message.status != 'success'
                or calls[call_id] != 1 or returns[call_id] != 1
                or preceding.get(call_id) != message.name):
            continue
        content = message.content
        if isinstance(content, list):
            if len(content) != 1 or not isinstance(content[0], dict) or content[0].get('type') != 'text':
                continue
            raw = content[0].get('text')
        else:
            raw = content
        if not isinstance(raw, str):
            continue
        try:
            value = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if (not isinstance(value, dict) or value.get('data_kind') != 'synthetic_demo_data'
                or value.get('ok') is False or 'error' in value
                or value.get('historical_result_omitted')
                or not (value.get('ticket_id') or value.get('order_id'))):
            continue
        # Identity/status/date/amount pointers survive. Deferred fields are
        # explicit and remain complete in the checkpoint, never overwritten.
        keep = {'data_kind', 'ticket_id', 'order_id', 'status', 'revision', 'case_kind',
                'requested_resolution', 'reported_at', 'business_reported_at',
                'delivered_at', 'currency', 'paid_amount_minor', 'citations'}
        projected = {key: item for key, item in value.items() if key in keep}
        omitted = sorted(set(value) - set(projected) - {'proposal'})
        proposal = value.get('proposal')
        citation_key = None
        if isinstance(proposal, dict):
            small = {key: item for key, item in proposal.items()
                     if not isinstance(item, (dict, list)) or key == 'citations'}
            citations = proposal.get('citations')
            if isinstance(citations, list) and citations:
                citation_key = json.dumps(citations, ensure_ascii=False, sort_keys=True)
                if citation_key in citation_sources:
                    small.pop('citations')
                    small['citations_from_tool_call_id'] = citation_sources[citation_key]
            removed = sorted(set(proposal) - set(small))
            small['omitted_fields'] = removed
            if 'policy_basis' in removed:
                small['policy_basis_deferred_to_sources'] = True
            projected['proposal'] = small
            omitted.extend('proposal.' + key for key in removed)
        elif 'proposal' in value:
            projected['proposal'] = proposal
        if not omitted:
            continue
        projected.update(historical_result_omitted=True, authorizes_current_action=False,
                         omitted_fields=omitted,
                         original_content_sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                         reread_required=True)
        try:
            compact = json.dumps(projected, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            # Compare against the *existing* v0.3.5 projection, not pretty JSON.
            baseline = dict(value)
            if message.name == 'after-sales-demo_propose_after_sales_resolution' and isinstance(proposal, dict) and proposal.get('citations') and 'policy_basis' in proposal:
                baseline['proposal'] = {key: item for key, item in proposal.items() if key != 'policy_basis'}
                baseline['proposal']['policy_basis_deferred_to_sources'] = True
            baseline_chars = len(json.dumps(baseline, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
        except (ValueError, TypeError):
            continue
        if len(compact) >= baseline_chars:
            if citation_key and citation_key not in citation_sources:
                citation_sources[citation_key] = call_id
            continue
        if citation_key and citation_key not in citation_sources:
            citation_sources[citation_key] = call_id
        if isinstance(content, list):
            compact = [{**content[0], 'text': compact}]
        result[index] = message.model_copy(update={'content': compact})
    return result
