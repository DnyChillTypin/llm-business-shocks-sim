"""Build a two-page reader summary and attach the sealed technical report."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf'
WORK = ROOT / 'tmp/pdfs/professor_report'
ORIGINAL_SHA = 'f06c146513fa0d0db223becd8e4db8d5c1b90373e20502ecc39d64bbea63e11f'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    original = ROOT / 'report/main.pdf'
    assert digest(original) == ORIGINAL_SHA, 'Original report changed; review required.'
    WORK.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT / 'professor_summary.tex', WORK / 'professor_summary.tex')
    engine = Path(os.environ['LOCALAPPDATA']) / 'Programs/MiKTeX/miktex/bin/x64/pdflatex.exe'
    env = dict(os.environ, SOURCE_DATE_EPOCH='1792368000', FORCE_SOURCE_DATE='1', MIKTEX_ENABLE_INSTALLER='0')
    for number in range(2):
        result = subprocess.run([str(engine), '--disable-installer', '--no-shell-escape',
            '-interaction=nonstopmode', '-halt-on-error', 'professor_summary.tex'],
            cwd=WORK, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        (WORK / f'pass-{number + 1}.txt').write_bytes(result.stdout)
        assert result.returncode == 0, 'Compilation failed; inspect temporary logs.'
    log = (WORK / 'professor_summary.log').read_text(encoding='utf-8', errors='replace')
    for issue in ('Overfull \\hbox', 'Overfull \\vbox', 'Missing character:', 'undefined references'):
        assert issue not in log, issue
    summary = pymupdf.open(WORK / 'professor_summary.pdf')
    source = pymupdf.open(original)
    assert len(summary) == 2 and len(source) == 12, f'Summary has {len(summary)} pages'
    combined = pymupdf.open()
    combined.insert_pdf(summary)
    combined.insert_pdf(source)
    # PyMuPDF does not copy named destinations during insert_pdf. Resolve them
    # to explicit local links so citations and figure references stay clickable.
    for index, page in enumerate(source):
        for link in page.get_links():
            if link['kind'] == pymupdf.LINK_NAMED and 'page' in link:
                target_page = link['page']
                point = link['to'] * source[target_page].transformation_matrix
                combined[index + 2].insert_link({'kind': pymupdf.LINK_GOTO,
                    'from': link['from'], 'page': target_page + 2, 'to': point})
    combined.set_metadata({'title': 'Can LLMs Adapt to Business Shocks? - Findings and Technical Report',
        'author': 'Project technical report', 'subject': 'Preliminary findings with reader summary, 19 October 2026'})
    combined.set_toc([[1, 'Main findings: reader summary', 1], [1, 'Failures and limitations', 2],
        [1, 'Technical report (18 October 2026)', 3],
        *[[level + 1, title, page + 2] for level, title, page in source.get_toc()]])
    combined.set_page_labels([{'startpage': 0, 'prefix': '', 'style': 'r', 'firstpagenum': 1},
        {'startpage': 2, 'prefix': '', 'style': 'D', 'firstpagenum': 1}])
    target = OUT / 'professor_report.pdf'
    combined.save(target, garbage=4, deflate=True, no_new_id=True)
    combined.close()
    final = pymupdf.open(target)
    assert len(final) == 14 and final.embfile_count() == 0
    for index, page in enumerate(final):
        text = page.get_text()
        assert text.strip() and '\ufffd' not in text
        if index >= 2:
            assert text == source[index - 2].get_text(), 'Technical report text changed.'
            assert page.get_pixmap().samples == source[index - 2].get_pixmap().samples, 'Report appearance changed.'
        page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(WORK / f'page-{index + 1:02}.png')
    assert digest(original) == ORIGINAL_SHA
    record = {'status': 'built_pending_visual_review', 'pages': len(final), 'summary_pages': 2,
        'original_report_sha256': ORIGINAL_SHA, 'original_report_text_and_render_unchanged': True,
        'pdf_sha256': digest(target), 'source_sha256': digest(OUT / 'professor_summary.tex'),
        'builder_sha256': digest(Path(__file__)), 'new_model_calls': 0,
        'evidence_sources': {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p) for p in [
            ROOT / 'docs/results/stage6/status.json', ROOT / 'docs/results/stage6/per_scenario_summaries.csv',
            ROOT / 'docs/results/stage8/status.json', ROOT / 'report/tables/facts.tex']}}
    (OUT / 'professor_report_manifest.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'pages': len(final), 'unchanged_original_pages': 12, 'final_log_checks': 'passed'}))


if __name__ == '__main__':
    main()
