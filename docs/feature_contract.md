# Hợp đồng dữ liệu ngày 4

Tài liệu mô tả mã nguồn hiện tại trong `scripts/day4_features.sql` và `scripts/day4_feature_engineering.py`. Các mốc cố định thuộc bộ synthetic 2025; `--raw-end` điều chỉnh độ đủ của nhãn, không tự đổi split sang năm khác.

## 1. Đơn vị của một dòng

Khóa duy nhất là `(master_account, report_date)`. Tài khoản được giữ dưới dạng chuỗi, tránh mất số 0 đầu. `report_date = D` là ngày chốt dữ liệu theo `Asia/Ho_Chi_Minh`; tiền tính bằng VND.

Một snapshot training phải đáp ứng:

- Ngày D nằm trong 2025-02-01 đến 2025-12-31 và thuộc một split.
- Tài khoản đã mở ít nhất 30 ngày; D trước ngày đóng hoặc ngày bắt đầu dormant.
- Có dữ liệu balance đầy đủ từ ngày mở đến `raw_end`.
- D+30 không vượt quá `raw_end`, mặc định 2026-01-30.

Trạng thái `account_status` ở cuối kỳ không được dùng để loại toàn bộ lịch sử: một tài khoản đã đóng cuối năm vẫn có thể có snapshot hợp lệ trước ngày đóng.

## 2. Nguồn tối thiểu

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

Thiếu bảng/cột hoặc sai nhóm kiểu dữ liệu sẽ trả source FAIL trước khi normalize/build. Null ở cột lifecycle tùy chọn vẫn hợp lệ; các ràng buộc khóa, enum, giá trị và đối soát dư nợ được kiểm tra tiếp trong quality gate.

## 3. Feature

| Nhóm | Feature | Cách tính |
|---|---|---|
| `fs_demographic` | `account_age_days` | D trừ ngày mở tài khoản |
| | `margin_segment` | `nu`, `lu`, `au` theo lịch sử đến D |
| `fs_trading_behavior` | `trade_count_7d`, `trade_count_30d` | Số giao dịch trong D−6..D và D−29..D |
| | `total_trading_amount_7d`, `total_trading_amount_30d` | Tổng `trade_value` trong hai cửa sổ tương ứng |
| | `active_trading_days_30d` | Số ngày có giao dịch trong D−29..D |
| `fs_margin_balance` | `margin_debt`, `margin_limit` | Giá trị chốt cuối ngày D |
| | `margin_utilization_ratio` | Dư nợ / hạn mức; mẫu số 0 trả về 0.0 |
| | `debt_change_7d` | Dư nợ D trừ dư nợ đúng ngày D−7 |
| `fs_asset_balance` | `cash_balance`, `asset_value` | Tiền/tài sản chốt cuối ngày D |
| | `collateral_value` | Làm tròn `asset_value × ratio`, ratio LOW=0.60, MEDIUM=0.70, HIGH=0.80 |
| | `cash_to_asset_ratio` | Tiền / tài sản; mẫu số 0 trả về 0.0 |
| | `NAV` | Tài sản + tiền − dư nợ |
| `fs_portfolio` | `portfolio_value`, `holding_symbol_count`, `portfolio_concentration` | Quy mô và mức tập trung danh mục tại D |
| | `unrealized_loss_ratio`, `risky_asset_ratio` | Tỷ lệ lỗ chưa thực hiện và tài sản rủi ro tại D |
| `fs_campaign` | `campaign_count_30d`, `days_since_last_campaign` | Lịch sử tiếp xúc campaign đến D |

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

## 5. Split và quality gate

| Vùng thời gian | Ngày snapshot |
|---|---|
| Train | 2025-02-01..2025-06-30 |
| Embargo | 2025-07-01..2025-07-30 |
| Validation | 2025-07-31..2025-09-30 |
| Embargo | 2025-10-01..2025-10-30 |
| Test | 2025-10-31..2025-12-31 |

Không random split. Class weights tính riêng từng segment trên train: `N / (2 × N_class)`; validation/test không tham gia tính weights.

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

Đọc `data/features/current.json` một lần, lấy `path`, sau đó đọc `quality_report.json` trong chính thư mục đó. Kiểm tra `status == PASS`, `run_id` khớp pointer và `feature_contract` đúng phiên bản downstream hỗ trợ. Dùng đường dẫn trong `outputs`; không tự chọn thư mục mới nhất theo tên.

| Artifact | Ý nghĩa |
|---|---|
| Sáu `fs_*.parquet` | Khóa + feature của từng nhóm, không có label; mọi ngày đủ điều kiện đến `raw_end` (contract `day4-v4`) |
| `training_dataset.parquet` | Feature account-day, `loan_label_next`, `overdue_label_next_30d` và split |
| `loan_overdue_labels.parquet` | Entity table cho Feast: `master_account`, `report_date`, `event_timestamp` (cuối ngày D), nhãn loan/overdue, `overdue_eligible`, split. Không có feature |
| `campaign_labels.parquet` | Entity table cho Feast: một dòng mỗi lần gửi, `event_timestamp` = `sent_at` thật, cột offer/kênh/lịch sử campaign (tính riêng cho lần gửi), nhãn, split |
| `feast_check.json` | Kết quả `scripts/day5_feast_check.py` (parity, null, TTL, thời gian) |
| `campaign_training_dataset.parquet` | Feature campaign-event và `campaign_response_label_14d` |
| `usecase_registry.json` | Mapping use case → label, dataset và feature groups |
| `class_weights.json` | Counts/weights theo segment, chỉ fit trên train |
| `quality_report.json` | Check results, snapshot nguồn/đích, SHA-256 của Parquet và số dòng |
| `data/features/current.json` | Phiên bản được chọn cho downstream |
| `data/source_current.json` | Nguồn mặc định cho lần chạy tiếp theo |

Mỗi file JSON được thay thế nguyên tử. Hai pointer chưa phải một transaction; khi có lỗi giữa hai lần ghi, report trong feature run là nguồn thông tin lineage để đối chiếu. Không chạy đồng thời nhiều tiến trình publisher trong MVP này.

## 7. Ranh giới trước khi dùng online

Từ contract `day4-v4`, feature và nhãn được tách thành hai bảng:

```
windowed ──► scoring_features  (mọi ngày đủ điều kiện đến raw_end, KHÔNG nhãn, KHÔNG split) ──► 6 bảng fs_*
                   │
                   └─ JOIN nhãn, chỉ ngày đủ cửa sổ 30 ngày ──► snapshots ──► candidate (bỏ embargo) ──► training_dataset
```

- `fs_*` gồm cả ngày embargo và 30 ngày cuối chưa có nhãn, nên batch scoring luôn có ngày mới nhất (`raw_end`).
- `training_dataset` lấy feature **sao chép** từ `scoring_features`, không tính lại; quality gate `scoring.training_parity` kiểm tra mọi feature trùng nhau ở cùng khóa, `scoring.covers_every_candidate_key` kiểm tra không thiếu khóa.
- Điều kiện vòng đời vẫn áp dụng cho scoring: tài khoản mở ít nhất 30 ngày, trước ngày đóng hoặc dormant.
- `campaign_training_dataset` có grain campaign-event riêng và vẫn ghép với `candidate`.
- Online (Redis, Feast online) thuộc giai đoạn 2; khi làm, nạp từ `fs_*` này.

Kiểm thử point-in-time hiện kiểm chứng theo **event time**. Chưa có `ingested_at`/`available_at` để chứng minh một event đến muộn đã thực sự sẵn sàng tại thời điểm dự báo lịch sử.

## 8. Feast offline (contract `day4-v5`)

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
