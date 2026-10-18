# Preliminary portfolio release checklist

Local QC is complete. Final signoff awaits the reviewed-candidate GitHub workflow.
Original native benchmark coverage remains incomplete (14 validated, one ICBE failure, four Retail tasks deferred).

| Gate | Result | Evidence |
|---|---|---|
| R1: Evidence and claims | passed | [Verification](stage8/verification.json) |
| R2: Fresh installation | passed | [Environment](stage8/environment.json) and [verification](stage8/verification.json) |
| R3: Tests and fixtures | passed | [Verification](stage8/verification.json) |
| R4: Notebooks and analysis | passed | [Verification](stage8/verification.json) |
| R5: Paid-path previews | passed | [Verification](stage8/verification.json) |
| R6: Report verification | passed | [Report rebuild](stage8/verification.json) and [visual binding](stage7/visual_review.json) |
| R7: Citation and attribution | passed | [Citation checks](stage8/citation_checks.json) and [attribution](../RELEASE_ATTRIBUTION.md) |
| R8: Publication boundary | passed | [Privacy scan](stage8/privacy.json) |
| R9: Reader and release review | local_pass_pending_ci | [Reproduction guide](../REPRODUCIBILITY.md); exact-head CI pending |

The receipt pins the passing reviewed-candidate workflow. The final publication head is checked again after pushing; its live run is linked in the delivery handoff.

All 98 existing research tests plus two new scanner tests passed. Eight notebooks ran from fresh kernels, all 36 original saved episodes replayed, and the 12-page report rebuilt byte-identically on the verified toolchain.

No new model calls or paid experiments. Cumulative conservative exposure remains 2.186206858 credits under the ten-credit ceiling. See [execution details](../STAGE8_EXECUTION.md) for reproducibility, scanner and inference limits.
