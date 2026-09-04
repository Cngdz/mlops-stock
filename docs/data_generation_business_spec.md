# Đặc tả nghiệp vụ sinh dữ liệu synthetic

## 1. Mục đích và phạm vi

Tài liệu này là đặc tả nghiệp vụ cho việc sinh dữ liệu synthetic phục vụ demo nền tảng MLOps dự báo nhu cầu vay margin/MBLink.

Dữ liệu được sinh để kiểm thử toàn bộ vòng đời ML:

```text
Sinh dữ liệu → tạo feature/label → train → đăng ký model → serving → monitoring
```

Dữ liệu synthetic phải có quan hệ nghiệp vụ hợp lý, có tín hiệu đủ rõ để model học được, nhưng không được dùng để kết luận về hành vi khách hàng thật hoặc hiệu quả kinh doanh thật.

Phạm vi của tài liệu:

- Bốn bảng dữ liệu nguồn ở Gold layer.
- Quy tắc tạo tài khoản, giao dịch, số dư margin và sự kiện giải ngân.
- Quy tắc tạo `loan_label_next`.
- Quy ước thời gian, khóa, kiểu dữ liệu và ràng buộc chất lượng.
- Cách xuất dữ liệu Parquet để các pipeline pandas/DuckDB/Iceberg/Feast sử dụng.

Không nằm trong phạm vi:

- Mô phỏng giá cổ phiếu chính xác.
- Mô hình hóa đầy đủ nghiệp vụ tín dụng thật.
- Sử dụng dữ liệu cá nhân hoặc dữ liệu production.
- Kết luận tài chính từ kết quả model trên dữ liệu synthetic.

## 2. Bối cảnh nghiệp vụ

Hệ thống cần dự báo xác suất một tài khoản chứng khoán sẽ phát sinh ít nhất một sự kiện giải ngân margin/MBLink trong 30 ngày tiếp theo.

Tại ngày `report_date`, hệ thống chỉ được nhìn thấy dữ liệu đến hết ngày đó. Model tạo ra điểm số cho tài khoản và có thể được dùng để cá nhân hóa ưu đãi lãi suất margin.

Ví dụ:

```text
Tài khoản: 0001234567
Ngày dự báo: 2026-01-10
Khoảng quan sát: dữ liệu <= 2026-01-10
Khoảng tạo nhãn: 2026-01-11 đến 2026-02-09
```

Nếu trong khoảng tạo nhãn có một sự kiện giải ngân hợp lệ thì `loan_label_next = 1`; nếu không thì `loan_label_next = 0`.

Đây là bài toán propensity/response prediction, không phải bài toán dự báo giá cổ phiếu.

## 3. Quy ước chung

### 3.1 Thời gian

- Múi giờ nghiệp vụ: `Asia/Ho_Chi_Minh`.
- Các cột ngày dùng kiểu `DATE` hoặc Parquet `date32`.
- Các cột thời điểm dùng kiểu timestamp có timezone hoặc quy đổi nhất quán về UTC khi lưu trữ.
- `business_date` là ngày mà số dư được chốt.
- `report_date` là ngày snapshot dùng để tạo một dòng huấn luyện hoặc một request scoring.
- Khoảng nhãn là đóng ở hai đầu theo ngày nghiệp vụ:

  ```text
  report_date + 1 <= event_date <= report_date + 30
  ```

### 3.2 Tiền và số lượng

- Đơn vị tiền: VND.
- Số tiền lưu dạng số thực hoặc số nguyên VND, không dùng chuỗi có dấu phân cách.
- Số dư, hạn mức, giá trị tài sản và giá trị giao dịch không âm.
- Khối lượng cổ phiếu là số nguyên dương.
- Giá cổ phiếu là số thực dương.

### 3.3 Khóa và định danh

- `master_account` là khóa nghiệp vụ của tài khoản, dạng chuỗi 10 ký tự để không mất số 0 ở đầu.
- Không dùng số thứ tự dòng làm khóa nghiệp vụ.
- `transaction_id` và `cash_flow_id` là duy nhất trong toàn bộ dataset.
- Các bảng con chỉ được tham chiếu tới tài khoản tồn tại trong `customer_account`.

