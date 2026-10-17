import unittest

from src.analysis.native_metrics import finer_label_counts, reasoning_metric


class NativeMetricTests(unittest.TestCase):
    def test_finer_label_accuracy_is_distinct_from_whole_case_accuracy(self):
        records = [{"result": {"final_answer": "a,wrong", "target": "a,b"}},
                   {"result": {"final_answer": "c", "target": "c"}}]
        result = reasoning_metric("firm:finer", {"correct": 1, "total": 2, "accuracy": 2/3}, records)
        self.assertEqual(result["native_accuracy_unit"], "entity_label")
        self.assertEqual(result["native_correct_units"], 2)
        self.assertEqual(result["native_scored_units"], 3)
        self.assertEqual(result["exact_case_accuracy"], .5)
        with self.assertRaises(ValueError):
            reasoning_metric("firm:finer", {"correct": 1, "total": 2, "accuracy": .5}, records)

    def test_missing_and_extra_labels_follow_the_native_denominator(self):
        self.assertEqual(finer_label_counts("A", "a,b"), (1, 2))
        self.assertEqual(finer_label_counts("A,B,extra", "a,b"), (2, 2))
