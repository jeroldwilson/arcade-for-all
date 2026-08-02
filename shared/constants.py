"""
constants.py — Shared display constants for Arcade for All

Import these instead of redefining W/H in every file:
    from shared.constants import BASE_W, BASE_H
"""

# Reference resolution that all scale factors (sc = min(W/BASE_W, H/BASE_H)) are based on.
BASE_W: int = 800
BASE_H: int = 600