### 3.4 Tính tái lập

- Generator phải nhận `seed` từ tham số dòng lệnh hoặc file cấu hình.
- Cùng `seed`, cùng khoảng thời gian và cùng tham số phải tạo ra cùng dữ liệu.
- Không dùng dữ liệu thật, tên thật, số tài khoản thật hoặc mã định danh có thể truy ngược cá nhân.
- Nên lưu metadata sinh dữ liệu: seed, thời gian bắt đầu/kết thúc, số tài khoản, phiên bản generator.

## 4. Quy mô dữ liệu đề xuất

Dataset mặc định:

| Thành phần | Giá trị đề xuất |
|---|---:|
| Số tài khoản | 5.000–10.000 |
| Lịch sử | 6 tháng, có thể mở rộng 12 tháng |
| Ngày giao dịch | Các ngày trong tuần, loại trừ một số ngày nghỉ mô phỏng |
| Giao dịch | Khoảng 20–100 giao dịch/tài khoản/tháng tùy hành vi |
| Snapshot training | Hàng ngày hoặc 2–3 ngày/lần |
| Số snapshot/tài khoản | Chỉ lấy các ngày còn đủ 30 ngày tương lai để tạo nhãn |

Với 10.000 tài khoản và snapshot hằng ngày, số dòng feature có thể lên đến khoảng 1–2 triệu dòng. Nếu laptop thiếu tài nguyên, dùng snapshot hằng tuần trước rồi mở rộng sau.

## 5. Mô hình hành vi ẩn dùng để sinh dữ liệu

Generator nên tạo một số biến ẩn để điều khiển hành vi. Các biến này chỉ dùng trong generator, không xuất trực tiếp vào feature table để tránh leakage.

Mỗi tài khoản có thể có:

- `wealth_level`: mức tài sản tiềm năng.
- `trading_propensity`: xu hướng giao dịch.
- `margin_affinity`: xu hướng sử dụng margin.
- `risk_appetite`: mức chấp nhận rủi ro.
- `activity_stability`: mức ổn định của hoạt động.

Các biến ẩn nên được lấy từ phân phối có seed và được giới hạn trong khoảng `[0, 1]`.

Xác suất hoạt động trong một ngày có thể được xây dựng theo dạng:

```text
p_trade = sigmoid(
    intercept
    + 1.5 * trading_propensity
    + 0.4 * activity_stability
    + nhiễu theo ngày
)
```

Xác suất phát sinh giải ngân có thể phụ thuộc vào giao dịch, tài sản, hạn mức và segment:

```text
p_margin_event = sigmoid(
    intercept
    + 1.0 * margin_affinity
    + 0.5 * recent_trade_activity
    + 0.4 * wealth_level
    + 0.3 * risk_appetite
    + hiệu ứng segment
)
```

Các hệ số chỉ là gợi ý. Mục tiêu là tạo tương quan nghiệp vụ có thể giải thích, không phải tạo một ground truth quá dễ đoán.

Không được tạo feature trực tiếp từ `p_margin_event`, `margin_affinity` hoặc một biến tương đương với label.

## 6. Phân khúc khách hàng

Ba segment phục vụ ba model riêng:

| Segment | Ý nghĩa nghiệp vụ | Điều kiện xác định tại `report_date` |
|---|---|---|
| `nu` | Non-user | Chưa từng có sử dụng margin/MBLink hợp lệ trước hoặc tại `report_date` |
| `lu` | Lapsed user | Từng sử dụng margin/MBLink nhưng hiện không còn dư nợ và không có hoạt động gần đây |
| `au` | Active user | Đang có dư nợ hoặc có hoạt động margin gần đây |

Segment phải được xác định chỉ từ lịch sử đến `report_date`. Không được nhìn vào sự kiện trong 30 ngày tương lai.

Quy tắc cụ thể có thể dùng:

