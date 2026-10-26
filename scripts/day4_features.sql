-- Date-range frames use local calendar days, never row counts.
CREATE TABLE daily_trades AS
SELECT master_account, trade_date, count(*)::BIGINT AS trades, sum(trade_value)::BIGINT AS turnover
FROM trades GROUP BY ALL;
CREATE TABLE daily_events AS
SELECT master_account, event_day, count(*)::BIGINT AS n FROM valid_events GROUP BY ALL;

CREATE TABLE panel_base AS
SELECT b.master_account, CAST(b.business_date AS DATE) AS report_date,
       b.cash_balance::BIGINT AS cash_balance, b.asset_value::BIGINT AS asset_value,
       b.margin_debt::BIGINT AS margin_debt, b.margin_limit::BIGINT AS margin_limit,
       b.normalized_margin_status AS margin_status,
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
       c.last_campaign_date
FROM balance_label_source b JOIN customer_account a USING(master_account)
LEFT JOIN daily_trades t ON t.master_account=b.master_account AND t.trade_date=b.business_date
LEFT JOIN daily_events e ON e.master_account=b.master_account AND e.event_day=b.business_date
LEFT JOIN portfolio_daily p ON p.master_account=b.master_account AND p.business_date=b.business_date
LEFT JOIN campaign_daily c ON c.master_account=b.master_account AND c.campaign_day=b.business_date;

-- over_limit_streak counts consecutive CALENDAR days with debt above limit ending at D.
-- It approximates the generator's 3-trading-day OVERDUE rule from observable data only.
CREATE TABLE panel_reset AS
SELECT *, sum(CASE WHEN over_limit=0 THEN 1 ELSE 0 END) OVER (PARTITION BY master_account ORDER BY report_date) AS ol_reset
FROM panel_base;
CREATE TABLE panel AS
SELECT * EXCLUDE(ol_reset),
       sum(over_limit) OVER (PARTITION BY master_account, ol_reset ORDER BY report_date) AS over_limit_streak
FROM panel_reset;

-- EXCLUDE: without it the running max below would be renamed last_campaign_date_1 and scoring_features would read
-- the per-day value (campaign on D or NULL), i.e. days_since_last_campaign = 0/365 instead of the real gap.
CREATE TABLE windowed AS
SELECT * EXCLUDE(last_campaign_date), sum(trades) OVER w7 AS trade_count_7d, sum(trades) OVER w30 AS trade_count_30d,
    sum(turnover) OVER w7 AS total_trading_amount_7d, sum(turnover) OVER w30 AS total_trading_amount_30d,
    sum(CASE WHEN trades>0 THEN 1 ELSE 0 END) OVER w30 AS active_trading_days_30d,
    sum(events) OVER w30 AS recent_events,
    sum(over_limit) OVER w30 AS over_limit_days_30d,
    sum(campaigns) OVER w14 AS campaign_count_14d,
    sum(events) OVER (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS history_count,
    sum(campaigns) OVER w30 AS campaign_count_30d,
    max(last_campaign_date) OVER (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS last_campaign_date,
    coalesce(sum(events) OVER (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 1 DAY FOLLOWING AND INTERVAL 30 DAY FOLLOWING),0) AS next_events,
    coalesce(sum(events) OVER (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 1 DAY FOLLOWING AND INTERVAL 14 DAY FOLLOWING),0) AS next_events_14
FROM panel
WINDOW w7 AS (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 6 DAY PRECEDING AND CURRENT ROW),
       w14 AS (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 14 DAY PRECEDING AND CURRENT ROW),
       w30 AS (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 29 DAY PRECEDING AND CURRENT ROW);

-- ---------------------------------------------------------------------------
-- 1) Scoring features: EVERY eligible account-day up to raw_end, no label, no split.
--    Embargo days and the last 30 days (label not yet known) are kept, so batch
--    scoring always has the latest day. fs_* tables are exported from here.
--    The last three columns are internal helpers, never exported.
-- ---------------------------------------------------------------------------
CREATE TABLE scoring_features AS
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
    w.history_count, w.recent_events, w.campaign_count_14d AS campaign_count_14d_internal
FROM windowed w LEFT JOIN panel p ON p.master_account=w.master_account AND p.report_date=w.report_date-INTERVAL 7 DAY
WHERE w.report_date BETWEEN DATE '2025-02-01' AND $raw_end::DATE
  AND w.report_date>=w.account_open_date+INTERVAL 30 DAY
  AND w.report_date<coalesce(CAST(w.account_close_date AS DATE),DATE '9999-12-31')
  AND w.report_date<coalesce(CAST(w.dormant_start_date AS DATE),DATE '9999-12-31');

-- ---------------------------------------------------------------------------
-- 2) Training snapshots = scoring features JOIN labels, only where the label
--    window is complete. Features are copied from scoring_features, never
--    recomputed, so training and scoring see identical values for a key.
-- ---------------------------------------------------------------------------
CREATE TABLE snapshots AS
SELECT f.* EXCLUDE(history_count, recent_events, campaign_count_14d_internal),
    CAST(w.next_events>0 AS TINYINT) AS loan_label_next,
    -- Overdue use case: only accounts with debt or margin history, never rows already OVERDUE at D.
    -- The label is a NEW overdue spell in D+1..D+30. Rows outside the candidate set keep a NULL label.
    CAST((f.margin_debt>0 OR f.history_count>0) AND w.margin_status<>'OVERDUE' AS TINYINT) AS overdue_eligible,
    CAST(CASE WHEN (f.margin_debt>0 OR f.history_count>0) AND w.margin_status<>'OVERDUE' THEN
         EXISTS (SELECT 1 FROM balance_label_source future_balance
                 WHERE future_balance.master_account=f.master_account
                   AND future_balance.business_date>f.report_date
                   AND future_balance.business_date<=f.report_date+INTERVAL 30 DAY
                   AND future_balance.normalized_margin_status='OVERDUE') END AS TINYINT) AS overdue_label_next_30d,
    CASE WHEN f.report_date BETWEEN '2025-02-01' AND '2025-06-30' THEN 'train'
         WHEN f.report_date BETWEEN '2025-07-31' AND '2025-09-30' THEN 'validation'
         WHEN f.report_date BETWEEN '2025-10-31' AND '2025-12-31' THEN 'test' END AS split,
    f.history_count, f.recent_events, w.next_events_14 AS baseline_events_14d, f.campaign_count_14d_internal
