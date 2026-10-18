"""Scan tracked content and optional reachable history; report rules/paths, never matches."""
import argparse
import base64
import json
import os
import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'openai_style_key': rb'\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}',
    'github_token': rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})',
    'aws_access_key': rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
    'private_key': rb'-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----',
    'credential_in_url': rb'https?://[^/\s:"<>]+:[^/@\s"<>]+@',
    'private_user_path': rb'(?:[A-Za-z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+[\\/]|/Users/[A-Za-z0-9_.-]+/)',
}


def git(*args, data=None):
    return subprocess.check_output(['git', *args], cwd=ROOT, input=data)


def scan(include_history=False, inspect_pdf=False):
    patterns = {name: re.compile(value) for name, value in PATTERNS.items()}
    values = {**os.environ, **{k:v for k,v in dotenv_values(ROOT / '.env').items() if v}}
    secrets = [v.encode() for k,v in values.items() if v and len(v) > 8
               and any(t in k.upper() for t in ('API_KEY', 'ACCESS_TOKEN', 'AUTH_TOKEN', 'CLIENT_SECRET'))]
    findings, pdf_count, attachments, notebook_count = set(), 0, 0, 0

    def inspect(data, path, scope, pdf=True):
        nonlocal pdf_count, attachments, notebook_count
        for name, pattern in patterns.items():
            if pattern.search(data):
                findings.add((scope, path, name))
        if any(secret in data for secret in secrets):
            findings.add((scope, path, 'actual_local_credential'))
        if inspect_pdf and pdf and data.startswith(b'%PDF-'):
            import pymupdf
            with pymupdf.open(stream=data, filetype='pdf') as document:
                pdf_count += 1
                attachments += document.embfile_count()
                if document.is_encrypted:
                    findings.add((scope, path, 'encrypted_pdf_uninspected'))
                for page in document:
                    inspect(page.get_text().encode(), path, scope, False)
                    inspect(json.dumps(page.get_links(), default=str).encode(), path, scope, False)
                inspect(json.dumps(document.metadata).encode(), path, scope, False)
                if document.embfile_count():
                    findings.add((scope, path, 'unexpected_pdf_attachment'))
        if path.endswith('.ipynb'):
            notebook_count += 1
            notebook = json.loads(data)
            for cell in notebook.get('cells', []):
                for record in [*cell.get('outputs', []), *cell.get('attachments', {}).values()]:
                    for mime, content in record.get('data', record).items():
                        if mime in ('image/png','image/jpeg','application/pdf'):
                            inspect(base64.b64decode(''.join(content)), path + ':embedded', scope)

    files = [p.decode('utf-8') for p in git('ls-files','-z').split(b'\0') if p]
    forbidden = []
    for name in files:
        path = Path(name)
        if name == '.env' or name.startswith(('vendor/', 'results/', '.cache/')) or path.suffix in ('.db','.sqlite','.jsonl'):
            forbidden.append(name)
        if name.startswith('data/raw/') and path.suffix in ('.csv','.zip'):
            forbidden.append(name)
        inspect((ROOT / name).read_bytes(), name, 'tracked')
    for name in forbidden:
        findings.add(('tracked', name, 'private_or_raw_artifact_path'))
    blobs = 0
    if include_history:
        objects = git('rev-list','--objects','--all').decode('utf-8').splitlines()
        names = {row.split(' ',1)[0]:row.split(' ',1)[1] if ' ' in row else '<commit-or-tree>' for row in objects}
        info = git('cat-file','--batch-check', data=('\n'.join(names)+'\n').encode()).decode().splitlines()
        ids = [row.split()[0] for row in info if row.split()[1] == 'blob']
        process = subprocess.Popen(['git','cat-file','--batch'], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        try:
            for oid in ids:
                process.stdin.write((oid+'\n').encode())
                process.stdin.flush()
                header = process.stdout.readline().split()
                size = int(header[2])
                data = process.stdout.read(size)
                assert len(data)==size and process.stdout.read(1)==b'\n'
                inspect(data, names[oid], 'history')
                blobs += 1
        finally:
            process.stdin.close()
            try:
                assert process.wait(timeout=15)==0
            finally:
                process.stdout.close()
    return dict(status='passed' if not findings else 'review_required', tracked_files=len(files),
        reachable_history_blobs=blobs, history_scanned=include_history, pdf_inspection=inspect_pdf,
        pdf_objects_inspected=pdf_count, pdf_attachments=attachments, notebook_objects_inspected=notebook_count,
        recognizable_secret_patterns=list(PATTERNS), actual_local_value_comparison_performed=bool(secrets),
        findings=[dict(scope=s,path=p,rule=r) for s,p,r in sorted(findings)],
        limitations='Recognizable patterns and locally available credential values; not a proof against all possible secrets or image-encoded content.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--pdf', action='store_true', help='Requires optional PyMuPDF; inspect PDF text, links, metadata and attachments.')
    parser.add_argument('--output', type=Path, help='Optional ignored Stage 8 evidence path.')
    args=parser.parse_args()
    result=scan(args.history, args.pdf)
    if args.output:
        destination=args.output.resolve()
        assert destination.is_relative_to(ROOT / 'results/verification/stage8') or destination.is_relative_to(ROOT / '.cache/stage8')
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
    if result['findings']:
        raise SystemExit(2)


if __name__=='__main__':
    main()
