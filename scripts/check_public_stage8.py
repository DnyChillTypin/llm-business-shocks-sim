"""Verify the preliminary release package; no credentials, simulations or model calls."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from check_public_stage2 import check
from export_report_assets import digest
from src.research.design import canonical_hash

PUBLIC=ROOT/'docs/results/stage8'
PREPARATION_FILES={'preparation.json','source_snapshot.json','gate_plan.csv'}
EXECUTION_FILES={'status.json','qc_summary.json','verification.json','environment.json',
    'citation_checks.json','privacy.json','artifact_manifest.json'}
RELEASE_FILES={'README.md','.github/workflows/tests.yml','configs/release/stage8.template.json',
    'docs/STAGE8_PREPARATION.md','docs/STAGE8_EXECUTION.md','docs/REPRODUCIBILITY.md',
    'docs/RELEASE_ATTRIBUTION.md','docs/results/release_checklist.md',
    'scripts/check_stage8_readiness.py','scripts/check_public_stage8.py','scripts/check_release_privacy.py',
    'tests/test_release_privacy.py'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf',action='store_true',help='Also run optional local PDF text/geometry checks.')
    args=parser.parse_args()
    status=read(PUBLIC/'status.json')
    complete=status['status']=='complete'
    assert complete or status['status']=='ready_for_ci'
    expected=PREPARATION_FILES|EXECUTION_FILES|({'ci_receipt.json'} if complete else set())
    assert {p.name for p in PUBLIC.iterdir()}==expected
    for path in PUBLIC.glob('*.json'):
        text=path.read_text(encoding='utf-8')
        check(json.loads(text))
        assert not re.search(r'\b[0-9a-f]{32}\b|\b20\d{6}T\d{12,}Z\b',text),path.name
    prep,snapshot=read(PUBLIC/'preparation.json'),read(PUBLIC/'source_snapshot.json')
    plan=read(ROOT/'configs/release/stage8.template.json')
    assert prep['status']==plan['status']=='prepared_not_executed'
    assert not prep['stage8_exit_gate_passed'] and not prep['release_executed'] and not plan['release_executed']
    assert canonical_hash(snapshot)==prep['source_snapshot_sha256']==status['source_snapshot_sha256']
    assert canonical_hash(plan)==prep['plan_sha256']
    assert len(snapshot['files'])==96
    for name,value in snapshot['files'].items():
        assert (ROOT/name).resolve().is_relative_to(ROOT) and digest(ROOT/name)==value,name
    for name,record in snapshot['saved_notebook_baseline'].items():
        assert digest(ROOT/name)==record['sha256'],name
    assert status['stage']==8 and status['local_release_qc_complete']
    assert status['exit_gate_passed']==complete
    assert status['tested_source_commit']=='0615016e823df125a045fcf67469c3c3164d66b9'
    assert status['report_pdf_sha256']==prep['report_pdf_sha256']==digest(ROOT/'report/main.pdf')
    assert status['native_coverage']==prep['native_coverage']==dict(validated=14,failed=1,deferred=4)
    assert status['original_native_scope_complete'] is False
    assert status['new_model_completion_calls']==status['new_paid_experiments']==status['new_primary_evaluation_episodes']==0
    assert status['cumulative_project_exposure_credits']==prep['cumulative_project_exposure_credits']==2.186206858
    verification=read(PUBLIC/'verification.json')
    records=verification['fresh_clone_commands']
    assert len(records)==48 and all(r['exit_code']==0 for r in records)
    labels={r['check'] for r in records}
    assert {f'notebook_{i:02d}' for i in range(1,9)} <= labels
    assert {f'native_plan_{i:02d}' for i in range(19)} <= labels
    assert verification['fresh_install']['credentials_present'] is False
    assert verification['research_tests']==dict(tests=98,failures=0,errors=0)
    assert verification['privacy_regression_tests']==dict(tests=2,failures=0,errors=0)
    assert verification['design_checks']==31 and verification['validation_episodes']==36
    notebooks=verification['notebooks']
    assert {n['notebook'] for n in notebooks}==set(snapshot['saved_notebook_baseline'])
    assert len(notebooks)==8 and all(n['error_outputs']==0 and n['executed_code_cells']==n['code_cells'] for n in notebooks)
    assert verification['dry_runs']==dict(native_plans=19,kaggle_matrix_episodes=36,kaggle_matrix_llm_decisions=252,single_llm_cell_decisions=21,paid_calls_authorized=False)
    audit=verification['private_audit']
    assert audit['status']=='passed' and audit['saved_action_replay_episodes']==36 and audit['replay_checks']==864
    assert audit['original_episode_evidence_unchanged'] and audit['ledger_and_allowance_unchanged'] and audit['gateway_clients_blocked']
    report=verification['report_rebuild']
    assert report['byte_identical'] and report['original_unchanged'] and report['report_pages']==12
    assert report['rebuilt_pdf_sha256']==status['report_pdf_sha256'] and report['source_files']==29
    privacy=read(PUBLIC/'privacy.json')
    assert privacy['status']=='passed' and privacy['findings']==[] and privacy['history_scanned'] and privacy['pdf_inspection']
    assert privacy['actual_local_value_comparison_performed'] and privacy['pdf_attachments']==0
    assert privacy['reachable_history_blobs']>=503 and privacy['tracked_files']>=331
    citations=read(PUBLIC/'citation_checks.json')
    register=read(ROOT/'docs/results/stage7/citation_register.json')
    assert citations['register_sha256']==digest(ROOT/'docs/results/stage7/citation_register.json')
    assert [r['key'] for r in citations['records']]==[r['key'] for r in register['citations']]
    assert len(citations['records'])==7 and all(r['verified'] for r in citations['records'])
    environment=read(PUBLIC/'environment.json')
    assert environment['research_environment']['python'].startswith('3.12.') and environment['research_environment']['system']=='Windows'
    assert all(set(p)=={'name','version'} for p in environment['research_environment']['packages'])
    assert not environment['complete_dependency_lock']
    qc=read(PUBLIC/'qc_summary.json')
    assert qc['all_local_checks_passed'] and all(qc['checks'].values())
    assert [g['gate'] for g in qc['gates']]==plan['required_gates']
    assert all(g['status']=='passed' for g in qc['gates'][:8])
    assert qc['gates'][8]['status']==('passed' if complete else 'local_pass_pending_ci')
    if complete:
        receipt=read(PUBLIC/'ci_receipt.json')
        assert receipt['status']=='completed' and receipt['conclusion']=='success'
        assert re.fullmatch('[0-9a-f]{40}',receipt['head_sha'])
        assert receipt['html_url']==f"https://github.com/DnyChillTypin/llm-business-shocks-sim/actions/runs/{receipt['id']}"
        assert status['reviewed_candidate_commit']==receipt['head_sha']
    manifest=read(PUBLIC/'artifact_manifest.json')
    expected_paths=set(snapshot['files'])|set(snapshot['saved_notebook_baseline'])|RELEASE_FILES
    expected_paths|={f'docs/results/stage8/{name}' for name in expected-{'artifact_manifest.json'}}
    assert set(manifest['files'])==expected_paths
    for name,value in manifest['files'].items():
        assert (ROOT/name).resolve().is_relative_to(ROOT) and digest(ROOT/name)==value,name
    for name in ['README.md','docs/REPRODUCIBILITY.md','docs/RELEASE_ATTRIBUTION.md','docs/STAGE8_EXECUTION.md','docs/results/release_checklist.md']:
        text=(ROOT/name).read_text(encoding='utf-8')
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',text):
            if '://' not in target and not target.startswith('#'):
                assert ((ROOT/name).parent/target.split('#')[0]).resolve().exists(),(name,target)
    readme=(ROOT/'README.md').read_text(encoding='utf-8')
    assert '2/9' in readme and '7/9' in readme and '108/252' in readme
    assert 'Primary Kaggle comparisons have not started' not in readme
    workflow=(ROOT/'.github/workflows/tests.yml').read_text(encoding='utf-8')
    assert 'scripts/check_public_stage8.py' in workflow and 'scripts/check_release_privacy.py' in workflow
    command=[sys.executable,str(ROOT/'scripts/check_public_stage7.py')]
    if args.pdf: command.append('--pdf')
    subprocess.run(command,check=True)
    print(f"Stage 8 release package passed: 98 research + 2 privacy tests, 8 notebooks, 36 saved replays, 19 native previews; status={status['status']}. Original native scope remains incomplete.")


if __name__=='__main__':
    main()
