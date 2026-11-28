"""Forge DV agent: writes testbenches, checks RTL bit-exactness against golden
models, and runs lint / simulation / formal checks on generated RTL.

Verdicts follow the Forge gate: PASS, FAIL or INCOMPLETE. Only PASS counts.
"""

__version__ = "0.1.0"
