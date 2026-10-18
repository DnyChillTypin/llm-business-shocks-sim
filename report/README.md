# Findings report source bundle

`main.pdf` is the preliminary Stage 7 findings report. Native task coverage remains incomplete as stated in the report. All business results come from the verified Stage 6 package; no model calls are needed to build or read the report.

## Build from this directory

The bundle is self-contained: `main.tex`, `references.bib`, `tables/`, and `figures/` are all local. With pdfLaTeX and BibTeX installed, run pdfLaTeX, BibTeX, then pdfLaTeX twice. On the verified Windows installation:

```powershell
$texBin = Join-Path $env:LOCALAPPDATA 'Programs\MiKTeX\miktex\bin\x64'
& (Join-Path $texBin 'pdflatex.exe') --disable-installer --no-shell-escape -interaction=nonstopmode -halt-on-error main.tex
& (Join-Path $texBin 'bibtex.exe') main
& (Join-Path $texBin 'pdflatex.exe') --disable-installer --no-shell-escape -interaction=nonstopmode -halt-on-error main.tex
& (Join-Path $texBin 'pdflatex.exe') --disable-installer --no-shell-escape -interaction=nonstopmode -halt-on-error main.tex
```

On TeX Live, use `pdflatex -no-shell-escape -interaction=nonstopmode -halt-on-error main.tex` (the MiKTeX `--disable-installer` option is specific to MiKTeX) and the same BibTeX/two further passes. The exact local package and compiler versions are recorded in `build_manifest.json`. Installations with different font/package versions can produce different PDF bytes or pagination. No operating-system packages are auto-installed by project scripts.

## Reproduce from the project root

The Python wrappers use the project research environment plus the optional `requirements-report.txt` dependencies (PyMuPDF for PDF checks). The standalone LaTeX build above does not require Python.

```powershell
.\.venv\Scripts\python.exe scripts/export_report_assets.py
.\.venv\Scripts\python.exe scripts/build_report.py --check-isolated
.\.venv\Scripts\python.exe scripts/check_public_stage7.py
```

The exporter verifies the Stage 7 preparation snapshot, copies its 12 selected assets and generates compact tables, numeric macros, citations, source pins and two page-sized chart variants from the same reviewed trace values. Original figures remain unchanged as supplements. It refuses changed copied assets or unreviewed overwrites. `--refresh-generated` refreshes generated assets only if prior manifest-bound outputs remain intact. A rebuild invalidates the completed visual-review binding until the new PDF has been rendered and inspected again; the public checker rejects stale review hashes.

The build wrapper uses the verified per-user Windows MiKTeX binaries, disables package installation and shell escape, checks final logs, and optionally rebuilds an isolated copy of this source bundle. Local logs and rendered previews belong under ignored `results/verification/stage7/`; they are not required to build the bundle.

## Evidence and boundaries

`artifact_manifest.json` binds copied/generated assets to reviewed inputs and records display rounding and full-precision headline facts. `build_manifest.json` binds the compiled PDF to all source inputs, tool versions, page/text checks and the isolated build. `claim_map.csv` supplies the source table and limitation for each headline claim. The project's Stage 7 public checkpoint separately records the final page-by-page review and PDF hash.

The bundle includes some full supplementary tables that are not printed in the short PDF. Complete condition-level CSVs, all action traces and sensitivity summaries remain in `docs/results/stage6/` in the repository. No daily observations are treated as independent replications. All fallback days, failed native coverage and censored recovery cases remain visible. Private raw model transcripts, account information and upstream datasets/code are excluded.
