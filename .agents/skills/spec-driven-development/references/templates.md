# SDD Templates

Copy and adapt. Delete sections that do not apply; shorter is better.

## specs/mission.md

```markdown
# Mission

## Vision
One or two sentences: what this product is and why it exists.

## Target audience
Who uses it, and what problem it solves for them.

## Scope
- In scope: ...
- Non-goals: ...

## Tone and principles
(Product voice, UX principles, quality bar.)

## Business goals
(What success looks like.)
```

## specs/techstack.md

```markdown
# Tech Stack

## Languages and frameworks
(Name + version for each.)

## Data
(Database, migrations approach.)

## Styling / UI
(CSS tooling, design tokens, component library.)

## Tooling
(Package manager, linting, formatting, test framework, strictness settings.)

## Conventions
(Folder structure, naming, error handling, commit style.)

## Decisions and trade-offs
| Decision | Chosen | Rejected | Why |
|---|---|---|---|
```

## specs/roadmap.md

```markdown
# Roadmap

Each phase should fit one feature branch.

## Phase 1 - <name>
Goal:
Done when:

## Phase 2 - <name>
...
```

## specs/features/<date>-<name>/plan.md

```markdown
# Plan: <feature>

## Task group 1 - <name>
- [ ] Task
- [ ] Task

## Task group 2 - <name>
- [ ] Task
```

## specs/features/<date>-<name>/requirements.md

```markdown
# Requirements: <feature>

## Goal
## User flows
## Technical requirements
## Constraints (from techstack.md and this feature)
## Out of scope
## Open questions
```

## specs/features/<date>-<name>/validation.md

```markdown
# Validation: <feature>

## Scorecard
| # | Criterion | How to check | Status |
|---|---|---|---|
| 1 | | command or manual step | |

## Review notes
(High-level fit, drift found, follow-ups.)
```

## Interview starters

- Constitution: "Who is this for and what must it never become?", "Which languages/versions are fixed, and which are open?", "What is the smallest slice that would be useful?"
- Feature: "What does done look like for a user?", "What must not break?", "Any data, auth or migration risk?", "How will we prove it works?"