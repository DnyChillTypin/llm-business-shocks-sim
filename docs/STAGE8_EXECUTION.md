# Stage 8: reproduction and preliminary portfolio release

Local release QC ran on 18 October 2026 from preparation commit `0615016`.
The [release checklist](results/release_checklist.md) records each gate; the
machine-readable [status](results/stage8/status.json) distinguishes a local release
candidate from final signoff after its GitHub workflow passes. This checkpoint
releases the preliminary portfolio deliverable, with original native research
coverage still incomplete.

## Reproduction evidence

A fresh public clone, separate Python 3.12 environment and declared research
requirements installed successfully without credentials, private results or the
29 GB historical LFS archive. Pinned RetailBench/FirmBench/ICBE sources and the
downloaded Kaggle v8 checksum were verified. All 98 existing research tests,
31 frozen-design checks, 36 free validation episodes and eight notebooks passed.
Two new privacy regression tests also passed in that fresh environment; they
check historical-token detection and notebook-output detection without echoing
secret values. The publication CI runs the combined 100-test suite.

All 19 native evaluation plans, the 36-episode/252-decision Kaggle matrix and a
single 21-decision LLM cell passed metadata-only dry runs. No execution allowance
was supplied. Fresh baselines and scripted validation fixtures are reproduction
checks, not new genuine model results.

Separately, all 36 original saved episodes were replayed locally with real
gateway clients blocked: 756 policy-days and 864 passing checks. The original
episode evidence, allowance and cumulative ledger remained unchanged. The report
and aggregate checks preserved all fallback days, costs, coverage and censoring.
Public aggregate analysis is reproducible; raw conversation/native-case rescoring
requires the private evidence, which is not redistributed.

## Report, citations and publication boundary

Compiling 29 report source files in a copied folder reproduced exactly the
published 12-page PDF bytes, text and page records on the verified MiKTeX toolchain.
The original 31-file bundle, report PDF and Stage 7 visual-review binding remained
unchanged. PDF text, page geometry, citations and source/result hashes passed.
Since no report bytes changed, the existing page-by-page rendered review remains
applicable; Stage 8 does not claim a newly edited or newly typeset report.

Seven citation records were rechecked against official paper metadata, pinned
repository files and public dataset metadata. Current attribution, missing ICBE
license metadata and compatibility qualifications are in
[the release addendum](RELEASE_ATTRIBUTION.md). Frozen source notes were preserved.

The privacy scanner examines the tracked tree and reachable Git history using
recognizable credential patterns and actual locally available credential values
in memory. It inspects notebook outputs/embedded data and PDF text, links, metadata
and attachments; output contains rule names and paths, never matched values.
The final [scan summary](results/stage8/privacy.json) records counts and no
unaddressed findings. This is a bounded scan plus publication review, not a proof
against all possible secrets or image-encoded content. No raw dataset, upstream
case content, model conversation or account/approval record was added to Git.

## Reader-facing changes and release verification

README now leads with the report, actual mixed findings, coverage and reproducible
commands. It removes stale current-facing claims that the primary matrix has not
started or that the former six-credit cap is current. Full-suite setup now includes
the small FirmBench and ICBE checkouts needed for frozen design and tests.
[Reproduction instructions](REPRODUCIBILITY.md) distinguish free fixtures, public
saved analysis, local replay, standalone LaTeX compilation and future paid previews.
The [sanitized environment](results/stage8/environment.json) records package
versions without local user paths or editable-install URLs.

The release checker binds these documents, execution summaries, code and unchanged
report inputs. CI verifies the package and current tracked-content privacy before
executing all eight notebooks. A passing reviewed-candidate CI receipt is added at
signoff; the final pushed head is checked again and its live run linked in the
delivery handoff. Compiler versions may affect PDF bytes on another installation;
requirements are ranges rather than a full lock. Linux CI and the fresh Windows
checks are separate evidence.

No new model calls, paid experiments or primary replications occurred. Cumulative
exposure remains 2.186206858 credits of the ten-credit ceiling, including existing
unknown-charge holds. The 14 validated native tasks, retained ICBE failure after
177/600 valid rounds and four deferred native Retail tasks remain unchanged.
Synthetic mechanisms, three selected blocks, uncertain prior window use,
pre-shock divergence, 17 fallback days and six censored adaptive recoveries retain
their reporting qualifications. No GitHub release tag or message to the lead was
created; the reviewed repository checkpoint is the portfolio publication.
