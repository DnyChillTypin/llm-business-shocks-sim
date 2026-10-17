# Stage 0 handoff verification

This checkpoint verifies the environment and previously prepared work. It does not add LLM research results. The machine-readable record is [`results/handoff_audit.json`](results/handoff_audit.json); the native check snapshot is [`results/benchmark_readiness.json`](results/benchmark_readiness.json).

## Verification performed

- Verified all three source commits against `configs/sources.json` and confirmed that tracked vendor files are unchanged.
- Re-read and validated the synthetic Kaggle CSV: 76,000 rows, 100 store–product series, 760 days each. The SHA-256 matches the configured checksum.
- Verified the RetailBench LFS inventory: 93,958 downloaded and checked-out files, totaling 29,010,737,647 bytes. This is an inventory check, not a new hash audit of every large asset.
- Ran the isolated FormulaEval timeout test, the full 19-test suite, and `pip check` successfully.
- Ran all 20 native readiness checks successfully in one fresh batch. Portable per-check evidence is included under `docs/results/stage0/checks/`.
- Executed both notebooks in fresh project kernels. The regenerated baseline summary matches the prior output within numeric tolerance. Previous processed pilot inputs, tables and figures were preserved locally before execution.
- Verified an existing MiKTeX installation by compiling a document with `booktabs`, `graphicx`, `hyperref`, a table and a BibTeX bibliography. Package auto-installation and shell escape were disabled.
- Confirmed the setup commit's GitHub CI passed. CI now also executes notebook 02, in addition to notebook 01 and the tests. CI displays saved native readiness evidence; it does not rerun the full native suite.

The native readiness batch is recorded in the evidence. CI for the stage commit is checked after pushing and its outcome is reported in the checkpoint response; the setup commit's CI success does not establish the new commit's outcome.

## Timeout diagnosis

The earlier test stalled under the managed sandbox. That environment also refused writes to `results/verification/`. Running the bounded diagnostic outside the sandbox completed in about two seconds, and all 19 tests then passed in about eight seconds. No FormulaEval implementation defect was reproduced, and no compatibility-code change was necessary. The precise sandbox subprocess restriction was not independently isolated.

Run these checks from a normal project terminal. An agent using a restricted sandbox may need the environment's execution approval mechanism. A future stalled test should be stopped using a process-tree watchdog rather than repeatedly started without a bound.

## Reusable commands

From the project root in PowerShell:

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -m unittest discover -s tests -v
& $py -m pip check
& $py scripts/verify_notebook.py
& $py scripts/verify_notebook.py --notebook notebooks/02_benchmark_setup.ipynb
& $py scripts/run_benchmarks.py list
& $py scripts/run_benchmarks.py check
```

The notebook verifier saves fresh execution output into the notebook. Notebook 01 also creates a new baseline session and regenerates its export files. The native check command blocks model calls; it creates `results/setup_checks/<timestamp>/readiness.json` plus per-task logs and check results. Its output does not automatically update the public snapshot: that snapshot must be reviewed and linked to the fresh evidence.

The local MiKTeX binaries are available through an explicit path, even though they are absent from the current PATH:

```powershell
$texBin = Join-Path $env:LOCALAPPDATA 'Programs\MiKTeX\miktex\bin\x64'
& (Join-Path $texBin 'pdflatex.exe') --version
# From the future report directory:
& (Join-Path $texBin 'pdflatex.exe') --disable-installer --no-shell-escape -interaction=nonstopmode -halt-on-error main.tex
& (Join-Path $texBin 'bibtex.exe') main
& (Join-Path $texBin 'pdflatex.exe') --disable-installer --no-shell-escape -interaction=nonstopmode -halt-on-error main.tex
& (Join-Path $texBin 'pdflatex.exe') --disable-installer --no-shell-escape -interaction=nonstopmode -halt-on-error main.tex
```

No compiler installation or global PATH change was needed. The compiler emits a MiKTeX update-check advisory; it did not prevent compilation. The final report's exact package set will need its own build and visual verification.

## Evidence and limitations

Portable checkpoint evidence is stored under `docs/results/stage0/`. Full local logs, the compiler smoke PDF and backups are under the ignored `results/verification/stage0/`. Environment versions are a snapshot of the successful installation, not a tested cross-platform lockfile. Historical gateway evidence is retained with its original verification date; no new paid compatibility calls were made.

The experiment implementation remains at the handoff scope: two Kaggle rule-based policies and a 19-task native launcher. The Kaggle LLM policy, bounded paid pilots, complete latency/failure/cost instrumentation, spending guard, new matched evaluation matrix, and findings report remain to be completed. The gateway balance and full-suite cost remain unknown. The original pilot has already been inspected and must remain labeled exploratory.

## Next checkpoint and GitHub workflow

Next is Stage 1: freeze questions, comparisons, metrics, selected series and dates, assumptions and failure rules before new evaluation. No API budget is needed for that stage. Pilot and total spending limits remain separate decisions before paid calls.

At the user's request, commit and push every completed stage and useful intermediate milestone. Review the selected diff, check for credentials, and verify CI for the pushed commit. A failed CI run is a checkpoint failure to diagnose, not a reason to report the stage as fully validated.
