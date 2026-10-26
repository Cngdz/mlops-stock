# Hợp đồng dữ liệu đặc trưng (fs-v6)

Mô tả mã nguồn hiện tại của Feature Store theo ngày ([features/](../features/), tài liệu luồng chương 3) và dữ liệu
huấn luyện (`features.build_training`). Nguồn chuẩn của danh sách cột là `GROUPS` trong
[features/common.py](../features/common.py): bước `features.quality` so schema Iceberg của từng bảng với nó mỗi ngày,
và `tests/test_features.py` kiểm tra tài liệu này liệt kê đủ mọi cột. Đổi một cột = sửa `GROUPS`, sửa mục 3, tăng
`FEATURE_CONTRACT`. Các mốc cố định thuộc bộ synthetic 2025.

## 1. Đơn vị của một dòng

Khóa duy nhất là `(master_account, report_date)`. Tài khoản được giữ dưới dạng chuỗi, tránh mất số 0 đầu. `report_date = D` là ngày chốt dữ liệu theo `Asia/Ho_Chi_Minh`; tiền tính bằng VND.

Một snapshot training phải đáp ứng:

- Ngày D nằm trong 2025-02-01 đến 2025-12-31 và thuộc một split.
- Tài khoản đã mở ít nhất 30 ngày; D trước ngày đóng hoặc ngày bắt đầu dormant.
- Có dữ liệu balance đầy đủ từ ngày mở đến ngày Gold cuối cùng (trạng thái mang sang ngày sau cần mỗi ngày một dòng).
- D+30 không vượt quá ngày Gold cuối cùng (`label_end`, hiện 2026-01-30).

Trạng thái `account_status` ở cuối kỳ không được dùng để loại toàn bộ lịch sử: một tài khoản đã đóng cuối năm vẫn có thể có snapshot hợp lệ trước ngày đóng.

## 2. Nguồn Gold

| Bảng | Khóa | Các cột pipeline sử dụng |
|---|---|---|
| `customer_account` | `master_account` | `account_open_date`, `account_status`, `account_close_date`, `dormant_start_date`, `risk_profile` |
| `stock_transaction` | `transaction_id` | `master_account`, `transaction_time`, `quantity`, `price`, `trade_value`, `side` |
| `margin_balance_daily` | tài khoản + `business_date` | `cash_balance`, `asset_value`, `margin_debt`, `margin_limit` |
| `margin_cash_flow` | `cash_flow_id` | `master_account`, `event_date`, `status`, `fk_product`, `fk_cash_flow_type`, `fk_deliver_type`, `amount` |

Ba nguồn mở rộng phục vụ các use case dùng chung feature platform:

| Bảng | Khóa | Vai trò |
|---|---|---|
| `security_master` | `symbol` | Dimension ngành, thanh khoản và rủi ro của mã |
| `portfolio_holding_daily` | tài khoản + ngày + mã | Snapshot danh mục và mức độ tập trung |
| `customer_campaign` | `campaign_event_id` | Lần gửi ưu đãi, không chứa kết quả phản hồi |

Các ngày phải có kiểu `DATE`, khóa/enum có kiểu chuỗi, số lượng/tiền có kiểu số. Timestamp hỗ trợ kiểu timestamp hoặc chuỗi parse được; nguồn chuẩn cần timezone rõ ràng. Gate không thay thế việc kiểm tra timezone của dữ liệu đến muộn hoặc timestamp thiếu offset.

Gold nằm trong namespace `gold` của catalog Postgres `iceberg_catalog` (`scripts/migrate_gold.py`), hệ thống chỉ đọc. `features.check_source --date T` trả FAIL khi thiếu bảng/cột, sai nhóm kiểu, hoặc bảng snapshot ngày (`margin_balance_daily`, `portfolio_holding_daily`, `stock_price_daily`) chưa tới T; khi đó không tính gì. Null ở cột lifecycle tùy chọn vẫn hợp lệ. Kiểm tra sâu trên chính Gold (đối soát dư nợ với dòng tiền, vòng đời giao dịch) thuộc tầng Gold và nằm ngoài phạm vi; đầu ra fs_* có cổng riêng ở mục 7, dữ liệu huấn luyện ở mục 5.

