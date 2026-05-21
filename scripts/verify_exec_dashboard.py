# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only
"""Verify exec dashboard endpoints against a live deployment.

Run from anywhere that can reach the Observal instance:
  python scripts/verify_exec_dashboard.py --base-url https://dashboard.observal.io --token <JWT>

For EC2: run from your local machine pointed at the public URL,
or SSH into the instance and hit localhost.
"""

import argparse
import sys

import httpx

# ---------------------------------------------------------------------------
# Test definitions
# ---------------------------------------------------------------------------

CHECKS = [
    # (name, method, path, assertions_fn)
]


def check_adoption(data):
    assert data["total_users"] > 0, f"total_users={data['total_users']}"
    assert data["active_users"] >= 0
    assert 0 <= data["current_pct"] <= 100
    assert isinstance(data["monthly"], list)
    assert data["departments_covered"] >= 0


def check_agent_counts(data):
    assert data["total"] >= 0
    assert data["published"] >= 0
    assert data["in_development"] >= 0
    assert isinstance(data["by_category"], list)
    assert data["total"] >= data["published"] + data["in_development"]


def check_usage_by_category(data):
    assert isinstance(data, list)
    for item in data:
        assert "category" in item
        assert "sessions" in item
        assert "growth_pct" in item


def check_platform_coverage(data):
    assert isinstance(data, list)
    for item in data:
        assert "platform" in item
        assert "users" in item
        assert "sessions" in item


def check_platforms(data):
    assert isinstance(data, list)
    for p in data:
        assert "platform" in p
        assert "sessions" in p
        assert "success_rate" in p
        assert "avg_cost" in p
        assert "avg_latency_ms" in p
        # composite_score should be session-rank based (0-100)
        assert 0 <= p["composite_score"] <= 100


def check_velocity(data):
    assert isinstance(data["weekly"], list)
    assert "multiplier" in data
    assert "current_weekly_avg" in data
    assert "baseline_weekly_avg" in data
    if data["weekly"]:
        assert data["multiplier"] >= 0


def check_top_agents(data):
    assert isinstance(data, list)
    for a in data:
        assert "name" in a
        assert "composite_score" in a
        assert "sessions" in a
        assert "downloads" in a
        assert isinstance(a["weekly_trend"], list)


def check_departments(data):
    assert "departments" in data
    for d in data["departments"]:
        assert "department" in d
        assert "user_count" in d
        assert 0 <= d["utilization_pct"] <= 100
        assert d["sessions_per_user"] >= 0


def check_dept_tokens(data):
    assert isinstance(data, list)
    for t in data:
        assert "department" in t
        assert "tokens_used" in t
        assert "cost_per_task" in t
        assert "trend_pct" in t


def check_cost_summary(data):
    assert "configured" in data
    if data["configured"]:
        assert "monthly_savings" in data
        assert "cost_reduction_pct" in data
        assert "cost_per_task" in data
        assert isinstance(data["monthly_trend"], list)
        assert isinstance(data["by_category"], list)


def check_roi_projections(data):
    assert "projections" in data
    assert "roi_multiple" in data
    if data["projections"]:
        for p in data["projections"]:
            assert "quarter" in p
            assert 0.5 <= p["confidence"] <= 1.0


def check_strategic_insights(data):
    assert isinstance(data["model_comparison"], list)
    assert isinstance(data["department_gaps"], list)
    assert isinstance(data["quick_wins"], list)
    assert "power_user_value_pct" in data
    assert "automatable_pct" in data
    # Quick wins should use new schema
    for w in data["quick_wins"]:
        assert "observed_delta" in w, f"Quick win missing observed_delta: {w}"
        assert "context" in w, f"Quick win missing context: {w}"


def check_developer_breakdown(data):
    assert "total_developers" in data
    assert "active_developers" in data
    assert "top_20_value_pct" in data
    assert isinstance(data["developers"], list)
    for d in data["developers"]:
        assert "percentile" in d
        assert 1 <= d["percentile"] <= 100


