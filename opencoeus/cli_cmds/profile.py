from __future__ import annotations

import sys

from ..db import AuditStore
from ..profiles import (
    create_profile,
    delete_profile,
    list_profiles,
    load_profile_by_name,
)


def run_profile(args) -> int:
    store = AuditStore()
    try:
        if args.profile_action == "list":
            profiles = list_profiles(store)
            if not profiles:
                print("No profiles saved.")
            for profile in profiles:
                print(f"  {profile.name}  root={profile.root_path}  extract_docs={profile.document_extraction}")
            return 0
        if args.profile_action == "create":
            created = create_profile(store, args.name, root_path=args.root)
            print(f"Created profile '{created.name}' (id={created.profile_id}).")
            return 0
        if args.profile_action == "delete":
            profile = load_profile_by_name(store, args.name)
            if profile is None:
                print(f"Error: Profile '{args.name}' not found.", file=sys.stderr)
                return 1
            delete_profile(store, profile.profile_id)
            print(f"Deleted profile '{args.name}'.")
            return 0
        if args.profile_action == "show":
            profile = load_profile_by_name(store, args.name)
            if profile is None:
                print(f"Error: Profile '{args.name}' not found.", file=sys.stderr)
                return 1
            print(f"Name: {profile.name}")
            print(f"Root: {profile.root_path}")
            print(f"Included: {profile.included_folders}")
            print(f"Excluded: {profile.excluded_folders}")
            print(f"Custom patterns: {profile.custom_protected_patterns}")
            print(f"Document extraction: {profile.document_extraction}")
            return 0
        return 0
    finally:
        store.close()
