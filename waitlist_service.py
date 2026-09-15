"""Compatibility entry point for retired scheduler callers; performs no I/O."""
async def check_waitlist():
    return {'status':'disabled','reason':'waitlist_retired'}
