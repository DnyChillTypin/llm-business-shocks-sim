"""Verify the prepared release gates and unchanged Stage 7 evidence; no experiments."""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from check_public_stage2 import check
from export_report_assets import digest
from src.research.design import canonical_hash

PUBLIC = ROOT / 'docs/results/stage8'
PREPARATION = {'preparation.json', 'source_snapshot.json', 'gate_plan.csv'}
GATES = [f'R{i}' for i in range(1, 10)]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def required_sources():
    stage7 = ROOT / 'docs/results/stage7'
    names = set(read(stage7 / 'source_snapshot.json')['files'])
    names.update(read(stage7 / 'artifact_manifest.json')['files'])
    names.add('docs/results/stage7/artifact_manifest.json')
    return names


def main():
    execution_present = (PUBLIC / 'status.json').exists()
    allowed = PREPARATION
    if execution_present:
        from check_public_stage8 import EXECUTION_FILES
        allowed = allowed | EXECUTION_FILES
        if read(PUBLIC / 'status.json')['status'] == 'complete':
            allowed = allowed | {'ci_receipt.json'}
    assert {p.name for p in PUBLIC.iterdir()} == allowed, 'Unexpected Stage 8 artifact'
    plan_path = ROOT / 'configs/release/stage8.template.json'
    for path in [*(PUBLIC / name for name in PREPARATION), plan_path]:
        text = path.read_text(encoding='utf-8')
        assert not re.search(r'\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b', text), path.name
        if path.suffix == '.json':
            check(json.loads(text))
        else:
            for row in csv.DictReader(text.splitlines()):
                check(row)
    prep, snapshot, plan = read(PUBLIC / 'preparation.json'), read(PUBLIC / 'source_snapshot.json'), read(plan_path)
    assert prep['stage'] == plan['stage'] == 8
    assert prep['status'] == plan['status'] == 'prepared_not_executed'
    assert prep['preparation_complete'] and not prep['stage8_exit_gate_passed']
    assert not prep['release_executed'] and not plan['release_executed']
    assert prep['new_model_completion_calls'] == prep['new_simulation_episodes'] == 0
    assert not plan['paid_calls_authorized'] and plan['gateway_cost_credits'] == 0
    assert not plan['new_primary_or_native_experiments']
    assert prep['source_commit'] == snapshot['source_commit'] == plan['source_commit'] == '7abb2d67c21fe7a9a6927afc07d6a456c3061de7'
    assert canonical_hash(snapshot) == prep['source_snapshot_sha256'] == plan['source_snapshot_sha256']
    assert canonical_hash(plan) == prep['plan_sha256']
    assert digest(PUBLIC / 'gate_plan.csv') == prep['gate_plan_sha256']
    assert snapshot['hash_rule'] == 'SHA-256; text CRLF normalized to LF; PDF/PNG verbatim'
    assert set(snapshot['files']) == required_sources()
    assert len(snapshot['files']) == prep['pinned_source_files']
    for name, value in snapshot['files'].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT) and digest(path) == value, name
    stage7 = read(ROOT / 'docs/results/stage7/status.json')
    stage6 = read(ROOT / 'docs/results/stage6/status.json')
    assert stage7['status'] == 'complete' and stage7['exit_gate_passed']
    assert stage7['report_pdf_sha256'] == prep['report_pdf_sha256'] == digest(ROOT / 'report/main.pdf')
    assert stage7['report_pages'] == prep['report_pages'] == 12
    assert stage7['native_coverage'] == prep['native_coverage'] == {'validated': 14, 'failed': 1, 'deferred': 4}
    assert stage6['budget_snapshot']['inclusive_project_exposure_credits'] == stage7['cumulative_project_exposure_credits'] == prep['cumulative_project_exposure_credits']
    ci = prep['prior_stage7_ci']
    assert ci['head_sha'] == prep['source_commit'] and ci['status'] == 'completed' and ci['conclusion'] == 'success'
    assert ci['html_url'] == f"https://github.com/DnyChillTypin/llm-business-shocks-sim/actions/runs/{ci['id']}"
    rows = list(csv.DictReader((PUBLIC / 'gate_plan.csv').read_text(encoding='utf-8').splitlines()))
    assert [r['gate'] for r in rows] == plan['required_gates'] == GATES
    assert len(rows) == prep['planned_release_gates'] == 9
    assert all(r['status'] == 'planned_not_executed' and r['exit_evidence'] for r in rows)
    notebooks = sorted(ROOT.glob('notebooks/*.ipynb'))
    assert [p.relative_to(ROOT).as_posix() for p in notebooks] == plan['notebooks']
    assert set(snapshot['saved_notebook_baseline']) == set(plan['notebooks'])
    assert len(notebooks) == prep['saved_notebooks'] == 8
    for path in notebooks:
        notebook = nbformat.read(path, as_version=4)
        nbformat.validate(notebook)
        cells = [c for c in notebook.cells if c.cell_type == 'code']
        baseline = snapshot['saved_notebook_baseline'][path.relative_to(ROOT).as_posix()]
        assert digest(path) == baseline['sha256'], path.name
        assert len(cells) == baseline['code_cells'] == baseline['executed_code_cells']
        assert all(c.execution_count is not None for c in cells)
        assert not any(o.output_type == 'error' for c in cells for o in c.get('outputs', []))
    for name in plan['existing_entrypoints']:
        assert (ROOT / name).is_file(), name
    assert plan['expected_primary'] == {'episodes': 36, 'policy_days': 756, 'llm_decisions': 252}
    assert plan['expected_native_plans'] == 19
    assert plan['disposable_clone_required'] and plan['full_tracked_tree_and_history_scan']
    assert plan['preserve_frozen_documents'] == ['docs/BENCHMARKS.md', 'docs/THIRD_PARTY.md']
    subprocess.run([sys.executable, str(ROOT / 'scripts/check_public_stage7.py')], check=True)
    if execution_present:
        subprocess.run([sys.executable, str(ROOT / 'scripts/check_public_stage8.py')], check=True)
        print('Historical Stage 8 preparation preserved; release execution verified separately.')
    else:
        print(f"Stage 8 preparation passed: {len(snapshot['files'])} pinned sources, 8 saved notebooks and 9 planned release gates. Release execution remains pending; no model calls or simulation runs.")


if __name__ == '__main__':
    main()
