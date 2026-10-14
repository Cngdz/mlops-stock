# Data Generation Decision Baseline

## 0. Mục đích

Đây là bộ quyết định làm **nguồn chuẩn duy nhất** để lập trình generator dữ liệu synthetic cho bài toán dự báo nhu cầu vay margin/MBLink. Các giá trị được chốt cho MVP demo trên laptop; không phải thông số production và không được dùng để kết luận kinh doanh thật.

Khi có mâu thuẫn với tài liệu mô tả trước đó, các quyết định trong file này được ưu tiên.

Nguyên tắc:

- Mọi tham số nghiệp vụ quan trọng nằm trong config hoặc công thức canonical của file này; giá trị thực tế và checksum phải được ghi vào `generation_run.json`.
- Cùng config và cùng seed phải cho cùng dữ liệu.
- Thay một giá trị đã chốt phải tăng `generator_version` và ghi lý do.
- Biến ẩn chỉ dùng để sinh dữ liệu, không xuất thành feature hoặc label.

## 0.1 Thay đổi ở generator_version 0.2.0 (hỗ trợ ba use case)

Lý do: rà soát dữ liệu `day4_v2` (2026-10-07) cho thấy hai use case phụ chưa học được gì có ý nghĩa.

| # | Vấn đề đã đo | Quyết định |
|---|---|---|
| 1 | Campaign sinh sau events và độc lập với chúng: response rate 12,5–13,8% đều nhau giữa các `offer_type` | Campaign sinh **trong vòng lặp ngày**, có hiệu ứng nhân quả lên `p_margin_event` trong 14 ngày sau gửi (§8.6) |
| 2 | Campaign ~2 mỗi tài khoản, chỉ 4.129/1.623/1.678 dòng train/val/test; có gửi cho tài khoản dormant/closed | 3–12 campaign mỗi tài khoản, chỉ gửi khi ACTIVE (§8.6) |
| 3 | `overdue_label_next_30d`: dòng đang OVERDUE có nhãn dương 96,3%; 847k dòng không dư nợ chỉ 2,2% | Nhãn mới = **bắt đầu OVERDUE**, loại dòng đang OVERDUE; candidate chỉ gồm tài khoản có dư nợ hoặc lịch sử margin (§11.3) |
| 4 | `portfolio_value / asset_value` trung vị ~2,1, có ngày `asset_value=0` nhưng còn holdings; ước tính ~19,6 triệu dòng holdings | Chốt chính sách đối soát và kích thước ở §9.2 |
| 5 | Gate chưa có ngưỡng cho nhãn overdue và campaign | Thêm §14.5 |

## 1. Cấu hình chính đã chốt

```yaml
generator_version: "0.2.0"
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
repayment_probability_if_debt: 0.10
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

campaign_generation:
  enabled: true
  stream: "campaign"
  eligible_status: ACTIVE            # chỉ gửi khi ACTIVE tại ngày gửi
  min_days_since_open: 30
  last_send_offset_days: 14          # sent_date <= raw_end - 14 ngày
  send_probability_base: 0.035       # 0.020 -> val 4.263 / test 3.707; 0.055 + cap 8 -> test 2.489 (cap cạn trước kỳ test); 0.035 + cap 12 để rải đều theo thời gian
  send_probability_by_segment: {nu: 1.20, lu: 1.20, au: 0.60}   # nhân với base; segment đầu ngày
  min_gap_days: 14                   # không gửi chồng cửa sổ phản hồi
  max_campaigns_per_account: 12
  delivered_probability: 0.96
  send_time_local: "10:00-17:59"
  channel: {APP: 0.50, SMS: 0.30, EMAIL: 0.20}
  offer_type: {RATE_DISCOUNT: 0.40, FEE_WAIVER: 0.30, LIMIT_BOOST: 0.30}
  interest_rate_offer: {min: 0.065, max: 0.105}
  campaign_id_pool: 4                # MARGIN-01..MARGIN-04
  response_window_days: 14

campaign_uplift:                     # cộng vào logit p_margin_event, chỉ khi có campaign DELIVERED còn hiệu lực
  active_from_day: 1                 # ngày t+1 sau ngày gửi t, khớp cửa sổ nhãn D+1..D+14
  active_to_day: 14
  offer_effect: {RATE_DISCOUNT: 0.60, LIMIT_BOOST: 0.45, FEE_WAIVER: 0.25}
  rate_slope: 0.30                   # + 0.30 * (0.105 - interest_rate_offer) / 0.04
  channel_effect: {APP: 0.15, SMS: 0.00, EMAIL: -0.10}
  affinity_interaction: 0.80         # + 0.80 * margin_affinity
  stack_rule: "most_recent_delivered_only"

overdue_label:
  definition: "new_overdue"          # xem §11.3
  exclude_current_overdue: true
  candidate_filter: "margin_debt>0 OR history_count>0"

portfolio_generation:
  reconcile_with_asset_value: false  # xem §9.2
  frequency: daily
  max_rows_warning: 25000000

price_generation:
  initial_min: 10000
  initial_max: 150000
  return_mu: 0.0002
  return_sigma: 0.02
  price_floor: 1000
  price_ceiling: 500000

repayment_generation:
  probability_if_active_and_debt: 0.10
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
    + campaign_logit_uplift          # §8.6; = 0 nếu không có campaign DELIVERED còn hiệu lực
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

Cập nhật được người dùng đồng ý ngày 2026-09-04: tăng xác suất trả nợ từ 0.05 lên 0.10 mỗi account-day có dư nợ và đang ACTIVE. Pilot cho thấy 0.05 làm tỷ trọng `lu` quá thấp; 0.10 cải thiện vòng đời vay/trả mà không đổi logic nhãn. Phân phối repayment_ratio vẫn là Normal(0.15, 0.05).

Repayment không phụ thuộc vào việc tài khoản có BUY trong 7 ngày hay không. Với mỗi account-day, kể cả ngày không giao dịch:

```text
p_repayment_day = repayment_probability_if_debt (0.10) nếu status_at_day = ACTIVE và margin_debt_before_day > 0
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

