# Agentic Coding Stuff (Agencos)

Write each agent and skill once under the canonical `.agents/` layout, then
materialize and synchronize files for Claude Code, GitHub Copilot, OpenCode, and Antigravity.

```
.agents/agents/<id>/agent.md                  # sub-agent (frontmatter + prompt)
.agents/agents/<id>/scripts/                  # optional scripts the agent bundles
.agents/skills/<id>/SKILL.md                  # skill (Agent Skills standard)
.agents/skills/<id>/scripts|references|assets/ # optional skill bundle
.agents/AGENTS.md                             # shared instructions (AGENTS.md)
.agents/DESIGN.md                             # optional design principles & guidelines
.agents/mcp.json                              # MCP servers ({ "mcpServers": ... })
```

This repository contains both the harness content and the tooling (`agencos.py`, with `harness.py` maintained as a backward-compatible shim).

---

## Prerequisites
- Python v3.9+
- Node.js v22.20+ (only for the optional `degit` bootstrap)

---

## Setup & Quick Start

Clone or degit the repo, then materialize the harness for a tool:

```bash
npx degit luispsarmiento/agentic-coding-stuff agencos
python agencos/agencos.py sync -t opencode -o ./
```

`agencos sync` reads the canonical `.agents/` from its **own** folder (not the CWD)
and, by default, adds `agencos/` to `.git/info/exclude` so the tool folder does not
dirty your project. Pass `--harness-ignore track` to version it instead.

For project and repository-root installs, the first real `sync` also creates a
starter `.agents/` workspace with `agents/`, `memories/`, and `skills/` directories,
plus `agents.md` and an empty `mcp.json`. Existing files are left untouched.

---

## Use it as a command (PATH)

Keep one copy of the tool and run `agencos` (or `harness`) from anywhere. The launchers live in `cli/`:

- **Windows**: add this repo's `cli\` to your PATH (it contains `agencos.cmd` and `harness.cmd`).
  ```cmd
  setx PATH "%PATH%;C:\path\to\agentic-coding-stuff\cli"
  ```
- **Unix**: add `cli/` to PATH and make the launcher executable.
  ```bash
  chmod +x cli/agencos cli/harness
  export PATH="$PWD/cli:$PATH"   # add to ~/.bashrc / ~/.zshrc
  ```

Then:
```bash
agencos sync --all          # materialize the tool's .agents/ into the current project
agencos sync --where global # install user-wide (all projects)
agencos doctor
```

---

## Installation, Updates & Scoping

Install from GitHub, a local directory, or a `.dotagents` bundle:

```bash
python agencos.py install luispsarmiento/agentic-coding-stuff --where project -t claude opencode
python agencos.py install ./my-harness --where global --git ignore
python agencos.py install owner/repo --ref v1.2.0 --path .agents
```

### Installation Flags & Selective Setup
- **Select Subagents & Skills**:
  ```bash
  python agencos.py install <source> --agents code-reviewer test-writer --skills spec-driven-development
  ```
- **Custom User Assets**:
  Provide your own pre-prepared skills and agents folder to incorporate:
  ```bash
  python agencos.py install <source> --custom-dir ./my-custom-agents
  python agencos.py install <source> --custom-skills ./skills --custom-agents ./agents
  ```
- **Migrate Existing Project Specs & Memories**:
  ```bash
  python agencos.py install <source> --migrate-specs --with-memory
  ```
- **Import Existing `AGENTS.md` and `DESIGN.md`**:
  ```bash
  python agencos.py install <source> --import-instructions --import-design
  ```
  *(In interactive terminal mode, agencos will automatically ask you if it detects pre-existing `AGENTS.md`, `DESIGN.md`, or `specs/`)*.

### Update & Uninstall
```bash
python agencos.py update            # re-fetch source and re-sync
python agencos.py status            # lock + drift detection
python agencos.py uninstall         # remove generated files + ignore rules
python agencos.py uninstall --purge # also delete canonical .agents/
```

---

## Project Memory (User Data vs In-Repo)

