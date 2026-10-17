"""Publication figures from saved native evaluation aggregates; no API calls."""
import json
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "docs/results/stage3"
OUTPUT = ROOT / "docs/assets/stage3"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cohorts = json.loads((PUBLIC / "evaluation_cohorts.json").read_text())
    by_task = {r["task"]: r for r in cohorts if r["status"] == "validated_complete" and r["scored_cases"] is not None}
    rows = list(by_task.values())
    if rows:
        fig, ax = plt.subplots(figsize=(10, 6))
        colors = ["#b87926" if row["task"] == "firm:factset" else "#315c86" for row in rows]
        labels = [r["task"].removeprefix("firm:") + (" (extension)" if r["task"] == "firm:factset" else "") for r in rows]
        ax.barh(labels, [r["accuracy"] for r in rows], color=colors)
        for position, row in enumerate(rows):
            ax.text(row["accuracy"] + .012, position, f"{row['native_correct_units']}/{row['native_scored_units']}", va="center", fontsize=10)
        ax.set(xlim=(0, 1.13), xlabel="Native scorer accuracy", title="Reasoning evaluation by dataset")
        ax.xaxis.set_major_formatter(PercentFormatter(1))
        ax.set_xticks([0, .2, .4, .6, .8, 1.0])
        ax.invert_yaxis()
        ax.spines[["top", "right"]].set_visible(False)
        fig.text(.02, .015, "Native units: entity labels for finer; cases for other datasets. One cohort each; substituted gateway model.", fontsize=9)
        fig.tight_layout(rect=(0, .04, 1, 1))
        fig.savefig(OUTPUT / "reasoning_accuracy.png", dpi=200)
        plt.close(fig)
    families = json.loads((PUBLIC / "family_metrics.json").read_text())
    icbe = next((r for r in reversed(families) if r["task"] == "icbe"), None)
    if icbe:
        grouped = defaultdict(lambda: [0., 0])
        phase_names = []
        for row in icbe["phase_metrics"]:
            phase = row["phase"]
            if phase not in phase_names:
                phase_names.append(phase)
            for actor in ("a", "b"):
                total = grouped[(row[f"model_{actor}"], phase)]
                total[0] += row[f"cooperation_rate_{actor}"] * row["rounds"]
                total[1] += row["rounds"]
        fig, ax = plt.subplots(figsize=(10, 5))
        for model in dict.fromkeys(key[0] for key in grouped):
            values = [grouped[(model, phase)][0] / grouped[(model, phase)][1] for phase in phase_names]
            ax.plot(range(1, len(phase_names) + 1), values, marker="o", linewidth=2, label=model)
        ax.set(xticks=range(1, len(phase_names) + 1), ylim=(-.03, 1.03), xlabel="Native market phase (25 rounds each)",
               ylabel="Cooperation rate", title="ICBE cooperation across changing payoff phases")
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.legend(fontsize=9)
        ax.spines[["top", "right"]].set_visible(False)
        fig.text(.02, .015, "100 decisions per model per phase; dependent rounds, one ordered match per pair. Output ceiling: 4,096 tokens.", fontsize=9)
        fig.tight_layout(rect=(0, .05, 1, 1))
        fig.savefig(OUTPUT / "icbe_phase_cooperation.png", dpi=200)
        plt.close(fig)
    print("Saved native evaluation figures from aggregate evidence.")


if __name__ == "__main__":
    main()