FROM scoring_features f JOIN windowed w USING(master_account, report_date)
WHERE f.report_date<=DATE '2025-12-31'
  AND f.report_date<=$raw_end::DATE-INTERVAL 30 DAY;

CREATE TABLE candidate AS SELECT * FROM snapshots WHERE split IS NOT NULL;

-- Campaign-response grain: one DELIVERED campaign sent to an ACTIVE account.
-- Account features come from the shared candidate row of the send date, so campaigns sent
-- to dormant, closed or too-young accounts, or inside embargo, are dropped by the join.
-- campaign_count_30d and days_since_last_campaign describe campaigns BEFORE this one.
CREATE TABLE campaign_candidate AS
SELECT c.campaign_event_id, c.campaign_id, c.master_account, s.report_date,
       c.channel, c.offer_type, c.interest_rate_offer,
       s.account_age_days, s.margin_segment, s.trade_count_30d, s.total_trading_amount_30d,
       s.margin_debt, s.margin_limit, s.margin_utilization_ratio,
       s.cash_balance, s.asset_value, s.cash_to_asset_ratio, s.NAV,
       s.holding_symbol_count, s.portfolio_concentration,
       (SELECT count(*) FROM customer_campaign p
         WHERE p.master_account=c.master_account AND p.status<>'FAILED' AND p.sent_at<c.sent_at
           AND p.sent_at>=c.sent_at-INTERVAL 30 DAY)::BIGINT AS campaign_count_30d,
       coalesce(least(date_diff('day',
           (SELECT max(CAST(timezone('Asia/Ho_Chi_Minh', CAST(p.sent_at AS TIMESTAMPTZ)) AS DATE)) FROM customer_campaign p
             WHERE p.master_account=c.master_account AND p.status<>'FAILED' AND p.sent_at<c.sent_at),
           s.report_date), 365), 365)::BIGINT AS days_since_last_campaign,
       CAST(EXISTS (SELECT 1 FROM customer_campaign p WHERE p.master_account=c.master_account
                      AND p.status<>'FAILED' AND p.sent_at<c.sent_at) AS TINYINT) AS has_campaign_history,
       CAST(EXISTS (SELECT 1 FROM valid_events e
                    WHERE e.master_account=c.master_account
                      AND e.event_day>s.report_date
                      AND e.event_day<=s.report_date+INTERVAL 14 DAY) AS TINYINT) AS campaign_response_label_14d,
       s.split
FROM customer_campaign c
JOIN candidate s ON s.master_account=c.master_account
 AND s.report_date=CAST(timezone('Asia/Ho_Chi_Minh', CAST(c.sent_at AS TIMESTAMPTZ)) AS DATE)
WHERE c.status='DELIVERED'
  AND s.report_date<=$raw_end::DATE-INTERVAL 14 DAY;

-- ---------------------------------------------------------------------------
-- 3) Label tables for Feast (entity_df). Keys + labels only, features are
--    fetched from Feast at event_timestamp. event_timestamp is added on export:
--    end of day D for account-day rows, the exact sent_at for campaigns.
-- ---------------------------------------------------------------------------
CREATE TABLE loan_overdue_labels AS
SELECT master_account, report_date, loan_label_next, overdue_eligible, overdue_label_next_30d, split
FROM candidate;

-- At sent_at (e.g. 10:37 on D) the latest COMPLETE daily snapshot is D-1, so Feast
-- returns D-1 features. Sends without a D-1 snapshot (first eligible day) are dropped.
-- Campaign-history columns are request features computed per send (exclude this send).
CREATE TABLE campaign_labels AS
SELECT c.campaign_event_id, c.campaign_id, c.master_account, c.report_date AS send_date, cc.sent_at,
       c.channel, c.offer_type, c.interest_rate_offer,
       c.campaign_count_30d, c.days_since_last_campaign, CAST(c.has_campaign_history AS BIGINT) AS has_campaign_history,
       c.campaign_response_label_14d, c.split
FROM campaign_candidate c JOIN customer_campaign cc USING(campaign_event_id)
WHERE EXISTS (SELECT 1 FROM scoring_features f
              WHERE f.master_account=c.master_account AND f.report_date=CAST(c.report_date-INTERVAL 1 DAY AS DATE));
