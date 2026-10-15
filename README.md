# Agentic Coding Stuff

Write each agent once in `agents-src/`, then generate files for Claude Code,
GitHub Copilot, OpenCode and Antigravity (skill fallback).

## Prerequisites
To use all this stuff, make sure you have:
- Python v3.15+
- Node JS v22.20+

## Setup

    npx degit luispsarmiento/agentic-coding-stuff/agents-src .agents/agents-src
    npx degit luispsarmiento/agentic-coding-stuff/scripts .agents/scripts
    python .agents/scripts/sync_agents.py -t opencode -s .agents/agents-src -o ./

## Usage

    python scripts/sync_agents.py                  # asks which subagent(s), all targets
    python scripts/sync_agents.py --all            # all subagents, no prompt
    python scripts/sync_agents.py -t claude opencode
    python scripts/sync_agents.py -t copilot -n    # dry run
    python scripts/sync_agents.py -t claude -o ~   # user-level (~/.claude/agents)
    make sync                                      # == --all (non-interactive)
    make sync-select                               # == --select (interactive)

## Selecting agents

By default the script asks which subagent(s) to sync (interactive picker, same idea
as the skills package). In a non-interactive context (CI, `make sync`, pipes) it
falls back to syncing all of them.

    python scripts/sync_agents.py --all                                # everything, no prompt
    python scripts/sync_agents.py --agents code-reviewer test-writer   # by name, no prompt
    python scripts/sync_agents.py --select                             # force the picker

The picker accepts `a` (all), indexes (`1`, `1,3`), ranges (`1-3`) or names.
`--all`, `--agents` and `--select` are mutually exclusive.

## Git handling of generated files

    python scripts/sync_agents.py --git track            # commit generated files (recommended)
    python scripts/sync_agents.py --git ignore           # ignore locally (.git/info/exclude)
    python scripts/sync_agents.py --git ignore --scope shared   # ignore via .gitignore
    python scripts/sync_agents.py --git ask              # re-ask and overwrite saved choice

Without `--git`: uses the choice saved in `agents-src/.sync.json`, otherwise asks
(interactive) or skips (non-interactive). Ignore mode writes exact file paths in a
managed block (never whole folders), so hand-written agents stay visible to git.
Ignoring does not untrack files already committed; the script warns and prints the fix.

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
Antigravity output keeps only `name` and `description`.

## Output locations

| Target      | Path                                  |
|-------------|---------------------------------------|
| claude      | .claude/agents/<name>.md              |
| copilot     | .github/agents/<name>.agent.md        |
| opencode    | .opencode/agents/<name>.md            |
| antigravity | .agents/skills/<name>/SKILL.md        |

## Notes

- Do not edit generated files; edit `agents-src/` and re-run.
- Git: use `--git` (above). Keep the Option A lines in `.gitignore` commented out; the script manages its own block.
- Parser is simple `key: value` per line. For multi-line YAML, switch to PyYAML.
- Verify each tool loads a trivial agent first; parsers can be stricter than docs.