```text
au = margin_debt(report_date) > 0
      OR có sự kiện margin hợp lệ trong 30 ngày trước report_date

lu = đã từng có sự kiện margin hợp lệ trước report_date
      AND margin_debt(report_date) = 0
      AND không có sự kiện margin hợp lệ trong 30 ngày trước report_date

nu = chưa từng có sự kiện margin hợp lệ trước hoặc tại report_date
```

Nếu một tài khoản có thể chuyển segment theo thời gian, segment phải được lưu ở snapshot feature table, không nên coi là thuộc tính bất biến của `customer_account`.

Generator phải kiểm tra số lượng và positive rate của cả ba segment. Không để một segment có toàn bộ label bằng 0 hoặc toàn bộ label bằng 1.

## 7. Bảng nguồn `customer_account`

### 7.1 Grain

Một dòng đại diện cho một tài khoản duy nhất.

### 7.2 Schema đề xuất

| Cột | Kiểu | Bắt buộc | Ý nghĩa |
|---|---|---:|---|
| `master_account` | string | Có | Mã tài khoản synthetic, khóa chính |
| `account_open_date` | date | Có | Ngày mở tài khoản |
| `account_status` | string | Có | `ACTIVE`, `DORMANT`, `CLOSED` |
| `customer_group` | string | Có | Nhóm khách hàng ổn định, không phải segment model |
| `risk_profile` | string | Có | Ví dụ `LOW`, `MEDIUM`, `HIGH` |
| `created_at` | timestamp | Có | Thời điểm sinh bản ghi |

### 7.3 Ràng buộc

- `master_account` duy nhất và không null.
- `account_open_date` không nằm sau ngày bắt đầu lịch sử.
- Tài khoản `CLOSED` không phát sinh giao dịch mới sau ngày đóng.
- `customer_group` và `risk_profile` là thuộc tính synthetic ổn định; không dùng chúng để mã hóa trực tiếp label.

## 8. Bảng nguồn `stock_transaction`

### 8.1 Grain

Một dòng đại diện cho một giao dịch mua hoặc bán của một tài khoản.

### 8.2 Schema đề xuất

| Cột | Kiểu | Bắt buộc | Ý nghĩa |
|---|---|---:|---|
| `transaction_id` | string | Có | Khóa giao dịch |
| `master_account` | string | Có | Khóa tham chiếu tài khoản |
| `symbol` | string | Có | Mã cổ phiếu synthetic |
| `transaction_time` | timestamp | Có | Thời điểm giao dịch |
| `side` | string | Có | `BUY` hoặc `SELL` |
| `quantity` | int64 | Có | Khối lượng |
| `price` | float64 | Có | Giá tại thời điểm giao dịch |
| `trade_value` | float64 | Có | `quantity * price` |
| `is_margin_buy` | boolean | Có | Có mua bằng nguồn margin hay không |

### 8.3 Quy tắc sinh

- Chỉ sinh giao dịch trong ngày giao dịch.
- Tài khoản có `trading_propensity` cao sinh nhiều giao dịch hơn.
- `BUY` và `SELL` có phân phối khác nhau nhưng tổng thể phải hợp lý.
- Mã cổ phiếu lấy từ một universe synthetic cố định, ví dụ 20–50 mã.
- Giá có thể sinh bằng random walk đơn giản, không cần mô phỏng thị trường thực.
- `trade_value` phải khớp với `quantity * price` trong sai số cho phép.
- `is_margin_buy` chỉ dùng để mô phỏng quan hệ với margin; không dùng trực tiếp làm feature nếu nó tiết lộ label.

## 9. Bảng nguồn `margin_balance_daily`

### 9.1 Grain

Một dòng đại diện cho trạng thái margin của một tài khoản tại một `business_date`.

### 9.2 Schema đề xuất

