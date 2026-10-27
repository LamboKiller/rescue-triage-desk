"""Verification-only guard: enforce LOAD's forbidden reads in gate subprocesses.

Set PYTHONPATH to this directory ONLY while running verification. It neither
changes the gate's checks nor substitutes results. Denied checks fail visibly.
"""
import os
import sys


def load_audit(event, args):
    if event not in ('open', 'os.listdir', 'os.scandir') or not args:
        return
    path = args[0]
    if not isinstance(path, (str, bytes, os.PathLike)):
        return
    path = os.fsdecode(os.path.abspath(path)).replace('\\', '/').casefold()
    if (path.endswith('/.env') or any('/review/'+part+'/' in path+'/'
            for part in ('sealed50', 'holdout2', 'realdev'))):
        raise PermissionError('LOAD brief forbids reading this path')


sys.addaudithook(load_audit)
