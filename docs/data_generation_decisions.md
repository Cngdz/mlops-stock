# Data Generation Decision Baseline

## 0. Mục đích

Đây là bộ quyết định làm **nguồn chuẩn duy nhất** để lập trình generator dữ liệu synthetic cho bài toán dự báo nhu cầu vay margin/MBLink. Các giá trị được chốt cho MVP demo trên laptop; không phải thông số production và không được dùng để kết luận kinh doanh thật.

Khi có mâu thuẫn với tài liệu mô tả trước đó, các quyết định trong file này được ưu tiên.

Nguyên tắc:

- Mọi tham số nghiệp vụ quan trọng nằm trong config hoặc công thức canonical của file này; giá trị thực tế và checksum phải được ghi vào `generation_run.json`.
- Cùng config và cùng seed phải cho cùng dữ liệu.
- Thay một giá trị đã chốt phải tăng `generator_version` và ghi lý do.
- Biến ẩn chỉ dùng để sinh dữ liệu, không xuất thành feature hoặc label.

## 1. Cấu hình chính đã chốt

```yaml
generator_version: "0.1.0"
seed: 42
num_accounts: 5000
timezone: "Asia/Ho_Chi_Minh"
currency: "VND"
raw_start: "2025-01-01"
raw_end: "2026-01-30"          # 12 tháng quan sát + 30 ngày label tail
observation_start: "2025-01-01"
observation_end: "2025-12-31"
label_window_days: 30
snapshot_frequency: "daily"
snapshot_warmup_days: 30
max_event_date_policy: "configured_raw_end"
report_start: "2025-02-01"
report_end: "2025-12-31"
train_start: "2025-02-01"
train_end: "2025-06-30"
train_val_embargo_days: 30
validation_start: "2025-07-31"
validation_end: "2025-09-30"
validation_test_embargo_days: 30
test_start: "2025-10-31"
test_end: "2025-12-31"
trade_value_tolerance_vnd: 1
cancelled_rate: 0.02
min_event_amount_vnd: 1000000
min_margin_limit_vnd: 5000000
max_margin_limit_vnd: 500000000
repayment_probability_if_debt: 0.05
repayment_ratio_mean: 0.15
repayment_ratio_sigma: 0.05
positive_rate_targets:
  nu: 0.15
  lu: 0.25
  au: 0.35
positive_rate_tolerance: 0.03
calibration_method: "deterministic_bisection"
calibration_scope: "segment_effect_margin"
calibration_intercept_lower: -7.0
calibration_intercept_upper: -2.0
calibration_max_iterations: 8

calendar:
  fixed_holidays: ["2025-01-01", "2025-04-30", "2025-05-01", "2025-09-02", "2026-01-01"]

account_generation:
  open_date_start: "2025-01-01"
  open_date_end: "2025-01-31"
  close_date_start: "2025-10-01"
  close_date_end: "2025-11-30"
  dormant_date_start: "2025-09-01"
  dormant_date_end: "2025-11-30"
  status_at_raw_end: {ACTIVE: 0.95, DORMANT: 0.04, CLOSED: 0.01}
  customer_group: {RETAIL: 0.85, VIP: 0.10, CORPORATE: 0.05}
  risk_profile: {LOW: 0.30, MEDIUM: 0.50, HIGH: 0.20}
  latent_archetype: {NU_LIKELY: 0.45, LU_LIKELY: 0.30, AU_LIKELY: 0.25}

trade_generation:
  trade_intercept: -2.40
  trading_propensity_coef: 1.60
  activity_stability_coef: 0.50
  segment_effect: {nu: -0.30, lu: 0.00, au: 0.30}
  day_noise_sigma: 0.25
  lambda_base: 0.20
  lambda_coef: 5.0
  lambda_max: 8.0
  transactions_per_day_max: 20
  buy_probability: 0.55
  quantity_lognormal_mean: 6.0
  quantity_lognormal_sigma: 0.8
  quantity_min: 10
  quantity_max: 100000
  trading_start: "09:00:00"
  trading_end: "14:45:00"

margin_event_generation:
  base_intercept: -4.60
  margin_affinity_coef: 1.40
  recent_trade_activity_coef: 1.00
  wealth_level_coef: 0.60
  risk_appetite_coef: 0.40
  segment_effect: {nu: -0.80, lu: 0.00, au: 0.80}
  day_noise_sigma: 0.20
  valid_probability: 0.85
  non_target_probability: 0.15
  product_probability: {MARGIN_MBS: 0.70, MBLINK: 0.30}
  non_target_type_probability: {FEE: 0.60, OTHER: 0.40}
  recent_trade_count_cap: 30
  recent_trade_amount_cap_vnd: 50000000
  amount_ratio_min: 0.20
  amount_ratio_max: 0.60
  fee_amount_min_vnd: 10000
  fee_amount_max_vnd: 500000
  other_amount_min_vnd: 100000
  other_amount_max_vnd: 5000000

price_generation:
  initial_min: 10000
  initial_max: 150000
  return_mu: 0.0002
  return_sigma: 0.02
  price_floor: 1000
  price_ceiling: 500000

repayment_generation:
  probability_if_active_and_debt: 0.05
  ratio_mean: 0.15
  ratio_sigma: 0.05
  minimum_amount: 1000000

balance_generation:
  initial_asset_lognormal_mean: 17.5
  initial_asset_lognormal_sigma: 0.7
  initial_asset_min_vnd: 10000000
  initial_asset_max_vnd: 500000000
  initial_cash_ratio_min: 0.20
  initial_cash_ratio_max: 0.60
  collateral_ratio: {LOW: 0.60, MEDIUM: 0.70, HIGH: 0.80}
  collateral_to_limit_ratio: 0.50
```

