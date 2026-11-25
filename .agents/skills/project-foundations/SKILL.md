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

- Keep `.agents/agents.md` short, actionable, and structured.
- **Agent Memory Protocol (Mandatory First Step)**: Always instruct agents to consult `agent-memory` before all tasks, before making changes, and to record lessons after making changes.
- **Working Agreement**: Outline verifiable rules, minimal refactoring boundaries, and exact test execution commands.
- **Skills to load**: Provide an evidence-based roster of skills relevant to the project's technology and workflow.
- Add a memory only when it captures a stable, useful project fact. Use descriptive filenames and keep each note focused.
- Record exact commands only when verified from repository configuration, scripts, or documentation.
- Prefer references to source paths over copied explanations or duplicated documentation.
- Omit sections without evidence instead of filling a template with assumptions.
- Keep transient task notes in the current conversation, not project memory.

### Standard Template for `.agents/agents.md`

When creating or augmenting `.agents/agents.md`, follow this layout tailored with verified project facts:

```markdown
---
kind: agents
---

# [Project Name] Agent Guidelines

The authoritative project instructions live in the repository-root `AGENTS.md` (AGENTS.md standard).
Read it first. This file only adds agent-runtime notes.

## Agent Memory Protocol
- **Always check agent-memory first**: Query the project memory (`memory_search`, `graph_query`, notes, and specs) before planning or executing any task to inspect past decisions, lessons, and codebase maps.
- **Memory before and after changes**: Consult memory *before* making any change, and persist new architectural discoveries, ADRs, or lessons into memory *after* completing changes.
- **Never skip or bypass memory**: Always keep memory in the loop across all sessions.

## Working agreement
- Plan before coding on any change touching more than one module: state files to change, the port(s) involved, and the tests to add.
- Prefer the smallest change that satisfies the requirement. Do not refactor unrelated code.
- Run `<verified test/check command>` after each logical change and report the result honestly, including failures.
- If a requirement conflicts with an architecture rule in AGENTS.md, stop and propose an ADR instead of bending the rule.
- Never invent library APIs: read the installed package source or docs before using an unfamiliar API.

## Skills to load
- Architecture decisions & spec management: `spec-driven-development`
- Reviewing code quality & conventions before commits: `code-reviewer`
- Writing automated test coverage: `test-writer`
- Code graph & memory initialization: `graph-init`
```

## Boundaries

- Do not change application code, build configuration, or harness installation settings as part of this workflow.
- Do not edit generated tool-specific instruction files directly. `.agents/agents.md` is the canonical project instruction source; use the harness sync workflow to materialize it for supported tools.
- Do not store secrets, credentials, personal data, or sensitive operational details in instructions or memories.
- Do not claim a command or convention is verified unless you found evidence for it.