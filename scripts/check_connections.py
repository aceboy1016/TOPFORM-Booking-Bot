"""Explicit read-only connection check. Never prints customer records."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read-live', action='store_true', required=True)
    parser.parse_args()
    from calendar_service import calendar_service
    from sheets_service import sheets_service
    try:
        snapshot = calendar_service.fetch_all_bookings()
        customers = sheets_service.fetch_customer_master()
        print('Calendar and customer sheet reads succeeded.')
        print(f'Calendar records: {len(snapshot.ishihara) + len(snapshot.ebisu) + len(snapshot.hanzoomon)}; customers: {len(customers)}')
    except Exception as exc:
        print(f'Connection check failed: {type(exc).__name__}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
