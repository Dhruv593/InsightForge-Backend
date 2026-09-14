# Agent prompts

Edit `<agentname>_prompt.py` to change an LLM agent's instructions. Each starts with a role paragraph, followed by task, grounding, output, and constraint sections. Shared prompt-injection boundaries are in `common_prompt.py`. Retry guidance lives in `llm_recovery_prompt.py`.

Structured agents export `OUTPUT_MODEL` and `OUTPUT_SCHEMA`. Both reference the existing Pydantic schema instead of maintaining a second handwritten JSON definition. Providers still receive the model and apply their existing provider-specific schema conversion and validation. Analyst and statistical-validator interpretations intentionally remain plain text.

The profile interpreter, analytical tool selection and several fallback/report paths are deterministic code, not LLM calls; they have no artificial unused prompt. Updating an agent prompt affects that agent when invoked, not deterministic fallback behavior. No extra model calls were introduced.

Prompts are instructions, not a security or numeric-validation boundary. Existing schema checks, column validation, numeric grounding, evidence checks and fallback handling remain authoritative. Restart the backend after edits.
