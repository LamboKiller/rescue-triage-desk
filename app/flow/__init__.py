"""Fluxo dos agentes: read-only projection of what the desk already records (no state, no network, no model calls)."""
from .build import build_flow

__all__ = ['build_flow']
