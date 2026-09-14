"""Validate service configuration without printing any secret values."""
import json,sys

def check(config):
    containers=config.get('spec',{}).get('template',{}).get('spec',{}).get('containers',[])
    env={e['name']:e for e in containers[0].get('env',[])} if containers else {}
    required=('DATABASE_URL','ADMIN_API_TOKEN','CUSTOMER_SHEET_NAME','ADMIN_USER_ID','LINE_CHANNEL_SECRET','LINE_CHANNEL_ACCESS_TOKEN','GOOGLE_CREDENTIALS_JSON')
    missing=[key for key in required if key not in env or not (env[key].get('value') or env[key].get('valueFrom'))]
    if missing: raise ValueError('Missing environment variable names: '+', '.join(missing))
    url=env['DATABASE_URL'].get('value')
    if url and not url.startswith('postgresql+asyncpg://'): raise ValueError('Persistent PostgreSQL is required')

if __name__=='__main__':
    try: check(json.load(sys.stdin))
    except ValueError as exc: print(str(exc),file=sys.stderr);sys.exit(1)
