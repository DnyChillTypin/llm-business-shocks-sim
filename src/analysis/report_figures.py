"""Page-sized presentation variants of existing Stage 6 traces; no new metrics."""
from io import BytesIO

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def make_report_figures(directory):
    outputs={}
    colors={'fixed':'#7e8a97','adaptive':'#008b98','llm_with_fallback':'#c75b30'}
    cases=[('S001','P0001'),('S004','P0006'),('S003','P0016')]
    scenarios=['control','demand_surge','demand_decline','delivery_disruption']
    phases=['pre_shock','shock','post_shock']
    phase=pd.read_csv(directory/'phase_summaries.csv')
    diagnostic=pd.read_csv(directory/'diagnostic_traces.csv').rename(columns={'episode_day':'day'})
    with plt.rc_context({'font.size':8,'axes.titlesize':9,'axes.labelsize':8,'xtick.labelsize':7,'ytick.labelsize':7,
        'legend.fontsize':8,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False}):
        fig,axes=plt.subplots(2,3,figsize=(6.8,3.55))
        labels=[c+p for c in ['C','U','D','L'] for p in ['0','1','2']]
        for col,(store,product) in enumerate(cases):
            group=phase.query('store_id == @store and product_id == @product')
            for policy,color in colors.items():
                f=group.query('policy == @policy').set_index(['scenario','phase'])
                for row,metric in enumerate(['contribution','fill_rate']):
                    values=[f.loc[(s,p),metric] for s in scenarios for p in phases]
                    if metric=='fill_rate': values=np.array(values)*100
                    axes[row,col].plot(range(12),values,color=color,lw=1.2,marker='o',ms=2,label=policy)
            axes[0,col].set_title(f'{store}/{product}')
            for row in (0,1):
                axes[row,col].set_xticks(range(12),labels,rotation=90)
                axes[row,col].grid(axis='y',alpha=.2)
                for x in (2.5,5.5,8.5): axes[row,col].axvline(x,color='#ddd',lw=.6)
                if row==1: axes[row,col].set_ylim(0,105)
        axes[0,0].set_ylabel('Contribution (dataset units)')
        axes[1,0].set_ylabel('Demand-weighted fill (%)')
        fig.legend(axes[0,0].lines[:3],['Fixed','Adaptive','LLM + fallback'],loc='lower center',ncol=3,frameon=False)
        fig.subplots_adjust(left=.105,right=.995,top=.93,bottom=.18,hspace=.48,wspace=.36)
        buffer=BytesIO();fig.savefig(buffer,format='pdf',metadata={'CreationDate':None,'ModDate':None});plt.close(fig)
        outputs['figures/phase_report.pdf']=buffer.getvalue()
        fig,axes=plt.subplots(2,3,figsize=(6.8,3.55))
        for row,(store,scenario) in enumerate([('S001','delivery_disruption'),('S004','demand_surge')]):
            f=diagnostic.query('store_id == @store and scenario == @scenario').sort_values('day')
            for col,metric in enumerate(['closing_inventory','order_quantity','price_multiplier']):
                axis=axes[row,col]
                axis.axvspan(8,14,color='#f3d99c',alpha=.28,lw=0)
                axis.plot(f.day,f[metric],color=colors['llm_with_fallback'],label='LLM shock + fallback')
                axis.plot(f.day,f['adaptive_shock_'+metric],color=colors['adaptive'],label='Adaptive shock')
                axis.plot(f.day,f['llm_control_'+metric],color='#888',ls='--',label='LLM control')
                fallback=f.loc[f.fallback_used]
                axis.scatter(fallback.day,fallback[metric],c='black',marker='x',s=17,zorder=5)
                axis.set_xticks([1,8,14,21]);axis.set_xlim(.5,21.5);axis.grid(axis='y',alpha=.2)
                axis.set_title(('S001 delay' if row==0 else 'S004 surge')+'\n'+['Closing stock','Order quantity','Price / reference'][col])
                axis.set_xlabel('Episode day')
        for row in (0,1):
            axes[row,0].set_ylabel('Units');axes[row,1].set_ylabel('Units');axes[row,2].set_ylabel('Multiplier')
        fig.legend(axes[0,0].lines[:3],['LLM shock + fallback','Adaptive shock','LLM control'],loc='lower center',ncol=3,frameon=False)
        fig.subplots_adjust(left=.10,right=.995,top=.88,bottom=.18,hspace=.85,wspace=.48)
        buffer=BytesIO();fig.savefig(buffer,format='pdf',metadata={'CreationDate':None,'ModDate':None});plt.close(fig)
        outputs['figures/diagnostic_report.pdf']=buffer.getvalue()
    return outputs
