# Stage 7 preparation: LaTeX findings report

Prepared on 18 October 2026 against completed Stage 6 commit `4805b0d`. **Preparation is complete; report authoring and final PDF compilation have not started.** The evidence supports a preliminary findings report with explicit incomplete native coverage. Stage 8 remains the later reproduction and release checkpoint.

## Deliverable and argument

Write a self-contained `report/main.pdf`, `main.tex`, `references.bib`, generated `tables/` and `figures/`, an asset/build manifest and reproducible build instructions. Target 5-8 main pages plus a compact appendix (approximately 2-4 pages, adjusted for legibility). Use the project title and label the document a preliminary technical report. Avoid inventing personal authorship or affiliations. The [report template](../configs/report/stage7.template.json), [asset plan](results/stage7/asset_plan.csv), [citation register](results/stage7/citation_register.json) and [source snapshot](results/stage7/source_snapshot.json) bind the drafting inputs. Templates are planning metadata; they do not claim a written or approved PDF.

The central result is mixed. Raw LLM contribution exceeded adaptive in 2/9 shock comparisons; the control-adjusted contrast was positive in 7/9, with a negative mean for surge. Explain both using the same nine comparisons. Retain 108/252 first-pass valid decisions, 127 successful repairs, 17 fallback days and 161 invalid affordability responses. Recovery in 9/9 LLM episodes is relative to its own control, which carries high inventory; adaptive has six right-censored episodes. These results do not establish economic optimality, causal learning or population superiority. All nine LLM shock/control pairs already diverged before the shock.

Native coverage remains 14 validated tasks, one retained ICBE failure after 177/600 valid complete rounds, and four deferred native Retail tasks. Include the 457 supported reasoning cases and separate 50-case Factset extension; finer entity labels and exact cases have different denominators. Preserve Consulting's eight recovered complete cases and two fresh cases, all failed charges, BeerGame's extreme upstream cost and terminal backlog proxy qualification, and EDT's one scenario decision plus 96 ABM steps. None may become a pooled adaptation score.

## Section and asset plan

| Section | Required evidence and narrative |
|---|---|
| Abstract and scope | Actual matrix and native coverage; mixed contribution results, reliability and explicit limitations |
| Questions and context | Four frozen RQs; native capability, retail outcomes, behavioral response/recovery and operating reliability |
| Data and methods | Synthetic 76,000-row source; training-only series choice; chronology and uncertain prior manual outcome use; three matched blocks; shared observations/actions; assumptions, valuation, repair/fallback |
| Retail findings | All nine adaptive shock effects, fixed secondary effects and six control comparisons; contribution, service and inventory; separate raw and control-adjusted effects |
| Recovery and diagnostics | Frozen three-day rule and six censored adaptive cases; both positive and reliability-failure illustrations, labeled post-outcome selection |
| Reliability and cost | First-pass/repair/fallback denominators; primary and repair requests, tokens/latency; 0.252123564 primary credits and 2.186206858 cumulative exposure including old holds |
| Baseline sensitivity | 24 reused primary plus 48 new free baseline episodes at elasticities 0.75/1.5/2.25; scope limited to simulator baselines |
| Native findings | Dataset-specific metrics and separate Consulting, BeerGame and EDT units; ICBE failure and deferred Retail coverage |
| Discussion and conclusion | What the configured policy achieved, service/inventory/reliability tradeoffs, limits of adaptation attribution, concrete future work |
| Appendix | All 19 task statuses; pins/models/prompt and config provenance; compatibility changes, metrics/denominators, recovery detail and reproduction commands |

The asset plan selects seven existing PDF figures and five existing LaTeX tables, plus eight aggregate data inputs for compact tables and reconciliation. Main figures emphasize contribution, recovery, reliability, sensitivity and balanced diagnostics; two further figures support the appendix. Fit and readability determine final placement during drafting. Every selected source has a Stage 6 hash. Preserve full public tables and trace links even where the short report summarizes them. No raw cases, model conversations, request identifiers, account details or full external datasets belong in the report bundle.

## Citations and attribution

Metadata was checked on 18 October 2026 against pinned repository files and primary public sources. RetailBench's title/authors/DOI match its [arXiv record](https://arxiv.org/abs/2603.16453); cite the paper and separately state the frozen code commit. The [FirmBench repository](https://github.com/sduyangmin/FirmBench) calls its README project EnterpriseBench and leaves its paper BibTeX block empty. Cite the pinned software repository under the FirmBench/EnterpriseBench label without inventing a paper, venue or personal author list. The [ICBE repository](https://github.com/ruxi-stnmr/icbe-2026-strategic-behavior-llms) supplies the simulator description without a formal paper citation; use a pinned repository citation. No license file was found in that pinned ICBE tree; no upstream source is to be copied into the report.

