"""Seed a test skill into the local Observal instance for testing skill installs.

Usage:
    python scripts/seed_test_skill.py

Requires the server to be running at localhost:8000 with demo accounts enabled.
"""

import sys

import requests

BASE = "http://localhost:8000"

# Login as admin (can approve skills)
print("1. Logging in as admin...")
r = requests.post(f"{BASE}/api/v1/auth/login", json={
    "email": "admin@demo.example",
    "password": "admin-changeme",
})
if r.status_code != 200:
    print(f"   FAILED to login: {r.status_code} {r.text}")
    sys.exit(1)
admin_token = r.json()["access_token"]
print("   OK — got token")

# Use admin token for everything (user account may not exist)
user_token = admin_token
print("2. Using admin token for skill submission too")

# Submit a skill as user
print("3. Submitting test skill...")
skill_payload = {
    "name": "code-review-ai",
    "version": "1.0.0",
    "description": "AI-powered code review that checks for bugs, security issues, and style violations. Provides inline suggestions and generates review summaries.",
    "owner": "demo-user",
    "git_url": "https://github.com/observal/skills-library.git",
    "skill_path": "skills/code-review-ai",
    "task_type": "code-review",
    "slash_command": "review",
    "target_agents": ["claude-code", "cursor", "kiro"],
    "activation_keywords": ["review", "check code", "audit"],
    "supported_ides": ["claude-code", "cursor", "vscode", "kiro"],
}
r = requests.post(
    f"{BASE}/api/v1/skills/submit",
    json=skill_payload,
    headers={"Authorization": f"Bearer {user_token}"},
)
if r.status_code == 409:
    print("   Skill already exists — looking it up...")
    r2 = requests.get(
        f"{BASE}/api/v1/skills/my",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    skills = r2.json()
    skill = next((s for s in skills if s["name"] == "code-review-ai"), None)
    if not skill:
        print("   FAILED to find existing skill")
        sys.exit(1)
    skill_id = skill["id"]
    print(f"   Using existing skill: {skill_id}")
elif r.status_code != 200:
    print(f"   FAILED: {r.status_code} {r.text}")
    sys.exit(1)
else:
    skill_id = r.json()["id"]
    print(f"   OK — skill ID: {skill_id}")

# Approve as admin
print("4. Approving skill as admin...")
r = requests.post(
    f"{BASE}/api/v1/review/{skill_id}/approve",
    headers={"Authorization": f"Bearer {admin_token}"},
)
if r.status_code == 200:
    print("   OK — approved!")
elif "already" in r.text.lower() or r.status_code == 400:
    print("   Already approved (or status doesn't allow re-approve)")
else:
    print(f"   Warning: {r.status_code} {r.text}")

# Verify it shows up in the public list
print("5. Verifying skill appears in list...")
r = requests.get(f"{BASE}/api/v1/skills")
skills = r.json()
found = next((s for s in skills if s["name"] == "code-review-ai"), None)
if found:
    print(f"   OK — visible in list! Status: {found.get('status')}")
else:
    print("   WARNING: not visible in public list (may need approval)")

# Test install endpoint
print("6. Testing install endpoint...")
r = requests.post(
    f"{BASE}/api/v1/skills/{skill_id}/install",
    json={"ide": "claude-code", "scope": "project"},
    headers={"Authorization": f"Bearer {user_token}"},
)
if r.status_code == 200:
    config = r.json()["config_snippet"]
    print(f"   OK — install response has skill_file: {'skill_file' in config}")
    if "skill_file" in config:
        print(f"   Path: {config['skill_file']['path']}")
        print(f"   Content preview: {config['skill_file']['content'][:100]}...")
else:
    print(f"   FAILED: {r.status_code} {r.text}")


# ── Part 2: Create an agent that bundles the skill ──

print("\n7. Creating agent with skill bundled...")
agent_payload = {
    "name": "test-skill-agent",
    "version": "1.0.0",
    "description": "Test agent to verify skill file generation on install",
    "prompt": "You are a helpful coding assistant with code review capabilities.",
    "owner": "demo-admin",
    "model_name": "claude-sonnet-4",
    "supported_ides": ["claude-code", "cursor", "vscode", "kiro"],
    "components": [
        {"component_type": "skill", "component_id": skill_id}
    ],
    "external_mcps": [],
    "goal_template": {
        "description": "Code review and assistance",
        "sections": [
            {"name": "default", "description": "Default goal section"}
        ],
    },
}
r = requests.post(
    f"{BASE}/api/v1/agents",
    json=agent_payload,
    headers={"Authorization": f"Bearer {admin_token}"},
)
if r.status_code == 409:
    print("   Agent already exists — looking it up...")
    r2 = requests.get(
        f"{BASE}/api/v1/agents",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    agents = r2.json()
    agent = next((a for a in agents if a["name"] == "test-skill-agent"), None)
    if not agent:
        print("   FAILED to find existing agent")
        sys.exit(1)
    agent_id = agent["id"]
    print(f"   Using existing agent: {agent_id}")
elif r.status_code not in (200, 201):
    print(f"   FAILED: {r.status_code} {r.text}")
    sys.exit(1)
else:
    agent_id = r.json()["id"]
    print(f"   OK — agent ID: {agent_id}")

# Approve the agent
print("8. Approving agent...")
r = requests.post(
    f"{BASE}/api/v1/review/{agent_id}/approve",
    headers={"Authorization": f"Bearer {admin_token}"},
)
if r.status_code == 200:
    print("   OK — approved!")
else:
    print(f"   Status: {r.status_code} {r.text}")

# Test agent install
print("9. Testing agent install (claude-code)...")
r = requests.post(
    f"{BASE}/api/v1/agents/{agent_id}/install",
    json={"ide": "claude-code"},
    headers={"Authorization": f"Bearer {admin_token}"},
)
if r.status_code == 200:
    result = r.json()
    has_skills = "skill_files" in result
    print(f"   OK — response has skill_files: {has_skills}")
    if has_skills:
        for sf in result["skill_files"]:
            print(f"   → {sf['path']}")
    else:
        print(f"   Keys in response: {list(result.keys())}")
else:
    print(f"   FAILED: {r.status_code} {r.text}")

print("\n--- DONE ---")
print(f"Skill ID: {skill_id}")
print(f"Agent ID: {agent_id}")
print("\nTest from frontend:")
print("  1. Go to http://localhost:3000")
print("  2. Login: admin@demo.example / admin-changeme")
print("  3. Find 'test-skill-agent' → Install → pick IDE")
print("  4. Response should include skill_files with SKILL.md")
print("\nTest from CLI:")
print(f"  observal agent install {agent_id} --ide claude-code")
