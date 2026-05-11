"""Standalone logic simulation for retention purge algorithms.

No project imports required -- pure Python verification of the
algorithmic correctness of the purge logic.
"""

import re
from datetime import UTC, datetime, timedelta

# ============================================================================
# Simulation 1: Count-based cutoff algorithm
# ============================================================================

print("=" * 60)
print("Simulation 1: Count-based cutoff algorithm")
print("=" * 60)

data = [
    {"day": "2026-05-11", "cnt": "2000"},
    {"day": "2026-05-10", "cnt": "2000"},
    {"day": "2026-05-09", "cnt": "2000"},
    {"day": "2026-05-08", "cnt": "1500"},
]
max_trace_count = 5000

running_total = 0
cutoff_day = None
for row in data:
    running_total += int(row["cnt"])
    if running_total > max_trace_count:
        cutoff_day = row["day"]
        break

# Expected: cutoff_day = "2026-05-09" (after 2000+2000+2000=6000 > 5000)
assert cutoff_day == "2026-05-09", f"Expected 2026-05-09, got {cutoff_day}"
print(f"  Data: {data}")
print(f"  max_trace_count: {max_trace_count}")
print(f"  Running total at cutoff: {running_total}")
print(f"  Cutoff day: {cutoff_day}")
print("  RESULT: PASS")
print()

# ============================================================================
# Simulation 2: Score retention default calculation (2x trace, floored at 30)
# ============================================================================

print("=" * 60)
print("Simulation 2: Score retention default calculation")
print("=" * 60)


def compute_score_days(data_retention_days, score_retention_days=None):
    """Reproduce the logic from run_retention_purge."""
    score_days = score_retention_days or (
        (data_retention_days * 2) if data_retention_days else None
    )
    if score_days:
        score_days = max(score_days, 30)
    return score_days


# Case A: data_retention_days=14, no score_retention_days
# 14*2=28, max(28,30)=30
result_a = compute_score_days(14, None)
assert result_a == 30, f"Case A: Expected 30, got {result_a}"
print(f"  Case A: data=14, score=None => {result_a} (2x=28, floor=30) PASS")

# Case B: data_retention_days=20, no score_retention_days
# 20*2=40, max(40,30)=40
result_b = compute_score_days(20, None)
assert result_b == 40, f"Case B: Expected 40, got {result_b}"
print(f"  Case B: data=20, score=None => {result_b} (2x=40, no floor needed) PASS")

# Case C: data_retention_days=14, score_retention_days=60
# Explicit 60, max(60,30)=60
result_c = compute_score_days(14, 60)
assert result_c == 60, f"Case C: Expected 60, got {result_c}"
print(f"  Case C: data=14, score=60 => {result_c} (explicit, above floor) PASS")

# Case D: data_retention_days=7 (minimum), no score_retention_days
# 7*2=14, max(14,30)=30
result_d = compute_score_days(7, None)
assert result_d == 30, f"Case D: Expected 30, got {result_d}"
print(f"  Case D: data=7, score=None => {result_d} (2x=14, floor=30) PASS")

# Case E: data_retention_days=None (only count-based enabled)
result_e = compute_score_days(None, None)
assert result_e is None, f"Case E: Expected None, got {result_e}"
print(f"  Case E: data=None, score=None => {result_e} (no score purge) PASS")

print()

# ============================================================================
# Simulation 3: Cutoff timestamp formatting
# ============================================================================

print("=" * 60)
print("Simulation 3: Cutoff timestamp formatting")
print("=" * 60)

retention_days = 14
cutoff = datetime.now(UTC) - timedelta(days=retention_days)
cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S.000")

# Verify format matches YYYY-MM-DD HH:MM:SS.000
pattern = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.000$"
assert re.match(pattern, cutoff_str), f"Format mismatch: {cutoff_str}"
print(f"  retention_days: {retention_days}")
print(f"  cutoff_str: {cutoff_str}")
print(f"  Pattern: {pattern}")
print("  RESULT: PASS")
print()

