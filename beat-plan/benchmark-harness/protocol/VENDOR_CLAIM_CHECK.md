# Vendor-claim check (forge-vendor-claim-check)

> **Provenance.** The `forge-vendor-claim-check` SKILL.md was not in this checkout. This is the procedure the harness
> implements. Reconcile it with the real SKILL.md on merge.

## Procedure

1. **Capture the claim word for word.** Record the URL, the access date and the exact quote, and save a snapshot (HTML or
   PDF) under `data/sources/` with its sha256. Set `quote_status`:
   `verbatim-primary` (read from the vendor's own page), `verbatim-secondary` (an article quoting it), `search-summary`
   (a search engine's summary, the weakest), or `founder-brief`.
2. **Record the stated conditions** in `conditions`: model, precision, chip count, input and output lengths, batch or
   concurrency, token counting, and whether the vendor calls the number measured, estimated or simulated. Leave unknowns
   as `null`. Do not fill them from memory.
3. **Register it** in `data/claims.json` as `VENDOR-CLAIM` with `stated_by`, `claim_type` and `quote`.
4. **Check its arithmetic** (`consistency_checks`). Do the vendor's own figures agree with each other?
5. **Analyse what it implies** (`vendor_analyses`). Using the published architecture, the checker computes the compute
   and weight bandwidth each chip needs, under both token-counting conventions, and tests which convention the vendor's
   own baseline allows against that baseline's published peak.
6. **Compare only through `comparisons`.** The checker labels a comparison NOT COMPARABLE when conditions differ,
   COMPARABILITY UNVERIFIED when they are unknown, and always states whether both sides are measured.

## Current result for Etched (see `out/REPORT.md`)

- Etched's figure of over 500,000 tok/s is a VENDOR-CLAIM. Its wording reached this session only through a search
  summary, because etched.com was unreachable.
- The arithmetic of Etched's own figures is consistent. A modelled 173.9 H100s is at least the 160 H100s the vendor claims.
- Etched's own H100 baseline (a vendor claim of about 23,000 tok/s per 8xH100 server) is only physically possible if
  input tokens are counted, so the claim most likely counts input+output tokens. On that reading each Sohu chip must
  sustain a modelled 8.74 PFLOP/s of FP8 compute, 4.42 times an H100's dense FP8 peak (also modelled, from NVIDIA's
  stated sparse figure).

## Phrasebook for anything outward-facing

| Write | Never write |
|---|---|
| "474,713 tok/s (modelled arithmetic, not measured)" | the beat-plan figure presented as a hardware result, or as what Forge "does" |
| "Etched claims over 500,000 tok/s (vendor claim, Llama-3 70B, 8 chips)" | Etched's figure stated as a fact about the chip |
| "modelled vs vendor claim; neither side measured" | Forge as a percentage of Etched, or "matches Etched" |
| "no FPGA run yet" | any watts or tokens-per-second figure for hardware that has not run |

The linter (`python3 -m claimcheck lint <files>`) catches the "Never write" column automatically for tok/s figures: a
tok/s figure called measured without a run record, or with no label at all, is an error.