## 3. Feature (bảng fs_*)

### Quy ước chung

- Mỗi bảng là một bảng Iceberg `features.<tên>` trong catalog Postgres `iceberg_catalog`, dữ liệu ở
  `s3://warehouse/features.db/<tên>/`, partition identity theo `report_date`.
- Khoá: `master_account` (string) + `report_date` (date). Mỗi ngày đúng một dòng cho mỗi tài khoản đủ điều kiện:
  ACTIVE (chưa đóng, chưa ngủ đông) và đã mở ít nhất 30 ngày. Sáu bảng có cùng tập khoá trong mỗi ngày.
- `event_timestamp` (timestamptz, UTC): 23:59:59 giờ Việt Nam của `report_date`.
- Mọi cột bắt buộc, không null. Cửa sổ tính theo ngày lịch giờ Việt Nam: 7 ngày = D−6..D, 30 ngày = D−29..D.
- Không có nhãn trong fs_*. Nhãn chỉ được tính khi dựng dữ liệu huấn luyện (`features.build_training`).
- Bảng nội bộ `features.fs_state` (history_count, over_limit_streak, last_campaign_date theo ngày) chỉ để ngày
  sau tiếp tục tính, không phải đầu vào model và không thuộc hợp đồng này.

### `fs_demographic`

| Cột | Kiểu Iceberg | Ý nghĩa |
|---|---|---|
| `account_age_days` | long | Số ngày từ ngày mở tài khoản đến D (≥ 30) |
| `margin_segment` | string | `au`: còn dư nợ hoặc có giải ngân hợp lệ trong 30 ngày; `lu`: từng giải ngân nhưng không thuộc au; `nu`: chưa từng |

### `fs_trading_behavior`

| Cột | Kiểu Iceberg | Ý nghĩa |
|---|---|---|
| `trade_count_7d` | long | Số lệnh khớp D−6..D |
| `trade_count_30d` | long | Số lệnh khớp D−29..D |
| `total_trading_amount_7d` | long | Tổng giá trị khớp D−6..D |
| `total_trading_amount_30d` | long | Tổng giá trị khớp D−29..D |
| `active_trading_days_30d` | long | Số ngày có giao dịch trong D−29..D (0..30) |

### `fs_margin_balance`

| Cột | Kiểu Iceberg | Ý nghĩa |
|---|---|---|
| `margin_debt` | long | Dư nợ margin cuối ngày D |
| `margin_limit` | long | Hạn mức margin |
| `margin_utilization_ratio` | double | `margin_debt / margin_limit` (0 khi hạn mức 0) |
| `debt_change_7d` | long | Dư nợ D trừ dư nợ đúng ngày D−7 |
| `over_limit_streak` | long | Số ngày lịch liên tiếp dư nợ vượt hạn mức, tính đến D |
| `over_limit_days_30d` | long | Số ngày vượt hạn mức trong D−29..D (0..30) |
| `margin_status` | string | Trạng thái margin cuối ngày D (Gold). Không phải đặc trưng model: xác định `overdue_eligible` (segment ≠ nu và chưa OVERDUE tại D) giống nhau khi huấn luyện và khi chấm |

### `fs_asset_balance`

| Cột | Kiểu Iceberg | Ý nghĩa |
|---|---|---|
| `cash_balance` | long | Tiền mặt |
| `asset_value` | long | Giá trị tài sản |
| `collateral_value` | long | Tài sản đảm bảo = `asset_value` × 0,60 / 0,70 / 0,80 theo risk_profile LOW / MEDIUM / HIGH |
| `cash_to_asset_ratio` | double | `cash_balance / asset_value` (0 khi tài sản 0) |
| `NAV` | long | `asset_value + cash_balance − margin_debt` |

### `fs_portfolio`

