"""HTML export for insight reports — self-contained single-file report."""

from __future__ import annotations

import html
from datetime import datetime


def _esc(text: str | None) -> str:
    """HTML-escape text."""
    return html.escape(str(text)) if text else ""


def _format_cost(val: float | None) -> str:
    if val is None:
        return "$0.00"
    if val < 0.01:
        return f"${val:.4f}"
    return f"${val:.2f}"


def _severity_color(severity: str) -> str:
    return {"high": "#dc2626", "medium": "#d97706", "low": "#2563eb"}.get(severity, "#6b7280")


def _priority_color(priority: str) -> str:
    return {"high": "#dc2626", "medium": "#d97706", "low": "#16a34a"}.get(priority, "#6b7280")


def _health_color(health: str) -> str:
    return {"healthy": "#16a34a", "mixed": "#d97706", "concerning": "#dc2626"}.get(health, "#6b7280")


def render_report_html(report: dict) -> str:
    """Render a complete insight report as a self-contained HTML document.

    Args:
        report: Full report dict with keys: id, agent_id, status, period_start,
                period_end, metrics, narrative, sessions_analyzed, etc.
    """
    metrics = report.get("metrics") or {}
    narrative = report.get("narrative") or {}
    report.get("agent_id", "Unknown")
    period_start = report.get("period_start", "")
    period_end = report.get("period_end", "")
    sessions_analyzed = report.get("sessions_analyzed", 0)
    report_id = report.get("id", "")

    # Format dates
    if isinstance(period_start, datetime):
        period_start = period_start.strftime("%Y-%m-%d")
    elif isinstance(period_start, str) and "T" in period_start:
        period_start = period_start.split("T")[0]

    if isinstance(period_end, datetime):
        period_end = period_end.strftime("%Y-%m-%d")
    elif isinstance(period_end, str) and "T" in period_end:
        period_end = period_end.split("T")[0]

    # Extract sections
    at_a_glance = narrative.get("at_a_glance", {})
    usage_patterns = narrative.get("usage_patterns", {})
    what_works = narrative.get("what_works", {})
    friction = narrative.get("friction_analysis", {})
    suggestions = narrative.get("suggestions", {})
    token_opt = narrative.get("token_optimization", {})
    user_exp = narrative.get("user_experience", {})
    regression = narrative.get("regression_detection", {})
    fun_ending = narrative.get("fun_ending", {})

    # Metrics
    overview = metrics.get("overview", {})
    tokens = metrics.get("tokens", {})
    cost = metrics.get("cost", {})
    errors = metrics.get("errors", {})
    duration = metrics.get("duration", {})
    tools = metrics.get("tools", [])
    tool_errors = metrics.get("tool_errors", {})
    metrics.get("interruptions", {})

    # Build HTML sections
    sections_html = []

    # ── At a Glance ──
    if at_a_glance and isinstance(at_a_glance, dict):
        health = at_a_glance.get("health", "mixed")
        sections_html.append(f"""
    <section class="at-a-glance">
      <h2>At a Glance</h2>
      <div class="health-badge" style="background: {_health_color(health)}; color: white; display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: 600; margin-bottom: 16px;">
        {_esc(health).upper()}
      </div>
      <div class="glance-grid">
        <div class="glance-card glance-good">
          <h4>What's Working</h4>
          <p>{_esc(at_a_glance.get("whats_working", ""))}</p>
        </div>
        <div class="glance-card glance-bad">
          <h4>What's Hindering</h4>
          <p>{_esc(at_a_glance.get("whats_hindering", ""))}</p>
        </div>
        <div class="glance-card glance-action">
          <h4>Quick Win</h4>
          <p>{_esc(at_a_glance.get("quick_win", ""))}</p>
        </div>
      </div>
    </section>""")

    # ── Key Metrics ──
    sections_html.append(f"""
    <section class="metrics-overview">
      <h2>Key Metrics</h2>
      <div class="metrics-grid">
        <div class="metric-card">
          <span class="metric-value">{overview.get("total_sessions", 0)}</span>
          <span class="metric-label">Sessions</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">{overview.get("unique_users", 0)}</span>
          <span class="metric-label">Unique Users</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">{_format_cost(cost.get("total_cost_usd"))}</span>
          <span class="metric-label">Total Cost</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">{_format_cost(cost.get("avg_cost_per_session"))}</span>
          <span class="metric-label">Cost/Session</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">{round(float(cost.get("cache_efficiency_ratio", 0)) * 100, 1)}%</span>
          <span class="metric-label">Cache Efficiency</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">{round(float(duration.get("avg_duration_seconds", 0)) / 60, 1)}m</span>
          <span class="metric-label">Avg Duration</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">{round(float(errors.get("error_rate", 0)) * 100, 1)}%</span>
          <span class="metric-label">Error Rate</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">{int(tokens.get("total_tokens", 0)):,}</span>
          <span class="metric-label">Total Tokens</span>
        </div>
      </div>
    </section>""")

    # ── Usage Patterns ──
    if usage_patterns and isinstance(usage_patterns, dict):
        usage_narrative = usage_patterns.get("narrative", "")
        tool_dist = usage_patterns.get("tool_distribution", [])
        session_profile = usage_patterns.get("session_profile", {})

        tool_dist_html = ""
        if tool_dist and isinstance(tool_dist, list):
            max_calls = max((t.get("calls", 0) for t in tool_dist), default=1) or 1
            tool_rows = ""
            for t in tool_dist[:10]:
                calls = t.get("calls", 0)
                pct = (calls / max_calls) * 100
                err_rate = t.get("error_rate", 0)
                tool_rows += f"""
              <div class="tool-row">
                <span class="tool-name">{_esc(t.get("tool", ""))}</span>
                <div class="tool-bar-container">
                  <div class="tool-bar" style="width: {pct}%"></div>
                </div>
                <span class="tool-calls">{calls}</span>
                <span class="tool-err" style="color: {"#dc2626" if err_rate > 5 else "#6b7280"}">{err_rate:.1f}%</span>
              </div>"""
            tool_dist_html = f'<div class="tool-distribution"><h4>Tool Distribution</h4>{tool_rows}</div>'

        profile_html = ""
        if session_profile and isinstance(session_profile, dict):
            profile_html = f"""
          <div class="session-profile">
            <h4>Typical Session</h4>
            <div class="profile-stats">
              <span><strong>{session_profile.get("avg_duration_minutes", "?")}m</strong> duration</span>
              <span><strong>{session_profile.get("avg_tool_calls", "?")}</strong> tool calls</span>
              <span><strong>{session_profile.get("avg_prompts", "?")}</strong> prompts</span>
              <span>Type: <strong>{_esc(session_profile.get("session_type", "?"))}</strong></span>
            </div>
          </div>"""

        sections_html.append(f"""
    <section class="usage-patterns">
      <h2>Usage Patterns</h2>
      <p class="narrative">{_esc(usage_narrative)}</p>
      {tool_dist_html}
      {profile_html}
    </section>""")

    # ── What Works ──
    if what_works and isinstance(what_works, dict):
        strengths = what_works.get("strengths", [])
        if strengths and isinstance(strengths, list):
            strength_cards = ""
            for s in strengths:
                if isinstance(s, dict):
                    strength_cards += f"""
              <div class="strength-card">
                <h4>{_esc(s.get("title", ""))}</h4>
                <p>{_esc(s.get("description", ""))}</p>
              </div>"""
            sections_html.append(f"""
    <section class="what-works">
      <h2>What Works Well</h2>
      <p class="section-intro">{_esc(what_works.get("intro", ""))}</p>
      <div class="strengths-grid">{strength_cards}</div>
    </section>""")

    # ── Friction Analysis ──
    if friction and isinstance(friction, dict):
        categories = friction.get("categories", [])
        if categories and isinstance(categories, list):
            friction_cards = ""
            for c in categories:
                if isinstance(c, dict):
                    sev = c.get("severity", "low")
                    friction_cards += f"""
              <div class="friction-card" style="border-left: 4px solid {_severity_color(sev)}">
                <div class="friction-header">
                  <h4>{_esc(c.get("title", ""))}</h4>
                  <span class="severity-badge" style="background: {_severity_color(sev)}; color: white;">{_esc(sev).upper()}</span>
                </div>
                <p>{_esc(c.get("description", ""))}</p>
                <code class="evidence">{_esc(c.get("evidence", ""))}</code>
                <p class="impact"><em>Impact: {_esc(c.get("impact", ""))}</em></p>
              </div>"""
            sections_html.append(f"""
    <section class="friction-analysis">
      <h2>Friction Analysis</h2>
      <p class="section-intro">{_esc(friction.get("intro", ""))}</p>
      <div class="friction-list">{friction_cards}</div>
    </section>""")

    # ── Suggestions ──
    if suggestions and isinstance(suggestions, dict):
        items = suggestions.get("items", [])
        if items and isinstance(items, list):
            suggestion_cards = ""
            for idx, item in enumerate(items, 1):
                if isinstance(item, dict):
                    priority = item.get("priority", "medium")
                    suggestion_cards += f"""
              <div class="suggestion-card">
                <div class="suggestion-header">
                  <span class="suggestion-num">#{idx}</span>
                  <h4>{_esc(item.get("title", ""))}</h4>
                  <span class="priority-badge" style="background: {_priority_color(priority)}; color: white;">{_esc(priority).upper()}</span>
                </div>
                <div class="suggestion-action">
                  <strong>Action:</strong> {_esc(item.get("action", ""))}
                </div>
                <p class="suggestion-why"><em>Why: {_esc(item.get("why", ""))}</em></p>
              </div>"""
            sections_html.append(f"""
    <section class="suggestions">
      <h2>Suggestions</h2>
      <p class="section-intro">{_esc(suggestions.get("intro", ""))}</p>
      <div class="suggestions-list">{suggestion_cards}</div>
    </section>""")

    # ── Token Optimization ──
    if token_opt and isinstance(token_opt, dict):
        tok_metrics = token_opt.get("metrics", {})
        opportunities = token_opt.get("opportunities", [])
        opp_html = ""
        if opportunities and isinstance(opportunities, list):
            for opp in opportunities:
                if isinstance(opp, dict):
                    opp_html += f"""
              <div class="opportunity-card">
                <h4>{_esc(opp.get("title", ""))}</h4>
                <p>{_esc(opp.get("description", ""))}</p>
                <span class="savings">{_esc(opp.get("estimated_savings", ""))}</span>
              </div>"""
        sections_html.append(f"""
    <section class="token-optimization">
      <h2>Cost & Token Optimization</h2>
      <p class="narrative">{_esc(token_opt.get("summary", ""))}</p>
      <div class="cost-metrics">
        <div class="metric-card"><span class="metric-value">{_format_cost(tok_metrics.get("total_cost_usd"))}</span><span class="metric-label">Total Cost</span></div>
        <div class="metric-card"><span class="metric-value">{_format_cost(tok_metrics.get("cost_per_session"))}</span><span class="metric-label">Per Session</span></div>
        <div class="metric-card"><span class="metric-value">{round(float(tok_metrics.get("cache_efficiency_pct", 0)), 1)}%</span><span class="metric-label">Cache Efficiency</span></div>
      </div>
      {f'<div class="opportunities"><h4>Opportunities</h4>{opp_html}</div>' if opp_html else ""}
    </section>""")

    # ── User Experience ──
    if user_exp and isinstance(user_exp, dict):
        signals = user_exp.get("signals", [])
        indicators = user_exp.get("satisfaction_indicators", {})
        signals_html = ""
        if signals and isinstance(signals, list):
            for sig in signals:
                if isinstance(sig, dict):
                    signals_html += f"""
              <div class="signal-row">
                <span class="signal-obs">{_esc(sig.get("signal", ""))}</span>
                <span class="signal-interp">{_esc(sig.get("interpretation", ""))}</span>
              </div>"""
        sections_html.append(f"""
    <section class="user-experience">
      <h2>User Experience</h2>
      <p class="narrative">{_esc(user_exp.get("narrative", ""))}</p>
      {f'<div class="signals"><h4>Signals</h4>{signals_html}</div>' if signals_html else ""}
      {
            f'''<div class="satisfaction-indicators">
        <span>Completion: <strong>{_esc(str(indicators.get("completion_rate", "N/A")))}</strong></span>
        <span>Interruptions: <strong>{_esc(str(indicators.get("interruption_rate", "N/A")))}</strong></span>
        <span>Retries: <strong>{_esc(str(indicators.get("retry_patterns", "none")))}</strong></span>
      </div>'''
            if indicators
            else ""
        }
    </section>""")

    # ── Regression Detection ──
    if regression and isinstance(regression, dict) and regression.get("has_previous_data"):
        changes = regression.get("changes", [])
        if changes and isinstance(changes, list):
            change_rows = ""
            for ch in changes:
                if isinstance(ch, dict):
                    direction = ch.get("direction", "stable")
                    arrow = "↑" if direction == "improved" else "↓" if direction == "degraded" else "→"
                    color = (
                        "#16a34a" if direction == "improved" else "#dc2626" if direction == "degraded" else "#6b7280"
                    )
                    change_rows += f"""
              <tr>
                <td>{_esc(ch.get("metric", ""))}</td>
                <td style="color: {color}; font-weight: 600;">{arrow} {_esc(direction)}</td>
                <td>{_esc(str(ch.get("previous_value", "")))}</td>
                <td>{_esc(str(ch.get("current_value", "")))}</td>
                <td>{ch.get("magnitude_pct", 0):.1f}%</td>
                <td>{_esc(ch.get("significance", ""))}</td>
              </tr>"""
            sections_html.append(f"""
    <section class="regression-detection">
      <h2>Period-over-Period Changes</h2>
      <p class="narrative">{_esc(regression.get("summary", ""))}</p>
      <table class="changes-table">
        <thead><tr><th>Metric</th><th>Direction</th><th>Previous</th><th>Current</th><th>Change</th><th>Significance</th></tr></thead>
        <tbody>{change_rows}</tbody>
      </table>
    </section>""")

    # ── Top Tools Table ──
    if tools:
        tool_rows = ""
        for t in tools[:15]:
            invocations = int(t.get("invocations", 0))
            errs = int(t.get("errors", 0))
            err_rate = (errs / invocations * 100) if invocations > 0 else 0
            tool_rows += f"""
          <tr>
            <td><code>{_esc(t.get("name", ""))}</code></td>
            <td>{invocations}</td>
            <td>{errs}</td>
            <td style="color: {"#dc2626" if err_rate > 10 else "#6b7280"}">{err_rate:.1f}%</td>
          </tr>"""
        sections_html.append(f"""
    <section class="tools-table">
      <h2>Tool Usage</h2>
      <table>
        <thead><tr><th>Tool</th><th>Invocations</th><th>Errors</th><th>Error Rate</th></tr></thead>
        <tbody>{tool_rows}</tbody>
      </table>
    </section>""")

    # ── Error Categories ──
    if tool_errors and tool_errors.get("categories"):
        cats = tool_errors["categories"]
        cat_rows = ""
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            cat_rows += f"<tr><td>{_esc(cat)}</td><td>{count}</td></tr>"
        sections_html.append(f"""
    <section class="error-categories">
      <h2>Error Categories</h2>
      <table>
        <thead><tr><th>Category</th><th>Count</th></tr></thead>
        <tbody>{cat_rows}</tbody>
      </table>
    </section>""")

    # ── Fun Ending ──
    if fun_ending and isinstance(fun_ending, dict) and fun_ending.get("headline"):
        sections_html.append(f"""
    <section class="fun-ending">
      <div class="fun-card">
        <h3>{_esc(fun_ending.get("headline", ""))}</h3>
        <p>{_esc(fun_ending.get("detail", ""))}</p>
      </div>
    </section>""")

    body_content = "\n".join(sections_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Insight Report — {_esc(period_start)} to {_esc(period_end)}</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text: #1e293b;
      --text-muted: #64748b;
      --border: #e2e8f0;
      --green: #16a34a;
      --green-bg: #f0fdf4;
      --red: #dc2626;
      --red-bg: #fef2f2;
      --amber: #d97706;
      --amber-bg: #fffbeb;
      --blue: #2563eb;
      --blue-bg: #eff6ff;
      --purple: #7c3aed;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 40px 20px;
    }}
    .container {{ max-width: 900px; margin: 0 auto; }}
    header {{
      text-align: center;
      margin-bottom: 40px;
      padding-bottom: 24px;
      border-bottom: 2px solid var(--border);
    }}
    header h1 {{ font-size: 28px; margin-bottom: 8px; }}
    header .subtitle {{ color: var(--text-muted); font-size: 14px; }}
    section {{
      background: var(--card-bg);
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
      border: 1px solid var(--border);
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    section h2 {{
      font-size: 20px;
      margin-bottom: 16px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }}
    .narrative {{ color: var(--text); margin-bottom: 16px; white-space: pre-wrap; }}
    .section-intro {{ color: var(--text-muted); margin-bottom: 16px; font-style: italic; }}

    /* Metrics grid */
    .metrics-grid, .cost-metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 12px;
    }}
    .metric-card {{
      background: var(--bg);
      padding: 16px;
      border-radius: 8px;
      text-align: center;
      border: 1px solid var(--border);
    }}
    .metric-value {{ display: block; font-size: 24px; font-weight: 700; color: var(--blue); }}
    .metric-label {{ display: block; font-size: 12px; color: var(--text-muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}

    /* At a glance */
    .glance-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }}
    .glance-card {{ padding: 16px; border-radius: 8px; }}
    .glance-card h4 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
    .glance-card p {{ font-size: 14px; }}
    .glance-good {{ background: var(--green-bg); border: 1px solid #bbf7d0; }}
    .glance-good h4 {{ color: var(--green); }}
    .glance-bad {{ background: var(--red-bg); border: 1px solid #fecaca; }}
    .glance-bad h4 {{ color: var(--red); }}
    .glance-action {{ background: var(--blue-bg); border: 1px solid #bfdbfe; }}
    .glance-action h4 {{ color: var(--blue); }}

    /* Strengths */
    .strengths-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
    .strength-card {{
      background: var(--green-bg);
      border: 1px solid #bbf7d0;
      padding: 16px;
      border-radius: 8px;
    }}
    .strength-card h4 {{ color: var(--green); margin-bottom: 8px; font-size: 14px; }}
    .strength-card p {{ font-size: 13px; color: var(--text); }}

    /* Friction */
    .friction-list {{ display: flex; flex-direction: column; gap: 12px; }}
    .friction-card {{
      padding: 16px;
      border-radius: 8px;
      background: var(--bg);
    }}
    .friction-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
    .friction-header h4 {{ flex: 1; font-size: 15px; }}
    .severity-badge, .priority-badge {{
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 10px;
      font-weight: 600;
      letter-spacing: 0.5px;
    }}
    .evidence {{
      display: block;
      background: #1e293b;
      color: #e2e8f0;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      margin: 8px 0;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .impact {{ color: var(--text-muted); font-size: 13px; }}

    /* Suggestions */
    .suggestions-list {{ display: flex; flex-direction: column; gap: 12px; }}
    .suggestion-card {{
      padding: 16px;
      border-radius: 8px;
      background: var(--bg);
      border: 1px solid var(--border);
    }}
    .suggestion-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }}
    .suggestion-num {{ font-size: 18px; font-weight: 700; color: var(--blue); min-width: 30px; }}
    .suggestion-header h4 {{ flex: 1; font-size: 15px; }}
    .suggestion-action {{ background: var(--card-bg); padding: 12px; border-radius: 6px; border: 1px solid var(--border); font-size: 13px; margin-bottom: 8px; }}
    .suggestion-why {{ color: var(--text-muted); font-size: 13px; }}

    /* Tools table */
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    thead {{ background: var(--bg); }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }}
    th {{ font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text-muted); }}
    code {{ background: var(--bg); padding: 2px 6px; border-radius: 4px; font-size: 12px; }}

    /* Tool distribution */
    .tool-distribution {{ margin-top: 16px; }}
    .tool-distribution h4 {{ margin-bottom: 12px; font-size: 14px; }}
    .tool-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
    .tool-name {{ font-size: 12px; min-width: 100px; font-family: monospace; }}
    .tool-bar-container {{ flex: 1; height: 20px; background: var(--bg); border-radius: 4px; overflow: hidden; }}
    .tool-bar {{ height: 100%; background: var(--blue); border-radius: 4px; transition: width 0.3s; }}
    .tool-calls {{ font-size: 12px; min-width: 40px; text-align: right; font-weight: 600; }}
    .tool-err {{ font-size: 11px; min-width: 40px; text-align: right; }}

    /* Session profile */
    .session-profile {{ margin-top: 16px; }}
    .session-profile h4 {{ margin-bottom: 8px; font-size: 14px; }}
    .profile-stats {{ display: flex; gap: 20px; flex-wrap: wrap; font-size: 13px; }}

    /* Signals */
    .signals {{ margin-top: 12px; }}
    .signals h4 {{ margin-bottom: 8px; font-size: 14px; }}
    .signal-row {{ display: flex; gap: 16px; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }}
    .signal-obs {{ flex: 1; font-weight: 500; }}
    .signal-interp {{ flex: 1; color: var(--text-muted); }}
    .satisfaction-indicators {{ display: flex; gap: 20px; margin-top: 12px; font-size: 13px; }}

    /* Opportunities */
    .opportunities {{ margin-top: 16px; }}
    .opportunities h4 {{ margin-bottom: 12px; font-size: 14px; }}
    .opportunity-card {{ background: var(--amber-bg); border: 1px solid #fde68a; padding: 12px; border-radius: 8px; margin-bottom: 8px; }}
    .opportunity-card h4 {{ font-size: 13px; color: var(--amber); margin-bottom: 4px; }}
    .opportunity-card p {{ font-size: 13px; }}
    .savings {{ font-size: 12px; color: var(--green); font-weight: 600; }}

    /* Changes table */
    .changes-table th, .changes-table td {{ font-size: 12px; padding: 8px; }}

    /* Fun ending */
    .fun-card {{
      background: linear-gradient(135deg, #eff6ff, #f0fdf4);
      padding: 24px;
      border-radius: 8px;
      text-align: center;
    }}
    .fun-card h3 {{ font-size: 18px; margin-bottom: 8px; color: var(--purple); }}
    .fun-card p {{ color: var(--text-muted); font-size: 14px; }}

    /* Footer */
    footer {{
      text-align: center;
      color: var(--text-muted);
      font-size: 12px;
      margin-top: 40px;
      padding-top: 20px;
      border-top: 1px solid var(--border);
    }}

    @media print {{
      body {{ padding: 20px; }}
      section {{ break-inside: avoid; box-shadow: none; }}
    }}
    @media (max-width: 640px) {{
      .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .glance-grid {{ grid-template-columns: 1fr; }}
      .strengths-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Agent Insight Report</h1>
      <p class="subtitle">
        Period: {_esc(period_start)} to {_esc(period_end)} &middot;
        {sessions_analyzed} sessions analyzed &middot;
        Report ID: {_esc(str(report_id)[:8])}
      </p>
    </header>

    {body_content}

    <footer>
      Generated by Observal &middot; {datetime.now().strftime("%Y-%m-%d %H:%M")}
    </footer>
  </div>
</body>
</html>"""