| Cột | Kiểu | Bắt buộc | Ý nghĩa |
|---|---|---:|---|
| `master_account` | string | Có | Khóa tài khoản |
| `business_date` | date | Có | Ngày chốt số dư |
| `margin_debt` | float64 | Có | Dư nợ margin |
| `margin_limit` | float64 | Có | Hạn mức margin |
| `asset_value` | float64 | Có | Giá trị tài sản |
| `cash_balance` | float64 | Có | Số dư tiền |
| `collateral_value` | float64 | Có | Giá trị tài sản đảm bảo |
| `margin_status` | string | Có | `NO_MARGIN`, `ACTIVE`, `OVERDUE` |

### 9.3 Quy tắc sinh

- Có tối đa một dòng cho mỗi cặp `(master_account, business_date)`.
- `margin_limit >= 0`, `margin_debt >= 0`, `asset_value >= 0`.
- Tài khoản `nu` không có dư nợ trước lần sử dụng margin đầu tiên.
- Tài khoản `au` thường có `margin_debt > 0` hoặc lịch sử dư nợ gần đây.
- Có thể cho phép `margin_debt <= margin_limit`; nếu mô phỏng quá hạn thì ghi rõ quy tắc riêng, không tạo dữ liệu mâu thuẫn ngẫu nhiên.
- Tính được `margin_utilization_ratio = margin_debt / margin_limit`; khi `margin_limit = 0`, phải có policy rõ ràng, ví dụ gán `0.0` hoặc null.

## 10. Bảng nguồn `margin_cash_flow`

### 10.1 Grain

Một dòng đại diện cho một sự kiện dòng tiền margin/MBLink.

### 10.2 Schema đề xuất

| Cột | Kiểu | Bắt buộc | Ý nghĩa |
|---|---|---:|---|
| `cash_flow_id` | string | Có | Khóa sự kiện |
| `master_account` | string | Có | Khóa tài khoản |
| `event_date` | date | Có | Ngày phát sinh sự kiện |
| `fk_product` | string | Có | `MARGIN_MBS`, `MBLINK`, hoặc loại không mục tiêu |
| `fk_cash_flow_type` | string | Có | Loại dòng tiền |
| `fk_deliver_type` | string | Có | Mục đích giải ngân |
| `amount` | float64 | Có | Số tiền |
| `status` | string | Có | `POSTED`, `CANCELLED` |

### 10.3 Tổ hợp nghiệp vụ hợp lệ

Một event được xem là event tạo label dương nếu thỏa mãn một trong hai tổ hợp:

```text
(fk_product = 'MARGIN_MBS'
 AND fk_cash_flow_type = 'INTERM_DELIVER'
 AND fk_deliver_type = 'BUY_SHARE')

OR

(fk_product = 'MBLINK'
 AND fk_cash_flow_type = 'TLO_DELIVER_CASH'
 AND fk_deliver_type = 'BUY')
```

Các event khác có thể được sinh để mô phỏng dữ liệu nghiệp vụ nhưng không được tính là positive event.

### 10.4 Quy tắc sinh

- Event phải tham chiếu tài khoản tồn tại.
- `amount > 0` với event `POSTED`.
- Event `CANCELLED` không được tính vào label.
- Xác suất event phụ thuộc vào giao dịch, dư nợ, tài sản và `margin_affinity` ẩn.
- Không sinh event hợp lệ cho tài khoản `nu` trước thời điểm nó chuyển sang trạng thái đã sử dụng margin.
- Không tạo nhiều bản ghi trùng `cash_flow_id`.

## 11. Thứ tự sinh dữ liệu

Phải sinh theo thứ tự sau để đảm bảo khóa ngoại và quan hệ thời gian:

1. Sinh lịch ngày và universe mã cổ phiếu.
2. Sinh `customer_account`.
3. Sinh `stock_transaction` theo hoạt động của từng tài khoản.
4. Sinh `margin_cash_flow` dựa trên giao dịch, tài sản và hành vi ẩn.
5. Sinh `margin_balance_daily` từ trạng thái ban đầu, event và biến động tài sản.
6. Tạo các `report_date` hợp lệ.
7. Tính segment tại từng `report_date`.
8. Tạo feature snapshot và `loan_label_next`.
9. Chạy data-quality checks.
10. Xuất Parquet và metadata.

