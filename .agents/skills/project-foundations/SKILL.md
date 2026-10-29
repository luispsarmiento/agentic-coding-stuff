---
name: project-foundations
description: "Use after installing agentic-coding-stuff in a project, or whenever asked to establish, review, or refresh project agent foundations. Inspect the repository and create evidence-based project instructions in .agents/agents.md and durable project notes in .agents/memories/."
---

# Project Foundations

Establish concise, evidence-based foundations for coding agents working in a project. Treat repository files as evidence, not as permission to invent project policies.

## Workflow

1. Confirm the repository root and inspect the existing `.agents/` workspace, including `agents.md`, `memories/`, and any existing instruction files. Preserve all existing content.
2. Build a focused evidence base from relevant project files: README or docs, manifests, source layout, test and build configuration, CI workflows, and contributor guidance. Inspect only what is needed to verify useful project facts.
3. Separate findings into:
   - **Project instructions** for `.agents/agents.md`: durable practices that should guide most coding tasks, such as verified test commands, architecture constraints, and contribution conventions.
   - **Memories** for `.agents/memories/`: concise, reusable project facts that help across sessions but do not belong in always-loaded instructions, such as a verified module map or domain vocabulary.
4. Distinguish verified facts from inferences. Mark uncertainty, and ask focused questions when missing information would materially change the guidance.
5. Present the proposed files and exact contents or changes before writing. Wait for user approval. Do not overwrite or merge existing content without approval.
6. After approval, create only the agreed files. For existing files, make the smallest approved additions and preserve unrelated content.
7. Report what was created or updated, the repository evidence supporting it, and any remaining questions.

## Content Guidelines

- Keep `.agents/agents.md` short and broadly applicable. Avoid duplicating generic agent behavior already supplied by the harness.
- Add a memory only when it captures a stable, useful project fact. Use descriptive filenames and keep each note focused.
- Record exact commands only when verified from repository configuration, scripts, or documentation.
- Prefer references to source paths over copied explanations or duplicated documentation.
- Omit sections without evidence instead of filling a template with assumptions.
- Keep transient task notes in the current conversation, not project memory.

## Boundaries

- Do not change application code, build configuration, or harness installation settings as part of this workflow.
- Do not edit generated tool-specific instruction files directly. `.agents/agents.md` is the canonical project instruction source; use the harness sync workflow to materialize it for supported tools.
- Do not store secrets, credentials, personal data, or sensitive operational details in instructions or memories.
- Do not claim a command or convention is verified unless you found evidence for it.