Agencos connects your coding agents to persistent project memory (code graphs, notes, and specs) through the `memory` MCP tool:

```bash
agencos memory init            # scaffold layout, build graph, wire MCP server
agencos memory sync           # re-index code graph
agencos memory status         # show memory paths and status
agencos memory hook install   # post-commit hook for auto-sync
agencos memory backup         # git-commit the memory folder
```

### Memory Location Modes:
1. **User Data (Default)**:
   Keeps memory cleanly outside your project workspace under `~/agent-memory/<project-id>/`.
2. **In-Repo Workspace**:
   Store memory directly inside the project root (`.agents/memories/`):
   ```bash
   agencos memory init --root local
   # or on install:
   agencos install <source> --with-memory --memory-root local
   ```
   Stored in `.agent-profile.json` so tools automatically locate it.

### Layout:
```
~/agent-memory/ (or .agents/memories/)
├── <project-id>/
│   ├── graph/   # graphify / codegraph output (graph.json, GRAPH_REPORT.md)
│   ├── notes/   # decisions, architecture lessons
│   └── specs/   # feature plans, requirements, constitutions
├── _global/     # cross-project lessons
└── server.py    # stdio MCP server (memory_search, graph_query, spec_get, memory_save)
```

The `memory_search` MCP tool automatically searches across all sections: `notes/`, `specs/`, `graph/` (`graph.json` & markdown reports), and `_global/lessons/`.

---

## Profiles

A profile selects a subset of the harness. Place `<name>.json` in `.agents/profiles/`:

```json
{
  "description": "review setup",
  "targets": ["claude", "opencode"],
  "agents": ["code-reviewer"],
  "skills": [],
  "instructions": true,
  "mcp": false
}
```

```bash
python agencos.py profile                 # list profiles
python agencos.py sync --profile review
python agencos.py install <source> --profile review
```

---

## Bundles (.dotagents)

Package the canonical harness into a portable `.dotagents` archive:

```bash
python agencos.py bundle --name my-agencos --version 1.0.0
python agencos.py install ./my-agencos-1.0.0.dotagents --where global
```

---

## Git Handling (Tracking vs Ignoring)

When target files are generated (`.claude/`, `.github/`, `.opencode/`, etc.), `agencos` asks how git should treat them:

- **Track in repo (`--git track`)**: Keeps and commits them to git so teammates, CI, and cloud agents can use them.
- **Untrack / Ignore shared (`--git ignore --scope shared`)**: Adds them to `.gitignore` so no one commits generated files.
- **Untrack / Ignore locally (`--git ignore --scope local`)**: Adds them to `.git/info/exclude` (local only; keeps the repo diff clean).
- **Untrack existing tracked files (`--git-untrack`)**: Automatically runs `git rm --cached` on files currently tracked in git if you choose to ignore them.
- **Ignore directories (`--git-folders`)**: Ignores whole target directories (`/.claude/agents/`, etc.) instead of individual file entries.

---

## Output Locations

| Target      | Subagents                              | Skills                                | Instructions                          | MCP Config                          |
|-------------|----------------------------------------|---------------------------------------|---------------------------------------|-------------------------------------|
| claude      | `.claude/agents/<name>.md`             | `.claude/skills/<name>/`              | `CLAUDE.md`                           | `.mcp.json`                         |
| copilot     | `.github/agents/<name>.agent.md`       | `.github/skills/<name>/`              | `.github/copilot-instructions.md`     | `.mcp.json`                         |
| opencode    | `.opencode/agents/<name>.md`           | `.opencode/skills/<name>/`            | `AGENTS.md`                           | — (internal opencode.json)          |
| antigravity | — (skill/tool native)                  | `.agents/skills/<name>/` (native)     | `AGENTS.md`                           | `.agents/mcp_config.json`           |

---

## Makefile Shortcuts

```bash
make sync          # python agencos.py sync --all
make sync-select   # python agencos.py sync --select
make sync-global   # python agencos.py sync --all --where global
make status        # python agencos.py status
make doctor        # python agencos.py doctor
```
