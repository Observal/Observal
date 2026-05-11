# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Check ScanCode scan results for prohibited licenses."""

import json
import sys


def main():
    if len(sys.argv) != 2:
        print("Usage: check_license_policy.py <scan-results.json>")
        sys.exit(2)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    if "files" not in data or not isinstance(data["files"], list):
        print("::error::Unexpected ScanCode output format (no 'files' list)")
        sys.exit(2)

    violations = []
    restricted = []

    for resource in data.get("files", []):
        if not isinstance(resource, dict):
            continue
        policies = resource.get("license_policy", [])
        for policy in policies:
            if not policy:
                continue
            entry = {
                "path": resource["path"],
                "license": policy.get("license_key", "unknown"),
            }
            if policy.get("label") == "Prohibited License":
                violations.append(entry)
            elif policy.get("label") == "Restricted License":
                restricted.append(entry)

    if violations:
        print(f"::error::Found {len(violations)} prohibited license(s):")
        for v in violations:
            print(f"  - {v['path']}: {v['license']}")
        sys.exit(1)

    if restricted:
        print(f"::warning::Found {len(restricted)} restricted license(s) (requires review):")
        for r in restricted:
            print(f"  - {r['path']}: {r['license']}")

    file_count = len(data.get("files", []))
    print(f"License policy check passed ({file_count} files scanned)")


if __name__ == "__main__":
    main()
