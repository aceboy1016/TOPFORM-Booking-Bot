"""Legacy diagnostic entrypoint; offline coverage lives in tests/."""
if __name__ == "__main__":
    raise SystemExit("Use python -m pytest -q for offline tests, or python scripts/check_connections.py --read-live for a read-only connection check.")
