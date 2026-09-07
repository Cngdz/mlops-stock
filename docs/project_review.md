# Nhận xét dự án và kế hoạch cải thiện

Ngày rà soát: 2026-09-06. Phạm vi: mã nguồn, tests, cấu hình hạ tầng, tài liệu nghiệp vụ/lộ trình và metadata dữ liệu cục bộ. Lộ trình gốc có thay đổi đang làm trước phiên rà soát; tài liệu này bổ sung nhận xét riêng.

## 1. Đánh giá tổng thể

Dự án có nền tảng dữ liệu tốt cho một đồ án MLOps: quy tắc nghiệp vụ rõ, generator tái lập, chia tập theo thời gian và cơ chế chặn dữ liệu lỗi trước khi xuất bản. Giá trị nổi bật nằm ở khả năng giải thích một dòng training được tạo từ đâu và vì sao được duyệt.

Khoảng cách lớn nhất nằm giữa **pipeline dữ liệu đã có mã** và **vòng đời MLOps đầy đủ trong lộ trình**. Nên hoàn thiện một luồng nhỏ có bằng chứng chạy được, rồi mở rộng tích hợp. Việc thêm nhiều công cụ cùng lúc sẽ làm khó xác định lỗi thuộc dữ liệu, model hay hạ tầng.

| Thành phần | Bằng chứng trong repository | Đánh giá |
|---|---|---|
| Nghiệp vụ và generator | Business spec, decision, calibration, account/event/balance generators | Có chiều sâu; cần bổ sung lineage cấu hình |
| Lưu trữ nguồn | Parquet → PyIceberg, SQLite catalog, local warehouse | Đã có mã; ingest cần tách rõ từng batch |
| Feature/label | SQL rolling, lifecycle, embargo, nhãn D+1..D+30 | Khá chặt cho historical training |
| Chất lượng | Source gate, quality gate, readback toàn bộ, hashes | Nền tảng tốt; cần mở rộng tình huống lỗi xuất bản |
| MLflow | Helm values và Iris smoke script | Chưa phải training pipeline margin |
| Feast, API, KServe, Airflow, monitoring | Mô tả trong timeline | Chưa có mã tương ứng trong repository |

## 2. Những điểm nên giữ

1. **Nhãn gắn với event thực sự.** Phân biệt tổ hợp nghiệp vụ, POSTED/CANCELLED, ngày D và D+30; không tạo nhãn độc lập rồi ép feature theo nhãn.
2. **Kiểm thử theo biên nghiệp vụ.** Có fixture ngày D−6/D−29/D+30/D+31 và test thay dữ liệu tương lai để phát hiện leakage.
3. **Tách stream ngẫu nhiên.** Thêm tài khoản không làm thay dữ liệu tài khoản cũ; calibration cash flow không tiêu thụ RNG giao dịch.
4. **Version và chất lượng đi cùng nhau.** Lưu snapshot IDs, SHA-256, class weights chỉ từ train và đối chiếu Iceberg với Parquet trước khi chọn run.
5. **Decision baseline có giải thích.** Thay đổi repayment 5% → 10% được ghi lại cùng lý do; không âm thầm hạ gate cho dữ liệu vượt qua.

## 3. Các vấn đề đã sửa trong lần rà soát

| Vấn đề trước sửa | Thay đổi | Lợi ích |
|---|---|---|
| README chỉ mô tả ngày 4, dẫn tới báo cáo/lịch sử không có trong Git | Viết lại onboarding, thứ tự chạy, trạng thái triển khai, liên kết tài liệu | Người clone mới hiểu cần làm gì và chưa có gì |
| Schema gate chỉ kiểm tra hai cột cash flow | Kiểm tra các bảng, toàn bộ cột được pipeline dùng và nhóm kiểu dữ liệu | Thiếu `cash_balance` hoặc ngày lưu dạng chuỗi trở thành source FAIL có cấu trúc |
| Tài khoản không có balance và ngày mở NULL chịu ảnh hưởng của so sánh SQL với NULL | Dùng kiểm tra NULL/`IS DISTINCT FROM` ở source gate | Chặn lịch sử không đủ trước khi tính rolling |
| Ingest bỏ qua từng bảng tồn tại rồi tạo bảng còn thiếu | Từ chối batch có xung đột; kiểm tra đủ file và footer trước khi tạo bảng | Tránh trộn bảng của hai nguồn hoặc ghi dở chỉ vì thiếu file cuối |
| Ghi trực tiếp pointer JSON | Ghi file tạm cùng thư mục, flush rồi thay thế nguyên tử | Giữ pointer cũ khi thao tác thay file thất bại |
| Report giả định mọi run dùng thư mục nguồn cố định | Bỏ đường dẫn và lịch sử nguồn suy đoán | Báo cáo chỉ dẫn tới metadata của run được kiểm tra |

