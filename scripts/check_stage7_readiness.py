"""Check the Stage 7 writing plan and pinned inputs; no report authoring or model calls.

--local-tools also verifies MiKTeX/packages and renders a saved figure into ignored
results/verification/stage7_preparation/. Default checks run in CI without local tools.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_public_stage2 import check
from src.research.design import canonical_hash

PUBLIC = ROOT / 'docs/results/stage7'
FILES = {'preparation.json', 'source_snapshot.json', 'citation_register.json', 'asset_plan.csv'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    path = Path(path)
    data = path.read_bytes()
    if path.suffix not in ('.png', '.pdf'):
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def local_tools(plan):
    tex = Path(os.environ['LOCALAPPDATA']) / 'Programs/MiKTeX/miktex/bin/x64'
    poppler = Path(os.environ['USERPROFILE']) / '.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin'
    run = lambda args: subprocess.run([str(a) for a in args], capture_output=True, text=True, check=True, timeout=30)
    compiler = run([tex / 'pdflatex.exe', '--version']).stdout.splitlines()[0]
    bibliography = run([tex / 'bibtex.exe', '--version']).stdout.splitlines()[0]
    assert 'MiKTeX' in compiler and 'MiKTeX' in bibliography
    for package in plan['build']['packages']:
        assert run([tex / 'kpsewhich.exe', package]).stdout.strip(), package
    version = run([poppler / 'pdftoppm.exe', '-v'])
    renderer = (version.stdout + version.stderr).splitlines()[0]
    source = ROOT / 'docs/assets/stage6/contribution_contrasts.pdf'
    assert re.search(r'Pages:\s+1\b', run([poppler / 'pdfinfo.exe', source]).stdout)
    folder = ROOT / 'results/verification/stage7_preparation'
    folder.mkdir(parents=True, exist_ok=True)
    run([poppler / 'pdftoppm.exe', '-f', '1', '-singlefile', '-scale-to', '1500', '-png', source, folder / 'renderer_probe'])
    assert (folder / 'renderer_probe.png').stat().st_size > 1000
    result = dict(compiler=compiler, bibliography=bibliography, renderer=renderer,
        planned_packages_available=len(plan['build']['packages']), saved_figure_pdf_render_passed=True,
        new_report_build_performed=False, model_completion_calls=0)
    (folder / 'tools.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f"Local report tools passed: {compiler}; {renderer}; {len(plan['build']['packages'])} packages. No report authored or compiled.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-tools', action='store_true')
    args = parser.parse_args()
    assert {p.name for p in PUBLIC.iterdir() if p.is_file()} == FILES
    for path in [*PUBLIC.iterdir(), ROOT / 'configs/report/stage7.template.json']:
        text = path.read_text(encoding='utf-8')
        assert not re.search(r'\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b', text), path.name
        if path.suffix == '.json':
            check(json.loads(text))
        else:
            for row in csv.DictReader(text.splitlines()):
                check(row)
    prep = read(PUBLIC / 'preparation.json')
    snapshot = read(PUBLIC / 'source_snapshot.json')
    plan = read(ROOT / 'configs/report/stage7.template.json')
    register = read(PUBLIC / 'citation_register.json')
    assert prep['status'] == 'prepared_not_authored' and prep['preparation_complete']
    assert not prep['report_authored'] and not prep['report_compiled'] and not prep['stage7_exit_gate_passed']
    assert not plan['approved'] and not plan['report_authored'] and not plan['report_compiled']
    assert not plan['paid_calls_authorized'] and not plan['new_simulations_authorized']
    assert prep['new_model_completion_calls'] == prep['new_simulation_episodes'] == 0
    assert prep['source_commit'] == snapshot['source_commit'] == plan['source_commit'] == '4805b0d'
    assert canonical_hash(snapshot) == prep['source_snapshot_sha256'] == plan['source_snapshot_sha256']
    assert canonical_hash(plan) == prep['plan_sha256']
    assert digest(PUBLIC / 'citation_register.json') == prep['citation_register_sha256']
    assert digest(PUBLIC / 'asset_plan.csv') == prep['asset_plan_sha256']
    stage6_manifest = read(ROOT / 'docs/results/stage6/artifact_manifest.json')['files']
    assert set(stage6_manifest) <= set(snapshot['files'])
    assert 'docs/results/stage6/artifact_manifest.json' in snapshot['files']
    assert len(snapshot['files']) == prep['pinned_source_files']
    for name, value in snapshot['files'].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT) and digest(path) == value, name
    stage6 = read(ROOT / 'docs/results/stage6/status.json')
    assert stage6['exit_gate_passed'] and stage6['status'] == 'complete'
    assert prep['cumulative_project_exposure_credits'] == stage6['budget_snapshot']['inclusive_project_exposure_credits']
    with (PUBLIC / 'asset_plan.csv').open(encoding='utf-8', newline='') as stream:
        assets = list(csv.DictReader(stream))
    assert len(assets) == 20 and len({a['destination'] for a in assets}) == 20
    assert sum(a['kind'] == 'copy' for a in assets) == plan['copy_assets'] == prep['planned_copy_assets'] == 12
    assert sum(a['kind'] == 'table_input' for a in assets) == plan['generated_table_inputs'] == prep['generated_table_inputs'] == 8
    assert sum(a['source'].endswith('.pdf') for a in assets) == 7
    for asset in assets:
        assert asset['source_sha256'] == stage6_manifest[asset['source']] == snapshot['files'][asset['source']]
        assert (ROOT / asset['destination']).resolve().is_relative_to(ROOT / 'report')
    citations = register['citations']
    assert len(citations) == prep['citation_records'] == 7
    assert [r['key'] for r in citations] == plan['citation_keys']
    assert len(set(plan['citation_keys'])) == 7 and all(r['url'].startswith('https://') for r in citations)
    keys = {r['key']: r for r in citations}
    sources = read(ROOT / 'configs/sources.json')
    assert keys['retailbench_code']['commit'] == sources['retailbench']['commit']
    assert keys['firmbench_code']['commit'] == sources['reference_repositories']['FirmBench']['commit']
    assert keys['icbe_code']['commit'] == sources['reference_repositories']['ICBE']['commit']
    assert keys['atomicd_v8']['version'] == sources['dataset']['version'] == 8
    assert keys['atomicd_v8']['csv_sha256'] == sources['dataset']['csv_sha256']
    assert keys['firmbench_code']['paper_citation_status'] == 'empty_upstream_bibtex_block'
    assert keys['icbe_code']['paper_citation_status'] == 'no_formal_paper_citation_in_pinned_readme'
    assert len(plan['required_qualifications']) == 11
    assert plan['evidence'] == dict(primary_episodes=36, policy_days=756, matched_blocks=3, llm_decisions=252,
        new_stage6_free_baselines=48, native_validated=14, native_failed=1, native_deferred=4)
    assert plan['build']['all_pages_visual_review'] and plan['build']['isolated_source_bundle_build']
    assert '--disable-installer' in plan['build']['pdftex_options'] and '--no-shell-escape' in plan['build']['pdftex_options']
    subprocess.run([sys.executable, str(ROOT / 'scripts/check_stage6_readiness.py')], check=True)
    if args.local_tools:
        local_tools(plan)
    print(f"Stage 7 preparation passed: {len(snapshot['files'])} pinned files, 12 copy assets, 8 table inputs and 7 citation records. Report execution remains pending.")


if __name__ == '__main__':
    main()
