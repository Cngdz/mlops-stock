# Báo cáo Ngày 4 — Feature engineering và nhãn

## Kết luận

**PASS 90/90 quality checks** trên nguồn raw_day4_v4.
Run: 20261026T104902612352; 1,580,646 snapshot; 193.19 giây cho pipeline ngày 4.
Positive rate toàn bộ: 24.6053%. Null ở cột bắt buộc: 0.

Đầu ra đã được duyệt qua data/features/current.json. Nguồn mặc định cho lần chạy tiếp theo nằm trong data/source_current.json.

## Các lỗi nguồn đã sửa

- Sinh timestamp bằng datetime/timedelta; lưu UTC microsecond trong Iceberg, tính ngày nghiệp vụ theo Asia/Ho_Chi_Minh.
- Cash-flow dùng schema chuẩn fk_product/fk_cash_flow_type/fk_deliver_type; phân biệt POSTED/CANCELLED, repayment, fee và non-target event.
- Suy ra ACTIVE/DORMANT/CLOSED theo từng ngày. Giữ balance đến raw_end; số dư về 0 từ ngày đóng.
- Hạn mức theo risk_profile; amount giải ngân bị chặn bởi available_limit; OVERDUE chỉ sau ba ngày giao dịch vượt hạn mức.
- Tính NAV và collateral_value; tỷ lệ có mẫu số 0 trả về 0.0.
- Ngày mở tài khoản nằm trong tháng 1; archetype chỉ dùng nội bộ để sinh hành vi.
- RNG tách theo tài khoản/stream, được kiểm thử không thay đổi dữ liệu tài khoản cũ khi thêm tài khoản mới.

## Thay đổi đã được người dùng duyệt

Xác suất trả nợ tăng từ 5% lên 10%/ngày khi ACTIVE và có dư nợ; đã cập nhật decision §8.5 cùng các cấu hình tương ứng.
Giữ nguyên định nghĩa label và toàn bộ ngưỡng quality gate. Calibration chỉ điều chỉnh xác suất sinh event, không thay nhãn sau khi sinh.
Metadata/snapshot ID của chính nguồn được kiểm tra nằm trong quality_report.json. Tham số generator và calibration cần đối chiếu với generation_run.json của lần sinh nguồn tương ứng; báo cáo này không suy đoán từ tên thư mục.

## Feature và nhãn

Snapshot account-day có khóa (master_account, report_date). Bảng fs_* không chứa label; training_dataset dùng cho loan/overdue, còn campaign_training_dataset có grain campaign-event.
Feature chỉ dùng dữ liệu đến cuối ngày D; cửa sổ 7 ngày là D−6..D, 30 ngày là D−29..D.
debt_change_7d lấy đúng số dư D−7, không dịch bảy dòng trên một tập đã lọc.
loan_label_next dùng event POSTED đúng tổ hợp Margin MBS hoặc MBLink trong D+1..D+30. overdue_label_next_30d là lần bắt đầu OVERDUE mới trong D+1..D+30, chỉ cho tài khoản có dư nợ hoặc lịch sử margin và không đang OVERDUE tại D; campaign_response_label_14d dùng valid event trong 14 ngày sau lần gửi DELIVERED.
Segment: au khi còn dư nợ hoặc có event hợp lệ trong 30 ngày gần nhất; lu khi từng dùng nhưng hiện không dư nợ và không có event gần đây; còn lại nu.
Không xuất days_since_last_margin_event, biến ẩn hoặc cờ generator vào feature.

| Nhóm | Feature |
|---|---|
| fs_demographic | account_age_days, margin_segment |
| fs_trading_behavior | trade_count_7d, trade_count_30d, total_trading_amount_7d, total_trading_amount_30d, active_trading_days_30d |
| fs_margin_balance | margin_debt, margin_limit, margin_utilization_ratio, debt_change_7d, over_limit_streak, over_limit_days_30d |
| fs_asset_balance | cash_balance, asset_value, collateral_value, cash_to_asset_ratio, NAV |
| fs_portfolio | portfolio_value, holding_symbol_count, portfolio_concentration, unrealized_loss_ratio, risky_asset_ratio |
| fs_campaign | campaign_count_30d, days_since_last_campaign, has_campaign_history |

## Split và kết quả

Split mặc định (neo vào ngày có nhãn cuối 2025-12-31): train 2025-02-01..2025-06-30; validation 2025-07-31..2025-09-30; test 2025-10-31..2025-12-31. training.train --as-of chia lại theo cửa sổ trượt.
Giữ 296,464 snapshot embargo (split='embargo') để training.train --as-of chia lại theo ngày. Chỉ lấy tài khoản ACTIVE, tuổi ≥30 ngày và đủ 30 ngày dữ liệu tương lai.

