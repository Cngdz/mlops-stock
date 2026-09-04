# MLOps — Day 4

Pipeline chính thức: raw Iceberg → bốn nhóm `fs_*` + nhãn → training dataset → quality gate.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/day4_feature_engineering.py
```

- Input: namespace trong `data/source_current.json` (hiện là `raw_day4_v2`) ở SQLite catalog `data/catalog_full/pyiceberg.db`. Có thể chọn rõ bằng `--source-namespace`; chỉ fallback `raw` khi chưa có nguồn đã duyệt.
- Output khi PASS: `data/features/day4_runs/<run_id>/` và namespace Iceberg có version.
- Exit 0: đã duyệt, `data/features/current.json` trỏ tới phiên bản duy nhất được phép dùng.
- Exit 2: gate FAIL, chỉ ghi `source_validation.json` hoặc `rejected_quality_report.json` trong `data/features/`; không tạo dataset, class weights hay bảng Iceberg.
- Báo cáo: [docs/day4_report.md](docs/day4_report.md).
- Generator chỉ sinh source tables. Các dataset cũ/QA và smoke test đã xóa; số liệu lần kiểm tra cũ được giữ trong `docs/day4_quality_history.json` (đường dẫn output trong đó chỉ còn ý nghĩa lịch sử).

Giữ nguyên ngưỡng chất lượng theo business/decision. Lỗi timestamp/schema và phân phối nguồn phải sửa ở generator, không sửa label hoặc hạ ngưỡng trong feature pipeline.

Nguồn mới đã sửa schema, timestamp, lifecycle và balance; dùng xác suất trả nợ 10%/ngày được người dùng duyệt trong decision §8.5. Calibration pilot 500 tài khoản dùng seed 42; cấu hình nằm ở `data/generation_calibration.json`.

Để tạo một phiên bản nguồn khác, chọn thư mục và namespace mới chưa tồn tại:

```powershell
.\.venv\Scripts\python.exe -m data_generation.calibrate
.\.venv\Scripts\python.exe -m data_generation.generate_all --num-accounts 5000 --output data/generated/my_run --calibration data/generation_calibration.json
.\.venv\Scripts\python.exe scripts/day3_write_iceberg.py --input-dir data/generated/my_run --namespace raw_my_run
.\.venv\Scripts\python.exe scripts/day4_feature_engineering.py --source-namespace raw_my_run
```

Generator từ chối ghi đè thư mục có dữ liệu. Ingest không ghi đè bảng đã tồn tại. Source pointer chỉ đổi sau khi ngày 4 PASS. Muốn cập nhật báo cáo Markdown mà không tạo dataset mới: `scripts/day4_feature_engineering.py --report-only`.
