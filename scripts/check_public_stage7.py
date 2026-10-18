"""Verify the report source/assets, numeric exports, build and hash-bound visual review."""
import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from check_public_stage2 import check
from export_report_assets import digest, expected_outputs, read, verify_sources
from src.research.design import canonical_hash

PUBLIC=ROOT/'docs/results/stage7'
PREPARATION_FILES={'preparation.json','source_snapshot.json','citation_register.json','asset_plan.csv'}
EXECUTION_FILES={'status.json','qc_summary.json','visual_review.json','artifact_manifest.json'}


def verify_bundle(pdf_tools=False):
    snapshot=verify_sources()
    report=ROOT/'report'
    manifest=read(report/'artifact_manifest.json')
    assert manifest['source_snapshot_sha256']==canonical_hash(snapshot)
    generated,facts=expected_outputs()
    expected=set(generated)
    for name,data in generated.items():
        assert (report/name).read_bytes().replace(b'\r\n',b'\n')==data.replace(b'\r\n',b'\n'),name
    assert manifest['numeric_facts']==facts
    with (PUBLIC/'asset_plan.csv').open(encoding='utf-8',newline='') as stream:
        assets=list(csv.DictReader(stream))
    for asset in assets:
        if asset['kind']!='copy': continue
        destination=Path(asset['destination']).relative_to('report').as_posix()
        assert digest(report/destination)==asset['source_sha256']==digest(ROOT/asset['source']),destination
        assert manifest['provenance'][destination]['kind']=='copied'
        expected.add(destination)
    for name,source in [('figures/phase_report.pdf','docs/results/stage6/phase_summaries.csv'),
        ('figures/diagnostic_report.pdf','docs/results/stage6/diagnostic_traces.csv')]:
        expected.add(name)
        provenance=manifest['provenance'][name]
        assert provenance['presentation_variant'] and provenance['source']==source
        assert provenance['source_sha256']==snapshot['files'][source]==digest(ROOT/source)
    assert set(manifest['files'])==set(manifest['provenance'])==expected and len(expected)==26
    for name,value in manifest['files'].items():
        path=(report/name).resolve()
        assert path.is_relative_to(report) and digest(path)==value,name
    build=read(report/'build_manifest.json')
    assert build['status']=='compiled' and build['final_log_checks_passed']
    assert build['isolated_source_bundle_build'] and build['isolated_pdf_bytes_equal']
    assert build['pdf_sha256']==build['isolated_pdf_sha256']==digest(report/'main.pdf')
    assert build['new_model_completion_calls']==0
    assert build['pdf']['pages']==12 and len(build['pdf']['page_text_characters'])==12
    assert min(build['pdf']['page_text_characters'])>800
    assert set(build['source_files'])==expected|{'main.tex','README.md','artifact_manifest.json'}
    for name,value in build['source_files'].items():
        assert (report/name).resolve().is_relative_to(report) and digest(report/name)==value,name
    deliverables=expected|{'main.tex','README.md','artifact_manifest.json','build_manifest.json','main.pdf'}
    actual={p.relative_to(report).as_posix() for p in report.rglob('*') if p.is_file() and p.suffix in ('.tex','.pdf','.bib','.md','.json','.csv')}
    assert actual==deliverables and len(deliverables)==31
    main=(report/'main.tex').read_text(encoding='utf-8')
    for name in re.findall(r'\\input\{([^}]+)\}',main):
        assert (report/name).resolve().is_relative_to(report) and (report/name).is_file()
    figures=re.findall(r'\\reportfigure\{([^}]+)\}',main)
    assert len(figures)==6 and all((report/'figures'/(name+'.pdf')).is_file() for name in figures)
    keys={k for group in re.findall(r'\\cite[pt]\{([^}]+)\}',main) for k in group.split(',')}
    assert keys=={c['key'] for c in read(PUBLIC/'citation_register.json')['citations']}
    for required in ['\\RawWins{}','\\AdjustedWins{}','\\FirstPass{}','\\Fallback{}','\\Exposure{}',
        '177/600','four native Retail','right-censored','prior manual','not independently attested','baseline-only']:
        assert required.lower() in main.lower(),required
    assert facts['Decisions']==252 and facts['FirstPass']==108 and facts['RepairSuccess']==127 and facts['Fallback']==17
    assert facts['FirstPass']+facts['RepairSuccess']+facts['Fallback']==facts['Decisions']
    assert math.isclose(facts['PrimaryCost'],.252123564,abs_tol=1e-9)
    assert (report/'claim_map.csv').read_bytes().replace(b'\r\n',b'\n')==(ROOT/'docs/results/stage6/claim_map.csv').read_bytes().replace(b'\r\n',b'\n')
    for name in deliverables:
        path=report/name
        if path.suffix=='.pdf':
            assert path.read_bytes().startswith(b'%PDF-')
            continue
        text=path.read_text(encoding='utf-8')
        assert not re.search(r'\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b',text),name
        if path.suffix=='.json': check(json.loads(text))
    if pdf_tools:
        import pymupdf
        document=pymupdf.open(report/'main.pdf')
        assert len(document)==12
        texts=[page.get_text() for page in document]
        assert hashlib.sha256('\n'.join(texts).encode()).hexdigest()==build['pdf']['text_sha256']
        assert 'References' in texts[7] and 'Native coverage and reasoning denominators' in texts[8]
        assert not any('\ufffd' in text or '??' in text for text in texts)
        for page in document:
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines',[]):
                    for span in line['spans']:
                        x0,y0,x1,y1=span['bbox']
                        assert x0>=8 and y0>=8 and x1<=page.rect.width-8 and y1<=page.rect.height-8,span['text']
    return dict(pages=12,assets=26,source_bundle_files=31,citation_records=7,displayed_figures=6,
        pdf_sha256=build['pdf_sha256'],isolated_pdf_bytes_equal=True,numeric_exports_reconciled=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-only',action='store_true',help='Check the built bundle before the final visual review is sealed.')
    parser.add_argument('--pdf',action='store_true',help='Also inspect pages/text/geometry with locally available PyMuPDF.')
    args=parser.parse_args()
    result=verify_bundle(args.pdf)
    if not args.bundle_only:
        assert {p.name for p in PUBLIC.iterdir() if p.is_file()}==PREPARATION_FILES|EXECUTION_FILES
        for path in PUBLIC.iterdir():
            text=path.read_text(encoding='utf-8')
            assert not re.search(r'\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b',text),path.name
            if path.suffix=='.json': check(json.loads(text))
            else:
                for row in csv.DictReader(text.splitlines()): check(row)
        status=read(PUBLIC/'status.json');qc=read(PUBLIC/'qc_summary.json');review=read(PUBLIC/'visual_review.json')
        assert status['status']=='complete' and status['exit_gate_passed'] and qc['exit_gate_passed']
        assert status['report_pdf_sha256']==review['pdf_sha256']==result['pdf_sha256']
        assert status['report_pages']==review['page_count']==result['pages']
        assert status['main_pages']==8 and status['appendix_pages']==4
        assert review['status']=='passed' and [p['page'] for p in review['pages']]==list(range(1,13))
        assert all(p['status']=='passed' and re.fullmatch('[0-9a-f]{64}',p['rendered_page_sha256']) for p in review['pages'])
        assert qc['status']=='passed' and all(qc['checks'].values())
        assert status['new_model_completion_calls']==status['new_simulation_episodes']==0
        assert status['cumulative_project_exposure_credits']==read(ROOT/'docs/results/stage6/status.json')['budget_snapshot']['inclusive_project_exposure_credits']
        assert status['native_coverage']==dict(validated=14,failed=1,deferred=4)
        files=read(PUBLIC/'artifact_manifest.json')['files']
        expected={str((ROOT/'report'/name).relative_to(ROOT)).replace('\\','/') for name in read(ROOT/'report/build_manifest.json')['source_files']}
        expected|={'report/main.pdf','report/build_manifest.json'}
        expected|={p.relative_to(ROOT).as_posix() for p in PUBLIC.iterdir() if p.name!='artifact_manifest.json'}
        assert set(files)==expected
        for name,value in files.items():
            path=(ROOT/name).resolve()
            assert (path.is_relative_to(ROOT/'report') or path.is_relative_to(PUBLIC)) and digest(path)==value,name
    subprocess.run([sys.executable,str(ROOT/'scripts/check_stage6_readiness.py')],check=True)
    print(f"Stage 7 report passed: {result['pages']} pages, {result['assets']} assets, {result['citation_records']} citations, isolated build and source-bound numeric checks.")


if __name__=='__main__': main()
