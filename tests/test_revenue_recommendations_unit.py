import unittest
from app.services.revenue_recommendations import revenue_recommendations


class RevenueRecommendationsTests(unittest.TestCase):
    def test_supported_comparison(self):
        result = revenue_recommendations([{"method": "groupby_aggregate", "operation": {"metric": "Revenue", "group_by": ["Region"]}, "result": [{"Region": "North", "value": 100}, {"Region": "East", "value": 20}]}])
        self.assertEqual(len(result), 1)
        self.assertIn("North", result[0])
        self.assertIn("Test a small improvement", result[0])

    def test_no_evidence_and_invalid_values(self):
        self.assertEqual(revenue_recommendations([]), [])
        self.assertEqual(revenue_recommendations([{"method": "correlation", "result": {"r": 0.99}}]), [])
