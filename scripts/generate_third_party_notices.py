# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Generate THIRD_PARTY_NOTICES.md from Python and Node.js dependency licenses."""

import json
import subprocess
import sys
from pathlib import Path


def _escape_md(text: str) -> str:
    """Escape pipe characters for markdown table cells."""
    return text.replace("|", "\\|")


def get_python_licenses() -> list[dict]:
    """Get Python dependency licenses via pip-licenses."""
    result = subprocess.run(
        [
            "uv",
            "run",
            "--with",
            "pip-licenses",
            "pip-licenses",
            "--format=json",
            "--with-urls",
            "--with-license-file",
            "--no-license-path",
        ],
        capture_output=True,
        text=True,
        cwd="observal-server",
    )
    if result.returncode != 0:
        print(f"Warning: pip-licenses failed: {result.stderr}", file=sys.stderr)
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Warning: pip-licenses output is not valid JSON", file=sys.stderr)
        return []


def get_node_licenses() -> list[dict]:
    """Get Node.js dependency licenses via license-checker-rspack."""
    format_path = str(Path(__file__).parent / "license-format.json")
    result = subprocess.run(
        [
            "pnpm",
            "dlx",
            "license-checker-rspack",
            "--json",
            "--production",
            "--customPath",
            format_path,
        ],
        capture_output=True,
        text=True,
        cwd="web",
    )
    if result.returncode != 0:
        print(f"Warning: license-checker failed: {result.stderr}", file=sys.stderr)
        return []
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Warning: license-checker output is not valid JSON", file=sys.stderr)
        return []
    packages = []
    for name, info in raw.items():
        packages.append(
            {
                "Name": name,
                "License": info.get("licenses", "Unknown"),
                "URL": info.get("repository", ""),
                "LicenseText": info.get("licenseText", ""),
            }
        )
    return packages


def generate_notices(python_pkgs: list[dict], node_pkgs: list[dict], output: str):
    """Write the combined THIRD_PARTY_NOTICES.md file."""
    from datetime import UTC, datetime

    with open(output, "w") as f:
        f.write("# Third-Party Notices\n\n")
        f.write("This file lists all third-party dependencies used by Observal,\n")
        f.write("along with their respective licenses.\n\n")
        f.write(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d')}\n\n")
        f.write("---\n\n")

        # Python dependencies
        f.write("## Python Dependencies (observal-server)\n\n")
        f.write("| Package | License | URL |\n")
        f.write("|---------|---------|-----|\n")
        for pkg in sorted(python_pkgs, key=lambda p: p.get("Name", "").lower()):
            name = _escape_md(pkg.get("Name", ""))
            license_name = _escape_md(pkg.get("License", "Unknown"))
            url = _escape_md(pkg.get("URL", ""))
            f.write(f"| {name} | {license_name} | {url} |\n")

        f.write("\n---\n\n")

        # Node.js dependencies
        f.write("## Node.js Dependencies (web)\n\n")
        f.write("| Package | License | URL |\n")
        f.write("|---------|---------|-----|\n")
        for pkg in sorted(node_pkgs, key=lambda p: p.get("Name", "").lower()):
            name = _escape_md(pkg.get("Name", ""))
            license_name = _escape_md(pkg.get("License", "Unknown"))
            url = _escape_md(pkg.get("URL", ""))
            f.write(f"| {name} | {license_name} | {url} |\n")

        f.write("\n---\n\n")

        # Apache NOTICE section
        f.write("## NOTICE (Apache-2.0 Licensed Dependencies)\n\n")
        f.write("The following dependencies are licensed under the Apache License 2.0.\n")
        f.write("As required by Section 4(d), their NOTICE files are reproduced below\n")
        f.write("where available.\n\n")

        apache_pkgs = [p for p in python_pkgs + node_pkgs if "apache" in p.get("License", "").lower()]
        for pkg in sorted(apache_pkgs, key=lambda p: p.get("Name", "").lower()):
            name = pkg.get("Name", "")
            license_text = pkg.get("LicenseText", "")
            f.write(f"### {name}\n\n")
            if license_text and license_text != "UNKNOWN":
                # Truncate very long license texts to just the NOTICE portion
                text = license_text[:2000] if len(license_text) > 2000 else license_text
                f.write(f"```\n{text}\n```\n\n")
            else:
                f.write("NOTICE file not available in package metadata.\n\n")

    print(f"Generated {output}")
    print(f"  Python packages: {len(python_pkgs)}")
    print(f"  Node.js packages: {len(node_pkgs)}")
    print(f"  Apache-2.0 packages with NOTICE: {len(apache_pkgs)}")


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "THIRD_PARTY_NOTICES.md"
    python_pkgs = get_python_licenses()
    node_pkgs = get_node_licenses()
    generate_notices(python_pkgs, node_pkgs, output)


if __name__ == "__main__":
    main()
