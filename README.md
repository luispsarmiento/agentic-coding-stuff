# Agents Sync Kit

Write each agent once in `agents-src/`, then generate files for Claude Code,
GitHub Copilot, OpenCode and Antigravity (skill fallback).

## Usage

    python scripts/sync_agents.py                  # all targets
    python scripts/sync_agents.py -t claude opencode
    python scripts/sync_agents.py -t copilot -n    # dry run
    python scripts/sync_agents.py -t claude -o ~   # user-level (~/.claude/agents)
    make sync

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
