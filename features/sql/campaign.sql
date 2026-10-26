-- campaign_response grain: one DELIVERED send. Shared by training (campaign_accounts = training rows) and batch
-- scoring (campaign_accounts = the fs_* rows of day T), so both see the same values for a send.
-- Account features come from the account row of the send date: sends to dormant, closed or too-young accounts have
-- no such row and are dropped by the join. Campaign-history columns describe the sends BEFORE this one.
CREATE OR REPLACE TABLE campaign_rows AS
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
                      AND p.status<>'FAILED' AND p.sent_at<c.sent_at) AS TINYINT) AS has_campaign_history
FROM customer_campaign c
JOIN campaign_accounts s ON s.master_account=c.master_account
 AND s.report_date=CAST(timezone('Asia/Ho_Chi_Minh', CAST(c.sent_at AS TIMESTAMPTZ)) AS DATE)
WHERE c.status='DELIVERED';
