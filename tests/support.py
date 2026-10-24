"""Ordinary scratch directories avoid this sandbox's Windows tempfile ACL issue."""
import shutil
import uuid
from pathlib import Path
from app.config import ROOT


class Scratch:
    def __init__(self):
        self.path = ROOT/'.tmp'/uuid.uuid4().hex
        self.path.mkdir(parents=True)
        self.name = str(self.path)

    def cleanup(self):
        target = self.path.resolve()
        if ROOT.resolve() not in target.parents or '.tmp' not in target.parts:
            raise ValueError('Scratch path outside workspace')
        shutil.rmtree(target)