### 8.6 Campaign (mới ở 0.2.0)

Campaign được sinh **bên trong state machine theo ngày**, không phải bảng sinh riêng sau cùng, vì cần chịu ảnh hưởng của segment và đồng thời ảnh hưởng ngược lên giải ngân.

```text
Với mỗi account-day (đầu ngày t):
  điều kiện gửi: status = ACTIVE
                 AND t >= account_open_date + 30
                 AND t <= raw_end - 14
                 AND không có campaign trong 14 ngày trước
                 AND số campaign đã gửi < 8
  p_send = 0.035 * send_probability_by_segment[segment đầu ngày]
  nếu Bernoulli(p_send) = 1:
      sent_at = ngày t, giờ ~ Uniform(10:00, 17:59) theo Asia/Ho_Chi_Minh
      channel, offer_type, interest_rate_offer, campaign_id theo config
      status = DELIVERED (0.96) hoặc FAILED (0.04)
```

Tác động lên giải ngân:

```text
nếu tồn tại campaign DELIVERED gửi ngày s với 1 <= t - s <= 14:
    campaign_logit_uplift =
        offer_effect[offer_type]
      + 0.30 * (0.105 - interest_rate_offer) / 0.04
      + channel_effect[channel]
      + 0.80 * margin_affinity
ngược lại: 0
```

Ràng buộc:

- Campaign ngày `t` chỉ ảnh hưởng từ ngày `t+1`, nên không tạo rò rỉ vào feature cuối ngày `t` và khớp cửa sổ nhãn D+1..D+14.
- Campaign `FAILED` không có uplift và không tính vào feature.
- Nhắm campaign dùng segment đầu ngày (quan sát được), không dùng biến ẩn hay nhãn tương lai.
- Seed theo stream `campaign` riêng (`[seed, account, 4]`): campaign không dùng chung RNG với stream `trading`, `cash` và `balance`. Ảnh hưởng của campaign lên giao dịch chỉ đi qua margin event → `segment` → xác suất giao dịch (có chủ đích, vì khách vay nhiều thì giao dịch nhiều). Vì vậy khi uplift = 0, bật hay tắt campaign cho cùng stream giao dịch; test: `test_zero_uplift_does_not_change_trading_stream`.
- Hiệu ứng nhân quả phải đo được: lift response (có campaign / nền không campaign cùng segment) trong khoảng 1,2–2,5 (§14.5).

## 9. Sinh `margin_balance_daily`

### 9.1 Khởi tạo

```text
asset_value_0 = round(clip(exp(Normal(17.5, 0.7)), 10,000,000, 500,000,000))
cash_balance_0 = round(asset_value_0 * Uniform(0.20, 0.60))
margin_debt_0 = 0
```

### 9.2 Ý nghĩa và thứ tự xử lý hằng ngày

`asset_value` được định nghĩa là **giá trị thị trường của danh mục cổ phiếu, không bao gồm tiền mặt**. `cash_balance` là tiền mặt; `NAV` là tài sản ròng sau khi trừ dư nợ.