Có thêm test cho schema, lịch sử trống, gate FAIL không xuất bản, lỗi thay pointer, ingest dở và roundtrip SQLite/Iceberg thực trong thư mục tạm. Định nghĩa feature/label, split và các ngưỡng nghiệp vụ được giữ nguyên.

## 4. Những việc cần ưu tiên tiếp

### Ưu tiên 1 — Tách feature scoring khỏi nhãn training

`fs_*` hiện xuất từ `candidate`; candidate đã loại embargo và các ngày chưa đủ 30 ngày tương lai. Nếu dùng ngay làm offline source cho online serving, feature mới nhất sẽ bị thiếu hoặc cũ.

Đề xuất tách thành ba bước rõ ràng: feature tại ngày D dùng dữ liệu đến D; label tại D chỉ chốt sau D+30; training join feature với label đã đủ và áp dụng split/embargo. Dùng chung công thức feature giữa training và scoring để tránh sai lệch.

**Tiêu chí đạt:** với dữ liệu đến ngày T, xuất được feature tại T trong khi nhãn chỉ có đến T−30; feature ngày embargo vẫn tồn tại cho scoring; feature ở cùng khóa của hai luồng bằng nhau. Đây là việc nên làm trước tích hợp Feast/Redis.

### Ưu tiên 2 — Một training pipeline nhỏ, đầy đủ lineage

Đọc duy nhất run được `current.json` chọn. Chọn cột qua danh sách cho phép, fit preprocessing và class weights trên train; dùng validation chọn cấu hình, giữ test cho đánh giá cuối. Bắt đầu bằng baseline đơn giản trong stack scikit-learn đã có; việc thêm model so sánh theo timeline thực hiện sau khi luồng baseline chạy ổn.

Mỗi kết quả cần lưu feature run ID, snapshot nguồn, feature contract, seed, Git revision, metric theo segment và thời gian train. `master_account`, nhãn, split và biến ẩn không được trở thành input model.

**Tiêu chí đạt:** một lệnh tạo model cùng báo cáo; chạy lại trên cùng dữ liệu/config cho kết quả có thể đối chiếu; schema sai hoặc dataset chưa duyệt bị chặn. Thêm kiểm tra nhóm tài khoản chưa từng thấy nếu muốn đo khả năng tổng quát sang khách hàng mới; time split hiện tại chủ yếu đánh giá tương lai của tập tài khoản đã có.

### Ưu tiên 3 — Provenance generator và kiểm soát cấu hình

Decision baseline yêu cầu `generator_version`, giá trị cấu hình và checksum, nhưng `generation_run.json` hiện mới lưu seed, raw end, số tài khoản, intercepts, calibration và số dòng. Các hằng số đang lặp trong generator, SQL và gate.

Tạo cấu hình canonical có version, lưu cấu hình đã resolve cùng hash của từng file nguồn, Git revision và phiên bản dependencies. Namespace nguồn nên gắn với một manifest batch để chứng minh bốn bảng cùng lần sinh. Thêm validation cho tham số API như `repayment_probability` ngoài [0,1] và khoảng ngày mở vượt `raw_end` khi tùy biến generator.

**Tiêu chí đạt:** từ một feature run lần ngược được batch nguồn và cấu hình đầy đủ; sửa một tham số làm manifest thay đổi; không cần đoán từ tên thư mục.

### Ưu tiên 4 — Hoàn thiện lỗi xuất bản và khả năng chạy lại

Thay JSON nguyên tử bảo vệ từng file, chưa tạo transaction cho nhiều bảng hoặc hai pointer. Lỗi ghi Iceberg/Parquet vẫn có thể để lại artifacts dở; nhiều publisher đồng thời có thể chọn các run khác nhau.

Với MVP, vận hành tuần tự và chỉ cho downstream đọc pointer là đủ để tiến tiếp. Khi mở rộng, dùng một manifest có trạng thái STAGING/VERIFIED/PUBLISHED và khóa publisher; report lưu cùng run; cleanup artifacts dở là thao tác riêng có kiểm tra tham chiếu.

**Tiêu chí đạt:** giả lập lỗi ở từng bước ghi, readback, báo cáo và cập nhật pointer; consumer luôn chọn được một run hoàn chỉnh. Chạy lại không trộn source batch hay âm thầm nhân đôi dữ liệu.

### Ưu tiên 5 — Kiểm chứng giới hạn dữ liệu synthetic

Report cục bộ của run `20260904T040913850088` ghi 1.284.182 snapshot và tỷ trọng cuối kỳ khoảng nu=15,70%, lu=19,66%, au=64,64%. Đây là **số liệu report lịch sử**, chưa phải một lần full pipeline mới của phiên rà soát. Gate tối thiểu 10% mỗi segment đạt, nhưng tỷ trọng tham khảo trong decision baseline chưa đạt.

