"""Allow OpenAI and Anthropic as analysis providers."""
from alembic import op

revision = "20260922_0015"
down_revision = "20260922_0014"
branch_labels = None
depends_on = None

PROVIDERS = "('gemini', 'groq', 'openai', 'anthropic')"


def upgrade() -> None:
    op.drop_constraint("ck_analysis_runs_provider", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_provider", "analysis_runs", f"llm_provider IN {PROVIDERS}")
    op.drop_constraint("ck_agent_runs_provider", "agent_runs", type_="check")
    op.create_check_constraint("ck_agent_runs_provider", "agent_runs", f"provider IN {PROVIDERS}")
    op.drop_constraint("ck_llm_settings_provider", "llm_settings", type_="check")
    op.create_check_constraint("ck_llm_settings_provider", "llm_settings", f"provider IN {PROVIDERS}")


def downgrade() -> None:
    op.execute("UPDATE llm_settings SET provider = 'gemini' WHERE provider IN ('openai', 'anthropic')")
    op.execute("UPDATE analysis_runs SET llm_provider = 'gemini' WHERE llm_provider IN ('openai', 'anthropic')")
    op.execute("UPDATE agent_runs SET provider = 'gemini' WHERE provider IN ('openai', 'anthropic')")
    op.drop_constraint("ck_analysis_runs_provider", "analysis_runs", type_="check")
    op.create_check_constraint("ck_analysis_runs_provider", "analysis_runs", "llm_provider IN ('gemini', 'groq')")
    op.drop_constraint("ck_agent_runs_provider", "agent_runs", type_="check")
    op.create_check_constraint("ck_agent_runs_provider", "agent_runs", "provider IN ('gemini', 'groq')")
    op.drop_constraint("ck_llm_settings_provider", "llm_settings", type_="check")
    op.create_check_constraint("ck_llm_settings_provider", "llm_settings", "provider IN ('gemini', 'groq')")
