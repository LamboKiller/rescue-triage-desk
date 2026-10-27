"""Shared evaluation diagnostics, independent of decision correctness."""


def failure_kind(case):
    """One primary category; provider refusals retain their cause, not TIMEOUT."""
    kind = case.get('failure_kind')
    errors = case.get('errors') or []
    stages = (case.get('latency_budget') or {}).get('stages') or []
    failed = [r for r in stages if r.get('status') == 'code_fallback' or
              r.get('reason') == 'provider_pressure']
    kinds = {r.get('failure_kind') for r in failed} | {kind}
    if 'provider_refused' in kinds:
        return 'provider_refused'
    if kinds & {'TIMEOUT', 'provider_timeout'} or any(
            'deadline' in e.lower() or 'timeout' in e.lower() for e in errors):
        return 'TIMEOUT'
    if kind or errors or failed or case.get('review_degraded') or not case.get('complete', True):
        return 'agent_failure'
    return None


def failure_counts(cases):
    counts = dict(TIMEOUT=0, provider_refused=0, agent_failure=0)
    for case in cases:
        kind = failure_kind(case)
        if kind:
            counts[kind] += 1
    return counts