`max_event_date` dùng cho cắt label là global configured `raw_end`, không phải `MAX(event_date)` quan sát được theo từng tài khoản.

Quy ước kiểu dữ liệu: mọi cột tiền (`trade_value`, `amount`, `margin_debt`, `margin_limit`, `asset_value`, `cash_balance`, `collateral_value`, `NAV`) lưu `int64` theo VND và làm tròn tới VND gần nhất; `price` lưu `float64` với 2 chữ số thập phân; các ratio lưu `float64`; label lưu `int8`.

## 2. Lịch ngày giao dịch

Ngày giao dịch là Monday–Friday và không nằm trong danh sách nghỉ synthetic cố định:

```text
2025-01-01
2025-04-30
2025-05-01
2025-09-02
2026-01-01
```

Không mô phỏng nửa ngày giao dịch trong MVP. Đây là lịch synthetic để tái lập, không tuyên bố là lịch nghỉ chính thức.

`margin_balance_daily` ghi một dòng cho mọi ngày lịch từ `account_open_date` đến `raw_end`, bao gồm cuối tuần và ngày nghỉ, bằng cách carry-forward số dư gần nhất. `stock_transaction` và `margin_cash_flow` chỉ phát sinh trên ngày giao dịch theo calendar này.

## 3. RNG và tái lập

Seed gốc là `42`. Seed con theo entity/stream/date được tính bằng:

```text
entity_seed = uint64(
    SHA256("{global_seed}:{master_account}:{stream}:{date_or_null}")[0:16]
)
```

Stream tối thiểu:

```text
account_attributes, trading, price, cash_flow, balance, snapshot
```

Không dùng duy nhất một RNG tuần tự cho toàn bộ dataset. Cách trên đảm bảo thêm tài khoản mới không làm thay đổi dữ liệu tài khoản cũ.

## 4. Tài khoản và trạng thái

- Có đúng `5_000` tài khoản.
- `master_account` là chuỗi 10 chữ số từ `0000000001` đến `0000005000`.
- `transaction_id = TXN-{master_account}-{YYYYMMDD}-{sequence:05d}`.
- `cash_flow_id = CF-{master_account}-{YYYYMMDD}-{sequence:03d}`.
- Sequence bắt đầu từ `001` cho từng account-day; thứ tự cấp là repayment trước, disbursement sau. Transaction sequence sắp theo `transaction_time`.
- `account_open_date ~ Uniform(2025-01-01, 2025-01-31)`.
- Trạng thái tại `raw_end`: `ACTIVE=95%`, `DORMANT=4%`, `CLOSED=1%`.
- `account_close_date` chỉ có với `CLOSED`, Uniform trong `2025-10-01` đến `2025-11-30`.
- `dormant_start_date` chỉ có với `DORMANT`, Uniform trong `2025-09-01` đến `2025-11-30`.
- Không đóng/dormant trước khi tài khoản tồn tại tối thiểu 180 ngày.

Trạng thái tại một ngày được suy ra:

```text
if report_date >= account_close_date: CLOSED
else if report_date >= dormant_start_date: DORMANT
else: ACTIVE
```

