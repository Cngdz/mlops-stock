import unittest
from datetime import date
import pandas as pd
import pyarrow as pa

from data_generation.generate_accounts import generate_accounts
from data_generation.generate_all import generate_prices, generate_events, END, HOLIDAYS, COLLATERAL_RATIOS
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
        cls.tx,cls.cf,cls.bal=generate_events(cls.accounts,cls.prices)

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
        for actual,full in zip(frames,[self.tx,self.cf,self.bal]):
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


if __name__=='__main__':
    unittest.main()
