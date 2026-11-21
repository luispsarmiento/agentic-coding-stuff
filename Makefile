migrate:
	python agencos.py migrate

sync:
	python agencos.py sync --all

sync-select:
	python agencos.py sync --select

sync-global:
	python agencos.py sync --all --where global

sync-claude:
	python agencos.py sync -t claude

sync-track:
	python agencos.py sync --git track

sync-ignore:
	python agencos.py sync --git ignore

sync-dry:
	python agencos.py sync -n

status:
	python agencos.py status

doctor:
	python agencos.py doctor

profile:
	python agencos.py profile

bundle:
	python agencos.py bundle

clean:
	rm -rf .claude/agents .github/agents .opencode/agents .agents/skills

.PHONY: migrate sync sync-select sync-global sync-claude sync-track sync-ignore sync-dry status doctor profile bundle clean
