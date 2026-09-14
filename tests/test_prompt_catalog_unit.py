"""Offline prompt contracts: no model, API or database calls."""
import ast
import importlib
from pathlib import Path
import unittest


AGENTS = ("supervisor", "planner", "analyst", "statistical_validator", "claim_generator", "critic", "visualization", "report")


class PromptCatalogTests(unittest.TestCase):
    def test_prompts_have_role_sections_and_data_boundary(self):
        for name in AGENTS:
            with self.subTest(agent=name):
                module = importlib.import_module(f"app.prompts.{name}_prompt")
                self.assertTrue(module.SYSTEM_PROMPT.startswith("You are"))
                for heading in ("## Output", "## Constraints", "## Data safety"):
                    self.assertIn(heading, module.SYSTEM_PROMPT)

    def test_agent_instructions_are_imported_not_duplicated(self):
        for name in AGENTS:
            with self.subTest(agent=name):
                source = Path(f"app/agents/{name}.py").read_text()
                tree = ast.parse(source)
                imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
                self.assertIn(f"app.prompts.{name}_prompt", imports)
                self.assertNotIn('You are the ', source)

    def test_json_definitions_come_from_runtime_models(self):
        from app.schemas.supervisor import SupervisorDecision
        from app.schemas.analysis_plan import AnalysisPlanOutput
        from app.schemas.claim import ClaimGenerationOutput
        from app.schemas.claim_review import ClaimEvaluation
        from app.schemas.chart import VisualizationOutput
        from app.schemas.report import FinalReportOutput
        for name, model in zip(("supervisor", "planner", "claim_generator", "critic", "visualization", "report"), (SupervisorDecision, AnalysisPlanOutput, ClaimGenerationOutput, ClaimEvaluation, VisualizationOutput, FinalReportOutput)):
            with self.subTest(agent=name):
                module = importlib.import_module(f"app.prompts.{name}_prompt")
                self.assertIs(module.OUTPUT_MODEL, model)
                self.assertEqual(module.OUTPUT_SCHEMA, model.model_json_schema())
                self.assertIn("response_model=OUTPUT_MODEL", Path(f"app/agents/{name}.py").read_text())

    def test_interpretation_agents_remain_plain_text(self):
        for name in ("analyst", "statistical_validator"):
            source = Path(f"app/agents/{name}.py").read_text()
            self.assertIn("generate_text(", source)
            self.assertFalse(hasattr(importlib.import_module(f"app.prompts.{name}_prompt"), "OUTPUT_MODEL"))
