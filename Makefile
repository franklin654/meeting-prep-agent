# Demo tooling (T11). Run from the repo root. No docker commands live here.
# Every target runs from backend/ so the relative SQLite path resolves to backend/app.db.
#
#   make seed                # setup + ingest the 15 transcripts (resumable); stop the API first
#   make reset-demo-dry      # print the resolved DB path and bank id, change nothing
#   make reset-demo          # refuses (prints how to confirm); deletes nothing
#   make reset-demo RESET_ARGS='--confirm-bank ae-priya --confirm-db /abs/path/backend/app.db'

RESET_ARGS ?=
NAME ?=
RESTORE_ARGS ?=

.PHONY: seed reset-demo reset-demo-dry demo-snapshot demo-restore

seed:
	cd backend && uv run python ../data/scripts/seed.py

reset-demo:
	cd backend && uv run python ../data/scripts/reset_demo.py $(RESET_ARGS)

reset-demo-dry:
	cd backend && uv run python ../data/scripts/reset_demo.py --dry-run

demo-snapshot:
	cd backend && uv run python -m app.demo_tools snapshot --name "$(NAME)"

demo-restore:
	cd backend && uv run python -m app.demo_tools restore --name "$(NAME)" $(RESTORE_ARGS)
