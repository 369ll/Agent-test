$ErrorActionPreference = "Stop"
py -m uvicorn agentops_assessment.backend.app:app --reload --host 127.0.0.1 --port 8000

