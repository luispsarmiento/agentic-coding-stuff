# Agentic Coding Stuff

Write each agent and skill once under the canonical `.agents/` layout, then
generate files for Claude Code, GitHub Copilot, OpenCode and Antigravity.

    .agents/agents/<id>/agent.md          # sub-agent (frontmatter + prompt)
    .agents/agents/<id>/scripts/          # optional scripts the agent bundles
    .agents/skills/<id>/SKILL.md          # skill (Agent Skills standard)
    .agents/skills/<id>/scripts|references|assets/   # optional skill bundle
    .agents/AGENTS.md                     # shared instructions (AGENTS.md)
    .agents/mcp.json                      # MCP servers ({ "mcpServers": ... })

This repository is both the harness content and the tooling (`harness.py`).

## Prerequisites
To use all this stuff, make sure you have:
- Python v3.9+
- Node JS v22.20+ (only for the optional `degit` bootstrap)

## Setup

Clone or degit the repo, then materialize the harness for a tool:

    npx degit luispsarmiento/agentic-coding-stuff harness
    python harness/harness.py sync -t opencode -o ./

`harness sync` reads the canonical `.agents/` from its **own** folder (not the CWD)
and, by default, adds `harness/` to `.git/info/exclude` so the tool folder does not
dirty your project. Pass `--harness-ignore track` to version it instead.

## Use it as a command (PATH)

Keep one copy of the tool (instead of `degit`-ing it per project) and run `harness`
from anywhere. The launchers live in `bin/`:

- Windows: add this repo's `bin\` to your PATH (it contains `harness.cmd`).

      setx PATH "%PATH%;C:\path\to\agentic-coding-stuff\bin"

- Unix: add `bin/` to PATH and make the launcher executable.

      chmod +x bin/harness
      export PATH="$PWD/bin:$PATH"   # add to ~/.bashrc / ~/.zshrc

Then:

    harness sync --all          # materialize the tool's .agents/ into the current project
    harness sync --where global # install user-wide (all projects)
    harness doctor

Because the tool is installed once, its `.agents/` is the canonical harness for every
project — you update it in one place instead of per repo.

## Profiles

A profile selects a subset of the harness. Drop `<name>.json` in `.agents/profiles/`:

    {
      "description": "review setup",
      "targets": ["claude", "opencode"],
      "agents": ["code-reviewer"],   // ids, or ["*"] / omit for all, [] for none
      "skills": [],                  // same rules
      "instructions": true,          // false disables AGENTS.md output
      "mcp": false                   // false disables mcp.json output
    }

    python harness.py profile                 # list profiles
    python harness.py sync --profile review
    python harness.py install <source> --profile review

Explicit CLI flags (`--all`/`--agents`/`--skills`/`-t`/`--no-*`) override the profile.

## Bundles and the .agents Hub

Package the canonical harness into a portable `.dotagents` archive (a tar.gz holding
`.agents/` plus a `bundle.json` manifest) and install it back anywhere:

    python harness.py bundle --name my-harness --version 1.0.0   # -> my-harness-1.0.0.dotagents
    python harness.py install ./my-harness-1.0.0.dotagents --where global

