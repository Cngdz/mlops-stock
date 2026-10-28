-- Features for report_date in [$start, $end] from Gold rows of [$lookback_start, $end] plus seed_state.
-- Inputs: the views of features/gold.py normalize() and
--   seed_state(master_account, history_count, over_limit_streak, last_campaign_date) = accumulated values at $start - 1,
--   rebuilt from the small Gold tables by bootstrap_state.sql on every run.
-- Output: scoring_features (the fs_* rows of [$start, $end]).
-- Windows use local calendar days, never row counts. $lookback_start = $start - 30 days covers every window:
-- 30-day frames reach D-29, 7-day frames D-6, debt_change_7d reads D-7.
CREATE OR REPLACE TABLE w_daily_trades AS
SELECT master_account, trade_date, count(*)::BIGINT AS trades, sum(trade_value)::BIGINT AS turnover
FROM trades WHERE trade_date BETWEEN $lookback_start AND $end GROUP BY ALL;

CREATE OR REPLACE TABLE w_daily_events AS
SELECT master_account, event_day, count(*)::BIGINT AS n
FROM valid_events WHERE event_day BETWEEN $lookback_start AND $end GROUP BY ALL;

CREATE OR REPLACE TABLE w_campaign_daily AS
SELECT master_account, CAST(sent_at AS DATE) AS campaign_day, count(*)::BIGINT AS campaigns
FROM customer_campaign
WHERE status <> 'FAILED' AND CAST(sent_at AS DATE) BETWEEN $lookback_start AND $end GROUP BY ALL;

CREATE OR REPLACE TABLE w_panel_base AS
SELECT b.master_account, b.business_date AS report_date,
       b.cash_balance::BIGINT AS cash_balance, b.asset_value::BIGINT AS asset_value,
       b.margin_debt::BIGINT AS margin_debt, b.margin_limit::BIGINT AS margin_limit,
       b.margin_status,
       CAST(b.margin_debt>b.margin_limit AS TINYINT) AS over_limit,
       a.account_open_date, a.account_close_date, a.dormant_start_date, a.risk_profile,
       coalesce(t.trades,0)::BIGINT AS trades, coalesce(t.turnover,0)::BIGINT AS turnover,
       coalesce(e.n,0)::BIGINT AS events,
       coalesce(p.portfolio_value,0)::BIGINT AS portfolio_value,
       coalesce(p.holding_symbol_count,0)::BIGINT AS holding_symbol_count,
       coalesce(p.portfolio_concentration,0.0) AS portfolio_concentration,
       coalesce(p.unrealized_loss_ratio,0.0) AS unrealized_loss_ratio,
       coalesce(p.risky_asset_ratio,0.0) AS risky_asset_ratio,
       coalesce(c.campaigns,0)::BIGINT AS campaigns,
       c.campaign_day
FROM balances b JOIN customer_account a USING(master_account)
LEFT JOIN w_daily_trades t ON t.master_account=b.master_account AND t.trade_date=b.business_date
LEFT JOIN w_daily_events e ON e.master_account=b.master_account AND e.event_day=b.business_date
LEFT JOIN portfolio_daily p ON p.master_account=b.master_account AND p.business_date=b.business_date
LEFT JOIN w_campaign_daily c ON c.master_account=b.master_account AND c.campaign_day=b.business_date
WHERE b.business_date BETWEEN $lookback_start AND $end;

-- Unbounded-history values continue the seed (the big tables are still read for 30 days only):
--   history_count      = seed + valid events of [$start, D]
--   over_limit_streak  = consecutive CALENDAR days with debt above limit ending at D; the seed is added only while
--                        no day of [$start, D] broke the streak (ol_reset = 0). It approximates the generator's
--                        3-trading-day OVERDUE rule from observable data only.
--   last_campaign_date = max(seed, campaigns in the window): campaigns before $start are already in the seed.
CREATE OR REPLACE TABLE w_panel AS
WITH reset AS (
    SELECT *, sum(CASE WHEN over_limit=0 AND report_date>=$start THEN 1 ELSE 0 END)
                  OVER (PARTITION BY master_account ORDER BY report_date) AS ol_reset
    FROM w_panel_base)
