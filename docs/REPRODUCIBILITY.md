# Reproducing the preliminary findings release

Stage 8 tested a fresh public clone of `0615016e823df125a045fcf67469c3c3164d66b9`
on Windows with a separate Python 3.12 environment. The release adds documentation,
privacy checks and evidence validation; frozen scientific inputs, the original
eight notebooks and the report remain unchanged. Linux coverage comes from the
[Research validation workflow](https://github.com/DnyChillTypin/llm-business-shocks-sim/actions/workflows/tests.yml).
The [release environment](results/stage8/environment.json) records the packages
actually installed, not a universal dependency lock.

## Install the public research path

Use a new clone to preserve published notebook outputs. Git and Python 3.12 are
required; initial code/data downloads need internet access but no API key.

```powershell
git clone https://github.com/DnyChillTypin/llm-business-shocks-sim.git
cd llm-business-shocks-sim
py -3.12 -m venv .venv
$py = '.\.venv\Scripts\python.exe'
& $py -m pip install -r requirements-research.txt
& $py scripts/setup_project.py
& $py scripts/setup_benchmarks.py --only FirmBench
& $py scripts/setup_benchmarks.py --only ICBE
& $py -m unittest discover -s tests -v
& $py scripts/check_public_stage8.py
```

On macOS/Linux, use `python3.12 -m venv .venv` and `.venv/bin/python`.
Run commands in order and stop on a nonzero exit code. Inspect test names, final
test counts and checker summaries. `setup_project.py` downloads Kaggle version 8
and verifies its CSV checksum; each vendor checkout must match `configs/sources.json`
and contain no tracked changes. The small setup excludes RetailBench's historical
29 GB LFS outputs. FirmBench is needed for frozen native case selection and ICBE
for failure-handling tests; omitting them is insufficient for the full suite.

The fresh environment passed all 98 existing research tests. Two further release
scanner tests check that a removed historical token and a credential in notebook
output are detected without echoing the value. The current full suite includes both.
Requirements use ranges; preserve the tested environment snapshot, and diagnose
future dependency drift rather than relabeling a failed installation as reproduced.

## Baselines, fixtures and saved analysis

```powershell
& $py scripts/check_research_design.py
& $py scripts/check_kaggle_matrix.py
2..8 | ForEach-Object {
    & $py "scripts/check_public_stage$_.py"
    if ($LASTEXITCODE -ne 0) { throw "Public evidence check failed: stage $_" }
}
Get-ChildItem notebooks/*.ipynb | Sort-Object Name | ForEach-Object {
    & $py scripts/verify_notebook.py --notebook ("notebooks/" + $_.Name)
    if ($LASTEXITCODE -ne 0) { throw "Notebook failed: $($_.Name)" }
}
```

The design checker verifies 31 frozen constraints. The validation matrix runs 24
baseline and 12 scripted validation episodes with independent replay. These are
free software checks, not new genuine LLM findings. Notebook 01 reruns the earlier
eight-episode baseline pilot; notebooks 03-08 reconstruct the design or load saved
evidence. Inspect zero error outputs, matching denominators, cost units, all fallback
days and censored recovery. Every notebook was executed from a fresh kernel in Stage 8.

`verify_notebook.py` overwrites its input notebook and notebook 01 regenerates pilot
exports, so keep this work in the disposable clone. Raw logs, temporary inputs and
generated runs belong under ignored `.cache/` or `results/`. A completed Stage 8
checker verifies the published checkpoint, not a new paid experiment. Run the
historical preparation checker before changing notebook outputs; its baseline
hashes intentionally identify the preserved original notebook files.

## What public evidence can establish

| Evidence | What can be reproduced | What remains unavailable publicly |
|---|---|---|
| Aggregate tables and trace exports | Contribution contrasts, phase/recovery metrics, action summaries, costs and report tables | Independent scoring of original private conversations or native case contents |
| Baseline/fixture code and downloaded inputs | Deterministic integration, accounting, constraints, matched validation paths | A new genuine LLM decision or original model variability |
| Original private evidence | Saved-action replay, raw response parsing, attempt/ledger reconciliation | Not copied into the public repository |
| Report source bundle | Source-only LaTeX build and hash-bound report verification | Guaranteed byte identity on other font/compiler versions |

Stage 8 independently replayed all 36 original episodes/756 policy-days with real
gateway clients blocked. All 864 replay checks passed, original evidence was
unchanged, and the existing ledger/allowance were audited read-only. Public
[sanitized evidence](results/stage8/verification.json) records counts and outcomes,
not private identifiers. This replay reuses saved responses; it is not 36 new
primary replications. Exact new model responses or independently attested model
weights are not promised.

## Report and PDF verification

The published report has 12 pages: eight main pages including references and four
appendix pages. Its 31-file source bundle is self-contained. See
[the report instructions](../report/README.md) for pdfLaTeX/BibTeX commands and
TeX Live versus MiKTeX options. No Python or credentials are required for that
standalone build. Stage 8 compiled the 29 source files in a separate folder on the
verified toolchain and reproduced identical PDF bytes, text and page records.
The original PDF and Stage 7 page-by-page visual-review binding remain unchanged.

For local text/page-geometry checks, install the optional report requirements:

```powershell
& $py -m pip install -r requirements-report.txt
& $py scripts/check_public_stage7.py --pdf
```

Default public checks and CI do not require MiKTeX or PyMuPDF. The Stage 7 exporter
and build wrapper write files, including the build manifest; run them only in a
copy if reproducing this sealed release. If a revised PDF is published, refresh
its manifests, render and inspect every final page, and bind a new review.

## Future paid procedure: preview only

```powershell
& $py scripts/run_kaggle_experiment.py --config configs/study.json --dry-run
& $py scripts/run_kaggle_experiment.py --config configs/study.json --episode-index 2 --dry-run
& $py scripts/run_benchmarks.py list | ForEach-Object {
    & $py scripts/run_benchmarks.py run --task $_ --purpose evaluation --dry-run
    if ($LASTEXITCODE -ne 0) { throw "Native preview failed: $_" }
}
```

Inspect the 36-episode/252-decision matrix, one 21-decision LLM cell and all 19
native plans. `paid_calls_authorized_by_plan` must remain false. Stage 8 exercised
these dry runs without credentials or new requests. Actual model execution is a
separate procedure requiring a reviewed allowance, unchanged shared ledger and
appropriate run manifests. The checked-in templates preserve historical
unapproved states; changing a template is not authorization.

## Publication checks and interpretation

```powershell
& $py scripts/check_release_privacy.py --history
# With optional report requirements installed, inspect PDF text/metadata too:
& $py scripts/check_release_privacy.py --history --pdf
git diff --check
git status --short
git check-ignore .env
```

The scanner checks tracked files, notebook outputs/embedded binary data and
reachable Git blobs. Optional PDF inspection checks extracted text, links,
metadata and attachments. It compares locally available credential values in
memory and reports only rule names and paths. Recognizable patterns and known
values cannot prove the absence of every possible secret or image-encoded text;
the release also underwent source/aggregate-boundary review. Default CI has no
local credential values, so it does not claim that comparison was performed there.

The [attribution addendum](RELEASE_ATTRIBUTION.md) records seven checked references,
source terms and compatibility qualifications. The report remains preliminary:
synthetic mechanisms, three selected blocks, one LLM realization per condition,
uncertain prior window use, pre-shock divergence, 17 fallback days and six censored
adaptive recoveries constrain the findings. Native coverage remains 14 validated,
one failed and four deferred tasks. A portfolio release pass does not close those
research gaps. The [release checklist](results/release_checklist.md) links the gates
to their evidence, with GitHub validation checked for the pushed publication head.