| Cột | Kiểu Iceberg | Ý nghĩa |
|---|---|---|
| `portfolio_value` | long | Tổng giá trị thị trường danh mục |
| `holding_symbol_count` | long | Số mã đang nắm giữ |
| `portfolio_concentration` | double | Tỷ trọng lớn nhất của một mã (0..1) |
| `unrealized_loss_ratio` | double | Tỷ trọng giá trị các mã đang lỗ (0..1) |
| `risky_asset_ratio` | double | Tỷ trọng giá trị các mã rủi ro HIGH (0..1) |

### `fs_campaign`

| Cột | Kiểu Iceberg | Ý nghĩa |
|---|---|---|
| `campaign_count_30d` | long | Số chiến dịch (khác FAILED) nhận trong D−29..D |
| `days_since_last_campaign` | long | Số ngày từ chiến dịch gần nhất đến D, chặn 365; 365 khi chưa từng nhận |
| `has_campaign_history` | long | 1 nếu đã từng nhận chiến dịch đến D, ngược lại 0 |

Ghi chú fs-v6: trước phiên bản này `days_since_last_campaign` / `has_campaign_history` chỉ phản ánh "có chiến
dịch trong chính ngày D" (lỗi trùng tên cột trong SQL cũ). Model huấn luyện trên dữ liệu trước fs-v6 cần huấn
luyện lại trên dữ liệu mới trước khi dùng cho điểm hằng ngày.

Cửa sổ tính bằng **ngày lịch**, bao gồm ngày D; không phải 7 hoặc 30 dòng sau khi đã lọc dữ liệu. `collateral_value` được tính lại từ tài sản/risk profile, không lấy trực tiếp cột nguồn cùng tên.

Segment được xét theo thứ tự:

1. `au`: có dư nợ tại D **hoặc** có giải ngân hợp lệ trong D−29..D.
2. `lu`: không thuộc `au`, nhưng đã có giải ngân hợp lệ đến D.
3. `nu`: các trường hợp còn lại.

Không đưa `wealth_level`, `margin_affinity`, các biến ẩn khác, `master_account`, nhãn hoặc `split` vào ma trận feature khi train. `GROUPS` là danh sách cột feature được phép xuất; nếu train riêng từng segment thì dùng segment để định tuyến dữ liệu.

## 4. Nhãn và use case

`loan_label_next = 1` khi có ít nhất một cash flow `POSTED` trong **D+1..D+30**, với một trong hai tổ hợp:

| Product | Cash flow type | Deliver type |
|---|---|---|
| `MARGIN_MBS` | `INTERM_DELIVER` | `BUY_SHARE` |
| `MBLINK` | `TLO_DELIVER_CASH` | `BUY` |

Không có event thỏa điều kiện thì nhãn bằng 0. Event ngày D thuộc lịch sử, không thuộc nhãn. Event ngày D+31, cancelled, repayment, fee và tổ hợp sai không tạo nhãn dương.

Ví dụ D=2025-02-01: rolling 7 ngày là 2025-01-26..2025-02-01; rolling 30 ngày là 2025-01-03..2025-02-01; label là 2025-02-02..2025-03-03.

Platform cũng xuất thêm hai use case dùng chung feature account/trading/margin:

- `overdue_label_next_30d`: bằng 1 nếu tài khoản có `margin_status = OVERDUE` trong D+1..D+30. Candidate nên giới hạn ở tài khoản đang có dư nợ hoặc lịch sử margin.
- `campaign_response_label_14d`: bằng 1 nếu lần gửi campaign `DELIVERED` có valid event trong 14 ngày sau `sent_at`. Grain của dataset này là `(campaign_event_id, master_account, sent_at)`, không ép vào snapshot account-day.

Nhãn không được đưa vào feature view. Một feature view có thể được dùng bởi nhiều Feature Service/model.

## 5. Split và quality gate của dữ liệu huấn luyện

| Vùng thời gian | Ngày snapshot |
|---|---|
| Train | 2025-02-01..2025-06-30 |
| Embargo | 2025-07-01..2025-07-30 |
| Validation | 2025-07-31..2025-09-30 |
| Embargo | 2025-10-01..2025-10-30 |
| Test | 2025-10-31..2025-12-31 |