Candidate snapshot phục vụ model chỉ lấy tài khoản `ACTIVE` tại `report_date`. Sau ngày dormant/closed không sinh transaction hoặc cash flow mới; vẫn giữ balance rows đến `raw_end` để có dense daily panel.

Phân phối thuộc tính ổn định:

```text
customer_group: RETAIL=0.85, VIP=0.10, CORPORATE=0.05
risk_profile:   LOW=0.30, MEDIUM=0.50, HIGH=0.20
```

`customer_group` và `risk_profile` được sample độc lập; không có quy tắc ngầm rằng một nhóm khách hàng luôn có một risk profile cụ thể.

`created_at` là timestamp cố định `2025-01-01T00:00:00+07:00`, không lấy thời gian thực lúc chạy generator.

## 5. Biến ẩn và phân phối

Generator tạo `latent_archetype` nội bộ, không xuất ra bất kỳ bảng nào:

```text
NU_LIKELY=0.45, LU_LIKELY=0.30, AU_LIKELY=0.25
```

| Biến ẩn | NU_LIKELY | LU_LIKELY | AU_LIKELY |
|---|---|---|---|
| `wealth_level` | Beta(2.5,2.5) | Beta(2.5,2.5) | Beta(2.5,2.5) |
| `trading_propensity` | Beta(2.0,5.0) | Beta(2.5,4.0) | Beta(3.0,3.0) |
| `margin_affinity` | Beta(1.5,8.0) | Beta(3.0,5.0) | Beta(6.0,3.0) |
| `risk_appetite` | Beta(2.0,5.0) | Beta(3.0,4.0) | Beta(4.0,3.0) |
| `activity_stability` | Beta(4.0,2.0) | Beta(4.0,2.0) | Beta(4.0,2.0) |

Các biến đều nằm trong `[0,1]`. Archetype chỉ là prior; segment chính thức vẫn phải suy ra từ lịch sử đến `report_date`.

## 6. Universe mã cổ phiếu và giá

Universe gồm đúng 30 mã synthetic:

```text
SYN001, SYN002, SYN003, SYN004, SYN005,
SYN006, SYN007, SYN008, SYN009, SYN010,
SYN011, SYN012, SYN013, SYN014, SYN015,
SYN016, SYN017, SYN018, SYN019, SYN020,
SYN021, SYN022, SYN023, SYN024, SYN025,
SYN026, SYN027, SYN028, SYN029, SYN030
```

Mỗi transaction chọn `symbol` theo phân phối Uniform trên 30 mã; không có mã nào được ưu tiên trong MVP.

Giá khởi tạo mỗi mã:

```text
price_0 ~ Uniform(10,000, 150,000) VND
```

Với mỗi ngày giao dịch:

```text
r_t ~ Normal(mu=0.0002, sigma=0.02)
price_t = clip(price_(t-1) * exp(r_t), 1,000, 500,000)
price_t = round(price_t, 2)
```

Giá không âm và không vượt range sau clip. RNG giá dùng seed theo `symbol + date`.

## 7. Sinh `stock_transaction`

### 7.1 Tần suất giao dịch

`p_trade_day` là xác suất một tài khoản có hoạt động trong một ngày giao dịch, tính sau khi xác định segment hiện tại:

```text
segment_effect_trade: nu=-0.30, lu=0.00, au=+0.30
day_noise_trade ~ Normal(0, 0.25)

p_trade_day = sigmoid(
    -2.40
    + 1.60 * trading_propensity
    + 0.50 * activity_stability
    + segment_effect_trade[current_segment]
    + day_noise_trade
)
```

Trước khi tài khoản có valid margin event nào, `current_segment` mặc định là `nu`.

Nếu Bernoulli(`p_trade_day`) bằng 1:

```text
lambda_day = clip(0.20 + 5.0 * p_trade_day, 0.20, 8.0)
num_transactions ~ Poisson(lambda_day)
num_transactions = min(num_transactions, 20)
```

Mục tiêu kiểm tra sau sinh: trung bình giao dịch/tài khoản/tháng là `15–35` cho `nu`, `25–60` cho `lu`, `40–90` cho `au`, và `20–100` cho toàn bộ. Nếu lệch, điều chỉnh intercept/hệ số, không thay seed.

### 7.2 Thuộc tính giao dịch

