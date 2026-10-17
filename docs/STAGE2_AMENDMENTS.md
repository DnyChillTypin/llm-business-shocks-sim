# Stage 2 validation amendments

These changes precede all full native evaluations and primary Kaggle calls. The
Stage 1 frozen files and vendor sources remain unchanged. Failed pilot cohorts
remain visible; they are not overwritten or reclassified as successful.

## Allowance and bounded unknown charges

User instruction: “ok ill raise the limit to $2, go finish stage 2”. We interpret
this as a **$2 total** gateway-credit pilot cap inclusive of earlier usage and held
charges, with the original 250-client-attempt ceiling. Native allocation is $1.50;
Kaggle validation allocation is $0.50. Full evaluation remains unauthorized.

The existing ledger is amended transactionally, with both old/new manifests
retained. A known bounded failed request can carry its **entire original reserve**
against the allowance while remaining `uncertain`: no actual tokens or bill are
invented and no reserved amount is released. This applies to the original HTTP
503, cancellation of an in-flight paired ICBE request, and a 90-second transport
timeout in the first Kaggle control pilot. Token-envelope breaches,
unexplained missing usage and unapproved failure classes still block new calls.
Each carried request has its own approval/explanation entry. The monetary limit
remains conditional on the verified tariff and gateway token ceilings.

## ICBE output compatibility, cohort 2

The first ICBE pilot failed at the upstream **150-token** output limit:
the returned GPT-4o-mini response ended with `finish_reason=length` before an
explicit decision. The paired GPT-4.1-mini request was canceled; its charge is
unknown and its full reserve remains counted. Neither request is a scored choice.

The adapter now uses the configured **4,096-token output ceiling** for ICBE. This
is a documented local output-budget compatibility change, not an exact native
generation-setting reproduction. The native prompts, temperature, models,
payoffs, opponent-history window, ordered pairs, phase boundaries and evaluation
100-round horizon remain unchanged. The pilot still uses two rounds per pair.
New artifacts and cost measurements form a separate cohort. Future evaluation
must use and disclose the same adapter, not pool it with the failed 150-token
pilot as if their methods were identical.

Parsing additionally requires one unambiguous `DECISION: OPTION A/B` choice;
mentioning both options in reasoning cannot become a fabricated decision. No
cooperation/default substitution is allowed. A truncated completion still fails.

## Kaggle fallback review

The two complete 21-day validation episodes had 15 repairs and three explicit
fallbacks (7.1% of decisions), triggering the frozen review rule. The saved review
recomputed every invalid response's purchase cost against the same observation's
cash. Overruns were material, not numerical tolerance errors. It also verified
that all fallback actions exactly matched the frozen adaptive policy and that
cash/inventory/contribution reconciled.

The review retains the frozen operational policy and requires reporting its
first-pass validity, repairs, unassisted completion, fallbacks and costs. This
records negative model behavior without tuning it away. No system/repair prompt,
model, observation contract, action schema, test window or comparator changed.
The 5% threshold triggers review; it is not a license to discard fallback days.
Review records include action-file hashes. Separate evaluation budget approval
is still required before any primary comparison.