Mốc split nằm ở `training.splits` trong [features/settings.yaml](../features/settings.yaml). Không random split. Class weights tính riêng từng segment trên train: `N / (2 × N_class)`; validation/test không tham gia tính weights.

Quality gate yêu cầu khóa/null/foreign key hợp lệ, công thức balance và cửa sổ đúng, dataset không rỗng, cả hai lớp tồn tại trong từng split × segment. Các ngưỡng phân phối:

| Đại lượng | Ngưỡng PASS |
|---|---|
| Positive rate toàn bộ | 10–35% |
| Positive rate `nu` | 5–25% |
| Positive rate `lu` | 10–40% |
| Positive rate `au` | 15–50% |
| Tỷ trọng từng segment ở snapshot cuối | Ít nhất 10% |

Các khoảng tỷ trọng tham khảo nu=35–55%, lu=20–40%, au=15–35% trong decision baseline **không đồng nghĩa** với các gate tối thiểu trên. Calibration PASS và quality PASS cũng là hai kết luận khác nhau.

## 6. Đầu ra và cách downstream đọc

**Feature Store (hằng ngày).** Sáu bảng Iceberg `features.fs_*`, partition `report_date`, mỗi ngày ghi đè đúng một
partition. Một ngày chỉ được đọc khi `control.fs_status(report_date)` là `COMPLETE` (vòng trạng thái WRITING →
WRITTEN → QUALITY_PASSED | QUALITY_FAILED → COMPLETE; chạy lại một ngày đưa nó về WRITING ngay). `pipeline.predict`
và `pipeline.drift` đọc qua `features.store`, ghi `feature_run_id` = `run_id` của lần tính ngày đó.

**Dữ liệu huấn luyện (theo lần train).** `features.build_training` đọc lại các partition fs_* (mọi ngày phải
`COMPLETE`), tính nhãn từ Gold và ghi `data/features/day4_runs/<run_id>/` trên PVC. Đọc `data/features/current.json`
(hoặc `--run-dir` mà DAG truyền), rồi `quality_report.json` trong chính thư mục đó: `status == PASS`, `run_id` khớp,
`feature_contract` đúng phiên bản.

| Artifact | Ý nghĩa |
|---|---|
| `training_dataset.parquet` | Feature account-day (sao chép từ fs_*), `loan_label_next`, `overdue_eligible`, `overdue_label_next_30d`, split |
| `campaign_training_dataset.parquet` | Một dòng mỗi lần gửi `DELIVERED`: feature campaign-event và `campaign_response_label_14d` |
| `loan_overdue_labels.parquet` | `master_account`, `report_date`, `event_timestamp`, nhãn loan/overdue, `overdue_eligible`, split (nguồn nhãn của `pipeline.evaluate`) |
| `class_weights.json` | Counts/weights theo use case và segment, chỉ fit trên train |
| `quality_report.json` | Kết quả kiểm tra, khoảng fs_* (`fs_range`), `label_end`, các `run_id` fs đã đọc, SHA-256 và số dòng |
| `data/features/current.json` | Run được chọn cho downstream; chỉ đổi khi gate PASS |

Gate FAIL chỉ ghi `data/features/rejected_training_report.json`. Các file của script day4 cũ (`fs_*.parquet`,
`usecase_registry.json`, `campaign_labels.parquet`, `feast_check.json`) chỉ còn trong các run cũ.

## 7. Cổng chất lượng theo ngày (`features.quality`)

Chỉ đọc partition của ngày T. Không đạt thì ngày T là `QUALITY_FAILED` trong `control.fs_status` và không được
đánh dấu `COMPLETE`.

| Kiểm tra | Điều kiện đạt |
|---|---|
| Hợp đồng | Tên cột và kiểu Iceberg của mỗi bảng đúng như trên, không thiếu, không thừa |
| Khoá | Không null, không trùng; sáu bảng cùng tập khoá |
| Số dòng | > 0; số dòng ngày T / ngày trước trong `quality.row_count_ratio` ([features/settings.yaml](../features/settings.yaml)) |
| Null | Tỷ lệ null của các cột hợp đồng ≤ `quality.max_null_rate` (0) |
| Miền giá trị | segment ∈ {nu, lu, au}; tuổi ≥ 30; cửa sổ 7 ngày ≤ 30 ngày; số ngày trong 0..30; các tỷ lệ trong miền; `NAV` và các tỷ lệ đúng công thức |

