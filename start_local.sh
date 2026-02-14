#!/bin/bash
# Start local server with reload
# Usage: ./start_local.sh

source venv/bin/activate
uvicorn main:app --reload --port 8002
