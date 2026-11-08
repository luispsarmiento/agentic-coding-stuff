---
name: spec-driven-development
description: Guides a coding agent (or the user) through Spec-Driven Development (SDD) - writing a project "constitution" (mission, tech stack, roadmap), then planning, implementing, validating and replanning each feature from persistent spec files instead of ad-hoc "vibe coding" chats. Use this skill whenever the user wants to start a new project or feature with specs, mentions SDD, spec-driven, specs, constitution, mission.md, techstack.md, roadmap.md, feature plan/requirements/validation, Spec Kit, OpenSpec, or wants to reverse-engineer specs from an existing (brownfield) codebase. Also use it when the user asks for a structured way to build features with Claude Code or other coding agents, to avoid context decay, or to review/replan between features - even if they never say "SDD".
---

# Spec-Driven Development (SDD)

The agent is the muscle; the spec is the brain. The human acts as architect and supervisor: they own the **what and why** (the spec), and the agent owns the **how** (the implementation). Specs live in the repo as markdown, so they survive across sessions, agents and IDEs.

## Why this works (use it to justify decisions to the user)

1. **Downstream amplification** - one line changed in a spec (SQLite -> MongoDB, a design token) becomes hundreds of lines of correct code changes with little cognitive load.
2. **No context decay** - agents are stateless and long chats get polluted. Specs are a clean, durable anchor for every new session.
3. **Intent fidelity** - goals, constraints and success criteria written up front stop the model from guessing architecture.

"Vibe coding" (loose prompts, no saved artifacts) produces disposable code and cognitive debt. SDD trades a little upfront thinking for speed and reliability later: run slow to run fast.

## Step 0 - Detect where the user is

Check the repo before doing anything:

- No `specs/` (or equivalent) folder -> **Phase A: Constitution**.
- Constitution exists, user wants a new feature -> **Phase B: Feature loop**.
- Feature just merged, or global decisions changed -> **Phase C: Replan**.
- Existing code but no specs (brownfield) -> **Phase A, reverse-engineer mode**.

State which phase you are entering in one line, then proceed.

## Phase A - Constitution (project level)

Create three files under `specs/` (or the folder the project already uses). Draft them by **interviewing the user**, a few questions at a time, rather than inventing content.

| File | Pillar | Covers |
|---|---|---|
| `mission.md` | Why | Product vision, audience, tone, scope, non-goals, business goals |
| `techstack.md` | How & constraints | Languages, framework versions, database, styling tools, strictness settings (e.g. strict TypeScript), conventions, architectural trade-offs |
| `roadmap.md` | Phases | Small, ordered phases, each implementable as one feature |

Guidelines:
- Keep roadmap phases granular enough to finish in one feature branch. If a phase feels big, split it.
- Record trade-offs and rejected options in `techstack.md`; they stop the agent from re-litigating them later.
- Templates are in `references/templates.md`.

**Brownfield / legacy projects:** do not interview from scratch. Explore the code, commit history, `README.md`, `TODO.md` and the issue tracker, draft the three files from what you find, then ask the user to correct and fill gaps. Mark anything inferred as "inferred - confirm".

Commit the constitution before any feature work.

## Phase B - Feature loop

```
clean branch -> 1. Plan -> 2. Implement -> 3. Validate & review -> merge -> Phase C
```

### 1. Plan the feature
1. **Isolate**: create a dedicated git branch (e.g. `feature/<name>`). Ask before creating it if the user did not say.
2. **Fresh context**: recommend the user clear the session (`/clear` in Claude Code) so work is anchored in the specs, not stale chat. Then read `mission.md`, `techstack.md` and `roadmap.md`.
3. **Spec interview**: pick the next roadmap item (or the user's feature), interview the user, and generate three files in `specs/features/<date>-<feature-name>/`:
   - `plan.md` - task groups; each group is small and independently committable.
   - `requirements.md` - technical needs, constraints, user flows. Stay at the level of behaviour; leave out micro-details like variable names.
   - `validation.md` - scorecard: concrete criteria and the exact checks/commands that prove the feature is done.
4. **Human review**: the user reviews the three files. Apply requested changes **through you**, so plan, requirements and validation stay consistent with each other. Commit the specs before writing code.

### 2. Implement
- Work one task group at a time from `plan.md`, reading the specs first.
- For sensitive areas (database schemas, auth, migrations, payments) implement and commit **one task group at a time** and pause for review between groups. For low-risk work, several groups per pass is fine.
- Narrate progress briefly so the user can supervise live. If something in the spec is ambiguous or wrong, stop and propose a spec change instead of silently improvising.
- Tick off finished tasks in `plan.md`.

### 3. Validate and review
Work through `validation.md` with the user:
- **High-level first**: does the diff fit the architecture, are components extracted sensibly, does it match the spec? Only then drill into details.
- **Avoid silent drift**: if the user refactors or moves files by hand in their IDE, ask them to tell you, then update affected specs, docs and references.
- **Run tests and step through the main flow under a debugger** (or guide the user to) so the code is understood, not just accepted. This is the defence against cognitive debt.
- **Sub-agent audit**: where sub-agents are available, spawn one to audit the changed code against the feature specs and report back, so the main context stays small. Without sub-agents, do the audit as a separate, explicit pass.
- **Changelog**: update `CHANGELOG.md` (or the project's equivalent) so stakeholders stay aligned, then merge.

## Phase C - Replan between features

Do not jump straight into the next feature. On a short `replan/<topic>` branch:

- **Update the constitution** if global decisions changed (added a test framework, mobile responsiveness, new conventions). Propagate the change to earlier feature specs where it matters.
- **Revisit `roadmap.md`**: merge small related items, add newly discovered scope, reorder based on what was learned.
- **Research backlog**: if a different architecture or approach came up mid-feature, write it to `specs/backlog/<topic>.md` as a short research note instead of derailing current work.

## Scaling and automation (suggest when relevant, don't push)

- Repeated workflows (feature spec drafting, changelog generation, validation checks) are good candidates for their own agent skills. Calling a skill explicitly by name saves context tokens.
- Prefer lightweight CLI tools plus a skill (for example Context7 for fetching library docs) over heavy MCP servers when both would work, to cut context overhead.
- Existing frameworks cover this workflow if the user wants something off the shelf: GitHub **Spec Kit**, and **OpenSpec** (propose, explore, apply, archive).
- Keep the workflow portable: specs are plain markdown, so the user can switch IDEs and agents (Claude Code, Codex, OpenCode; editors via Agent Client Protocol) without losing them.

## Per-task checklist

Offer this when starting or closing a feature:

- [ ] Previous branch merged and session cleared (no context rot)
- [ ] Working on a dedicated branch
- [ ] Plan, requirements and validation produced via interview
- [ ] Code changes and spec docs are in sync
- [ ] Verified: tests run, debugger walkthrough, sub-agent audit
- [ ] Roadmap and changelog updated before the next feature

## Behaviour rules

- Interview before writing specs; ask a few focused questions at a time and propose sensible defaults the user can accept.
- Never start implementation without committed, user-reviewed specs. If the user insists on skipping, say what risk they take and offer a minimal one-page spec instead.
- Keep specs short and skimmable; a spec nobody reads is no better than no spec.
- When the user's request conflicts with the constitution, point it out and ask whether to change the code or update the constitution.
- Write spec files in the language the user works in unless the project already uses another.