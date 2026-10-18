"""Export hash-verified Stage 7 report inputs from reviewed aggregates; no experiments."""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.research.design import canonical_hash

PUBLIC = ROOT / 'docs/results/stage7'
REPORT = ROOT / 'report'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    path = Path(path)
    data = path.read_bytes()
    if path.suffix not in ('.pdf', '.png'):
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def verify_sources():
    snapshot = read(PUBLIC / 'source_snapshot.json')
    prep = read(PUBLIC / 'preparation.json')
    assert canonical_hash(snapshot) == prep['source_snapshot_sha256']
    for name, value in snapshot['files'].items():
        path = (ROOT / name).resolve()
        assert path.is_relative_to(ROOT) and digest(path) == value, name
    assert digest(PUBLIC / 'citation_register.json') == prep['citation_register_sha256']
    assert digest(PUBLIC / 'asset_plan.csv') == prep['asset_plan_sha256']
    assert read(ROOT / 'docs/results/stage6/status.json')['exit_gate_passed']
    return snapshot


def table(frame, headers=None, formats=None):
    frame = frame.copy()
    for column, fmt in (formats or {}).items():
        frame[column] = frame[column].map(lambda x: 'NA' if pd.isna(x) else fmt.format(x))
    if headers:
        frame = frame.rename(columns=headers)
    return frame.to_latex(index=False, escape=True, na_rep='NA', column_format='l' + 'r' * (len(frame.columns) - 1))