Có thể sinh `margin_balance_daily` trước `margin_cash_flow` nếu generator dùng state machine, nhưng đầu ra cuối cùng phải thỏa các ràng buộc ở cả hai bảng.

## 12. Tạo snapshot và nhãn

### 12.1 Candidate snapshot

Mỗi candidate snapshot là một cặp `(master_account, report_date)`.

Chỉ tạo snapshot nếu:

```text
report_date <= max_event_date - 30 ngày
```

Như vậy mọi snapshot đều có đủ cửa sổ tương lai để xác định label.

### 12.2 Logic label

Pseudo-SQL:

```sql
SELECT
    s.master_account,
    s.report_date,
    CASE WHEN EXISTS (
        SELECT 1
        FROM margin_cash_flow cf
        WHERE cf.master_account = s.master_account
          AND cf.event_date BETWEEN s.report_date + INTERVAL '1 day'
                                AND s.report_date + INTERVAL '30 day'
          AND cf.status = 'POSTED'
          AND (
                (cf.fk_product = 'MARGIN_MBS'
                 AND cf.fk_cash_flow_type = 'INTERM_DELIVER'
                 AND cf.fk_deliver_type = 'BUY_SHARE')
             OR (cf.fk_product = 'MBLINK'
                 AND cf.fk_cash_flow_type = 'TLO_DELIVER_CASH'
                 AND cf.fk_deliver_type = 'BUY')
          )
    ) THEN 1 ELSE 0 END AS loan_label_next
FROM snapshots s;
```

### 12.3 Ví dụ

| Tài khoản | `report_date` | Event hợp lệ trong 30 ngày sau | `loan_label_next` |
|---|---|---|---:|
| A | 2026-01-10 | Có event ngày 2026-01-20 | 1 |
| B | 2026-01-10 | Chỉ có event bị `CANCELLED` | 0 |
| C | 2026-01-10 | Có event không đúng tổ hợp nghiệp vụ | 0 |
| D | 2026-01-10 | Không có event | 0 |

## 13. Feature snapshot và chống leakage

Feature tại `report_date` chỉ được tính từ các bảng với điều kiện thời gian:

```text
transaction_time <= report_date cuối ngày
business_date <= report_date
event_date <= report_date
```

Ví dụ feature:

| Nhóm | Feature | Khoảng dữ liệu |
|---|---|---|
| Demographic | `account_age_days` | Từ ngày mở đến `report_date` |
| Trading | `trade_count_7d` | `report_date - 6` đến `report_date` |
| Trading | `total_trading_amount_30d` | 30 ngày kết thúc tại `report_date` |
| Margin | `margin_utilization_ratio` | Số dư tại `report_date` |
| Margin | `debt_change_7d` | So sánh dư nợ trong 7 ngày |
| Asset | `cash_balance`, `NAV` | Số dư tại `report_date` |

Ngày 4 không yêu cầu feature `days_since_last_margin_event`; lịch sử event vẫn cần để xác định segment tại snapshot.

Các cột sau không được làm input feature:

- `loan_label_next`.
- Ngày hoặc thông tin chỉ biết sau `report_date`.
- Biến ẩn như `margin_affinity` hoặc `risk_appetite` nếu không có ý nghĩa nghiệp vụ quan sát được.
- Cờ generator được tạo trực tiếp từ label.

## 14. Train/validation/test split

Split phải theo thời gian, không random toàn bộ dữ liệu.

Ví dụ:

```text
Train:      2025-02-01 .. 2025-06-30
Validation: 2025-07-31 .. 2025-09-30
Test:       2025-10-31 .. 2025-12-31
Embargo:    30 ngày giữa các tập
```

Khuyến nghị có embargo tối thiểu 30 ngày giữa các split nếu các cửa sổ label bị chồng lấn. Tài liệu kết quả phải ghi rõ mốc ngày của từng split.

Mỗi split cần kiểm tra:

- Có đủ cả ba segment.
- Có cả label 0 và 1.
- Positive rate không lệch quá cực đoan.
- Không có cùng một snapshot xuất hiện ở nhiều split.