`install` accepts an `owner/repo`, a GitHub URL, a local directory, or a `.dotagents`
archive. Publishing to the public [.agents Hub](https://hub.dotagentsprotocol.com)
(draft) is on the roadmap; the bundle format is designed to map onto it.

## Install, update, uninstall

Install a harness from GitHub (or a local dir) into a project or your home, then
materialize it for the selected tools:

    python harness.py install luispsarmiento/agentic-coding-stuff --where project -t claude opencode
    python harness.py install ./my-harness --where global --git ignore
    python harness.py install owner/repo --ref v1.2.0 --path .agents

`install` copies the source `.agents/` into `<scope>/.agents`, materializes it and
records provenance (source, ref, path) in the lock. `update` re-fetches that source,
re-materializes, prunes files that disappeared and backs up any locally edited file
to `.agents/.backups/<ts>/` before overwriting:

    python harness.py update            # same source/ref as recorded
    python harness.py update --ref v1.3.0
    python harness.py status            # lock + drift after updating

`uninstall` removes the generated files (skipping locally edited ones unless
`--force`) and the ignore rules, keeping the canonical `.agents/` unless `--purge`:

    python harness.py uninstall
    python harness.py uninstall --purge

## Usage

    python harness.py install <source> [--ref vX] [--where ...] [-t ...]
    python harness.py update [--ref vX]     # re-fetch recorded source + materialize
    python harness.py uninstall [--purge]   # remove generated files + ignore rules
    python harness.py migrate      # a legacy flat dir of *.md -> .agents/agents/<id>/agent.md
    python harness.py sync --all   # materialize .agents/ to every target, no prompt
    python harness.py sync -t claude opencode
    python harness.py sync -t copilot -n    # dry run
    python harness.py sync --where global   # install user-wide (all projects)
    python harness.py status       # lock + drift of generated files
    python harness.py doctor       # validate the source
    python harness.py profile      # list profiles
    python harness.py bundle       # package .agents/ into a .dotagents archive
    make sync                               # == harness sync --all (non-interactive)
    make sync-select                        # == harness sync --select (interactive)
    make sync-global                        # == harness sync --where global
    make migrate                            # == harness migrate
    make status                             # == harness status
    make doctor                             # == harness doctor

`harness sync` forwards its arguments to the sync engine (`scripts/sync_agents.py`).
Its default source is the tool's own `.agents/` folder; a flat dir of `*.md` is still
supported via `-s <dir>`.

## Selecting agents

By default the script asks which subagent(s) to sync (interactive picker, same idea
as the skills package). In a non-interactive context (CI, `make sync`, pipes) it
falls back to syncing all of them.

    python harness.py sync --all                                # everything, no prompt
    python harness.py sync --agents code-reviewer test-writer   # agents by name
    python harness.py sync --skills csv-cleaner                 # skills by name
    python harness.py sync --select                             # force the picker

The picker accepts `a` (all), indexes (`1`, `1,3`), ranges (`1-3`) or names.
`--all`, `--agents` and `--select` are mutually exclusive; `--skills` can be combined
with `--agents`. With no selection flag, the picker covers subagents and all skills
are synced.

## Where to install (scope)

After choosing the subagents, the script asks where to install them. Each target
writes to its own path for the chosen scope, so `global` works per tool:

    python harness.py sync --where project   # current repo (default)
    python harness.py sync --where root      # git repository root
    python harness.py sync --where global    # user config, shared across projects

The choice is remembered in `.agents/.sync.json` (override anytime with `--where`).
`global` writes outside the repo, so git handling is skipped. In non-interactive runs
the default is `project`.

`project` and `root` differ only when you run from a subfolder (root = git top level).
Antigravity's workspace scope is the workspace root, so project and root coincide there.

## Lock, status and doctor

`harness sync` records every generated file (path + sha256) in a lockfile,
`.agents/.lock.json`, next to the canonical content:

    python harness.py status   # show the lock and any drift vs the generated files
    python harness.py doctor   # validate the source (frontmatter, scripts, ids)

`status` reports `ok` / `edited` (drift) / `missing` per file and exits non-zero when
anything drifted, so it is CI-friendly. `doctor` exits non-zero on invalid
frontmatter, missing bundled scripts or duplicate agent ids. The lock is written only
on a real (non `--dry-run`) sync.

## Git handling of generated files

    python harness.py sync --git track            # commit generated files (recommended)
    python harness.py sync --git ignore           # ignore locally (.git/info/exclude)
    python harness.py sync --git ignore --scope shared   # ignore via .gitignore
    python harness.py sync --git ask              # re-ask and overwrite saved choice

Without `--git`: uses the choice saved in `.agents/.sync.json`, otherwise asks
(interactive) or skips (non-interactive). Ignore mode writes exact file paths in a
managed block (never whole folders), so hand-written agents stay visible to git.
Ignoring does not untrack files already committed; the script warns and prints the fix.
Git handling applies only to `project`/`root`; `--where global` skips it.

## The harness tool folder

When you install the tool into a project (e.g. `degit ... harness`), that folder is
tooling, not project code. By default `harness sync` adds it to `.git/info/exclude`
in its own managed block and tells you, so it does not dirty the project:

    python harness.py sync --harness-ignore local    # default: .git/info/exclude
    python harness.py sync --harness-ignore shared   # add it to .gitignore instead
    python harness.py sync --harness-ignore track    # keep it versionable (no ignore)

This is the one deliberate exception to the "never whole folders" rule: the entire
tool folder is excluded (or not). It is never the project root itself.

## Source format

    ---
    name: my-agent
    description: When to use it (written as a trigger).
    claude.tools: Read, Grep          # only written to Claude Code
    copilot.tools: ['read', 'search'] # only written to Copilot
    opencode.temperature: 0.1         # only written to OpenCode
    ---
    System prompt in Markdown...

Keys without a prefix go to every target. OpenCode automatically gets `mode: subagent`.

Each target only accepts certain frontmatter fields, so a field that another tool
would reject is **dropped with a warning** (and flagged by `harness doctor`). In
particular, OpenCode needs `tools` as an object and `model` as `provider/model`, so
we do not emit `tools`/`model` for OpenCode yet — use prefixed keys:

| Key | claude | copilot | opencode |
|-----|--------|---------|----------|
| `name`, `description` | ✓ | ✓ | ✓ |
| `tools` / `model` | ✓ | ✓ | — (dropped) |
| `target`, `handoffs`, `argument-hint`, `infer` | — | ✓ | — |
| `mode`, `temperature`, `permission`, `color`, `steps`, `variant` | — | — | ✓ |

Keys are written to every target unless prefixed with `<target>.` (e.g.
`claude.tools`, `copilot.tools`, `opencode.permission`).

Agent targets are Claude Code, Copilot and OpenCode (they support sub-agents).
Antigravity is a **skills-only** target (see below).

## Skills

Skills follow the Agent Skills standard: a folder with a `SKILL.md` plus optional
`scripts/`, `references/` and `assets/`. The whole bundle is copied verbatim (the
`{{scripts_dir}}` placeholder, if present in `SKILL.md`, is resolved per target):

    .agents/skills/csv-cleaner/
    ├── SKILL.md
    ├── scripts/clean.sh
    └── references/guide.md

    python harness.py sync --all              # agents + skills
    python harness.py sync --skills csv-cleaner

| Target      | Repo skill dir                    | Global skill dir                              |
|-------------|-----------------------------------|-----------------------------------------------|
| claude      | `.claude/skills/<name>/`          | `~/.claude/skills/<name>/`                    |
| copilot     | `.github/skills/<name>/`          | `~/.copilot/skills/<name>/`                   |
| opencode    | `.opencode/skills/<name>/`        | `~/.config/opencode/skills/<name>/`           |
| antigravity | `.agents/skills/<name>/` (native) | `~/.gemini/config/skills/<name>/`             |

Antigravity reads `.agents/skills/` natively, so at workspace scope the canonical
location already is the target (nothing is copied); global scope copies to
`~/.gemini/config/skills/`.

## Script dependencies

An agent can bundle the scripts it needs with the `scripts:` key (comma or
space separated). The sync copies each file from the agent's bundle
(`.agents/agents/<id>/scripts/`); `--scripts-src` (default `scripts/`) is a shared
fallback. Scripts land in the target's script directory **at the same scope** as
the agent, including `--where global` — so global installs are not broken:

    ---
    name: my-agent
    description: ...
    scripts: git-branch-report.sh helper.sh
    claude.scripts: git-branch-report.sh   # optional: override per target
    ---
    Run `{{scripts_dir}}/git-branch-report.sh` to collect data.

`{{scripts_dir}}` in the body is replaced per target and scope. `scripts:` itself is
not written to the generated frontmatter. On Unix the copied scripts get the exec bit.

| Target      | Repo script dir                       | Global script dir                                   |
|-------------|---------------------------------------|-----------------------------------------------------|
| claude      | `.claude/scripts/`                    | `~/.claude/scripts/`                                |
| copilot     | `.github/scripts/`                    | `~/.copilot/scripts/`                               |
| opencode    | `.opencode/scripts/`                  | `~/.config/opencode/scripts/`                       |

Agents have no Antigravity target; for skills, scripts stay inside the bundle.

## Instructions (AGENTS.md)

Put shared project instructions in `.agents/AGENTS.md` (or `.agents/agents.md`). The
sync writes them to each tool's own file, at the same scope:

| Target      | Repo path                             | Global path                                |
|-------------|---------------------------------------|--------------------------------------------|
| claude      | `CLAUDE.md`                           | `~/.claude/CLAUDE.md`                       |
| copilot     | `.github/copilot-instructions.md`     | `~/.copilot/copilot-instructions.md`        |
| opencode    | `AGENTS.md` (read natively)           | —                                           |
| antigravity | `AGENTS.md` (read natively)           | —                                           |

`--no-instructions` disables this. OpenCode and Antigravity share the root `AGENTS.md`.

## MCP servers (mcp.json)

Put MCP servers in `.agents/mcp.json` (`{"mcpServers": {...}}`). The sync writes them
to the dedicated MCP config of each tool that uses the same schema:

| Target      | Repo path                     | Global path                                  |
|-------------|-------------------------------|----------------------------------------------|
| claude      | `.mcp.json`                   | — (user MCP lives in `~/.claude.json`)       |
| copilot     | `.mcp.json`                   | `~/.copilot/mcp-config.json`                 |
| opencode    | — (different schema)          | —                                            |
| antigravity | `.agents/mcp_config.json`     | `~/.gemini/config/mcp_config.json`           |

OpenCode stores MCP inside `opencode.json` with a different schema, so it is skipped;
`--no-mcp` disables MCP output entirely. `harness doctor` validates `mcp.json`.

## Output locations

Installed at a scope chosen with `--where`. Repo paths are relative to the repo root;
global paths live under your home directory.

**Agents** (Claude Code, Copilot, OpenCode):

| Target      | Repo path                             | Global path                                |
|-------------|---------------------------------------|--------------------------------------------|
| claude      | `.claude/agents/<name>.md`            | `~/.claude/agents/<name>.md`               |
| copilot     | `.github/agents/<name>.agent.md`      | `~/.copilot/agents/<name>.agent.md`        |
| opencode    | `.opencode/agents/<name>.md`          | `~/.config/opencode/agents/<name>.md`      |

**Skills** (all four): see the Skills table above.

Env overrides the tools honor (not set by this script): `CLAUDE_CONFIG_DIR`,
`COPILOT_HOME`, `OPENCODE_CONFIG_DIR`.

## Notes

- Do not edit generated files; edit `.agents/` and re-run.
- Git: use `--git` (above). Keep the Option A lines in `.gitignore` commented out; the script manages its own block.
- Parser is simple `key: value` per line. For multi-line YAML, switch to PyYAML.
- Verify each tool loads a trivial agent first; parsers can be stricter than docs.