```text
side ~ Bernoulli(BUY=0.55, SELL=0.45)
quantity ~ LogNormal(mean=6.0, sigma=0.8)
quantity = clip(round(quantity), 10, 100,000)
transaction_time ~ Uniform(09:00:00, 14:45:00) theo Asia/Ho_Chi_Minh
price = giá của symbol tại ngày giao dịch
trade_value = round(quantity * price) tới VND gần nhất
```

Ràng buộc:

```text
abs(trade_value - round(quantity * price)) <= 1 VND
```

### 7.3 `is_margin_buy`

`is_margin_buy` không được xuất trong Gold `stock_transaction` vì có thể trở thành proxy trực tiếp cho label. Generator chỉ được dùng cờ nội bộ `internal_margin_candidate`; cờ này phải bị loại trước khi ghi Parquet.

## 8. Sinh `margin_cash_flow`

### 8.1 Tần suất event

`p_margin_event` là xác suất **một disbursement opportunity trên mỗi tài khoản-ngày giao dịch**, tính sau khi transaction ngày đó đã được sinh. Mỗi tài khoản-ngày tối đa một disbursement opportunity và không chạy Bernoulli cho từng transaction. Repayment được sinh bằng process độc lập ở §8.5.

```text
recent_trade_activity =
    0.5 * min(trade_count_30d / 30, 1.0)
    + 0.5 * min(total_trading_amount_30d / 50,000,000, 1.0)
```

```text
segment_effect_margin: nu=-0.80, lu=0.00, au=+0.80
day_noise_margin ~ Normal(0, 0.20)

p_margin_event = sigmoid(
    -4.60
    + 1.40 * margin_affinity
    + 1.00 * recent_trade_activity
    + 0.60 * wealth_level
    + 0.40 * risk_appetite
    + segment_effect_margin[current_segment]
    + day_noise_margin
)
```

Chỉ xét event khi tài khoản `ACTIVE` và có ít nhất một `BUY` trong 7 ngày gần nhất.

### 8.2 Loại event

Sau Bernoulli(`p_margin_event`) bằng 1:

```text
valid event:      0.85
non-target event: 0.15
```

Valid event:

```text
MARGIN_MBS + INTERM_DELIVER + BUY_SHARE (0.70)
MBLINK     + TLO_DELIVER_CASH + BUY   (0.30)
```

Non-target disbursement dùng các tổ hợp không tạo label, ví dụ:

```text
MBLINK     + FEE   + OTHER (0.60)
OTHER      + OTHER + OTHER (0.40)
```

Amount và tác động của non-target cash flow:

```text
FEE:
    amount ~ Uniform(10,000, 500,000), làm tròn VND
    chỉ làm giảm cash_balance nếu status = POSTED
    không thay đổi margin_debt

OTHER:
    amount ~ Uniform(100,000, 5,000,000), làm tròn VND
    không thay đổi cash_balance hoặc margin_debt
```

### 8.3 Tỷ lệ cancelled

Sau khi tạo mỗi cash-flow event (disbursement hoặc repayment):

```text
status = CANCELLED với xác suất 0.02
status = POSTED    với xác suất 0.98
```

`CANCELLED` không làm tăng dư nợ và không tạo label dương.

Chi tiết hiệu lực:

```text
CANCELLED disbursement: không tăng margin_debt và không tăng cash_balance
CANCELLED repayment:    không giảm margin_debt và không giảm cash_balance
CANCELLED FEE:          không giảm cash_balance
```

### 8.4 Công thức amount

Valid disbursement:

```text
latest_buy_value = BUY gần nhất trong 7 ngày
margin_debt_after_repayment = max(0, margin_debt_before_day - repayment_amount_effective)
available_limit = max(0, margin_limit_before_event - margin_debt_after_repayment)
requested_ratio ~ Uniform(0.20, 0.60)
requested_amount = requested_ratio * latest_buy_value
amount = min(requested_amount, available_limit)
```

Nếu ngày đó không có repayment thì quy ước `repayment_amount = 0`.

Nếu `available_limit < 1,000,000` thì bỏ event. Ngược lại:

```text
amount = max(1,000,000, round(amount))
```

Repayment được sinh độc lập ở §8.5, không nằm trong Bernoulli disbursement opportunity.

### 8.5 Cadence repayment độc lập

Repayment không phụ thuộc vào việc tài khoản có BUY trong 7 ngày hay không. Với mỗi account-day, kể cả ngày không giao dịch:

```text
p_repayment_day = repayment_probability_if_debt (0.05) nếu status_at_day = ACTIVE và margin_debt_before_day > 0
                  0.00 trong mọi trường hợp khác
```

