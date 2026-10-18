# Stage 8 preparation: final reproduction and portfolio release

Prepared on 18 October 2026 against completed Stage 7 commit `7abb2d6`. **Preparation is complete; Stage 8 execution and its exit gate remain pending.** Stage 7's 12-page preliminary report has passing [exact-commit CI](https://github.com/DnyChillTypin/llm-business-shocks-sim/actions/runs/39142253763), a reviewed PDF and a successful isolated source-bundle build. These are reused inputs, not newly completed Stage 8 checks.

Stage 8 makes the preliminary findings deliverable usable and honestly reproducible by another reader. It does not complete the original native benchmark scope: 14 tasks were validated, ICBE failed after 177/600 valid rounds and four native Retail evaluations remain deferred. No new paid experiment is needed. Cumulative recorded exposure remains 2.186206858 credits under the existing 10-credit ceiling.

## What will be reproduced

| Route | Inputs and check | Meaning and limit |
|---|---|---|
| Public baseline and validation | Fresh clone, pinned external code and checksum-verified Kaggle data; offline tests, baseline notebook and validation matrix | Reproduces simulator integration and free validation fixtures; fixtures are not LLM findings |
| Public saved-result analysis | Published aggregate tables, all eight notebooks, Stage 2-7 checkers and generated report tables | Recomputes supported contrasts and verifies published hashes/denominators; aggregates alone cannot independently rescore private model conversations |
| Local evidence audit | Existing ignored primary episode records, independent replay and unchanged budget ledger | Verifies retained local evidence read-only; no credentials, raw conversations or ledger identifiers are published |
| Report | Unchanged 31-file LaTeX bundle, report checker and an isolated build | Verifies source/result consistency and rendering; byte identity is expected only on the verified compiler/font toolchain |
| Future paid procedure | Native and Kaggle metadata-only dry runs | Verifies plans and authorization boundaries; no new model output, gateway identity verification or exact stochastic reproduction is claimed |

The [release template](../configs/release/stage8.template.json), [source snapshot](results/stage8/source_snapshot.json) and [gate plan](results/stage8/gate_plan.csv) define the review. Source pins preserve the report and its Stage 6 inputs. Preparation also records original notebook hashes and executed-cell counts as a historical baseline; fresh notebook outputs are assessed in a disposable clone rather than replacing the reviewed source notebooks.

## Execution order and evidence

| Gate | Work in order | Objective exit evidence |
|---|---|---|
| R1: evidence and claims | Run Stage 7 and the frozen design/public evidence checks. Reconcile README/report claims against coverage, costs, fallbacks, censoring and the claim map. Audit existing private evidence read-only. | Frozen inputs/PDF still match; 36 episodes, 756 policy-days, 252 LLM opportunities and native 14/1/4 coverage retained; allowance/ledger bytes unchanged |
| R2: fresh installation | Clone the reviewed commit into a new ignored folder; create a separate Python 3.12 environment, install the declared research requirements and fetch only needed pinned code/data. | Clean-clone setup succeeds without `.env`, private results or the 29 GB historical LFS archive; CSV and vendor commits match |
| R3: tests and fixtures | Run the full suite on Windows, including the timeout helper; run the frozen design and offline validation matrix. Retain Linux CI evidence separately. | All current tests pass (98 at this checkpoint), all 31 design checks and 36 validation episodes pass; no paid requests |
| R4: notebooks and analysis | Validate and execute all eight notebooks from fresh kernels in the clone. Inspect errors and outputs, then rerun public source/report checks. | Eight successful notebook executions, zero error outputs, saved analysis agrees with aggregate evidence; regenerated outputs remain separate from originals |
| R5: paid-path previews | Dry-run the full Kaggle matrix and one LLM cell; dry-run all 19 native task plans. Never add execution or budget arguments. | 36/252 full-matrix denominator, one 21-decision LLM cell and 19 native plans; no client construction, calls or ledger changes |
| R6: report verification | Run numeric/source/PDF checks. Compile a copy of the self-contained bundle in an isolated folder, compare text/pages/values and inspect rendered pages if output changes. | Source/PDF consistency, seven resolved citations and readable 12-page output; toolchain-specific reproduction recorded. A revised PDF needs a fresh visual-review binding |
| R7: citation and attribution | Recheck the seven citation records against primary records and pinned source licenses. Document exact code versions, compatibility changes and dataset attribution. | No invented FirmBench/ICBE paper metadata; ICBE's missing pinned license file remains explicit; no external source/data redistribution |
| R8: publication boundary | Scan the full tracked tree and notebook outputs, extract PDF text/metadata, inspect embedded attachments, and scan reachable Git history for recognizable secrets. Compare actual local credential values in memory without printing matches. | Zero unaddressed credential/private-account findings or raw case/data exports; report only sanitized counts and paths. If an actual historical secret is found, stop affected publication and arrange revocation; do not rewrite history silently |
| R9: reader and release review | Write reproduction instructions, correct current README status/roadmap, document environments and limitations; review selected diff, commit/push and verify exact-head CI. | Every release checklist row links to real evidence; source and pushed commit agree; CI passes; preliminary status and incomplete research scope stay prominent |

## Existing commands for the execution stage

These commands exist now, but preparing this stage does not run the full release sequence. Run setup/tests/notebooks in a **new disposable clone**, so verifier output and baseline exports cannot overwrite the original research evidence. `verify_notebook.py` writes the executed notebook back to its input path.

