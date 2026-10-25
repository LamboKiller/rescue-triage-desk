"""Credibility filter: code signals + a grounded agent verdict. Never discards a message (see reviewer.py)."""
from app.credibility.signals import detect
from app.credibility.reviewer import review, action_for, rule_verdict


def assess(text, *, time=None, history=(), hydro_conflict=None, client=None, deadline=None):
    """One call for the pipeline hook.

    Returns {verdict, source, signals, reasons, action, reason_pt|warning_pt, fallback_reason, never_discards}.
    client=None -> deterministic rule only (source 'rule'); with a client the agent reviews the signals.
    """
    signals = detect(text, time=time, history=history, hydro_conflict=hydro_conflict)
    if client is None or not signals:
        verdict = rule_verdict(signals)
        result = {'verdict': verdict, 'source': 'rule', 'reasons': [{'signal_id': s['id'], 'quote': s['quote']} for s in signals],
                  'agent_verdict': None, 'fallback_reason': None, 'note': None}
    else:
        result = review(client, signals, deadline)
    return {**result, 'signals': signals, **action_for(result['verdict']), 'never_discards': True}