Nếu Bernoulli(`p_repayment_day`) bằng 1:

```text
repayment_ratio ~ Normal(0.15, 0.05)
repayment_amount = round(repayment_ratio * margin_debt_before_day)
if margin_debt_before_day < 1,000,000:
    repayment_amount = margin_debt_before_day
else:
    repayment_amount = clip(repayment_amount, 1,000,000, margin_debt_before_day)
repayment_amount_effective = repayment_amount nếu status = POSTED, ngược lại 0
```

Mỗi ngày tối đa một repayment event. Repayment dùng `margin_debt_before_day`, sau đó disbursement dùng hạn mức còn lại; không có vòng lặp giữa hai event.

## 9. Sinh `margin_balance_daily`

### 9.1 Khởi tạo

```text
asset_value_0 = round(clip(exp(Normal(17.5, 0.7)), 10,000,000, 500,000,000))
cash_balance_0 = round(asset_value_0 * Uniform(0.20, 0.60))
margin_debt_0 = 0
```

### 9.2 Ý nghĩa và thứ tự xử lý hằng ngày

`asset_value` được định nghĩa là **giá trị thị trường của danh mục cổ phiếu, không bao gồm tiền mặt**. `cash_balance` là tiền mặt; `NAV` là tài sản ròng sau khi trừ dư nợ.

Mỗi ngày xử lý đúng thứ tự:

```text
1. Carry-forward balance từ ngày trước
2. Xác định status/segment đầu ngày từ dữ liệu đến ngày t-1
3. Sinh market return và giá cổ phiếu
4. Sinh stock transactions
5. Tính trading activity 7d/30d
6. Sinh repayment độc lập
7. Sinh disbursement opportunity
8. Cập nhật cash_balance, asset_value, margin_debt
9. Tính margin_limit và margin_status cuối ngày
```

Event ngày `t` chỉ ảnh hưởng đến segment từ ngày `t+1`.

### 9.3 Cập nhật số dư

```text
market_return ~ Normal(0.0002, 0.01) nếu là ngày giao dịch
market_return = 0 nếu là cuối tuần hoặc fixed holiday
buy_value  = tổng BUY trong ngày
sell_value = tổng SELL trong ngày
disbursement = tổng valid POSTED disbursement trong ngày
repayment = tổng POSTED repayment trong ngày
fee_amount = tổng POSTED FEE trong ngày

cash_balance_t = max(
    0,
    cash_balance_(t-1) + sell_value - buy_value
    + disbursement - repayment - fee_amount
)

asset_value_t = max(
    0,
    asset_value_(t-1) * (1 + market_return)
    + buy_value - sell_value
)
```

```text
NAV_t = asset_value_t + cash_balance_t - margin_debt_t
```

Ngày không giao dịch giữ giá trị danh mục và giao dịch gần nhất; `buy_value=sell_value=0`, `market_return=0`, nhưng repayment hợp lệ vẫn có thể cập nhật dư nợ/tiền mặt. FEE hợp lệ cũng trừ tiền mặt.

### 9.4 Hạn mức margin

Hạn mức được tính lại mỗi `business_date`. `margin_limit_before_event` là hạn mức tính từ giá trị danh mục sau market return và transaction trong ngày, trước repayment và disbursement:

```text
collateral_ratio: LOW=0.60, MEDIUM=0.70, HIGH=0.80
asset_value_pre_event =
    asset_value_(t-1) * (1 + market_return)
    + buy_value - sell_value
collateral_value_pre_event =
    asset_value_pre_event * collateral_ratio[risk_profile]
margin_limit_before_event = 0 nếu asset_value_pre_event <= 0
                             clip(0.50 * collateral_value_pre_event,
                                  5,000,000,
                                  500,000,000) nếu asset_value_pre_event > 0

collateral_value_t = asset_value_t * collateral_ratio[risk_profile]
margin_limit_t = 0 nếu asset_value_t <= 0
                 clip(0.50 * collateral_value_t,
                      5,000,000,
                      500,000,000) nếu asset_value_t > 0
```

Với tài khoản `DORMANT` hoặc `CLOSED` tại ngày đó, `margin_limit_t = 0`.

### 9.5 Dư nợ

```text
margin_debt_t = max(
    0,
    margin_debt_(t-1)
    + valid_posted_disbursement_t
    - posted_repayment_t
)
```

