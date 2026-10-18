"""Compile the self-contained report, inspect final logs and optionally build an isolated copy."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from export_report_assets import digest, read, verify_sources

OPTIONS=['--disable-installer','--no-shell-escape','-interaction=nonstopmode','-halt-on-error']


def compile_folder(folder,tex,logs,label):
    env=os.environ.copy()
    env['SOURCE_DATE_EPOCH']='1792281600'
    env['FORCE_SOURCE_DATE']='1'
    env['MIKTEX_ENABLE_INSTALLER']='0'
    for number,engine in enumerate(['pdflatex','bibtex','pdflatex','pdflatex'],1):
        command=[str(tex/(engine+'.exe')),*(OPTIONS if engine=='pdflatex' else []),'main.tex' if engine=='pdflatex' else 'main']
        result=subprocess.run(command,cwd=folder,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
        (logs/f'{label}-pass-{number}.log').write_bytes(result.stdout)
        if result.returncode:
            raise RuntimeError(f'{engine} pass {number} failed; inspect ignored {label} logs.')
    log=(folder/'main.log').read_text(encoding='utf-8',errors='replace')
    failures=['Overfull \\hbox','Overfull \\vbox','Missing character:','There were undefined references','There were undefined citations','Rerun to get cross-references right','Citation `','Reference `']
    found=[pattern for pattern in failures if pattern in log]
    assert not found, f'Unresolved report log issues: {found}'
    assert (folder/'main.pdf').stat().st_size>10000
    return log


def pdf_record(path):
    import pymupdf as fitz
    document=fitz.open(path)
    texts=[page.get_text() for page in document]
    assert all(text.strip() for text in texts)
    assert '\ufffd' not in ''.join(texts)
    return dict(pages=len(document),text_sha256=hashlib.sha256('\n'.join(texts).encode()).hexdigest(),
        page_text_characters=[len(text) for text in texts])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-isolated',action='store_true')
    args=parser.parse_args()
    verify_sources()
    report=ROOT/'report'
    manifest=read(report/'artifact_manifest.json')
    for name,value in manifest['files'].items(): assert digest(report/name)==value,name
    tex=Path(os.environ['LOCALAPPDATA'])/'Programs/MiKTeX/miktex/bin/x64'
    logs=ROOT/'results/verification/stage7'
    logs.mkdir(parents=True,exist_ok=True)
    compiler=subprocess.check_output([str(tex/'pdflatex.exe'),'--version'],text=True).splitlines()[0]
    bibliography=subprocess.check_output([str(tex/'bibtex.exe'),'--version'],text=True).splitlines()[0]
    source_names=['main.tex','references.bib','README.md','artifact_manifest.json',*manifest['files']]
    sources={name:digest(report/name) for name in sorted(set(source_names))}
    compile_folder(report,tex,logs,'primary')
    result=dict(status='compiled',visual_review='separate_hash_bound_review_required',compiler=compiler,bibliography=bibliography,
        pdf_qa_library='PyMuPDF '+importlib.metadata.version('PyMuPDF'),
        sequence=['pdflatex','bibtex','pdflatex','pdflatex'],pdftex_options=OPTIONS,
        source_date_epoch=1792281600,source_files=sources,pdf_sha256=digest(report/'main.pdf'),
        pdf=pdf_record(report/'main.pdf'),final_log_checks_passed=True,new_model_completion_calls=0,
        isolated_source_bundle_build=False)
    if args.check_isolated:
        temporary=Path(tempfile.mkdtemp(prefix='isolated_',dir=logs)).resolve()
        assert temporary.is_relative_to(logs.resolve())
        for name in sources:
            destination=(temporary/name).resolve()
            assert destination.is_relative_to(temporary)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(report/name,destination)
        compile_folder(temporary,tex,logs,'isolated')
        isolated=pdf_record(temporary/'main.pdf')
        assert isolated==result['pdf'],'Isolated source bundle must reproduce page count and extracted text.'
        result.update(isolated_source_bundle_build=True,isolated_pdf_sha256=digest(temporary/'main.pdf'),
            isolated_pdf_bytes_equal=digest(temporary/'main.pdf')==result['pdf_sha256'])
    (report/'build_manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=result['status'],pages=result['pdf']['pages'],isolated_build=result['isolated_source_bundle_build'])))


if __name__=='__main__': main()
