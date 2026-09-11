"""Offline tracing contract checks, without application/database startup."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core import tracing


class TracingTests(unittest.IsolatedAsyncioTestCase):
    def test_redaction_and_production_guard(self):
        payload = {"password": "secret", "note": "contact user@example.com https://private.example/data", "rows": [123]}
        preview = str(tracing._redact(payload))
        self.assertNotIn("user@example.com", preview)
        self.assertNotIn("private.example", preview)
        self.assertNotIn("123", preview)
        with patch.object(tracing, "get_settings", return_value=SimpleNamespace(langsmith_detail_mode=True, app_env="production")):
            self.assertFalse(tracing._details_enabled())

    async def test_nested_handoffs_and_recovery_outcome(self):
        from unittest.mock import Mock
        from uuid import uuid4
        runs = []

        def make_run(**kwargs):
            run = Mock()
            run.name = kwargs["name"]
            run.inputs = kwargs.get("inputs", {})
            run.events = []
            run.create_child.side_effect = make_run
            runs.append(run)
            return run

        @tracing.traced("stage.visualization")
        async def stage(state):
            await tracing.trace_event("statistics_unavailable", outcome="partial")
            await tracing.trace_event("visualization_fallback", outcome="completed_with_fallback")
            return {"chart_specs": [{"secret": "business-value"}]}

        @tracing.traced("analysis.request")
        async def root(analysis_run_id):
            return await stage({"accepted_claims": [1], "evidence": [1, 2], "dataset_profile": {}})

        settings = SimpleNamespace(langsmith_enabled=True, langsmith_project="offline", langsmith_detail_mode=False)
        with patch.object(tracing, "get_settings", return_value=settings), patch.object(tracing, "_client", return_value=Mock()), patch("langsmith.run_trees.RunTree", side_effect=make_run):
            await root(uuid4())
        self.assertEqual(len(runs), 2)
        runs[0].create_child.assert_called_once()
        handoffs = runs[1].inputs["handoffs"]
        self.assertEqual(handoffs[0]["from"], "critic")
        self.assertEqual(handoffs[0]["to"], "visualization")
        self.assertEqual(runs[0].end.call_args.kwargs["outputs"]["analysis_outcome"], "partial")
        self.assertNotIn("business-value", str(runs[1].end.call_args))
        self.assertIsNone(tracing._parent.get())
        self.assertIsNone(tracing._outcome.get())

    async def test_studio_topology_is_read_only(self):
        from app.graph.studio import graph
        from app.graph.topology import EDGES
        edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
        self.assertTrue(set(EDGES).issubset(edges))
        self.assertIn(("supervisor", "profile_interpreter"), edges)
        self.assertIn(("supervisor", "prepare_response"), edges)
        with self.assertRaisesRegex(RuntimeError, "Topology viewer only"):
            await graph.ainvoke({"user_query": "synthetic"})

    async def test_disabled_executes_once_without_sdk(self):
        calls = []

        @tracing.traced("test")
        async def operation():
            calls.append(1)
            return "result"

        with patch.object(tracing, "get_settings", return_value=SimpleNamespace(langsmith_enabled=False)), patch.object(tracing, "_client") as client:
            self.assertEqual(await operation(), "result")
            client.assert_not_called()
        self.assertEqual(calls, [1])

    async def test_export_failure_does_not_repeat_business_operation(self):
        calls = []

        @tracing.traced("test")
        async def operation():
            calls.append(1)
            raise ValueError("private business information")

        with patch.object(tracing, "get_settings", return_value=SimpleNamespace(langsmith_enabled=True)), patch.object(tracing, "_client", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(ValueError, "private business information"):
                await operation()
        self.assertEqual(calls, [1])
        self.assertIsNone(tracing._parent.get())

    def test_shape_does_not_expose_keys_or_values(self):
        self.assertEqual(tracing._shape({"secret-column": "secret-value"}), {"type": "dict", "count": 1})

    def test_completion_omits_content(self):
        from unittest.mock import Mock
        run = Mock()
        tracing._finish(run, {"password": "do-not-export"})
        self.assertNotIn("do-not-export", str(run.end.call_args))
        run.patch.assert_called_once()
