.PHONY: setup data train seed dev test smoke build api web meta-smoke
PY=.venv/bin/python
setup:
	python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r apps/api/requirements.txt && cd apps/web && npm install --silent
data:
	$(PY) scripts/fetch_uci.py
train:
	$(PY) scripts/train.py
seed:
	$(PY) scripts/seed_demo.py
api:
	cd apps/api && ../../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
web:
	cd apps/web && npm run dev -- --host
dev:
	@echo "API: http://localhost:8000  Web: http://localhost:5173"; ./scripts/dev.sh
test:
	cd apps/api && ../../$(PY) -m pytest -q && cd ../web && npm run typecheck
smoke:
	./scripts/smoke_test.sh
meta-smoke:
	$(PY) scripts/meta_live_smoke.py
build:
	cd apps/web && npm run build && cd ../.. && docker build -t thermomind . || echo "docker not available; web built to apps/web/dist"
