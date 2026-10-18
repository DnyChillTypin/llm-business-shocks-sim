"""Seal a completed page-by-page review against the unchanged built Stage 7 PDF."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from check_public_stage7 import PUBLIC, verify_bundle
from export_report_assets import digest, read


def main():
    verified=verify_bundle(pdf_tools=True)
    review=read(ROOT/'results/verification/stage7/visual_review.json')
    assert review['status']=='passed' and review['pdf_sha256']==verified['pdf_sha256']
    assert review['page_count']==12 and [x['page'] for x in review['pages']]==list(range(1,13))
    for page in review['pages']:
        assert page['status']=='passed'
        assert digest(ROOT/f"results/verification/stage7/pages/page-{page['page']:02d}.png")==page['rendered_page_sha256']
    checks=dict(pinned_sources_and_all_12_planned_copies_unchanged=True,generated_numeric_tables_and_macros_reconciled=True,
        bibliography_matches_7_checked_citation_records=True,all_19_native_task_statuses_and_metric_units_preserved=True,
        fallback_and_censored_outcomes_retained=True,final_latex_log_has_no_overflows_or_undefined_references=True,
        all_12_pages_visually_inspected=True,report_text_and_page_geometry_verified=True,
        isolated_source_bundle_build_passed=True,isolated_pdf_bytes_match=True,publication_boundary_checked=True)
    status=dict(stage=7,status='complete',exit_gate_passed=True,completed_on='2026-10-18',preparation_commit='d694aa3',
        source_analysis_commit='4805b0d',report_pdf='report/main.pdf',report_pdf_sha256=verified['pdf_sha256'],report_pages=12,
        main_pages=8,appendix_pages=4,report_label='Preliminary technical report',source_bundle_files=31,
        native_coverage=dict(validated=14,failed=1,deferred=4),new_model_completion_calls=0,new_simulation_episodes=0,
        cumulative_project_exposure_credits=2.186206858,
        completion_boundary='Stage 7 report complete; original native scope incomplete and Stage 8 broader release/reproduction QC remains pending.',
        presentation_changes='Two page-sized chart variants use the same reviewed traces. Diagnostics moved to appendix; original 7 selected figure PDFs and 5 LaTeX tables retained unchanged.')
    qc=dict(stage=7,status='passed',exit_gate_passed=True,checks=checks,report_pages=12,exported_assets=26,
        copied_original_assets=12,citation_records=7,displayed_figures=6,source_bundle_files=31,new_model_completion_calls=0)
    write=lambda path,value: path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    write(PUBLIC/'status.json',status);write(PUBLIC/'qc_summary.json',qc);write(PUBLIC/'visual_review.json',review)
    build=read(ROOT/'report/build_manifest.json')
    names={'report/'+name for name in build['source_files']}|{'report/main.pdf','report/build_manifest.json'}
    names|={p.relative_to(ROOT).as_posix() for p in PUBLIC.iterdir() if p.name!='artifact_manifest.json'}
    write(PUBLIC/'artifact_manifest.json',dict(hash_rule='SHA-256; text CRLF normalized to LF; PDF/PNG verbatim',files={name:digest(ROOT/name) for name in sorted(names)}))
    print('Stage 7 completed evidence sealed to the unchanged, visually inspected PDF and source bundle.')


if __name__=='__main__': main()
