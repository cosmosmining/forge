"""claimcheck: Forge benchmark harness and vendor-claim checker (Forge feature 6).

Every number this package handles carries exactly one label, MEASURED, MODELLED
or VENDOR-CLAIM (NOT-YET marks a number that does not exist yet), together with
a source and a method. The package refuses numbers that lack them.

Standard library only. Python 3.9 or newer.
"""

__version__ = "0.1.0"
