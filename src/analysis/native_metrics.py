"""Expose native reasoning metric units without conflating labels and cases."""
import ast
import math


def finer_label_counts(prediction, target):
    predicted = [p.lower().strip() for p in prediction.split(",")]
    expected = [p.lower().strip() for p in target.split(",")]
    predicted = (predicted + [""] * len(expected))[:len(expected)]
    correct = 0
    for guess, truth in zip(predicted, expected):
        # Audit saved outputs safely; never eval arbitrary model-generated code.
        try:
            equal = ast.literal_eval(guess.replace(",", "").replace("$", "")) == ast.literal_eval(truth)
        except (SyntaxError, ValueError, TypeError):
            equal = guess == truth
        correct += bool(equal)
    return correct, len(expected)


def reasoning_metric(task, score, records):
    numerator, denominator = score["correct"], score["total"]
    unit = "case"
    if task == "firm:finer":
        counts = [finer_label_counts(r["result"]["final_answer"], r["result"]["target"]) for r in records]
        numerator = sum(c for c, _ in counts)
        denominator = sum(n for _, n in counts)
        unit = "entity_label"
    if not denominator or not math.isclose(numerator / denominator, score["accuracy"], abs_tol=1e-12):
        raise ValueError("Audited metric denominator does not reconcile with the saved native scorer; inspect rather than relabel.")
    return {"native_accuracy_unit": unit, "native_correct_units": numerator, "native_scored_units": denominator,
            "exact_case_accuracy": score["correct"] / score["total"]}
