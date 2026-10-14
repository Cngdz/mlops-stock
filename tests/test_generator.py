import unittest
from datetime import date
import pandas as pd
import pyarrow as pa

from data_generation.generate_accounts import generate_accounts
import copy
from datetime import timedelta
from data_generation.generate_all import generate_prices, generate_events, END, HOLIDAYS, COLLATERAL_RATIOS, CAMPAIGN_CONFIG, campaign_logit_uplift
from scripts.day3_write_iceberg import normalize_timestamp_precision


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.accounts=generate_accounts(12)
        cls.accounts['account_close_date']=cls.accounts['account_close_date'].astype(object)
        cls.accounts.loc[0,'account_close_date']=date(2025,3,1)
        cls.accounts.loc[0,'account_status']='CLOSED'
        cls.accounts.loc[1,'dormant_start_date']=date(2025,4,1)
        cls.accounts.loc[1,'account_status']='DORMANT'
        cls.prices=generate_prices()
        cls.tx,cls.cf,cls.bal,cls.camp=generate_events(cls.accounts,cls.prices)

    def test_schema_and_lifecycle(self):
        self.assertTrue({'fk_cash_flow_type','fk_deliver_type'}<=set(self.cf.columns))
        self.assertEqual(self.tx.transaction_time.isna().sum(),0)
        self.assertTrue(all(self.bal.groupby('master_account').business_date.max()==END))
        closed=self.accounts.iloc[0].master_account
        after=self.bal[(self.bal.master_account==closed)&(self.bal.business_date>=date(2025,3,1))]
        self.assertEqual(after[['cash_balance','asset_value','margin_debt','margin_limit']].to_numpy().sum(),0)
        for a in self.accounts.itertuples():
            stop=a.account_close_date if pd.notna(a.account_close_date) else a.dormant_start_date
            if pd.notna(stop):
                self.assertTrue(all(self.tx.loc[self.tx.master_account==a.master_account,'transaction_time'].dt.date<stop))
                self.assertTrue(all(self.cf.loc[self.cf.master_account==a.master_account,'event_date']<stop))
        self.assertGreater(len(self.tx[self.tx.master_account==closed]),0)

    def test_account_streams_are_independent(self):
        frames=generate_events(self.accounts.iloc[:1],self.prices)
        account=self.accounts.iloc[0].master_account
        for actual,full in zip(frames,[self.tx,self.cf,self.bal,self.camp]):
            pd.testing.assert_frame_equal(actual.reset_index(drop=True),full[full.master_account==account].reset_index(drop=True))

    def test_iceberg_timestamp_preserves_instant(self):
        before=pa.Table.from_pandas(self.tx[['transaction_time']],preserve_index=False)
        after=normalize_timestamp_precision(before)
        self.assertEqual(after.schema.field('transaction_time').type,pa.timestamp('us',tz='UTC'))
        self.assertEqual(before['transaction_time'].to_pylist(),after['transaction_time'].to_pylist())

    def test_balance_formulas_and_event_accounting(self):
        self.assertTrue(all(self.bal.NAV==self.bal.asset_value+self.bal.cash_balance-self.bal.margin_debt))
        for a in self.accounts.itertuples():
            debt=0
            streak=0
            events=self.cf[(self.cf.master_account==a.master_account)&(self.cf.status=='POSTED')]
            for b in self.bal[self.bal.master_account==a.master_account].itertuples():
                for e in events[events.event_date==b.business_date].itertuples():
                    if e.fk_cash_flow_type in ['INTERM_DELIVER','TLO_DELIVER_CASH']:
                        debt+=e.amount
                    elif e.fk_cash_flow_type=='REPAYMENT':
                        debt-=e.amount
                if pd.notna(a.account_close_date) and b.business_date>=a.account_close_date:
                    debt=0
                self.assertEqual(debt,b.margin_debt)
                self.assertGreaterEqual(b.margin_debt,0)
                self.assertEqual(b.collateral_value,round(b.asset_value*COLLATERAL_RATIOS[a.risk_profile]))
                if debt==0:
                    streak=0
                elif b.business_date.weekday()<5 and b.business_date not in HOLIDAYS:
                    streak=streak+1 if debt>b.margin_limit else 0
                self.assertEqual(b.margin_status,'NO_MARGIN' if debt==0 else ('OVERDUE' if streak>=3 else 'ACTIVE'))

    def test_campaign_rules(self):
        cfg=CAMPAIGN_CONFIG
        self.assertGreater(len(self.camp),0)
        self.assertEqual(self.camp.campaign_event_id.duplicated().sum(),0)
        accounts=self.accounts.set_index('master_account')
        for account,group in self.camp.groupby('master_account'):
            a=accounts.loc[account]
            self.assertLessEqual(len(group),cfg['max_campaigns_per_account'])
            days=sorted(ts.date() for ts in group.sent_at)
            for earlier,later in zip(days,days[1:]):
                self.assertGreaterEqual((later-earlier).days,cfg['min_gap_days'])
            for day in days:
                self.assertGreaterEqual((day-a.account_open_date).days,cfg['min_days_since_open'])
                self.assertLessEqual(day,END-timedelta(days=cfg['last_send_offset_days']))
                if pd.notna(a.account_close_date):
                    self.assertLess(day,a.account_close_date)
                if pd.notna(a.dormant_start_date):
                    self.assertLess(day,a.dormant_start_date)
        self.assertTrue(set(self.camp.status)<={'DELIVERED','FAILED'})
        self.assertTrue(self.camp.interest_rate_offer.between(.065,.105).all())

    def test_campaign_uplift_window_and_failed_campaigns(self):
        cfg=CAMPAIGN_CONFIG
        sent=date(2025,5,1)
        campaign=(sent,'RATE_DISCOUNT','APP',.065)
        expected=.60+.30+.15+.80*.5
        self.assertEqual(campaign_logit_uplift(cfg,campaign,sent,.5),0.0)                     # same day: no effect
        self.assertAlmostEqual(campaign_logit_uplift(cfg,campaign,sent+timedelta(days=1),.5),expected)
        self.assertAlmostEqual(campaign_logit_uplift(cfg,campaign,sent+timedelta(days=14),.5),expected)
        self.assertEqual(campaign_logit_uplift(cfg,campaign,sent+timedelta(days=15),.5),0.0)  # D+15 outside window
        self.assertEqual(campaign_logit_uplift(cfg,None,sent+timedelta(days=3),.5),0.0)       # FAILED campaigns are never active
        disabled=copy.deepcopy(cfg); disabled['enabled']=False
        self.assertEqual(campaign_logit_uplift(disabled,campaign,sent+timedelta(days=3),.5),0.0)

    def test_zero_uplift_does_not_change_trading_stream(self):
        # Campaigns affect trading only through margin events (segment feedback),
        # so with uplift zeroed, sending campaigns must match not sending any.
        zero=copy.deepcopy(CAMPAIGN_CONFIG); u=zero['uplift']
        u['offer_effect']={k:0.0 for k in u['offer_effect']}; u['channel_effect']={k:0.0 for k in u['channel_effect']}
        u['rate_slope']=0.0; u['affinity_interaction']=0.0
        tx,_,_,camp=generate_events(self.accounts,self.prices,campaign_config=zero)
        self.assertGreater(len(camp),0)
        disabled=copy.deepcopy(CAMPAIGN_CONFIG); disabled['enabled']=False
        base=generate_events(self.accounts,self.prices,campaign_config=disabled)[0]
        pd.testing.assert_frame_equal(tx.reset_index(drop=True),base.reset_index(drop=True))

    def test_disabling_campaigns_removes_them(self):
        disabled=copy.deepcopy(CAMPAIGN_CONFIG); disabled['enabled']=False
        self.assertEqual(len(generate_events(self.accounts,self.prices,campaign_config=disabled)[3]),0)


if __name__=='__main__':
    unittest.main()