## 15. Data-quality checks bắt buộc

### 15.1 Kiểm tra cấu trúc

- Tất cả cột bắt buộc tồn tại.
- Kiểu dữ liệu đúng schema.
- Khóa chính không null và không trùng.
- Khóa ngoại hợp lệ.

### 15.2 Kiểm tra miền giá trị

- Tiền, giá, khối lượng không âm.
- `side`, `status`, `segment` chỉ nhận giá trị trong danh sách cho phép.
- `trade_value` khớp với quantity và price.
- Các tỷ lệ nằm trong khoảng hợp lý.

### 15.3 Kiểm tra thời gian

- Không có giao dịch trước ngày mở tài khoản.
- Không có event sau ngày đóng tài khoản.
- `business_date` và `event_date` nằm trong khoảng lịch sử.
- Feature không đọc dữ liệu sau `report_date`.
- Label chỉ đọc cửa sổ `report_date+1` đến `report_date+30`.

### 15.4 Kiểm tra nghiệp vụ

- Tài khoản `nu` không có lịch sử margin trước thời điểm phù hợp.
- `au` có dư nợ hoặc event gần đây theo định nghĩa.
- Mỗi tổ hợp event hợp lệ có thể truy vết được.
- Label được tái tính bằng query độc lập và khớp với bảng snapshot.

### 15.5 Kiểm tra phân phối

Theo từng segment, xuất báo cáo:

- Số tài khoản.
- Số snapshot.
- Positive rate.
- Số giao dịch trung bình.
- Giá trị giao dịch trung bình.
- Dư nợ và hạn mức trung bình.
- Tỷ lệ null.

Nếu một segment có positive rate bằng 0% hoặc 100%, phải điều chỉnh generator trước khi train.

## 16. Format và cấu trúc file đầu ra

Đề xuất cấu trúc:

```text
data/
├── raw/
│   ├── customer_account.parquet
│   ├── stock_transaction.parquet
│   ├── margin_balance_daily.parquet
│   └── margin_cash_flow.parquet
├── snapshots/
│   └── account_snapshots.parquet
├── features/
│   ├── fs_demographic.parquet
│   ├── fs_trading_behavior.parquet
│   ├── fs_margin_balance.parquet
│   ├── fs_asset_balance.parquet
│   └── training_dataset.parquet
└── metadata/
    └── generation_run.json
```

`generation_run.json` nên chứa:

```json
{
  "seed": 42,
  "num_accounts": 5000,
  "history_start": "2025-07-01",
  "history_end": "2026-01-31",
  "generator_version": "0.1.0"
}
```

Parquet phải giữ đúng kiểu dữ liệu và tên cột ổn định để dùng được trong pandas, DuckDB, PyArrow, Iceberg và Feast.

## 17. Tiêu chí nghiệm thu

Bộ dữ liệu được coi là đạt khi:

1. Có đủ bốn bảng nguồn Parquet.
2. Có thể join bốn bảng theo `master_account`.
3. Không có khóa chính trùng hoặc khóa ngoại mồ côi.
4. Có thể tái tính `loan_label_next` bằng query độc lập.
5. Có ít nhất hai class trong mỗi segment.
6. Có train/validation/test split theo thời gian.
7. Có báo cáo positive rate và phân phối chính.
8. Có kiểm tra không leakage.
9. Chạy lại cùng seed cho kết quả tái lập.
10. Dataset đọc được bằng pandas và DuckDB trước khi ghi sang Iceberg.

## 18. Nguyên tắc diễn giải kết quả

Dữ liệu synthetic chỉ nhằm chứng minh:

- Pipeline có chạy đúng hay không.
- Feature có được tạo đúng thời điểm hay không.
- Model có học được tín hiệu hay không.
- Registry, serving, monitoring và retraining có kết nối đúng hay không.

Không được diễn giải accuracy, AUC, lift hoặc tỷ lệ khách hàng dự báo dương trên dataset này như kết quả kinh doanh thực tế.