Calibration hiện đo positive rate trên tập candidate gồm các split. Phù hợp tạo dữ liệu demo theo phân phối mục tiêu, nhưng không biến test thành một bộ kiểm chứng độc lập cho thực tế. Nên thêm một bộ synthetic giữ riêng seed/cấu hình để kiểm tra độ bền sau khi chốt generator; không dùng kết quả synthetic để suy ra hiệu quả kinh doanh.

Các điểm cần đo thêm: giao dịch/tháng so với spec, chính sách cash/asset bị chặn tại 0, ảnh hưởng mô phỏng tài khoản dormant, `NaN`/`Inf` trong nguồn số và timestamp thiếu timezone. Nguồn chưa có ingestion time nên chưa kiểm chứng late-arriving data.

**Tiêu chí đạt:** một báo cáo phân phối có ngưỡng nào bắt buộc/tham khảo rõ ràng, một bộ kiểm tra giữ riêng và các giới hạn mô phỏng được ghi cụ thể.

## 5. Lộ trình dễ thực hiện hơn

Giữ timeline 14 ngày làm bản kiến trúc mục tiêu; dùng các mốc dưới đây để nghiệm thu theo kết quả thay vì chỉ theo ngày.

| Mốc | Việc chính | Bằng chứng cần có |
|---|---|---|
| A. Data foundation | Môi trường tái lập, ingest tách batch, quality gate | Tests đạt; FAIL không đổi pointer; một run có report và hashes |
| B. Feature dùng được | Tách daily features khỏi mature labels | Feature ngày mới nhất, test parity training/scoring |
| C. Model chạy được | Baseline margin + tracking + batch predict | Model version, metric từng segment, prediction có account/date/version |
| D. API và rollback | Một endpoint dự báo, schema gate, chọn model version | Gọi API thành công, xử lý thiếu feature, rollback tái lập |
| E. Tích hợp hệ thống | Feast/Redis, KServe, Airflow theo timeline | Mỗi thành phần có smoke test và lỗi được truy về đúng bước |
| F. Monitoring | Prediction history, drift, evaluate khi nhãn đủ | Có bằng chứng drift và hiệu năng; retrain vẫn đi qua promotion gate |

Mỗi mốc nên có một trang ngắn: đầu vào, một lệnh chạy, đầu ra, test và tình huống lỗi. Thêm CI chạy unit/integration tests trên môi trường sạch khi bắt đầu làm việc nhóm. Chưa cần đóng gói toàn bộ thành một framework phức tạp.

## 6. Cách trình bày đồ án thuyết phục hơn

Demo theo chuỗi bằng chứng: chọn một tài khoản/ngày → giải thích feature và label → chỉ ra source snapshot → chạy gate → xem model/prediction version → gây một lỗi có kiểm soát → chứng minh downstream bị chặn hoặc rollback đúng.

Slide kiến trúc nên đánh dấu “đã chạy”, “mô phỏng” và “dự kiến”. Chỉ ghi latency, training time hoặc recovery time sau khi đo trên cấu hình máy/quy mô dữ liệu được nêu rõ. Iris smoke test chỉ chứng minh kết nối MLflow, không đại diện chất lượng model margin.

## 7. Kiểm chứng trong phiên rà soát

- Baseline ban đầu: 11 tests đạt.
- Sau sửa: **20/20 tests đạt**, bao gồm roundtrip SQLite/Iceberg thực và kiểm tra chạy ingest lại không nhân đôi dữ liệu.
- Đã đọc namespace hiện có `raw_day4_v2`, chạy source validation, normalize, build và assess trong DuckDB: **PASS 47/47 quality checks trên 1.284.182 snapshot**. Đây là kiểm tra lại phần tính toán; không xuất một full feature run mới, không thay pointer và không đối chiếu lại toàn bộ artifacts của run lịch sử.
- Các liên kết file trong README và ba tài liệu mới đều tồn tại; `git diff --check` không phát hiện lỗi whitespace.
- Môi trường `.venv` cũ trỏ tới interpreter không còn khả dụng. Phiên rà soát dùng Python 3.12.14 sẵn có và thư viện 3.12 của dự án để chạy tests; chưa tái tạo môi trường sạch từ lockfile.
- Bộ tests bổ sung kiểm tra lỗi nguồn, từ chối publication, ghi JSON nguyên tử và ingest; có integration test với SQLite/PyIceberg thật trong thư mục tạm.
- Không triển khai Kubernetes, không chạy MLflow server và không tự triển khai các thành phần còn trong lộ trình.

Hướng dẫn thực thi nằm trong [README](../README.md), [runbook](runbook.md) và [feature contract](feature_contract.md).