def check_inactivity_alerts(data):
    assert isinstance(data["inactive_agents"], list)
    assert isinstance(data["inactive_users"], list)


def check_time_to_value(data):
    assert isinstance(data["agents"], list)
    # avg_days_to_100 can be null if no agent hit 100
    for a in data["agents"]:
        assert "days_to_100" in a
        assert "current_sessions" in a


def check_config(data):
    # Can be null if not configured
    if data is not None:
        assert "hourly_dev_cost" in data
        assert "pre_ai_baselines" in data


def check_ai_insights(data):
    assert "generated" in data


def check_403(status_code):
    assert status_code == 403 or status_code == 401, f"Expected 403/401, got {status_code}"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


ENDPOINT_CHECKS = [
    ("Adoption", "/exec/adoption", check_adoption),
    ("Agent Counts", "/exec/agent-counts", check_agent_counts),
    ("Usage by Category", "/exec/usage-by-category", check_usage_by_category),
    ("Platform Coverage", "/exec/platform-coverage", check_platform_coverage),
    ("Platforms", "/exec/platforms", check_platforms),
    ("Velocity", "/exec/velocity", check_velocity),
    ("Top Agents", "/exec/top-agents", check_top_agents),
    ("Departments", "/exec/departments", check_departments),
    ("Dept Tokens", "/exec/dept-tokens", check_dept_tokens),
    ("Cost Summary", "/exec/cost-summary", check_cost_summary),
    ("ROI Projections", "/exec/roi-projections", check_roi_projections),
    ("Strategic Insights", "/exec/strategic-insights", check_strategic_insights),
    ("Developer Breakdown", "/exec/developer-breakdown", check_developer_breakdown),
    ("Inactivity Alerts", "/exec/inactivity-alerts", check_inactivity_alerts),
    ("Time to Value", "/exec/time-to-value", check_time_to_value),
    ("Config", "/exec/config", check_config),
    ("AI Insights", "/exec/ai-insights", check_ai_insights),
]


def main():
    parser = argparse.ArgumentParser(description="Verify exec dashboard endpoints")
    parser.add_argument("--base-url", required=True, help="e.g. https://dashboard.observal.io")
    parser.add_argument("--token", required=True, help="Admin JWT token")
    parser.add_argument("--test-auth", action="store_true", help="Also test non-admin access returns 403")
    args = parser.parse_args()

    base = args.base_url.rstrip("/") + "/api/v1"
    headers = {"Authorization": f"Bearer {args.token}", "Content-Type": "application/json"}

    passed = 0
    failed = 0
    errors = []

    print("=== Exec Dashboard Verification ===")
    print(f"Target: {args.base_url}")
    print(f"Endpoints: {len(ENDPOINT_CHECKS)}\n")

    with httpx.Client(timeout=30, headers=headers) as client:
        for name, path, check_fn in ENDPOINT_CHECKS:
            try:
                r = client.get(f"{base}{path}")
                if r.status_code != 200:
                    print(f"  FAIL  {name} — HTTP {r.status_code}: {r.text[:100]}")
                    failed += 1
                    errors.append((name, f"HTTP {r.status_code}"))
                    continue

                data = r.json()
                check_fn(data)
                print(f"  PASS  {name}")
                passed += 1
            except AssertionError as e:
                print(f"  FAIL  {name} — {e}")
                failed += 1
                errors.append((name, str(e)))
            except Exception as e:
                print(f"  ERROR {name} — {type(e).__name__}: {e}")
                failed += 1
                errors.append((name, str(e)))

    # Auth test
    if args.test_auth:
        print("\n--- Auth Tests (no token) ---")
        with httpx.Client(timeout=10) as client:
            for name, path, _ in ENDPOINT_CHECKS[:3]:
                try:
                    r = client.get(f"{base}{path}")
                    check_403(r.status_code)
                    print(f"  PASS  {name} → {r.status_code} (correctly denied)")
                    passed += 1
                except AssertionError as e:
                    print(f"  FAIL  {name} — {e}")
                    failed += 1

    # Summary
    print(f"\n{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed")
    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  - {name}: {err}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