`CANCELLED` event không được đưa vào công thức.

### 9.6 `margin_status`

Theo dõi biến nội bộ `over_limit_streak`:

```text
if margin_debt_t == 0:
    margin_status = NO_MARGIN
    over_limit_streak = 0
elif margin_debt_t > margin_limit_t:
    over_limit_streak += 1
    margin_status = OVERDUE nếu over_limit_streak >= 3, ngược lại ACTIVE
else:
    over_limit_streak = 0
    margin_status = ACTIVE
```

`OVERDUE` nghĩa là dư nợ vượt hạn mức ít nhất 3 ngày giao dịch liên tiếp. Cuối tuần/ngày nghỉ không tăng streak và không reset streak; chỉ ngày giao dịch mới được đánh giá.

### 9.7 Dormant và closed

- Trước ngày dormant/closed, tài khoản hoạt động bình thường.
- Không ghi transaction, cash flow hoặc balance trước `account_open_date`.
- Từ ngày dormant/closed trở đi, không sinh transaction hoặc cash flow mới.
- Vẫn ghi balance row đến `raw_end` để giữ dense daily panel.
- Sau ngày đóng, set `margin_debt=0`, `margin_limit=0`, `cash_balance=0`, `asset_value=0`, `margin_status=NO_MARGIN`.

## 10. Segment tại từng `report_date`

Valid margin event là event `POSTED` thuộc một trong hai tổ hợp hợp lệ ở §8.2. Segment chỉ được tính từ lịch sử đến `report_date`:

```text
au = margin_debt(report_date) > 0
     OR có valid event trong 30 ngày trước report_date

lu = đã từng có valid event trước report_date
     AND margin_debt(report_date) = 0
     AND không có valid event trong 30 ngày trước report_date

nu = chưa từng có valid event trước hoặc tại report_date
```

Thứ tự đánh giá: `au` trước, sau đó `lu`, còn lại `nu`. Không gán segment bằng label tương lai.

Mục tiêu tỷ lệ segment tại snapshot cuối:

```text
nu: 35%–55%
lu: 20%–40%
au: 15%–35%
```

## 11. Snapshot và label

### 11.1 Snapshot hợp lệ

Snapshot là một cặp `(master_account, report_date)` và thỏa:

```text
report_date >= account_open_date + 30 ngày
report_date >= 2025-02-01
report_date <= raw_end - 30 ngày
status_at(report_date) = ACTIVE
```

Không dùng snapshot bị censor. `max_event_date` luôn là global configured `raw_end`.

### 11.2 Label window và công thức

```text
report_date + 1 <= event_date <= report_date + 30
```

```text
loan_label_next = 1 nếu tồn tại ít nhất một event:
  status = POSTED
  AND (MARGIN_MBS + INTERM_DELIVER + BUY_SHARE
       OR MBLINK + TLO_DELIVER_CASH + BUY)
  trong label window

loan_label_next = 0 trong các trường hợp còn lại
```

Event tại `report_date`, event bị `CANCELLED`, event sai tổ hợp hoặc event ngoài cửa sổ đều không tạo label dương.

## 12. Feature contract và chống leakage

Feature tại `report_date` chỉ đọc dữ liệu:

```text
transaction_time <= cuối ngày report_date
business_date <= report_date
event_date <= report_date
```

Danh sách feature MVP:

```text
account_age_days, trade_count_7d, trade_count_30d,
total_trading_amount_7d, total_trading_amount_30d,
active_trading_days_30d, margin_debt, margin_limit,
margin_utilization_ratio, debt_change_7d, cash_balance,
asset_value, collateral_value, cash_to_asset_ratio,
NAV, days_since_last_margin_event, margin_segment
```

Công thức:

```text
margin_utilization_ratio = 0.0 nếu margin_limit = 0
                            margin_debt / margin_limit nếu margin_limit > 0
cash_to_asset_ratio = 0.0 nếu asset_value = 0
                      cash_balance / asset_value nếu asset_value > 0
trade_count_7d = đếm transaction trong [report_date-6, report_date]
total_trading_amount_30d = tổng trade_value trong [report_date-29, report_date]
debt_change_7d = margin_debt(report_date) - margin_debt(report_date-7)
```

Numeric bắt buộc dùng `0.0` khi không có hoạt động; categorical bắt buộc dùng enum mặc định; không dùng null để ngầm biểu diễn trạng thái khác.