SELECT r.* EXCLUDE(ol_reset, campaign_day),
       sum(CASE WHEN r.report_date>=$start THEN r.over_limit ELSE 0 END)
           OVER (PARTITION BY r.master_account, r.ol_reset ORDER BY r.report_date)
         + CASE WHEN r.ol_reset=0 THEN coalesce(s.over_limit_streak,0) ELSE 0 END AS over_limit_streak,
       coalesce(s.history_count,0)
         + sum(CASE WHEN r.report_date>=$start THEN r.events ELSE 0 END)
               OVER (PARTITION BY r.master_account ORDER BY r.report_date
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS history_count,
       greatest(s.last_campaign_date,
                max(r.campaign_day) OVER (PARTITION BY r.master_account ORDER BY r.report_date
                                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS last_campaign_date
FROM reset r LEFT JOIN seed_state s USING(master_account);

CREATE OR REPLACE TABLE w_windowed AS
SELECT *, sum(trades) OVER w7 AS trade_count_7d, sum(trades) OVER w30 AS trade_count_30d,
    sum(turnover) OVER w7 AS total_trading_amount_7d, sum(turnover) OVER w30 AS total_trading_amount_30d,
    sum(CASE WHEN trades>0 THEN 1 ELSE 0 END) OVER w30 AS active_trading_days_30d,
    sum(events) OVER w30 AS recent_events,
    sum(over_limit) OVER w30 AS over_limit_days_30d,
    sum(campaigns) OVER w30 AS campaign_count_30d
FROM w_panel
WINDOW w7 AS (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 6 DAY PRECEDING AND CURRENT ROW),
       w30 AS (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 29 DAY PRECEDING AND CURRENT ROW);

-- Every eligible account-day of [$start, $end]: ACTIVE, at least 30 days old. No label, no split.
CREATE OR REPLACE TABLE scoring_features AS
SELECT w.master_account, w.report_date,
    date_diff('day',w.account_open_date,w.report_date)::BIGINT AS account_age_days,
    CASE WHEN w.margin_debt>0 OR w.recent_events>0 THEN 'au'
         WHEN w.history_count>0 THEN 'lu' ELSE 'nu' END AS margin_segment,
    w.trade_count_7d::BIGINT AS trade_count_7d, w.trade_count_30d::BIGINT AS trade_count_30d,
    w.total_trading_amount_7d::BIGINT AS total_trading_amount_7d,
    w.total_trading_amount_30d::BIGINT AS total_trading_amount_30d,
    w.active_trading_days_30d::BIGINT AS active_trading_days_30d,
    w.margin_debt, w.margin_limit,
    w.over_limit_streak::BIGINT AS over_limit_streak, w.over_limit_days_30d::BIGINT AS over_limit_days_30d,
    CASE WHEN w.margin_limit=0 THEN 0.0 ELSE w.margin_debt::DOUBLE/w.margin_limit END AS margin_utilization_ratio,
    (w.margin_debt-p.margin_debt)::BIGINT AS debt_change_7d,
    w.cash_balance,w.asset_value,
    round(w.asset_value * CASE w.risk_profile WHEN 'LOW' THEN 0.60 WHEN 'MEDIUM' THEN 0.70 WHEN 'HIGH' THEN 0.80 END)::BIGINT AS collateral_value,
    CASE WHEN w.asset_value=0 THEN 0.0 ELSE w.cash_balance::DOUBLE/w.asset_value END AS cash_to_asset_ratio,
    (w.asset_value+w.cash_balance-w.margin_debt)::BIGINT AS NAV,
    w.portfolio_value, w.holding_symbol_count, w.portfolio_concentration,
    w.unrealized_loss_ratio, w.risky_asset_ratio,
    w.campaign_count_30d::BIGINT AS campaign_count_30d,
    coalesce(least(date_diff('day', w.last_campaign_date, w.report_date), 365), 365)::BIGINT AS days_since_last_campaign,
    CAST(w.last_campaign_date IS NOT NULL AS BIGINT) AS has_campaign_history,
    w.margin_status
FROM w_windowed w LEFT JOIN w_panel p ON p.master_account=w.master_account AND p.report_date=w.report_date-INTERVAL 7 DAY
WHERE w.report_date BETWEEN $start AND $end
  AND w.report_date>=w.account_open_date+INTERVAL 30 DAY
  AND w.report_date<coalesce(CAST(w.account_close_date AS DATE),DATE '9999-12-31')
  AND w.report_date<coalesce(CAST(w.dormant_start_date AS DATE),DATE '9999-12-31');
