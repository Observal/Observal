# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Generate a timestamped OpenVEX document from static VEX statements."""

import json
import sys
from datetime import UTC, datetime


def main():
    source = ".github/vex/observal.vex.json"
    output = sys.argv[1] if len(sys.argv) > 1 else "observal.openvex.json"

    with open(source) as f:
        vex = json.load(f)

    vex["timestamp"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(output, "w") as f:
        json.dump(vex, f, indent=2)
        f.write("\n")

    print(f"Generated VEX document: {output} ({len(vex['statements'])} statements)")


if __name__ == "__main__":
    main()