**Chính sách portfolio (0.2.0, quyết định tạm thời):** `portfolio_holding_daily` là bản tái dựng từ giao dịch và giá, **không đối soát** với `asset_value` của `margin_balance_daily`. Đo thử trên 100 tài khoản cho thấy `portfolio_value / asset_value` có trung vị ~2,1 và có ngày `asset_value=0` nhưng vẫn có holdings. Vì vậy:

- `asset_value` là NAV cổ phiếu mô phỏng của balance; `portfolio_value` là nguồn riêng. Không đưa cả hai vào cùng tập feature với ý nghĩa thay thế nhau.
- `fs_portfolio` chỉ dùng cho cấu trúc danh mục (số mã, tập trung, lỗ chưa thực hiện, tỷ trọng mã rủi ro cao), không dùng `portfolio_value` làm proxy tài sản.
- Quality gate không yêu cầu hai giá trị khớp nhau; ghi tỷ lệ trung vị vào report để minh bạch.
- Cần xác nhận trước khi chạy: nếu muốn nhất quán hoàn toàn, tính `asset_value` từ holdings (đổi generator, phải calibrate lại).
- Quy mô ước tính ~19,6 triệu dòng cho 5.000 tài khoản; giữ daily, partition theo `business_month`, cảnh báo khi vượt `max_rows_warning`.

Mỗi ngày xử lý đúng thứ tự:

```text
1. Carry-forward balance từ ngày trước
2. Xác định status/segment đầu ngày từ dữ liệu đến ngày t-1
2b. Sinh campaign opportunity (§8.6); uplift có hiệu lực từ ngày t+1
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

### 11.3 `overdue_label_next_30d` (định nghĩa lại ở 0.2.0)

Định nghĩa cũ ("có OVERDUE trong D+1..D+30") bị loại vì dòng đang OVERDUE tại D có nhãn dương 96,3% (trạng thái kéo dài, `margin_utilization_ratio > 1` gần như tiết lộ nhãn).

```text
candidate overdue: snapshot hợp lệ AND (margin_debt(D) > 0 OR history_count(D) > 0)
                   AND margin_status(D) <> 'OVERDUE'

overdue_label_next_30d = 1 nếu tồn tại business_date trong [D+1, D+30]
                         với margin_status = 'OVERDUE'
                         (tức bắt đầu OVERDUE mới), ngược lại 0
```

- Nhóm `nu` không có dư nợ và không có lịch sử nên tự nhiên không thuộc candidate overdue.
- Dòng không thuộc candidate overdue có nhãn rỗng (null), không phải 0; dataset overdue lọc theo cột `overdue_eligible`.
- Dùng cùng `training_dataset` với cột `overdue_eligible` (int8); train model overdue chỉ trên các dòng `overdue_eligible=1`.
- Số quan sát trên `day4_v2`: nhóm "có dư nợ, chưa OVERDUE" có positive rate 12,1%.

### 11.4 `campaign_response_label_14d`

```text
dòng huấn luyện: mỗi campaign DELIVERED, grain (campaign_event_id)
                 AND account ACTIVE tại ngày gửi D (theo giờ Asia/Ho_Chi_Minh)
                 AND D <= raw_end - 14
label = 1 nếu có valid event POSTED trong [D+1, D+14], ngược lại 0
```

Event trong ngày gửi D không tính vào nhãn và campaign cùng ngày không tạo uplift cho ngày D, nên hai thứ nhất quán.

## 12. Feature contract và chống leakage

Cập nhật phạm vi Ngày 4: bỏ feature tùy chọn `days_since_last_margin_event` khỏi MVP. Lịch sử event vẫn được dùng nội bộ để xác định `nu/lu/au`. Snapshot được chốt cuối ngày; quy tắc segment đầu ngày trong generator không thay thế segment cuối ngày của feature snapshot.

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
NAV, margin_segment
```

Feature mở rộng (feature contract `day4-v3`):

```text
fs_portfolio: holding_symbol_count, portfolio_concentration,
              unrealized_loss_ratio, risky_asset_ratio
              (portfolio_value giữ trong fs_portfolio nhưng không dùng thay asset_value, §9.2)
fs_campaign:  campaign_count_30d, days_since_last_campaign
              (không có campaign => 9999 chỉ ở bảng nguồn; bản train thêm cờ has_campaign_history
               và tạo `days_since_last_campaign_capped` = min(giá trị, 365) để model tuyến tính không bị méo)
overdue:      over_limit_streak (số ngày giao dịch liên tiếp margin_debt > margin_limit tính đến D),
              over_limit_days_30d, debt_to_limit_change_7d
campaign dataset thêm: account_age_days, margin_segment, cash_balance, asset_value, NAV,
                       cash_to_asset_ratio, has_campaign_history
```

