"""One process-wide background preparation worker, with cheap visible readiness."""
import threading
import time


class Warmup:
    def __init__(self, tasks):
        self.lock = threading.Lock()
        self.tasks = {name: {'state': 'queued'} for name in tasks}
        def work():
            # Preparation should yield CPU/IO scheduling to request workers.
            import os
            if os.name == 'nt':
                import ctypes
                ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), -2)
            for name, prepare in tasks.items():
                start = time.monotonic()
                with self.lock:
                    self.tasks[name] = {'state': 'running'}
                try:
                    prepare()
                    state = {'state': 'ready'}
                except Exception as exc:
                    state = {'state': 'failed', 'error': type(exc).__name__}
                state['seconds'] = round(time.monotonic() - start, 3)
                with self.lock:
                    self.tasks[name] = state
        self.thread = threading.Thread(target=work, name='desk-warmup', daemon=True)
        self.thread.start()

    def task_ready(self, name):
        with self.lock:
            return self.tasks.get(name, {}).get('state') == 'ready'

    def snapshot(self):
        with self.lock:
            return {'ready': all(t['state'] == 'ready' for t in self.tasks.values()),
                    'tasks': {name: dict(state) for name, state in self.tasks.items()}}


def _streets():
    from app.data.source import LocalSource
    from app.geo.incident import prepared_index
    from app.agents.baseline import _street_patterns
    source = LocalSource()
    rows, landmarks = source.streets(), source.landmarks()
    prepared_index(rows, landmarks)
    for city in {r['municipality'] for r in rows}:
        _street_patterns(tuple(r['display_name'] for r in sorted(
            (r for r in rows if r['municipality'] == city), key=lambda r: len(r['display_name']), reverse=True)))


def _routing():
    import gc
    enabled = gc.isenabled()
    young, middle, old = gc.get_threshold()
    # The acyclic, process-lifetime geometry makes full-heap scans expensive.
    # Keep normal young-generation collection; scan the old generation less
    # often. During its one-time construction, collect once after publication.
    gc.set_threshold(young, middle, max(old, 100))
    gc.disable()
    try:
        _routing_data()
    finally:
        gc.collect(2)
        if enabled:
            gc.enable()


def _routing_data():
    from app.geo import routing, depth, water_routing
    from app.landing import points
    routing.warm_async()
    thread = routing._WARM['thread']
    if thread:
        thread.join()
    if not routing.router_ready():
        raise RuntimeError('Road preparation failed')
    for day in depth.DATES:
        with water_routing._LOCK:
            water_routing.default_water_router(day)._profile(.5)
        points._graph_launch_points(day)
    points._derived()


_LOCK = threading.Lock()
_SHARED = None


def start():
    global _SHARED
    with _LOCK:
        if _SHARED is None:
            _SHARED = Warmup({'streets': _streets, 'routing': _routing})
        return _SHARED
