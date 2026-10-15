sync:
	python scripts/sync_agents.py --all

sync-select:
	python scripts/sync_agents.py --select

sync-claude:
	python scripts/sync_agents.py -t claude

sync-track:
	python scripts/sync_agents.py --git track

sync-ignore:
	python scripts/sync_agents.py --git ignore

sync-dry:
	python scripts/sync_agents.py -n

clean:
	rm -rf .claude/agents .github/agents .opencode/agents .agents/skills

.PHONY: sync sync-select sync-claude sync-track sync-ignore sync-dry clean
