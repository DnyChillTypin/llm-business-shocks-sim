# Professor-facing report

`professor_report.pdf` is the copy to share: two plain-language summary pages dated 19 October 2026 followed by the unchanged 12-page technical report dated 18 October 2026. The summary highlights the economic comparison, the meaning of the control-adjusted result, service/inventory tradeoffs, reliability problems, incomplete native coverage and limits on inference.

No new experiments were run. The archived `report/main.pdf` and Stage 7/8 evidence bindings remain unchanged. The illustrative 100/70 versus 80/65 example is explicitly not observed study data. Original report page numbers are retained; summary pages use roman numerals and PDF bookmarks distinguish the two parts.

The accompanying manifest records source and PDF hashes, numerical evidence sources, and the completed visual review. Rebuild from the repository root with `.venv/Scripts/python.exe scripts/build_professor_report.py` using the existing Windows MiKTeX installation and `requirements-report.txt`. LaTeX package installation and shell escape are disabled. The builder checks that all original report pages retain identical extracted text and rendered appearance. Build files and page previews are written to `tmp/pdfs/professor_report/`; the builder resets the manifest to pending visual review after a rebuild. Inspect all newly rendered pages before marking it reviewed.

The summary is an editorial explanation of existing descriptive findings. It adds no claim of statistical significance, real-world superiority or causal learning, and it does not mark incomplete native evaluations complete.
