PY ?= python

.PHONY: setup dev seed test smoke self-check score clean

setup:
	$(PY) -m pip install -e ".[dev]"

dev:
	$(PY) -m uvicorn agentops_assessment.backend.app:app --reload --host 127.0.0.1 --port 8000

seed:
	$(PY) -m agentops_assessment.backend.seed

test:
	$(PY) -m pytest -q tests

smoke:
	$(PY) -m pytest -q tests/test_smoke.py

self-check:
	$(PY) scripts/self_check.py

score:
	$(PY) scripts/self_check.py

clean:
	$(PY) -c "import shutil; from pathlib import Path; [shutil.rmtree(p, ignore_errors=True) for p in [Path('.data'), Path('.assessment'), Path('.pytest_cache')]]"