```powershell
# From the reviewed project commit. The destination must not already exist.
$stage8Commit = (git rev-parse HEAD).Trim()
$stage8Clone = Join-Path (Get-Location) '.cache\stage8\fresh-clone'
git clone https://github.com/DnyChillTypin/llm-business-shocks-sim.git $stage8Clone
git -C $stage8Clone checkout --detach $stage8Commit
Set-Location $stage8Clone
py -3.12 -m venv .venv
$py = '.\.venv\Scripts\python.exe'
& $py -m pip install -r requirements-research.txt
& $py scripts/setup_project.py
& $py scripts/setup_benchmarks.py --only FirmBench
& $py scripts/setup_benchmarks.py --only ICBE
& $py -m unittest discover -s tests -v
& $py scripts/check_research_design.py
& $py scripts/check_kaggle_matrix.py
2..7 | ForEach-Object { & $py "scripts/check_public_stage$_.py" }
Get-ChildItem notebooks/*.ipynb | Sort-Object Name | ForEach-Object {
    & $py scripts/verify_notebook.py --notebook ("notebooks/" + $_.Name)
    if ($LASTEXITCODE -ne 0) { throw "Notebook failed: $($_.Name)" }
}
& $py scripts/check_public_stage7.py
& $py scripts/run_kaggle_experiment.py --config configs/study.json --dry-run
& $py scripts/run_kaggle_experiment.py --config configs/study.json --episode-index 2 --dry-run
& $py scripts/run_benchmarks.py list | ForEach-Object {
    & $py scripts/run_benchmarks.py run --task $_ --purpose evaluation --dry-run
    if ($LASTEXITCODE -ne 0) { throw "Native preview failed: $_" }
}
```

Treat any nonzero exit as a failed gate; retain per-command logs and exit codes. On macOS/Linux use `python3.12 -m venv .venv` and `.venv/bin/python`. Record installed package names/versions from `pip list --format=json`, Python version and OS/compiler versions, with no local user paths or editable-install URLs. Requirements currently use version ranges: record the environment actually tested rather than claiming a complete dependency lock or universal portability.

From the original workspace, the existing `scripts/check_stage6_readiness.py --private` performs the local evidence/ledger audit. `scripts/check_public_stage7.py --pdf` uses the optional PyMuPDF dependency for PDF text/page geometry. For another LaTeX build, follow [the standalone bundle instructions](../report/README.md) in a copied folder. Avoid rebuilding/re-exporting the sealed report in place merely to run release checks. The Stage 7 build wrapper writes `report/build_manifest.json`; its use is therefore restricted to the disposable clone during Stage 8.

## Documents and outputs to create during execution

Create `docs/REPRODUCIBILITY.md`, `docs/RELEASE_ATTRIBUTION.md`, `docs/results/release_checklist.md`, and sanitized `docs/results/stage8/{status.json,qc_summary.json,environment.json,artifact_manifest.json}`. Implement a small `scripts/check_public_stage8.py` for the final evidence bundle if needed. These are **planned outputs**, not currently completed deliverables. Keep clone contents, full test/compiler logs, scanner matches and page previews ignored under `.cache/stage8/` or `results/verification/stage8/`. Do not duplicate already-published result bundles or add raw data to Git.

README needs current reproduction routes and a concise findings/limitations entry point. Its historical roadmap still says primary comparisons have not started and describes the older six-credit allowance. Correct those current-facing statements while preserving the historical stage records. `docs/BENCHMARKS.md` and `docs/THIRD_PARTY.md` are already pinned Stage 7 sources; add current release qualifications in the new attribution/reproduction documents and README instead of silently invalidating those pins. No report/scientific source changes are planned. A discovered material report error must be corrected with refreshed manifests, compilation, page inspection and review binding.

## Completion boundary, failures and decisions

Stage 8 exits when all nine gates have linked evidence, the final release checklist passes, the reviewed changes are pushed and exact-head GitHub CI succeeds. A preparation pass, existing CI run or successful document checksum does not count as newly completed release QC. Release can be complete for this **preliminary portfolio deliverable** while original native coverage remains incomplete. New Retail runs, an amended ICBE protocol, additional models/windows or stronger scientific claims belong to separately authorized research work.

If dependency installation, external downloads or citations are unavailable, retain the failure and complete independent checks; do not infer a fresh-install pass. Diagnose notebook drift before changing saved results. A local compiler/package difference may produce different bytes; distinguish equivalent content from byte identity and never replace the reviewed PDF automatically. Failed privacy checks block affected publication until resolved. Recheck impacted gates after fixes, without repeating unrelated successful experiments.

Allow approximately 1-2 active hours plus dependency/download and CI time; bandwidth or a dependency mismatch can extend it. Gateway cost is zero. Free baselines and validation fixtures may run during execution and must be labeled as reproduction, never new primary evidence. The existing instruction to push completed stages authorizes the reviewed preliminary portfolio checkpoint; no further routine scope/budget decision is needed. This preparation does not create a GitHub release/tag or contact the lead.

The preparation checker is available now:

```powershell
.\.venv\Scripts\python.exe scripts/check_stage8_readiness.py
```

The next action after a later instruction to execute Stage 8 is to run that checker, audit the original local evidence read-only, and create the disposable clone at the reviewed commit.
