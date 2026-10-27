"""Immutable take input: the brief's original hero, isolated from concurrent fixture edits."""
import sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).resolve().parents[1])]
import demo_hero
demo_hero.HERO=Path(__file__).parent/'assets/hero-brief-snapshot.jsonl'
demo_hero.main()
