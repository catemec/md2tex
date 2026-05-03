"""Pytest configuration: add the repository root to sys.path so that
``import md2tex`` works without package installation."""

import sys
import os

# Ensure the repository root (parent of this conftest.py) is on sys.path.
sys.path.insert(0, os.path.dirname(__file__))
