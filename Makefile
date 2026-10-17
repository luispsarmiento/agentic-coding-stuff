migrate:
	python harness.py migrate

sync:
	python harness.py sync --all

sync-select:
	python harness.py sync --select

sync-global:
	python harness.py sync --all --where global

sync-claude:
	python harness.py sync -t claude

sync-track:
	python harness.py sync --git track

sync-ignore:
	python harness.py sync --git ignore

sync-dry:
	python harness.py sync -n

status:
	python harness.py status

doctor:
	python harness.py doctor

profile:
	python harness.py profile

bundle:
	python harness.py bundle

clean:
	rm -rf .claude/agents .github/agents .opencode/agents .agents/skills

.PHONY: migrate sync sync-select sync-global sync-claude sync-track sync-ignore sync-dry status doctor profile bundle clean