The Kaggle source is [atomicd's dataset](https://www.kaggle.com/datasets/atomicd/retail-store-inventory-and-demand-forecasting), version 8 with the frozen CSV checksum. The public API currently reports version 8, creator display name Wavelet and licenseName Apache 2.0; the original local metadata has an empty licenses array. Record those as distinct observations and preserve the frozen metadata. Attribute the stable publisher handle atomicd; publish aggregates and download instructions. Method background may cite the verified [CoT](https://arxiv.org/abs/2201.11903) and [ReAct](https://arxiv.org/abs/2210.03629) records. Their general results are not experimental findings of this project. Any additional literature or individual source-dataset claims need source verification before inclusion.

## Build and PDF review readiness

MiKTeX-pdfTeX 4.23 and MiKTeX-BibTeX 4.2 (MiKTeX 25.12) are installed at the Stage 0 explicit per-user path. They were rechecked successfully outside the managed filesystem restriction. The earlier PATH-only check did not establish compiler absence. Nine planned packages/classes are available: article, booktabs, graphicx, hyperref, geometry, longtable, natbib, caption and microtype. Stage 0 already compiled a table/bibliography smoke document. No new report PDF was generated during preparation.

Bundled Poppler 26.07.0 is available by explicit runtime path. `pdfinfo` opened the saved Stage 6 contrast figure and `pdftoppm` rendered it to an ignored PNG; the rendered image was visually inspected. PyMuPDF is also present in the project environment for PDF text/page checks. No installation or global PATH modification is required.

During execution, locate binaries as follows and keep auto-installation and shell escape disabled:

```powershell
$texBin = Join-Path $env:LOCALAPPDATA 'Programs\MiKTeX\miktex\bin\x64'
# From the report directory, AFTER main.tex and references.bib exist:
& (Join-Path $texBin 'pdflatex.exe') --disable-installer --no-shell-escape -interaction=nonstopmode -halt-on-error main.tex
& (Join-Path $texBin 'bibtex.exe') main
# Repeat the same pdflatex command twice, then inspect warnings and references.
```

Use the PDF skill during actual creation. Its artifact-start command must succeed exactly once immediately before the first report authoring command. The installed script is at the skill's `container_tools/mark_artifact_operation_started.mjs`; preparation has not invoked it because it has not authored a PDF. The study explicitly calls for LaTeX despite the skill's generic reportlab preference. Render every final page with Poppler into ignored `results/verification/stage7/` previews and inspect each one. Re-render after layout changes. Mark build status incomplete if a new package or compiler failure is unresolved; never substitute source-only delivery for a finished PDF claim.

## Execution sequence and exit gate

1. Run `scripts/check_stage7_readiness.py` and its `--local-tools` probe; confirm Stage 6 exit and every pinned source/asset hash. Stop on stale evidence.
2. Implement `scripts/export_report_assets.py` to copy only planned, hash-verified assets and generate compact tables from reviewed aggregates. Record source hashes, rounding and copy/generation provenance in `report/artifact_manifest.json`; prevent traversal and unexpected overwrite. Never regenerate experimental results while exporting.
3. Implement a small build wrapper and author `report/main.tex`, `references.bib` and `README.md`. Resolve every scientific claim to the Stage 6 claim map or a separately identified native metric/source. Write the abstract last from actual results.
4. Compile with the explicit MiKTeX/BibTeX sequence. Resolve undefined citations, missing references, missing glyphs and clipped/overflowing content. Check negative signs, units, denominators and censored cells in generated tables.
5. Render and visually inspect all pages; check figures remain readable at final page scale. Reconcile report values with full-precision source tables; preserve simulator-money versus gateway-credit units.
6. Build the self-contained report source bundle from an isolated folder with no credentials/private raw runs. Record exact compiler command/version, final PDF SHA-256, page count and review evidence. Keep local build paths/previews out of public manifests.
7. Update the Stage 7 completion checkpoint, README and appropriate CI source/asset checks; commit, push and check CI. Stage 8 then performs final broader reproduction/release QC.

Stage 7 exits only with a compiled, fully inspected findings PDF plus reproducible source, verified citations/cross-references, traceable tables/figures and truthful incomplete-work/limitations tables. Formatting changes may rearrange planned assets with a documented final manifest; scientific definitions, omissions or extra experiments require separate review. Default to this brief without another style/budget question. Estimated 3-5 active hours; zero model calls and zero gateway credits. Current cumulative exposure remains 2.186206858 credits under the existing 10-credit ceiling.

Preparation checks exist now:

```powershell
.\.venv\Scripts\python.exe scripts/check_stage7_readiness.py
.\.venv\Scripts\python.exe scripts/check_stage7_readiness.py --local-tools
```

The exporter, build wrapper and report files described above are execution deliverables, not existing launch commands. No report draft, final PDF or Stage 7 exit pass is claimed by this preparation checkpoint.
