"""Adds deployment/ to the import path, so tests can import
xbrl_llm_match.py and other modules that live one folder up.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