## 8. Tách feature và nhãn

Từ contract `day4-v4`, feature và nhãn được tách; từ fs-v6 chúng được tính ở hai bước khác nhau:

```
hằng ngày:   Gold T−30..T + fs_state(T−1) ──► features.compute ──► partition T của 6 bảng fs_*   (KHÔNG nhãn, KHÔNG split)
mỗi lần train: fs_* [start, end] + nhãn từ Gold (chỉ ngày đủ cửa sổ) ──► candidate (bỏ embargo) ──► training_dataset
```

- `fs_*` gồm cả ngày embargo và 30 ngày cuối chưa có nhãn, nên batch scoring luôn có ngày mới nhất.
- `training_dataset` đọc lại feature từ fs_*, không tính lại, nên cùng khóa thì huấn luyện và chấm điểm thấy cùng giá trị. `overdue_eligible` dùng một biểu thức SQL (`OVERDUE_ELIGIBLE_SQL`) cho cả hai phía; dòng campaign dùng chung `features/sql/campaign.sql`.
- Điều kiện vòng đời vẫn áp dụng cho scoring: tài khoản mở ít nhất 30 ngày, trước ngày đóng hoặc dormant.
- `campaign_training_dataset` có grain campaign-event riêng và vẫn ghép với `candidate`.
- Online (Redis, Feast online) thuộc giai đoạn 2; khi làm, nạp từ `fs_*` này.

Kiểm thử point-in-time hiện kiểm chứng theo **event time**. Chưa có `ingested_at`/`available_at` để chứng minh một event đến muộn đã thực sự sẵn sàng tại thời điểm dự báo lịch sử.

## 9. Feast offline (thử nghiệm cũ, contract `day4-v5`, ngoài phạm vi)

Feast nằm ngoài phạm vi tài liệu luồng (mục 1.6). Phần dưới mô tả thử nghiệm trên các run của script day4 cũ và
không áp dụng cho Feature Store theo ngày.


```
fs_* (+ event_timestamp) ──► feature_repo/definitions.py ──► feast apply ──► registry
                                                                  │
loan_overdue_labels / campaign_labels (entity_df) ──► get_historical_features ──► train / batch scoring
```

- **Timestamp:** snapshot ngày D có `event_timestamp` = 23:59:59 Asia/Ho_Chi_Minh ngày D, lưu UTC. Feast lấy dòng mới nhất có `event_timestamp ≤` thời điểm hỏi (bằng nhau được tính).
- **TTL = 1 ngày.** File offline store **bỏ hẳn dòng** không có feature trong TTL (không trả null), nên kiểm tra luôn đếm số dòng trả về.
- **Feature Service:** `loan_propensity`, `overdue_risk` dùng 6 nhóm; `campaign_response` dùng 5 nhóm, **không có `fs_campaign`** (đếm cả lần gửi ngày D). Lịch sử campaign lấy từ `campaign_labels`. `portfolio_value` không nằm trong service nào (không đối soát với `asset_value`).
- **Campaign:** hỏi tại `sent_at` (ví dụ 10:37 ngày D) nhận snapshot hoàn chỉnh gần nhất là **D−1**. Lần gửi không có snapshot D−1 (ngày đầu đủ điều kiện) bị loại khỏi `campaign_labels`. Khác `campaign_training_dataset` (dùng snapshot cuối ngày D), vốn có thể chứa giao dịch xảy ra sau giờ gửi.
- **Nguồn:** `definitions.py` đọc run từ `data/features/current.json` (hoặc `FEAST_RUN_DIR`). Có run mới thì chạy lại `feast apply`.
- **Nghiệm thu:** `day5_feast_check.py` PASS: đủ dòng, 0 null, 0 khác biệt với `training_dataset` (loan) và với snapshot D−1 (campaign), đủ tài khoản ngày mới nhất, không có giá trị cũ sau TTL.
