import unittest
from app.services.deterministic_recommendations import deterministic_recommendations, revenue_recommendations


class RevenueRecommendationsTests(unittest.TestCase):
    def test_supported_comparison(self):
        result = revenue_recommendations([{"method": "groupby_aggregate", "operation": {"metric": "Revenue", "group_by": ["Region"]}, "result": [{"Region": "North", "value": 100}, {"Region": "East", "value": 20}]}])
        self.assertEqual(len(result), 1)
        self.assertIn("North", result[0])
        self.assertIn("Test one focused improvement", result[0])

    def test_non_revenue_metric_gets_domain_neutral_recommendation(self):
        result = deterministic_recommendations([{
            "method": "groupby_aggregate",
            "operation": {"metric": "Resolution_Hours", "group_by": ["Support_Team"]},
            "result": [{"Support_Team": "A", "value": 12}, {"Support_Team": "B", "value": 5}],
        }])

        self.assertEqual(len(result), 1)
        self.assertIn("resolution hours", result[0])
        self.assertIn("support team", result[0])

    def test_no_evidence_and_invalid_values(self):
        self.assertEqual(revenue_recommendations([]), [])
        self.assertEqual(revenue_recommendations([{"method": "correlation", "result": {"r": 0.99}}]), [])

    def test_fallback_formats_periods_at_the_calculated_granularity(self):
        for frequency, label in [("monthly", "October 2025"), ("quarterly", "Q4 2025"), ("yearly", "2025"), ("daily", "31 October 2025")]:
            with self.subTest(frequency=frequency):
                result = revenue_recommendations([{
                    "method": "time_series_aggregate",
                    "operation": {"metric": "Net_Revenue", "date_column": "Order_Date", "frequency": frequency},
                    "result": [{"Order_Date": "2025-10-31T00:00:00", "value": 200}, {"Order_Date": "2025-01-31T00:00:00", "value": 100}],
                }])
                self.assertIn(label, result[0])
                self.assertNotIn("T00:00:00", result[0])