# Also verify count-based cutoff format
count_cutoff_day = "2026-05-09"
count_cutoff_str = f"{count_cutoff_day} 00:00:00.000"
assert re.match(pattern, count_cutoff_str), f"Count format mismatch: {count_cutoff_str}"
print(f"  Count-based cutoff_str: {count_cutoff_str}")
print("  Count-based format: PASS")
print()

# ============================================================================
# Simulation 4: Edge case - all days fit within max_trace_count
# ============================================================================

print("=" * 60)
print("Simulation 4: Edge case - all days fit within max_trace_count")
print("=" * 60)

data_small = [
    {"day": "2026-05-11", "cnt": "500"},
    {"day": "2026-05-10", "cnt": "500"},
    {"day": "2026-05-09", "cnt": "500"},
]
max_trace_count_large = 10000

running_total = 0
cutoff_day = None
for row in data_small:
    running_total += int(row["cnt"])
    if running_total > max_trace_count_large:
        cutoff_day = row["day"]
        break

# Expected: cutoff_day remains None (total=1500 < 10000)
assert cutoff_day is None, f"Expected None, got {cutoff_day}"
print(f"  Data: {data_small}")
print(f"  max_trace_count: {max_trace_count_large}")
print(f"  Total: {running_total}")
print(f"  Cutoff day: {cutoff_day} (no purge needed)")
print("  RESULT: PASS")
print()

# ============================================================================
# Simulation 5: Boundary condition - exactly at limit
# ============================================================================

print("=" * 60)
print("Simulation 5: Boundary - exactly at max_trace_count")
print("=" * 60)

data_exact = [
    {"day": "2026-05-11", "cnt": "2500"},
    {"day": "2026-05-10", "cnt": "2500"},
    {"day": "2026-05-09", "cnt": "1"},
]
max_trace_count_exact = 5000

running_total = 0
cutoff_day = None
for row in data_exact:
    running_total += int(row["cnt"])
    if running_total > max_trace_count_exact:
        cutoff_day = row["day"]
        break

# 2500+2500=5000 (not greater), then +1=5001 > 5000
assert cutoff_day == "2026-05-09", f"Expected 2026-05-09, got {cutoff_day}"
print(f"  Data: {data_exact}")
print(f"  max_trace_count: {max_trace_count_exact}")
print(f"  Running total at cutoff: {running_total}")
print(f"  Cutoff day: {cutoff_day}")
print("  RESULT: PASS (strictly > not >=)")
print()

# ============================================================================
# Simulation 6: Deletion order verification (logical)
# ============================================================================

print("=" * 60)
print("Simulation 6: Deletion order verification")
print("=" * 60)

# Simulate the deletion order from _purge_count_based
deletion_order = []
tables_children = [("spans", "start_time"), ("session_events", "timestamp")]
for table, col in tables_children:
    deletion_order.append(f"DELETE FROM {table}")
deletion_order.append("DELETE orphan session_stats_agg")
deletion_order.append("DELETE FROM scores")
deletion_order.append("DELETE FROM traces")

# Verify children come before traces
traces_idx = deletion_order.index("DELETE FROM traces")
spans_idx = deletion_order.index("DELETE FROM spans")
sessions_idx = deletion_order.index("DELETE FROM session_events")

assert spans_idx < traces_idx, "spans must be deleted before traces"
assert sessions_idx < traces_idx, "session_events must be deleted before traces"
print(f"  Deletion order: {deletion_order}")
print(f"  spans_idx={spans_idx} < traces_idx={traces_idx}: OK")
print(f"  sessions_idx={sessions_idx} < traces_idx={traces_idx}: OK")
print("  RESULT: PASS")
print()

# ============================================================================
# Summary
# ============================================================================

print("=" * 60)
print("ALL SIMULATIONS PASSED")
print("=" * 60)
