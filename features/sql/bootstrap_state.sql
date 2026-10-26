-- First run only (no fs_state partition for $seed_day yet): carried state at $seed_day from all Gold history.
-- Reads only the small inputs (valid cash-flow events, campaigns, debt/limit per day), never the portfolio.
CREATE OR REPLACE TABLE seed_state AS
WITH events AS (
    SELECT master_account, count(*)::BIGINT AS history_count
    FROM valid_events WHERE event_day <= $seed_day GROUP BY ALL),
campaigns AS (
    SELECT master_account, max(CAST(sent_at AS DATE)) AS last_campaign_date
    FROM customer_campaign WHERE status <> 'FAILED' AND CAST(sent_at AS DATE) <= $seed_day GROUP BY ALL),
days AS (
    SELECT master_account, business_date, margin_debt > margin_limit AS over_limit
    FROM balances WHERE business_date <= $seed_day),
last_ok AS (
    SELECT master_account, max(business_date) AS business_date FROM days WHERE NOT over_limit GROUP BY ALL),
streaks AS (
    -- days after the last day within the limit: all above it, so their count is the running streak
    SELECT d.master_account,
           count(*) FILTER (WHERE d.business_date > coalesce(k.business_date, DATE '0001-01-01'))::BIGINT AS over_limit_streak
    FROM days d LEFT JOIN last_ok k USING(master_account) GROUP BY ALL)
SELECT s.master_account, coalesce(e.history_count, 0) AS history_count, s.over_limit_streak, c.last_campaign_date
FROM streaks s LEFT JOIN events e USING(master_account) LEFT JOIN campaigns c USING(master_account);