def expected_outputs():
    """Deterministic table/fact/bibliography outputs; used by the public integrity check."""
    directory = ROOT / 'docs/results/stage6'
    load = lambda name: pd.read_csv(directory / (name + '.csv'))
    e = load('episode_metrics')
    c = load('control_comparisons')
    n = load('native_task_coverage')
    r = load('native_reasoning')
    costs = load('llm_episode_reliability_costs')
    sensitivity = load('baseline_elasticity_summary')
    s = load('per_scenario_summaries')
    pair = load('paired_shock_contrasts')
    recovery = load('recovery')
    llm = e.query("policy == 'llm_with_fallback'")
    primary = pair.query("comparator == 'adaptive'")
    status = read(directory / 'status.json')
    b = status['budget_snapshot']
    scenario = dict(control='Control', demand_surge='Surge', demand_decline='Decline', delivery_disruption='Delay')
    policies = dict(fixed='Fixed', adaptive='Adaptive', llm_with_fallback='LLM + fallback')
    outputs = {}
    f = e[['store_id', 'scenario', 'policy', 'contribution', 'fill_rate', 'mean_closing_inventory', 'repair_days', 'fallback_days']].copy()
    f['scenario'] = f.scenario.map(scenario); f['policy'] = f.policy.map(policies); f['fill_rate'] *= 100
    outputs['tables/derived_episode_metrics.tex'] = table(f, dict(store_id='Store',scenario='Case',policy='Policy', contribution='Contribution',fill_rate='Fill (pct)',mean_closing_inventory='Stock',repair_days='Repair',fallback_days='Fallback'),
        dict(contribution='{:,.2f}',fill_rate='{:.2f}',mean_closing_inventory='{:.1f}'))
    f = c.copy(); f['comparator'] = f.comparator.map(policies)
    outputs['tables/derived_control_comparisons.tex'] = table(f.drop(columns='product_id'),
        dict(store_id='Store',comparator='Baseline',contribution_difference='Raw difference',relative_gain_percent='Gain (pct)',fill_rate_difference_pp='Fill diff. (pp)'),
        dict(contribution_difference='{:,.2f}',relative_gain_percent='{:.2f}',fill_rate_difference_pp='{:.2f}'))
    f = n[['task','status','validated_units']].copy()
    f['task'] = f.task.str.replace('firm:', '', regex=False).str.replace('retail:', 'Retail: ', regex=False)
    f['status'] = f.status.replace({'validated_complete':'Validated','deferred':'Deferred','failed':'Failed'})
    outputs['tables/derived_native_task_coverage.tex'] = table(f, dict(task='Task',status='Coverage',validated_units='Validated units'))
    f = r.copy(); f['task'] = f.task.str.replace('firm:', '', regex=False)
    f['native_counts'] = f.apply(lambda row: f'{int(row.native_correct_units)}/{int(row.native_scored_units)}' + (' labels' if row.native_accuracy_unit == 'entity_label' else ' cases'), axis=1)
    f['accuracy'] *= 100; f['exact_case_accuracy'] *= 100
    outputs['tables/derived_native_reasoning.tex'] = table(f[['task','native_counts','accuracy','exact_case_accuracy']],
        dict(task='Dataset',native_counts='Native correct / scored',accuracy='Native (pct)',exact_case_accuracy='Exact cases (pct)'),dict(accuracy='{:.1f}',exact_case_accuracy='{:.1f}'))
    f = costs[['matrix_index','physical_attempts','repair_attempts','input_tokens','output_tokens','cost_credits','median_latency_seconds','p95_latency_seconds']]
    outputs['tables/derived_llm_episode_reliability_costs.tex'] = table(f,
        dict(matrix_index='Position',physical_attempts='Calls',repair_attempts='Repair',input_tokens='Input tok.',output_tokens='Output tok.',cost_credits='Credits',median_latency_seconds='Med. s',p95_latency_seconds='P95 s'),
        dict(input_tokens='{:,.0f}',output_tokens='{:,.0f}',cost_credits='{:.6f}',median_latency_seconds='{:.2f}',p95_latency_seconds='{:.2f}'))
    deltas=[]
    for (store, product, case), group in sensitivity.groupby(['store_id','product_id','scenario'], sort=False):
        row=dict(Store=store, Case=scenario[case])
        for elasticity in (.75,1.5,2.25):
            cell=group.loc[group.elasticity == elasticity].set_index('policy')
            row[str(elasticity)] = cell.loc['adaptive','contribution'] - cell.loc['fixed','contribution']
        deltas.append(row)
    outputs['tables/derived_baseline_elasticity_summary.tex'] = table(pd.DataFrame(deltas),formats={str(x):'{:,.2f}' for x in (.75,1.5,2.25)})
    f = s[['scenario','comparator','raw_mean','control_adjusted_mean','control_adjusted_minimum','control_adjusted_maximum','control_adjusted_positive']].copy()
    f['scenario'] = f.scenario.map(scenario); f['comparator'] = f.comparator.map(policies)
    outputs['tables/derived_per_scenario_summaries.tex'] = table(f,
        dict(scenario='Case',comparator='Baseline',raw_mean='Raw mean',control_adjusted_mean='Adj. mean',control_adjusted_minimum='Adj. min',control_adjusted_maximum='Adj. max',control_adjusted_positive='Positive / 3'),
        {k:'{:,.2f}' for k in ('raw_mean','control_adjusted_mean','control_adjusted_minimum','control_adjusted_maximum')})
    family = read(directory / 'native_family_metrics.json')
    bytask = {x['task']:x for x in family}
    beer = bytask['firm:beergame']; consult = bytask['firm:consulting']; edt = bytask['firm:edt']
    rows=[]
    for episode in beer['episodes']:
        audit=next(a for a in beer['offline_saved_action_audit']['episodes'] if a['scenario_id']==episode['scenario_id'])
        rows.append(dict(Scenario=episode['opponent_policy'],Retailer=episode['total_cost_controlled'],Chain=episode['total_cost_supply_chain'],Bullwhip=episode['bullwhip_controlled'],Backlog=audit['derived_time_average_backlog_controlled']))
    outputs['tables/derived_native_family_metrics.tex'] = table(pd.DataFrame(rows),dict(Scenario='BeerGame opponent',Retailer='Retailer cost',Chain='Chain cost',Bullwhip='Bullwhip',Backlog='Mean backlog'),
        dict(Retailer='{:,.1f}',Chain='{:,.1f}',Bullwhip='{:.2f}',Backlog='{:.2f}'))
    ratios=[]
    for _, l in llm.iterrows():
        a=e.query('store_id == @l.store_id and scenario == @l.scenario and policy == "adaptive"').iloc[0]
        ratios.append(l.mean_closing_inventory / a.mean_closing_inventory)
    facts=dict(PrimaryEpisodes=len(e),PolicyDays=int(e.days.sum()),Decisions=int(llm.days.sum()),
        FirstPass=int(llm.days.sum()-llm.repair_days.sum()),RepairAttempts=int(llm.repair_days.sum()),
        RepairSuccess=int(llm.repair_days.sum()-llm.fallback_days.sum()),Fallback=int(llm.fallback_days.sum()),
        Invalid=int(llm.invalid_responses.sum()),PhysicalRequests=int(costs.physical_attempts.sum()),
        RawWins=int((primary.contribution_difference>0).sum()),AdjustedWins=int((primary.control_adjusted_contribution>0).sum()),
        FirstPassPct=100*(llm.days.sum()-llm.repair_days.sum())/llm.days.sum(),FallbackPct=100*llm.fallback_days.sum()/llm.days.sum(),
        PrimaryCost=float(costs.cost_credits.sum()),InitialRequestCost=float(costs.primary_cost_credits.sum()),RepairCost=float(costs.repair_cost_credits.sum()),
        Exposure=b['inclusive_project_exposure_credits'],KnownCost=b['known_project_cost_credits'],HeldCost=b['retained_unknown_charge_credits'],ProjectAttempts=b['total_project_attempts'],
        InputTokens=int(costs.input_tokens.sum()),OutputTokens=int(costs.output_tokens.sum()),SerialApiMinutes=float(costs.total_serial_api_seconds.sum()/60),
        InventoryRatioMin=min(ratios),InventoryRatioMax=max(ratios),LLMRecoveries=int(recovery.query("policy == 'llm_with_fallback'").recovered.sum()),
        AdaptiveRecoveries=int(recovery.query("policy == 'adaptive'").recovered.sum()),RecoveryCensored=int(recovery.right_censored.sum()),
        ConsultingOverall=consult['native_mean_judge_scores']['overall'],EDTEarnings=edt['synthetic_business_metrics']['accumulated_earnings'])
    for case,label in [('demand_surge','Surge'),('demand_decline','Decline'),('delivery_disruption','Delivery')]:
        cell=s.query('scenario == @case and comparator == "adaptive"').iloc[0]
        facts[label+'AdjustedMean']=float(cell.control_adjusted_mean)
        facts[label+'ServicePP']=float(cell.mean_fill_rate_difference_pp)
        fixed_cell=s.query('scenario == @case and comparator == "fixed"').iloc[0]
        facts[label+'FixedAdjustedMean']=float(fixed_cell.control_adjusted_mean)
        facts[label+'FixedRawMean']=float(fixed_cell.raw_mean)
    rendered=[]
    for key,value in facts.items():
        if key.endswith('Cost') or key in ('Exposure','KnownCost','HeldCost'): fmt='{:.9f}'
        elif key.endswith('Pct'): fmt='{:.1f}'
        elif key.endswith('Mean') or key.endswith('ServicePP') or key in ('ConsultingOverall','InventoryRatioMin','InventoryRatioMax'): fmt='{:,.2f}'
        elif key=='SerialApiMinutes': fmt='{:.2f}'
        else: fmt='{:,.0f}'
        rendered.append('\\newcommand{\\'+key+'}{'+fmt.format(value)+'}')
    outputs['tables/facts.tex']='% Generated from reviewed Stage 6 tables; see artifact_manifest.json.\n'+'\n'.join(rendered)+'\n'
    register=read(PUBLIC/'citation_register.json')
    entries=[]
    for citation in register['citations']:
        author=' and '.join(citation.get('authors',[])) or '{'+citation['attribution']+'}'
        note=citation.get('version','')
        if 'commit' in citation: note='Pinned commit '+citation['commit']
        if citation['kind']=='dataset': note='Version 8. Accessed 18 October 2026'
        entries.append('@misc{'+citation['key']+',\n  author = {'+author+'},\n  title = {{'+citation['title']+'}},\n'+
            ('  year = {'+str(citation['year'])+'},\n' if 'year' in citation else '')+
            '  howpublished = {\\url{'+citation['url']+'}},\n  note = {'+note+'}\n}')
    outputs['references.bib']='\n\n'.join(entries)+'\n'
    outputs['claim_map.csv']=(directory/'claim_map.csv').read_text(encoding='utf-8')
    sources=read(ROOT/'configs/sources.json')
    frozen=read(ROOT/'docs/results/study_design_manifest.json')['artifact_text_sha256']
    pins=[('RetailBench',sources['retailbench']['commit']),('FirmBench',sources['reference_repositories']['FirmBench']['commit']),
        ('ICBE',sources['reference_repositories']['ICBE']['commit']),('Dataset CSV',sources['dataset']['csv_sha256'])]
    for path in ['configs/study.json','prompts/kaggle_policy_v1.txt','prompts/kaggle_repair_v1.txt','configs/kaggle_action.schema.json']:
        assert digest(ROOT/path)==frozen[path],path
        pins.append((path,frozen[path]))
    lines=['\\begin{tabular}{lp{0.66\\linewidth}}','\\toprule Source & Commit / SHA-256 \\\\','\\midrule']
    for label,value in pins:
        label=label.replace('_','\\_')
        broken='\\allowbreak{}'.join(value[i:i+16] for i in range(0,len(value),16))
        lines.append(label+' & \\texttt{'+broken+'} \\\\')
    outputs['tables/source_pins.tex']='\n'.join(lines+['\\bottomrule','\\end{tabular}'])+'\n'
    return {name:text.encode('utf-8') for name,text in outputs.items()}, facts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-generated',action='store_true',help='Refresh generated assets only when previous manifest-bound copies remain intact.')
    args=parser.parse_args()
    snapshot=verify_sources()
    old=read(REPORT/'artifact_manifest.json') if (REPORT/'artifact_manifest.json').exists() else None
    outputs,facts=expected_outputs()
    provenance={name:dict(kind='generated',source='reviewed Stage 6 aggregates or Stage 7 citation register') for name in outputs}
    from src.analysis.report_figures import make_report_figures
    variants=make_report_figures(ROOT/'docs/results/stage6')
    outputs.update(variants)
    for name,source in [('figures/phase_report.pdf','docs/results/stage6/phase_summaries.csv'),
        ('figures/diagnostic_report.pdf','docs/results/stage6/diagnostic_traces.csv')]:
        provenance[name]=dict(kind='generated',presentation_variant=True,source=source,source_sha256=digest(ROOT/source),
            qualification='Same reviewed trace values; resized fonts/layout for report page scale. Original Stage 6 figures remain included unchanged.')
    with (PUBLIC/'asset_plan.csv').open(encoding='utf-8',newline='') as stream:
        assets=list(csv.DictReader(stream))
    for asset in assets:
        if asset['kind']!='copy': continue
        target=Path(asset['destination']).relative_to('report').as_posix()
        source=ROOT/asset['source']
        assert digest(source)==asset['source_sha256']
        outputs[target]=source.read_bytes()
        provenance[target]=dict(kind='copied',source=asset['source'],source_sha256=asset['source_sha256'])
    for name,data in outputs.items():
        destination=(REPORT/name).resolve()
        assert destination.is_relative_to(REPORT)
        if destination.exists() and destination.read_bytes().replace(b'\r\n',b'\n') != data.replace(b'\r\n',b'\n'):
            assert args.refresh_generated and provenance[name]['kind']=='generated' and old and digest(destination)==old['files'][name], name
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(data)
    manifest=dict(stage=7, source_preparation_commit='d694aa3',source_snapshot_sha256=canonical_hash(snapshot),
        hash_rule='SHA-256; text CRLF normalized to LF; PDF/PNG verbatim',
        rounding='Generated compact tables use 2 decimal places unless labeled; copied Stage 6 tables preserve their formatting, including 4-decimal contribution tables. Facts retain 9 cost decimals. Counts and source CSVs remain exact; calculations precede formatting.',
        files={name:digest(REPORT/name) for name in sorted(outputs)},provenance=provenance,
        numeric_facts={key:float(value) if not isinstance(value,int) else value for key,value in facts.items()})
    (REPORT/'artifact_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(f'Exported {len(outputs)} report assets from pinned evidence; no experiments or model calls.')


if __name__=='__main__': main()
