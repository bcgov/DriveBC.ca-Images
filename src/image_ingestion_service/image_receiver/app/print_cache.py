# For testing to see the current state of the credential cache.
# To run this script, run `python -m app.print_cache` to print the entire cache,
# or `python -m app.print_cache <ID>` to print a specific entry by ID.

import sys
from app.auth import get_data_from_db, CREDENTIAL_CACHE

# Load the cache from the DB
get_data_from_db()

# Check for an optional ID argument
arg = sys.argv[1] if len(sys.argv) > 1 else None

if arg:
    try:
        target_id = int(arg)
        for entry in CREDENTIAL_CACHE:
            if entry.get("ID") == target_id:
                print(entry)
                break
        else:
            print(f"No entry found for ID: {target_id}")
    except ValueError:
        print("Please provide a numeric ID.")
else:
    # Print the whole cache
    for entry in CREDENTIAL_CACHE:
        print(entry)