Không đưa vào input feature: `loan_label_next`, dữ liệu sau `report_date`, biến ẩn, cờ generator hoặc `is_margin_buy`.

## 13. Split theo thời gian

```text
Train:      2025-02-01 → 2025-06-30
Embargo:    2025-07-01 → 2025-07-30
Validation: 2025-07-31 → 2025-09-30
Embargo:    2025-10-01 → 2025-10-30
Test:       2025-10-31 → 2025-12-31
```

Không random split theo dòng. Backtest dùng thêm snapshot `-40d` và `-80d` so với test cutoff.

## 14. Ngưỡng data quality

### 14.1 Cấu trúc và khóa

```text
missing required columns: 0
null ở required columns: 0
duplicate primary key: 0
orphan foreign key: 0
```

### 14.2 Miền giá trị và thời gian

```text
quantity <= 0: 0 dòng
price <= 0: 0 dòng
amount < 0: 0 dòng
trade_value < 0: 0 dòng
trade_value sai quá 1 VND: 0 dòng
enum ngoài danh sách: 0 dòng
transaction trước account_open_date: 0
transaction/cash_flow sau dormant hoặc close date: 0
feature đọc dữ liệu sau report_date: 0
snapshot không đủ label window: 0
```

### 14.3 Phân phối

| Phạm vi | Positive rate min | Positive rate max |
|---|---:|---:|
| Toàn bộ | 10% | 35% |
| `nu` | 5% | 25% |
| `lu` | 10% | 40% |
| `au` | 15% | 50% |

Tỷ lệ segment tại snapshot cuối: mỗi segment tối thiểu 10%; mỗi segment phải có cả label 0 và 1. Nếu không đạt, generator fail kèm báo cáo nguyên nhân.

### 14.4 Calibration positive rate

Do `loan_label_next` là kết quả tích lũy của event trong 30 ngày, intercept trong `p_margin_event` không được giả định là đã tạo đúng positive rate. Generator phải calibration deterministic trước khi chạy full dataset:

```text
1. Chạy pilot 500 account bằng cùng seed và cùng config.
2. Tính positive rate theo nu/lu/au.
3. Mục tiêu: nu=0.15, lu=0.25, au=0.35, sai số mỗi segment ±0.03.
4. Với mỗi segment, định nghĩa `effective_intercept = -4.60 + segment_effect_margin[segment]`; tìm `effective_intercept` độc lập bằng bisection trong `[-7.0, -2.0]`, sau đó ghi lại `segment_effect_margin = effective_intercept + 4.60`.
5. Lặp tối đa 8 lần, mỗi lần chạy lại pilot deterministically.
6. Ghi intercept cuối vào generation_run.json.
7. Nếu vẫn ngoài ngưỡng, fail thay vì sửa label sau khi sinh.
```

Calibration chỉ điều chỉnh `segment_effect_margin` của công thức event; không thay base intercept, seed, label window và không oversample label dương.

## 15. Schema tối thiểu đã chốt

### `customer_account`

```text
master_account: string[10], primary key
account_open_date: date
account_status: enum(ACTIVE, DORMANT, CLOSED)
account_close_date: date nullable
dormant_start_date: date nullable
customer_group: enum(RETAIL, VIP, CORPORATE)
risk_profile: enum(LOW, MEDIUM, HIGH)
created_at: timestamp
```

### `stock_transaction`

```text
transaction_id: string, primary key
master_account: string, foreign key
symbol: enum(SYN001..SYN030)
transaction_time: timestamp
side: enum(BUY, SELL)
quantity: int64
price: float64
trade_value: int64
```

Không có `is_margin_buy` trong output Gold.

### `margin_balance_daily`

```text
master_account: string
business_date: date
margin_debt: int64
margin_limit: int64
asset_value: int64
cash_balance: int64
collateral_value: int64
NAV: int64
margin_status: enum(NO_MARGIN, ACTIVE, OVERDUE)
primary key: (master_account, business_date)
```

### `margin_cash_flow`

```text
cash_flow_id: string, primary key
master_account: string, foreign key
event_date: date
fk_product: enum(MARGIN_MBS, MBLINK, OTHER)
fk_cash_flow_type: enum(INTERM_DELIVER, TLO_DELIVER_CASH, REPAYMENT, FEE, OTHER)
fk_deliver_type: enum(BUY_SHARE, BUY, SELL_SHARE, REPAY, OTHER)
amount: int64
status: enum(POSTED, CANCELLED)
```

### `training_dataset`

