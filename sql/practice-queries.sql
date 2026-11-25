-- Bokehline Programs: sample queries
-- Open bokehline_programs.db in DB Browser for SQLite (Execute SQL tab) and run one at a time.
-- The data is fictional and frozen "as of" 2026-11-20 (see the meta table).

-- 1. Active programs at Yellow or Red, worst SOP slip first
SELECT program_code, name, status, current_phase,
       sop_baseline, sop_forecast,
       CAST(julianday(sop_forecast) - julianday(sop_baseline) AS INTEGER) AS days_late
FROM programs
WHERE status IN ('Yellow', 'Red')
ORDER BY days_late DESC;

-- 2. Programs per phase and status (the "Status by phase" chart)
SELECT current_phase, status, COUNT(*) AS programs
FROM programs
GROUP BY current_phase, status
ORDER BY current_phase, status;

-- 3. Gates due in the next 45 days
SELECT p.program_code, p.name, g.gate, g.forecast_date,
       CAST(julianday(g.forecast_date) - julianday('2026-11-20') AS INTEGER) AS days_away
FROM gate_reviews g
JOIN programs p ON p.program_id = g.program_id
WHERE g.actual_date IS NULL
  AND g.forecast_date <= date('2026-11-20', '+45 days')
ORDER BY g.forecast_date;

-- 4. On-time gate rate by program manager
SELECT e.first_name || ' ' || e.last_name AS program_manager,
       COUNT(*) AS gates_held,
       ROUND(100.0 * AVG(g.actual_date <= g.planned_date), 0) AS pct_on_time
FROM gate_reviews g
JOIN programs p  ON p.program_id = g.program_id
JOIN employees e ON e.employee_id = p.program_manager_id
WHERE g.actual_date IS NOT NULL
GROUP BY program_manager
ORDER BY pct_on_time DESC;

-- 5. Top open risks (score = likelihood x severity)
SELECT p.program_code, r.title, r.category,
       r.likelihood * r.severity AS score, r.status, r.target_date
FROM risks r
JOIN programs p ON p.program_id = r.program_id
WHERE r.status <> 'Closed'
ORDER BY score DESC, r.target_date
LIMIT 10;

-- 6. Overdue actions by owner
SELECT e.first_name || ' ' || e.last_name AS owner, COUNT(*) AS overdue
FROM actions a
JOIN employees e ON e.employee_id = a.owner_id
WHERE a.completed_date IS NULL AND a.due_date < '2026-11-20'
GROUP BY owner
ORDER BY overdue DESC;

-- 7. Budget used per program, highest first
SELECT p.program_code, p.name,
       SUM(b.budget) AS budget, SUM(b.spent_to_date) AS spent,
       ROUND(100.0 * SUM(b.spent_to_date) / SUM(b.budget), 0) AS pct_used
FROM budget_lines b
JOIN programs p ON p.program_id = b.program_id
GROUP BY p.program_id
ORDER BY pct_used DESC;
