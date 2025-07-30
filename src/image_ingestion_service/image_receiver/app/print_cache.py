# For testing to see the current state of the credential cache.
# To run this script, run `. /vault/secrets/secrets.env &&  python -m app.print_cache` to print the entire cache,
# or `. /vault/secrets/secrets.env &&  python -m app.print_cache <ID>` to print a specific entry by ID.

import sys
from app.auth import get_data_from_db, CREDENTIAL_CACHE

# Load the cache from the DB
get_data_from_db()

# Check for an optional ID argument
arg = sys.argv[1] if len(sys.argv) > 1 else None

if arg:
    record = CREDENTIAL_CACHE.get(arg) # Access by key
    if record:
        print(record)
    else:
        print(f"No entry found for ID: {arg}")
else:
    # Print the whole cache (values of the dict)
    for record in CREDENTIAL_CACHE.values():
        print(record)
