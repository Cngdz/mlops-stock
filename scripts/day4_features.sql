-- Date-range frames use local calendar days, never row counts.
CREATE TABLE daily_trades AS
SELECT master_account, trade_date, count(*)::BIGINT AS trades, sum(trade_value)::BIGINT AS turnover
FROM trades GROUP BY ALL;
CREATE TABLE daily_events AS
SELECT master_account, event_day, count(*)::BIGINT AS n FROM valid_events GROUP BY ALL;

CREATE TABLE panel AS
SELECT b.master_account, CAST(b.business_date AS DATE) AS report_date,
       b.cash_balance::BIGINT AS cash_balance, b.asset_value::BIGINT AS asset_value,
       b.margin_debt::BIGINT AS margin_debt, b.margin_limit::BIGINT AS margin_limit,
       a.account_open_date, a.account_close_date, a.dormant_start_date, a.risk_profile,
       coalesce(t.trades,0)::BIGINT AS trades, coalesce(t.turnover,0)::BIGINT AS turnover,
       coalesce(e.n,0)::BIGINT AS events
FROM margin_balance_daily b JOIN customer_account a USING(master_account)
LEFT JOIN daily_trades t ON t.master_account=b.master_account AND t.trade_date=b.business_date
LEFT JOIN daily_events e ON e.master_account=b.master_account AND e.event_day=b.business_date;

CREATE TABLE windowed AS
SELECT *, sum(trades) OVER w7 AS trade_count_7d, sum(trades) OVER w30 AS trade_count_30d,
    sum(turnover) OVER w7 AS total_trading_amount_7d, sum(turnover) OVER w30 AS total_trading_amount_30d,
    sum(CASE WHEN trades>0 THEN 1 ELSE 0 END) OVER w30 AS active_trading_days_30d,
    sum(events) OVER w30 AS recent_events,
    sum(events) OVER (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS history_count,
    coalesce(sum(events) OVER (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 1 DAY FOLLOWING AND INTERVAL 30 DAY FOLLOWING),0) AS next_events
FROM panel
WINDOW w7 AS (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 6 DAY PRECEDING AND CURRENT ROW),
       w30 AS (PARTITION BY master_account ORDER BY report_date RANGE BETWEEN INTERVAL 29 DAY PRECEDING AND CURRENT ROW);

CREATE TABLE snapshots AS
SELECT w.master_account, w.report_date,
    date_diff('day',w.account_open_date,w.report_date)::BIGINT AS account_age_days,
    CASE WHEN w.margin_debt>0 OR w.recent_events>0 THEN 'au'
         WHEN w.history_count>0 THEN 'lu' ELSE 'nu' END AS margin_segment,
    w.trade_count_7d::BIGINT AS trade_count_7d, w.trade_count_30d::BIGINT AS trade_count_30d,
    w.total_trading_amount_7d::BIGINT AS total_trading_amount_7d,
    w.total_trading_amount_30d::BIGINT AS total_trading_amount_30d,
    w.active_trading_days_30d::BIGINT AS active_trading_days_30d,
    w.margin_debt, w.margin_limit,
    CASE WHEN w.margin_limit=0 THEN 0.0 ELSE w.margin_debt::DOUBLE/w.margin_limit END AS margin_utilization_ratio,
    (w.margin_debt-p.margin_debt)::BIGINT AS debt_change_7d,
    w.cash_balance,w.asset_value,
    round(w.asset_value * CASE w.risk_profile WHEN 'LOW' THEN 0.60 WHEN 'MEDIUM' THEN 0.70 WHEN 'HIGH' THEN 0.80 END)::BIGINT AS collateral_value,
    CASE WHEN w.asset_value=0 THEN 0.0 ELSE w.cash_balance::DOUBLE/w.asset_value END AS cash_to_asset_ratio,
    (w.asset_value+w.cash_balance-w.margin_debt)::BIGINT AS NAV,
    CAST(w.next_events>0 AS TINYINT) AS loan_label_next,
    CASE WHEN w.report_date BETWEEN '2025-02-01' AND '2025-06-30' THEN 'train'
         WHEN w.report_date BETWEEN '2025-07-31' AND '2025-09-30' THEN 'validation'
         WHEN w.report_date BETWEEN '2025-10-31' AND '2025-12-31' THEN 'test' END AS split,
    w.history_count, w.recent_events
FROM windowed w LEFT JOIN panel p ON p.master_account=w.master_account AND p.report_date=w.report_date-INTERVAL 7 DAY
WHERE w.report_date BETWEEN DATE '2025-02-01' AND DATE '2025-12-31'
  AND w.report_date>=w.account_open_date+INTERVAL 30 DAY
  AND w.report_date<coalesce(w.account_close_date,DATE '9999-12-31')
  AND w.report_date<coalesce(w.dormant_start_date,DATE '9999-12-31')
  AND w.report_date<=$raw_end::DATE-INTERVAL 30 DAY;

CREATE TABLE candidate AS SELECT * FROM snapshots WHERE split IS NOT NULL;