```text
master_account: string
report_date: date
margin_segment: enum(nu, lu, au)
account_age_days: float64
trade_count_7d: int64
trade_count_30d: int64
total_trading_amount_7d: int64
total_trading_amount_30d: int64
active_trading_days_30d: int64
margin_debt: int64
margin_limit: int64
margin_utilization_ratio: float64
debt_change_7d: int64
cash_balance: int64
asset_value: int64
collateral_value: int64
cash_to_asset_ratio: float64
NAV: int64
days_since_last_margin_event: int64
loan_label_next: int8 {0, 1}
split: enum(train, validation, test)
```

## 16. Cấu trúc output và metadata

```text
data/raw/customer_account.parquet
data/raw/stock_transaction.parquet
data/raw/margin_balance_daily.parquet
data/raw/margin_cash_flow.parquet
data/features/training_dataset.parquet
data/metadata/generation_run.json
```

Partition:

```text
stock_transaction: transaction_month
margin_cash_flow: event_month
margin_balance_daily: business_month
training_dataset: report_month
```

`generation_run.json` bắt buộc lưu:

Các giá trị `<computed-after-write>` trong ví dụ phải được generator thay bằng SHA-256 thực tế sau khi ghi xong từng file; không được phát hành placeholder.

```json
{
  "generator_version": "0.1.0",
  "seed": 42,
  "num_accounts": 5000,
  "raw_start": "2025-01-01",
  "raw_end": "2026-01-30",
  "report_start": "2025-02-01",
  "report_end": "2025-12-31",
  "label_window_days": 30,
  "snapshot_frequency": "daily",
  "timezone": "Asia/Ho_Chi_Minh",
  "schema_version": "1.0.0",
  "calibration_method": "deterministic_bisection",
  "positive_rate_targets": {"nu": 0.15, "lu": 0.25, "au": 0.35},
  "output_sha256": {
    "customer_account.parquet": "<computed-after-write>",
    "stock_transaction.parquet": "<computed-after-write>",
    "margin_balance_daily.parquet": "<computed-after-write>",
    "margin_cash_flow.parquet": "<computed-after-write>",
    "training_dataset.parquet": "<computed-after-write>"
  }
}
```

## 17. Trình tự thực thi generator

1. Load và validate config.
2. Khởi tạo calendar và fixed holidays.
3. Khởi tạo universe 30 mã và chuỗi giá.
4. Sinh `customer_account` và biến ẩn nội bộ.
5. Sinh transaction theo account-day.
6. Tính trading activity và sinh repayment độc lập.
7. Sinh disbursement opportunity sau transaction và repayment.
8. Tính balance theo state machine và margin status cuối ngày.
9. Tạo candidate snapshot.
10. Tính segment tại snapshot.
11. Tính feature chỉ từ dữ liệu quá khứ.
12. Tính label chỉ từ cửa sổ tương lai 30 ngày.
13. Gán split theo `report_date`.
14. Chạy toàn bộ data-quality checks.
15. Nếu pass, ghi Parquet và metadata; nếu fail, không phát hành dataset.

## 18. Tiêu chí nghiệm thu cuối cùng

Bản data generation đạt khi:

- Không còn tham số quan trọng ở dạng range/ví dụ trong config.
- Bốn bảng nguồn có schema và enum cố định.
- Tần suất event, tỷ lệ cancelled và amount có công thức cụ thể.
- Giá, hạn mức, dư nợ và số tiền event có công thức tái lập.
- Segment và label có định nghĩa temporal không mơ hồ.
- `max_event_date`, account close/dormant và RNG per-entity đã được chốt.
- Feature không chứa dữ liệu tương lai.
- Positive rate và segment share nằm trong ngưỡng.
- Chạy lại cùng seed cho cùng checksum đầu ra.
- Dataset đọc được bằng pandas/DuckDB trước khi ghi Iceberg.

## 19. Những gì không được tự ý thay đổi

Không tự ý thay đổi:

- Label window 30 ngày.
- Hai tổ hợp event tạo label.
- Segment bằng label tương lai.
- Biến ẩn hoặc `is_margin_buy` vào feature.
- Dùng `MAX(event_date)` theo tài khoản để cắt snapshot.
- Random split theo dòng.
- Gán label 0 cho snapshot bị censor.
- Sinh `margin_balance_daily` độc lập với `margin_cash_flow`.

Mọi thay đổi phải tạo config/version mới và cập nhật lại tài liệu này.
