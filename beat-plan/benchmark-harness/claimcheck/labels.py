"""The three labels every number must carry, plus NOT-YET for numbers that do not exist.

MEASURED      A tool printed it during a run (simulation, synthesis, timing, FPGA,
              silicon, or a reference run). The run's evidence file is named.
              Arithmetic inside ONE run on that run's own measured quantities
              (tokens / wall seconds, joules / tokens) is still MEASURED.
MODELLED      Computed rather than observed: arithmetic that takes a number to other
              conditions (a different clock, more chips, more engines) or an analytical
              model. The formula, inputs and assumptions are given.
VENDOR-CLAIM  Stated by a vendor or publisher about a product and not independently
              measured by Forge. A model publisher's architecture constants are
              recorded as VENDOR-CLAIM with claim_type "spec".
NOT-YET       The number does not exist yet (no run). Its value must be null.

The Forge public site uses four kinds. They map onto these labels as follows:
measured -> MEASURED, derived -> MODELLED (basis "arithmetic"),
model -> MODELLED (basis "analytical-model"), not yet -> NOT-YET.
"""

from __future__ import annotations

MEASURED = "MEASURED"
MODELLED = "MODELLED"
VENDOR_CLAIM = "VENDOR-CLAIM"
NOT_YET = "NOT-YET"

NUMBER_LABELS = (MEASURED, MODELLED, VENDOR_CLAIM)
ALL_LABELS = NUMBER_LABELS + (NOT_YET,)

MODELLED_BASES = ("arithmetic", "analytical-model")
CLAIM_TYPES = ("performance", "spec", "comparison")
QUOTE_STATUSES = ("verbatim-primary", "verbatim-secondary", "search-summary", "founder-brief")
EVIDENCE_STATUSES = ("present", "not-in-checkout", "run-record")

SITE_KIND_TO_LABEL = {
    "measured": MEASURED,
    "derived": MODELLED,
    "model": MODELLED,
    "not yet": NOT_YET,
}


def tag(label: str) -> str:
    """Bracketed tag used in generated reports, e.g. [MODELLED]."""
    if label not in ALL_LABELS:
        raise ValueError("unknown label %r" % (label,))
    return "[" + label + "]"


def computed_label() -> str:
    """Anything the harness computes from other numbers is MODELLED, never MEASURED."""
    return MODELLED
