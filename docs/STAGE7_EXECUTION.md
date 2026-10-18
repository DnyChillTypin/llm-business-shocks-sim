# Stage 7: compiled preliminary findings report

Stage 7 is complete on 18 October 2026. The [findings PDF](../report/main.pdf) contains eight main pages (including references) and four appendix pages. Its [self-contained LaTeX bundle](../report/README.md) builds from local source, bibliography, figures and tables without credentials or private raw runs. Original native coverage remains incomplete: 14 validated tasks, the retained ICBE validity failure and four deferred Retail tasks. Stage 8's broader reproduction and release checks remain pending.

## Results and reporting boundary

The report distinguishes raw LLM-versus-adaptive contribution (positive in 2/9 shocks) from the control-adjusted contrast (positive in 7/9, with a negative surge mean). It reports all 17 fallback days, first-pass versus repaired validity, six censored adaptive recovery episodes and the policy's high-stock control. All nine LLM shock/control pairs already diverged before the shock. Three selected blocks, one model realization per condition, synthetic mechanisms and uncertain prior manual window use restrict interpretation to descriptive simulator evidence.

Native datasets and serious games retain their own units, denominator definitions, recovered-case provenance and failures. The report includes all 19 native task statuses, finer label versus exact-case accuracy, the Factset extension, Consulting recovery, BeerGame's extreme upstream cost and terminal backlog proxy, EDT's scenario-level scope, and ICBE's 177/600 complete valid rounds without a final tournament score. No missing Retail score or cross-family pooled score is created.

## Build, assets and quality checks

- The exporter verifies the 57-file Stage 7 source snapshot. It copies all 12 planned assets unchanged, generates eight compact tables plus numeric facts/source pins/bibliography/claim mapping, and adds two page-sized chart variants using identical reviewed trace values. The resulting manifest binds 26 assets. Diagnostics moved to the appendix for readable labels; the original seven selected figure PDFs remain in the bundle.
- Seven citation records were checked during preparation. The bibliography is generated from that register. Software citations explicitly replace unavailable FirmBench/ICBE paper metadata; no publication or personal author list is invented.
- MiKTeX-pdfTeX 4.23 and BibTeX 4.2 compile with package auto-installation and shell escape disabled. A font-expansion compatibility issue was fixed by using the installed scalable default fonts and disabling expansion. Title alignment, overflowing lines and small appendix labels were corrected during visual review.
- The final LaTeX log has no overfull boxes, missing glyphs, unresolved citations or unresolved cross-references. Poppler rendered every page at 140 dpi. Every final page was visually checked for hierarchy, units, labels, table fit, negative signs, censoring and legibility. Independent PDF text/geometry checks supplement that inspection.
- An isolated copy of the 31-file report bundle rebuilt successfully and produced byte-identical PDF output on the verified local toolchain. This does not guarantee identical pagination/bytes with other font or compiler versions.

[Public status](results/stage7/status.json), [QC](results/stage7/qc_summary.json), [visual-review binding](results/stage7/visual_review.json) and the [publication manifest](results/stage7/artifact_manifest.json) bind the final PDF to its source and review evidence. The report's own asset and build manifests document exact hashes, tool versions, source files, rounding and reproduction results. Local compiler logs and page previews stay ignored under `results/verification/stage7/`.

## Reproduction

From the project root with the research environment and optional `requirements-report.txt` dependencies:

```powershell
.\.venv\Scripts\python.exe scripts/export_report_assets.py
.\.venv\Scripts\python.exe scripts/build_report.py --check-isolated
.\.venv\Scripts\python.exe scripts/check_public_stage7.py --pdf
```

The public checker verifies every copied asset, regenerates numeric tables/macros/bibliography for comparison, checks the build/source/PDF hashes, preserves the frozen Stage 6 inputs and rejects stale visual-review bindings. CI runs its source/binding checks without requiring MiKTeX or making model calls; local `--pdf` additionally checks PDF pages, text and geometry using PyMuPDF. A new PDF revision requires fresh rendering, inspection and review binding before it can pass the completed-report check.

No new model calls or simulation episodes were made. Cumulative exposure remains 2.186206858 credits of the existing ten-credit ceiling, including prior unknown-charge holds. The report is a completed preliminary findings deliverable; it does not close the original unexecuted native scope or Stage 8 release gate.