Mọi feature trên chỉ đọc dữ liệu đến cuối ngày `report_date` (với campaign là cuối ngày gửi). Cờ `overdue_eligible` không phải feature.

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

### 14.5 Gate cho nhãn mới (tạm thời, hiệu chỉnh sau lần chạy đầu)

| Đại lượng | Ngưỡng PASS | Ghi chú |
|---|---|---|
| `overdue_label_next_30d` positive rate trên `overdue_eligible=1` | 5%–30% | Quan sát tham khảo ~12% |
| Overdue positive rate theo segment `lu`, `au` | mỗi nhóm có cả lớp 0 và 1, rate 1%–40% | `nu` không thuộc candidate |
| Số dòng `overdue_eligible=1` mỗi split | tối thiểu 50.000 | |
| `campaign_response_label_14d` positive rate toàn bộ | 8%–40% | |
| Số dòng campaign mỗi split | tối thiểu 5.000 | Mục tiêu 3–12 campaign mỗi tài khoản |
| Lift campaign | 1,2–2,5 | response sau campaign DELIVERED / response nền không campaign, cùng segment |
| Chênh lệch response giữa `offer_type` | ít nhất 1,5 điểm phần trăm giữa offer cao nhất và thấp nhất | Chứng minh offer có tín hiệu |
| Campaign gửi cho tài khoản không ACTIVE | 0 | |
| `portfolio_value`/`asset_value` | chỉ ghi vào report | Không gate (§9.2) |

Nếu lift hoặc chênh lệch offer nằm ngoài ngưỡng thì điều chỉnh `campaign_uplift`, không sửa nhãn sau khi sinh.

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

### 14.6 Calibration có campaign

Campaign làm tăng xác suất giải ngân, nên pilot calibration của §14.4 **phải bật `campaign_generation`** và `campaign_uplift`, để positive rate `loan_label_next` được calibrate trên cùng quy trình sinh với full dataset. Thứ tự: cố định `campaign_uplift` và `campaign_generation` theo config, rồi bisection `segment_effect_margin`. Không calibrate lại `campaign_uplift` bằng bisection; chỉ kiểm tra lift ở §14.5 sau khi sinh.

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

### `customer_campaign`

```text
campaign_event_id: string, primary key (CMP-{master_account}-{sequence:03d})
campaign_id: string (MARGIN-01..MARGIN-04)
master_account: string, foreign key
sent_at: timestamp (Asia/Ho_Chi_Minh)
channel: enum(APP, SMS, EMAIL)
offer_type: enum(RATE_DISCOUNT, FEE_WAIVER, LIMIT_BOOST)
interest_rate_offer: float64
status: enum(DELIVERED, FAILED)
```

