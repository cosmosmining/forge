"""forge_testgen -- Forge feature 8: auto test-case generation + formal DV.

Generates directed and constrained-random tests from a block spec and a
golden model, runs them against RTL (Icarus/Verilator), measures coverage,
closes coverage holes (golden-guided search, then formal witnesses), proves
properties formally with SymbiYosys (equivalence vs the golden, protocol
assertions, cover properties) and measures how well all of that catches
injected bugs (mutation campaign).  See README.md.
"""

__version__ = "0.1.0"