| Split | Segment | Số dòng | Positive | Positive rate |
|---|---|---:|---:|---:|
| embargo | au | 118,039 | 45,763 | 38.7694% |
| embargo | lu | 73,413 | 20,481 | 27.8983% |
| embargo | nu | 105,012 | 14,041 | 13.3709% |
| test | au | 119,817 | 47,015 | 39.2390% |
| test | lu | 106,211 | 24,055 | 22.6483% |
| test | nu | 68,957 | 5,108 | 7.4075% |
| train | au | 158,627 | 57,138 | 36.0203% |
| train | lu | 39,693 | 15,484 | 39.0094% |
| train | nu | 481,912 | 75,707 | 15.7097% |
| validation | au | 125,515 | 48,312 | 38.4910% |
| validation | lu | 77,816 | 22,382 | 28.7627% |
| validation | nu | 105,634 | 13,436 | 12.7194% |

Tỷ trọng tại snapshot cuối (gate: mỗi segment ≥10%):

- nu: 21.4965%.
- lu: 39.3997%.
- au: 39.1038%.

## Class imbalance

Balanced class weight = N/(2×N_class), tính riêng từng segment trên train. Không resample validation/test; không kết hợp thêm scale_pos_weight.

| Segment | Weight 0 | Weight 1 |
|---|---:|---:|
| nu | 0.593188 | 3.182744 |
| lu | 0.819798 | 1.281742 |
| au | 0.781498 | 1.388104 |

## Kiểm chứng

- Source gate: schema, timestamp, lịch sử balance đầy đủ.
- Quality gate: khóa, null, foreign key, miền giá trị, vòng đời tài khoản, biên thời gian, cả hai lớp trong từng split/segment.
- Đối soát dư nợ toàn bộ panel bằng giải ngân/trả nợ POSTED và trạng thái đóng tài khoản.
- Đối chiếu độc lập rolling/label cho 150 snapshot bằng truy vấn trực tiếp.
- Đọc lại mọi bảng Iceberg, sắp theo khóa và so sánh toàn bộ nội dung với Parquet; có SHA-256 và snapshot IDs trong quality_report.json.
- Unit tests tại tests/test_day4.py và tests/test_generator.py: boundary, point-in-time, lifecycle, RNG độc lập, công thức số dư, timezone và class weights.

## Đầu ra

Thư mục: C:\hoctapUET\DE\MLops\data\features\day4_runs\20261026T104902612352

- fs_demographic.parquet: 1,722,576 dòng; Iceberg features_20261026t104902612352.fs_demographic.
- fs_trading_behavior.parquet: 1,722,576 dòng; Iceberg features_20261026t104902612352.fs_trading_behavior.
- fs_margin_balance.parquet: 1,722,576 dòng; Iceberg features_20261026t104902612352.fs_margin_balance.
- fs_asset_balance.parquet: 1,722,576 dòng; Iceberg features_20261026t104902612352.fs_asset_balance.
- fs_portfolio.parquet: 1,722,576 dòng; Iceberg features_20261026t104902612352.fs_portfolio.
- fs_campaign.parquet: 1,722,576 dòng; Iceberg features_20261026t104902612352.fs_campaign.
- training_dataset.parquet: 1,580,646 dòng; Iceberg features_20261026t104902612352.training_dataset.
- campaign_training_dataset.parquet: 36,399 dòng; Iceberg features_20261026t104902612352.campaign_training_dataset.
- loan_overdue_labels.parquet: 1,580,646 dòng; Iceberg features_20261026t104902612352.loan_overdue_labels.
- campaign_labels.parquet: 36,212 dòng; Iceberg features_20261026t104902612352.campaign_labels.
- quality_report.json: checks, provenance, hashes.
- class_weights.json: weights đã duyệt.
- data/features/current.json: trỏ đến phiên bản training đã duyệt.
- data/source_current.json: trỏ đến nguồn Iceberg đã duyệt.

## Giới hạn và phạm vi nghiệm thu

PASS áp dụng cho quality gate ngày 4. Tỷ trọng segment đã đạt ngưỡng tối thiểu; chưa khớp các mục tiêu tham khảo nu=35–55%, lu=20–40%, au=15–35% trong decision §10.
Chưa nghiệm thu mục tiêu thống kê bổ sung như số giao dịch/tháng. Chưa train model (ngày 6), chưa đánh giá hiệu quả kinh doanh trên dữ liệu thật.
Nguồn không có ingestion timestamp nên kiểm thử point-in-time hiện bao phủ event time, chưa bao phủ late-arriving data trong production.
Các đường dẫn trong báo cáo thuộc môi trường tạo run. Khi chuyển máy, cần ingest lại dữ liệu và tạo run mới; không suy ra trạng thái hiện tại chỉ từ một báo cáo lịch sử.

## Chạy lại

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/day4_feature_engineering.py
```

Exit 2 chỉ ghi báo cáo lỗi; không xuất dataset khi gate FAIL.
Muốn cập nhật Markdown từ run đã duyệt mà không tạo thêm dataset: thêm --report-only.
