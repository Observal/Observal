#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

# check_secrets.sh — pre-commit guard against .env files and hardcoded secrets
set -euo pipefail

RED='\033[0;31m'
NC='\033[0m'
EXIT_CODE=0

# 1. Block .env files (allow .env.example)
env_files=$(git diff --cached --name-only --diff-filter=ACR | grep -E '(^|/)\.env$' || true)
if [ -n "$env_files" ]; then
    echo -e "${RED}ERROR: .env file(s) staged for commit:${NC}"
    echo "$env_files"
    echo "These files contain secrets and must not be committed."
    EXIT_CODE=1
fi

# 2. Scan staged file contents for common secret patterns
patterns=(
    'AKIA[0-9A-Z]{16}'                          # AWS access key ID
    'aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}'  # AWS secret key
    'sk-[A-Za-z0-9]{20,}'                       # OpenAI / Anthropic style API keys
    'ghp_[A-Za-z0-9]{36}'                       # GitHub personal access token
    'gho_[A-Za-z0-9]{36}'                       # GitHub OAuth token
    'github_pat_[A-Za-z0-9_]{82}'               # GitHub fine-grained PAT
    'xox[bporas]-[A-Za-z0-9-]+'                 # Slack tokens
)

combined_pattern=$(IFS='|'; echo "${patterns[*]}")

# Only check text files that are staged (added/copied/modified), skip binary
staged_files=$(git diff --cached --name-only --diff-filter=ACRM | grep -v '\.env\.example$' || true)

if [ -n "$staged_files" ]; then
    # Check staged content (not working tree) via git show
    for file in $staged_files; do
        matches=$(git show ":${file}" 2>/dev/null | grep -nEo "$combined_pattern" || true)
        if [ -n "$matches" ]; then
            echo -e "${RED}ERROR: Possible secret found in ${file}:${NC}"
            echo "$matches"
            EXIT_CODE=1
        fi
    done
fi

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "If this is a false positive, use: git commit --no-verify"
fi

exit $EXIT_CODE
