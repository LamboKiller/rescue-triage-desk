"""Ordinary scratch directories work with restricted Windows ACLs."""
from contextlib import contextmanager
import shutil
import uuid
from app.config import ROOT


@contextmanager
def scratch():
    path = ROOT/'.tmp'/('audit-'+uuid.uuid4().hex)
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        target = path.resolve()
        if ROOT.resolve() not in target.parents or '.tmp' not in target.parts:
            raise ValueError('Scratch path outside workspace')
        shutil.rmtree(target)