Không có cột phản hồi; phản hồi chỉ tồn tại dưới dạng nhãn tính từ `margin_cash_flow`.

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
portfolio_value: int64
holding_symbol_count: int64
portfolio_concentration: float64
unrealized_loss_ratio: float64
risky_asset_ratio: float64
campaign_count_30d: int64
days_since_last_campaign: int64
over_limit_streak: int64
over_limit_days_30d: int64
overdue_eligible: int8 {0, 1}
loan_label_next: int8 {0, 1}
overdue_label_next_30d: int8 {0, 1}
split: enum(train, validation, test)
```

Dataset campaign-event được xuất riêng:

```text
campaign_event_id: string
campaign_id: string
master_account: string
report_date: date
channel: enum(APP, SMS, EMAIL)
offer_type: enum(RATE_DISCOUNT, FEE_WAIVER, LIMIT_BOOST)
interest_rate_offer: float64
account_age_days: float64
margin_segment: enum(nu, lu, au)
trade_count_30d: int64
total_trading_amount_30d: int64
margin_debt: int64
margin_limit: int64
margin_utilization_ratio: float64
cash_balance: int64
asset_value: int64
NAV: int64
holding_symbol_count: int64
portfolio_concentration: float64
campaign_count_30d: int64
days_since_last_campaign: int64
campaign_response_label_14d: int8 {0, 1}
split: enum(train, validation, test)
```

## 16. Cấu trúc output và metadata

```text
data/generated/day4_v2/                         # source Parquet
data/warehouse_full/raw_day4_v2/                # source Iceberg
data/features/day4_runs/<run_id>/               # fs_*, training datasets và usecase registry
data/warehouse_full/features_<run_id>/          # feature Iceberg
data/catalog_full/pyiceberg.db                  # catalog
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
  "generator_version": "0.2.0",
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
    "stock_price_daily.parquet": "<computed-after-write>",
    "stock_transaction.parquet": "<computed-after-write>",
    "margin_balance_daily.parquet": "<computed-after-write>",
    "margin_cash_flow.parquet": "<computed-after-write>",
    "security_master.parquet": "<computed-after-write>",
    "portfolio_holding_daily.parquet": "<computed-after-write>",
    "customer_campaign.parquet": "<computed-after-write>",
    "training_dataset.parquet": "<computed-after-write>"
  }
}
```

## 17. Trình tự thực thi generator

1. Load và validate config.
2. Khởi tạo calendar và fixed holidays.
3. Khởi tạo universe 30 mã và chuỗi giá.
4. Sinh `customer_account`, `security_master` và biến ẩn nội bộ.
5. Chạy state machine theo ngày cho từng tài khoản, theo thứ tự trong §9.2:
   campaign opportunity (uplift từ t+1) → stock transactions → trading activity →
   repayment → disbursement (có `campaign_logit_uplift`) → cập nhật balance và status.
   `customer_campaign` là đầu ra của chính vòng lặp này.
6. Tái dựng `portfolio_holding_daily` từ transaction + price (không đối soát với `asset_value`, §9.2).
7. Tạo candidate snapshot và segment tại snapshot.
8. Tính shared feature chỉ từ dữ liệu quá khứ, gồm feature mở rộng ở §12.
9. Tính các label: 30 ngày cho loan; "bắt đầu OVERDUE" cho overdue (§11.3); 14 ngày cho campaign response (§11.4).
10. Gán split theo `report_date`.
11. Chạy toàn bộ data-quality checks, gồm §14.5.
12. Nếu pass, ghi Parquet, `usecase_registry.json` và metadata; nếu fail, không phát hành dataset.

Calibration (§14.4, §14.6) chạy trước bước 5 của lần sinh full.

## 18. Tiêu chí nghiệm thu cuối cùng

Bản data generation đạt khi:

- Không còn tham số quan trọng ở dạng range/ví dụ trong config.
- Tám bảng nguồn có schema và enum cố định; bốn bảng nghiệp vụ cốt lõi được bổ sung `stock_price_daily`, `security_master`, `portfolio_holding_daily` và `customer_campaign` để phục vụ nhiều use case trên cùng feature platform.
- Tần suất event, tỷ lệ cancelled và amount có công thức cụ thể.
- Giá, hạn mức, dư nợ và số tiền event có công thức tái lập.
- Segment và label có định nghĩa temporal không mơ hồ.
- `max_event_date`, account close/dormant và RNG per-entity đã được chốt.
- Feature không chứa dữ liệu tương lai.
- Positive rate và segment share nằm trong ngưỡng.
- Chạy lại cùng seed cho cùng checksum đầu ra.
- Dataset đọc được bằng pandas/DuckDB trước khi ghi Iceberg.
- Cả ba use case đều có dataset đủ lớn, nhãn không tầm thường và đạt gate §14.5:
  `overdue_risk` không dùng dòng đang OVERDUE, `campaign_response` có lift đo được và chênh lệch giữa các offer.
- Campaign sinh trong cùng state machine với giải ngân; không có campaign cho tài khoản không ACTIVE.
- Có test biên: nhãn overdue tại D+30/D+31, nhãn campaign tại D+14/D+15, dòng đang OVERDUE bị loại khỏi candidate overdue, campaign `FAILED` không tính.

## 19. Những gì không được tự ý thay đổi

Không tự ý thay đổi:

- Label window 30 ngày.
- Hai tổ hợp event tạo label.
- Segment bằng label tương lai.
- Biến ẩn hoặc `is_margin_buy` vào feature.
- Dùng `MAX(event_date)` theo tài khoản để cắt snapshot.
- Random split theo dòng.
- Gán label 0 cho snapshot bị censor.
- Định nghĩa lại nhãn overdue hoặc campaign sau khi đã thấy kết quả model.
- Tạo campaign sau khi đã sinh events, hoặc cho campaign tác động ngược về ngày gửi.
- Sinh `margin_balance_daily` độc lập với `margin_cash_flow`.

Mọi thay đổi phải tạo config/version mới và cập nhật lại tài liệu này.
