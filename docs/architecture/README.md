# Architecture diagrams

This directory contains generated, reviewable views of the Tatparya backend architecture.

## Agent orchestration

- `tatparya-agent-flow.html` — interactive standalone diagram for presentation and exploration.
- `tatparya-agent-flow.workflow.json` — editable Archify workflow source used to regenerate the diagram.
- `tatparya-agent-flow.visual-check.json` — visual validation output for the generated diagram.

Open `tatparya-agent-flow.html` directly in a browser. Add `?present=1` to the file URL for presentation mode.

The written source of truth for agent responsibilities, contracts, fallbacks, and accuracy controls remains [`../../AGENT_PROCESS.md`](../../AGENT_PROCESS.md). Regenerate the diagram whenever that document or the workflow topology changes.
