   
- Timeline
    
    ## Bản đồ tiến độ: mỗi ngày xây phần nào của hệ thống?

    **Đích cuối:** từ dữ liệu tài khoản và giao dịch, tạo feature đúng thời điểm, huấn luyện model dự báo nhu cầu margin trong 30 ngày tới, quản lý phiên bản và tự động đưa model đã duyệt vào KServe (auto-deploy, reconcile, rollback). Gọi dự báo real-time qua API theo `master_account` (Feast online, Redis, FastAPI gateway) là giai đoạn 2. Hệ thống đồng thời chấm điểm hàng loạt, theo dõi chất lượng và kích hoạt huấn luyện lại khi cần; model mới vẫn phải qua promotion gate và bước duyệt trước khi phục vụ.

    Các ngày là thứ tự xây dựng năng lực. Khi vận hành, các luồng chạy theo lịch hoặc sự kiện riêng, không chạy lại tuần tự từ ngày 1 đến ngày 14 cho mỗi request.

    ### Phạm vi theo giai đoạn

    | | Giai đoạn 1 (14 ngày, mục tiêu hiện tại) | Giai đoạn 2 (sau khi giai đoạn 1 bàn giao) |
    | --- | --- | --- |
    | Luồng | 1 Feature pipeline, 3 Training & registry, **4 Auto-deploy & reconcile**, 6 Batch predict + self-healing, 7 Weekly evaluate | 2 Materialization, 5 Real-time inference |
    | Thành phần | Iceberg + PyIceberg/DuckDB (đọc `fs_*` và `training_dataset`), MLflow + Postgres + MinIO, **KServe, webhook deployer, reconcile loop**, Airflow, Evidently | Feast online + Redis, FastAPI inference gateway |
    | "Triển khai" nghĩa là | Alias `@production` đổi thì `InferenceService` trên KServe tự cập nhật; rollback đổi alias. Kiểm tra bằng cách gọi endpoint nội bộ của KServe với feature vector mẫu | Thêm đường `master_account → feature → model → score` cho client |
    | Use case | `loan_propensity` đầy đủ; `overdue_risk`, `campaign_response` theo thứ tự ưu tiên ở mục rủi ro | Cùng ba use case, mỗi use case một endpoint |

    Lý do tách: phần dễ trễ nhất của real-time là Redis online và gateway (cần feature scoring mới nhất, nối Feast, xử lý lỗi). Auto-deploy chỉ cần artifact trong MinIO và KServe nên giữ ở giai đoạn 1 để chứng minh MLOps logic cốt lõi (promotion gate, tự cập nhật, tự sửa lệch, rollback).

    ```mermaid
    flowchart TD
        A["Ngày 2–3: dữ liệu nguồn → Iceberg"] --> B["Ngày 4: feature + nhãn + quality gate"]
    B --> C["Ngày 5: Feast offline (kiểm chứng parity, chuẩn bị GĐ2)"]
        B --> D["GĐ2: materialize → Redis"]
        B --> E["Ngày 6–7: train → MLflow → gate + duyệt"]
        E --> F["Ngày 8–10: KServe + auto-deploy + rollback"]
        D --> G["GĐ2: FastAPI nhận master_account → lấy feature"]
        G --> F
        F --> H["Trả score cho client (GĐ2: qua gateway; GĐ1: gọi trực tiếp KServe nội bộ)"]
        B --> I["Ngày 11–12: batch predict → bảng pred_*"]
        E -->|"model production"| I
        I --> J["Ngày 12: drift + đánh giá khi nhãn đã đủ"]
        J -->|"khi đạt điều kiện retrain"| E
    ```

    **Các phần bao quanh sơ đồ:** ngày 1–2 cung cấp hạ tầng và cấu hình triển khai; ngày 11 lên lịch, quản lý dependency, log và retry cho các pipeline; ngày 13 kiểm chứng toàn hệ thống bằng lỗi mô phỏng và số đo; ngày 14 đóng gói tài liệu và demo.

    ### Đối chiếu với 7 luồng trong mục Architecture

    | Luồng cuối cùng | Các ngày đóng góp | Đường đi và giá trị tạo ra |
    | --- | --- | --- |
    | 1. Batch feature pipeline | 2–4 xây xử lý dữ liệu; 5 đăng ký feature; 11 lên lịch | Nguồn → feature snapshot → quality gate → xuất bản dữ liệu được duyệt. Cung cấp đầu vào nhất quán cho training và serving. |
    | 2. Feature materialization (**GĐ2**) | giai đoạn 2 | Feature offline đã duyệt → Redis. Chuẩn bị feature sẵn cho request online mà không phải tính lại lịch sử giao dịch. |
    | 3. Training & registry | 6 train; 7 tracking/gate; 11 điều phối | Đọc `training_dataset` (feature + nhãn + split từ ngày 4) → model theo `nu/lu/au` → MLflow → đánh giá và duyệt version. |
    | 4. Auto-deploy & reconcile | 8 có runtime; 9 tự cập nhật; 10 sửa lệch/rollback | Alias `@production` → artifact model → KServe. Giữ model đang phục vụ khớp phiên bản đã được duyệt. |
    | 5. Online inference (**GĐ2**) | giai đoạn 2 (KServe predictor đã có từ ngày 8, version đúng nhờ ngày 10) | Client → FastAPI → Feast/Redis → chọn model → KServe → score. Đây là đường người dùng cuối gọi trực tiếp. |
    | 6. Batch predict & self-healing | 11 tạo DAG; 12 hoàn thiện prediction/drift/retrain | Feature tại mốc batch + model production → `pred_*` → cảnh báo drift → retrain khi đạt ngưỡng. Cấp dữ liệu cho báo cáo và đánh giá về sau. |
    | 7. Weekly evaluate | 4 định nghĩa nhãn; 12 ghép dự báo với nhãn đã đủ; 13 kiểm chứng | Dự báo lịch sử + kết quả 30 ngày sau → metric thực tế → quyết định xem xét/trigger retrain. Drift đầu vào đơn thuần chưa chứng minh model giảm chất lượng. |

    ### Phân biệt nơi lưu dữ liệu để không nhầm vai trò

    | Thành phần | Lưu hoặc quản lý gì trong thiết kế này? | Ngày liên quan |
    | --- | --- | --- |
    | Iceberg + catalog SQLite local | Bảng nguồn, lịch sử feature; về sau có bảng dự báo. Catalog quản lý thông tin bảng, warehouse chứa file dữ liệu/metadata Iceberg. | 3–4, 12 |
    | Parquet xuất từ run được duyệt | Nguồn trung gian cho Feast khi dùng File offline store; phải giữ khóa, timestamp và lịch sử cần thiết. | 4–5 |
    | Feast registry | Định nghĩa Entity, Feature View, nguồn và metadata phục vụ truy xuất feature. | 5 |
    | Redis | Giá trị feature đã materialize để phục vụ online. | 1; GĐ2 (5, 9) |
    | PostgreSQL của MLflow | Metadata về experiment, run và model registry. | 1, 7 |
    | MinIO | Model/artifact của MLflow để KServe tải và phục vụ. Phần Feast local ngày 5 có thể đọc Parquet local mà không cần đưa feature lên MinIO. | 1, 7–8 |

    ### Đang ở đâu? Cách đọc mốc tiến độ

    **Ghi nhận ngày 04/09/2026:** repository có pipeline ngày 4 và `data/features/current.json` trỏ tới run `20260904T040913850088`. Thư mục run lịch sử có bốn file `fs_*`, `training_dataset.parquet`, `class_weights.json` và `quality_report.json` với `status: PASS`. Bản mở rộng hiện tại bổ sung `fs_portfolio`, `fs_campaign`, `campaign_training_dataset.parquet` và `usecase_registry.json`; run cũ không được coi là đã chứa các artifact mới.

    | Mốc | Khi deliverable đạt, hệ thống có thêm khả năng gì? | Việc kế tiếp được mở ra |
    | --- | --- | --- |
    | Hết ngày 1–3 | Có hạ tầng và dữ liệu nguồn truy vấn được | Xây feature và nhãn đúng nghiệp vụ |
    | Hết ngày 4 | Có feature/nhãn/split đã qua quality gate | **Mốc dữ liệu hiện đã có bằng chứng; bước tiếp theo là ngày 5** |
    | Hết ngày 5 | Feast offline đã đăng ký và kiểm chứng parity với `training_dataset` (chuẩn bị cho giai đoạn 2); feature scoring tách khỏi nhãn | Train bằng `training_dataset` (Feast không nằm trong luồng giai đoạn 1) |
    | Hết ngày 6–7 | Có model, metric, version và tiêu chí chọn bản phục vụ | Deploy một artifact xác định vào KServe |
    | Hết ngày 8–9 | Có predictor KServe (gọi bằng feature vector qua endpoint nội bộ); đổi alias tự cập nhật deployment | Hoàn thiện cơ chế phục hồi và vận hành định kỳ |
    | Hết ngày 10–11 | Rollback/reconcile hoạt động; pipeline có lịch, log, retry | Chạy batch và đóng vòng giám sát → retrain |
    | Hết ngày 12 | Có dự báo batch, đánh giá và phản hồi về training | Kiểm chứng hành vi khi lỗi và hiệu năng thực tế |
    | Hết ngày 13–14 | Có bằng chứng kiểm thử, số đo và demo tái lập được | Bàn giao toàn bộ vòng đời MLOps |

    **Cách tự cập nhật:** chỉ đánh dấu xong một ngày khi deliverable và phần “Tự kiểm tra” bên dưới đạt. Ghi kèm run ID, model version, log hoặc báo cáo làm bằng chứng. Các mốc tương lai trong bảng mô tả năng lực mục tiêu, không phải trạng thái đã hoàn thành.

    ## Tuần 1 — Nền tảng dữ liệu, feature, training, registry
    
    ### Ngày 1: Setup hạ tầng cơ bản

    **Vai trò trong tổng thể:** dựng nền chạy và nơi lưu trữ dùng chung cho các luồng. Redis phục vụ feature online; PostgreSQL và MinIO phục vụ MLflow; Kubernetes là nơi triển khai service và model.

    **Đầu vào → bàn giao:** máy local, Docker/Kubernetes và cấu hình service → endpoint, volume và thông tin kết nối cho Feast ngày 5, MLflow ngày 7, KServe ngày 8. Ngày 2 sẽ gom cấu hình thành Helmfile để dựng lại được.

    **Tự kiểm tra / mốc đạt:** service healthy, mở được MLflow UI và kiểm tra kết nối/lưu trữ cơ bản. Đến đây có nền hạ tầng; năng lực xử lý dữ liệu và dự đoán sẽ được xây ở các ngày tiếp theo.
    
    **Làm:**
    
    - Cài kind/minikube, Docker.
    - Deploy PostgreSQL, Redis, MinIO qua Helm chart có sẵn (bitnami hoặc tương đương).
    - Deploy MLflow (backend Postgres, artifact MinIO), verify UI truy cập được.
    
    **Học:** Helm cơ bản (`helm install`, `values.yaml`), khái niệm Deployment/Service/PVC/Secret trong K8s.
    
    **Deliverable cuối ngày:** 4 service chạy healthy, MLflow UI mở được.
    
    ---
    
    ### Ngày 2: Helmfile hoá + dữ liệu synthetic

    **Vai trò trong tổng thể:** cung cấp đầu vào cho luồng 1 và khả năng tái lập môi trường. Dữ liệu synthetic thay nguồn nghiệp vụ bên ngoài, cho phép kiểm soát cả hành vi bình thường lẫn tình huống kiểm thử.

    **Đầu vào → bàn giao:** hạ tầng ngày 1 + quy tắc nghiệp vụ tài khoản/giao dịch/margin → Helmfile và tám bảng nguồn Parquet cho ngày 3. `margin_cash_flow` cung cấp sự kiện để ngày 4 tạo nhãn tương lai.

    **Tự kiểm tra / mốc đạt:** dựng lại được cấu hình, dữ liệu giữ đúng khóa liên kết, schema và thứ tự thời gian. Đến đây có nguyên liệu để xây pipeline, chưa có feature hoặc model.
    
    **Làm:**
    
    - Gom các Helm release ở Ngày 1 vào 1 `helmfile.yaml` để quản lý tập trung.
    - Viết script sinh dữ liệu synthetic: bốn bảng nghiệp vụ cốt lõi cùng `stock_price_daily`, `security_master`, `portfolio_holding_daily`, `customer_campaign`; các bảng mở rộng phục vụ feature reuse và nhiều use case.
    
    **Học:** Helmfile syntax, thiết kế synthetic data có quan hệ nghiệp vụ hợp lý (correlation giữa turnover và margin usage).
    
    **Deliverable:** 8 bảng nguồn ở dạng Parquet, gồm 4 bảng nghiệp vụ cốt lõi và 3 bảng mở rộng (`security_master`, `portfolio_holding_daily`, `customer_campaign`) cùng `stock_price_daily`; kiểm tra được bằng pandas/DuckDB.
    
    ---
    
    ### Ngày 3: Ghi Iceberg + PyIceberg/DuckDB

    **Vai trò trong tổng thể:** xây lớp lưu trữ cho luồng 1. Đưa dữ liệu nguồn vào các bảng có schema và snapshot để các bước sau đọc đúng phiên bản và truy vết nguồn.

    **Đầu vào → bàn giao:** tám bảng Parquet ngày 2 → namespace/bảng Iceberg, catalog và khả năng truy vấn cho feature engineering ngày 4. Cách lưu này cũng được dùng cho feature và kết quả batch về sau.

    **Tự kiểm tra / mốc đạt:** đọc lại bảng, đối chiếu số dòng/schema và truy vấn mẫu với nguồn. Đến đây pipeline có kho dữ liệu truy vấn được để bắt đầu biến đổi thành đầu vào ML.
    
    **Làm:**
    
    - Setup Iceberg catalog local (SQLite catalog là nhanh nhất).
    - Ghi 8 bảng nguồn vào Iceberg qua PyIceberg.
    - Viết vài query DuckDB đọc thẳng Iceberg table để verify.
    
    **Học:** PyIceberg API (`catalog.create_table`, `append`), DuckDB `iceberg_scan` hoặc extension tương ứng.
    
    **Deliverable:** 8 bảng Iceberg query được qua DuckDB.
    
    ---
    
    ### Ngày 4: Feature engineering + nhãn

    **Vai trò trong tổng thể:** xây phần tính toán và quality gate của luồng 1, đồng thời chuẩn bị nhãn cho luồng 3 và 7. Chuyển giao dịch/số dư thành đặc trưng tại mốc dự đoán, rồi xác định kết quả xảy ra trong 30 ngày tiếp theo.

    **Đầu vào → bàn giao:** bảng nguồn Iceberg ngày 3 → shared `fs_*`, nhiều nhãn/use case, split, class weights và báo cáo chất lượng. Ngày 5 dùng feature; ngày 6 dùng nhãn/split; ngày 12 dùng cùng logic nhãn để đánh giá dự báo lịch sử.

    **Tự kiểm tra / mốc đạt:** quality gate PASS, không dùng dữ liệu tương lai trong feature, nhãn đủ cửa sổ quan sát và run được duyệt có pointer rõ ràng. Đến đây dữ liệu sẵn sàng để tích hợp Feast; việc lấy feature qua Feast được kiểm chứng ở ngày 5.
    
    **Làm:**
    
    - Xây dựng feature snapshot theo sáu nhóm, gồm account/trading/margin/asset và các nhóm portfolio/campaign dùng chung cho nhiều model.
    - Tạo `loan_label_next` và `overdue_label_next_30d` theo cửa sổ 30 ngày; tạo `campaign_response_label_14d` theo grain campaign-event, bảo đảm point-in-time và không leakage.
    - Chạy data-quality gate, kiểm tra positive rate theo `nu/lu/au`, và chốt cách xử lý mất cân bằng nhãn.
    - Chuẩn bị time-based train/validation/test split với embargo 30 ngày.
    
    **Học:** Rolling window aggregation, point-in-time correctness, event-based labeling và xử lý class imbalance.
    
    **Deliverable:** Sáu bảng `fs_*` trên Iceberg, `training_dataset`, `campaign_training_dataset`, `usecase_registry.json`, class weights và báo cáo chất lượng; chỉ dùng training khi quality gate đạt.
    
    ---
    
    ### Ngày 5: Feast setup (offline; chuẩn bị cho giai đoạn 2, không nằm trong luồng chính giai đoạn 1)

    **Vai trò trong tổng thể:** đăng ký feature cho luồng 2 và 5 ở giai đoạn 2 (offline → Redis). Ở giai đoạn 1, train đọc `training_dataset` và batch predict đọc `fs_*` qua PyIceberg/DuckDB; Feast offline chỉ dùng để kiểm chứng parity.

    **Đầu vào → bàn giao:** sáu `fs_*` từ run ngày 4 đã PASS + Redis ngày 1 → shared Entity/Feature View và Feature Service theo use case, online lookup cho FastAPI (giai đoạn 2). Khi cần, dùng Parquet xuất từ run được duyệt làm File offline store; lịch sử Iceberg vẫn là nguồn có thể truy vết.

    **Tự kiểm tra / mốc đạt (giai đoạn 1):** `feast apply` đăng ký đủ định nghĩa; truy vấn lịch sử lấy đúng snapshot trước/tại mốc yêu cầu trong TTL và khớp `training_dataset`. Materialize và đối chiếu lookup Redis để giai đoạn 2.
    
    **Làm:**
    
    - **Trước tiên:** tách feature scoring khỏi nhãn (ưu tiên 1 trong `project_review.md`). Feature tại ngày D chỉ dùng dữ liệu đến D; nhãn chỉ chốt sau D+30 (hoặc D+14); training join hai phần rồi áp split/embargo. Cần để batch predict (ngày 12) có feature của những ngày mới nhất.
    - Cài Feast, khai báo Entity (`master_account`), Data Source trỏ vào Iceberg/DuckDB, Feature View.
    - Chạy `feast apply`, test historical retrieval (point-in-time correctness).
    - (Giai đoạn 2) Materialize sang Redis và test online feature lookup. Giai đoạn 1 chỉ cần historical retrieval.
    
    **Học:** Feast concepts (Entity/FeatureView/OfflineStore/OnlineStore), cách viết custom offline store nếu Feast không hỗ trợ sẵn DuckDB (kiểm tra trước — nếu tốn quá nửa ngày để viết custom provider, fallback: dùng Feast **File offline store** trỏ vào Parquet export từ Iceberg, đơn giản hơn nhiều).
    
    **Deliverable (giai đoạn 1):** Feast offline đăng ký và kiểm chứng parity: `feature_repo/` (1 entity, 6 Feature View, 3 Feature Service), `scripts/day5_feast_check.py`; `feast_check.json` PASS trên run `20261007T095923177784` (mẫu 300 tài khoản, 0 dòng lệch so với `training_dataset` và snapshot D−1). Feature scoring đã tách khỏi nhãn. **Quyết định 14/10/2026:** giai đoạn 1 không dùng Feast trong train/predict, giữ nguyên code, không làm thêm tăng tốc retrieval hay tự động `feast apply`; online/Redis để giai đoạn 2 (chi tiết `feature_contract.md` mục 8).
    
    ---
    
    ### Ngày 6: Training pipeline

    **Vai trò trong tổng thể:** xây phần học mô hình của luồng 3. Biến feature và nhãn thành xác suất nhu cầu margin; baseline giúp kiểm tra model chính có đem lại cải thiện hay không.

    **Đầu vào → bàn giao:** `training_dataset` (feature + nhãn + split) và class weights ngày 4 → Logistic Regression/LightGBM và metric cho từng phân khúc, chuyển sang ngày 7 để tracking và quản lý version. Đây là ba bài toán phân loại nhị phân theo `nu/lu/au`, không phải dự đoán ba phân khúc bằng một nhãn đa lớp.

    **Tự kiểm tra / mốc đạt:** train/validation/test tuân thủ mốc thời gian, `loan_label_next` không nằm trong feature đầu vào, có metric theo từng phân khúc và tái lập được với seed/cấu hình cố định. Đến đây model chạy được trong pipeline training; phục vụ qua API được xây ở ngày 8–9.
    
    **Làm:**
    
    - Training pipeline đọc `training_dataset` (PyIceberg/DuckDB), lọc theo `split`, train Logistic Regression (baseline) + LightGBM cho 3 phân khúc (`nu`/`lu`/`au`).
    - Tính metric: ROC-AUC, precision, recall, F1, confusion matrix.
    - Cố định random seed.
    - Tham số hóa pipeline theo `usecase_registry.json` (label, dataset, entity key, feature groups). Train `loan_propensity` trước; `overdue_risk` (chỉ dòng `overdue_eligible=1`) và `campaign_response` (grain `campaign_event_id`) khi loan đã chạy ổn, với gate và ngưỡng riêng cho từng use case.
    
    **Học:** Huấn luyện model phân loại nhị phân riêng theo segment (`nu/lu/au`), xử lý class weight trong LightGBM.
    
    **Deliverable:** Model train xong, metric in ra console/notebook.
    
    ---
    
    ### Ngày 7: MLflow tracking + registry + promotion logic

    **Vai trò trong tổng thể:** hoàn thiện quản lý và kiểm soát model của luồng 3, tạo đầu mối version cho luồng 4. Mỗi kết quả training có nguồn gốc và tiêu chí để quyết định có đưa vào phục vụ hay không.

    **Đầu vào → bàn giao:** model/metric ngày 6 + MLflow/PostgreSQL/MinIO ngày 1 → run, artifact, signature, model version và kết quả promotion gate. Ngày 8 tải artifact để serve; ngày 9–10 dùng alias `@production` làm trạng thái mong muốn của deployment.

    **Tự kiểm tra / mốc đạt:** truy được từ version tới run/metric/artifact, backtest và test gate đạt, model chỉ chuyển `@production` sau quy trình duyệt. Khi chưa có model production để so sánh, ghi rõ cách duyệt baseline đầu tiên. Đến đây có model được quản lý và lựa chọn, chưa đồng nghĩa deployment đã cập nhật.
    
    **Làm:**
    
    - Tích hợp MLflow tracking (log param/metric/artifact/model signature).
    - Đăng ký model, gán alias `@staging`.
    - Viết hàm `should_promote(new_metrics, current_prod_metrics) -> bool`: pass nếu `new_auc >= current_auc - 0.03` VÀ `new_recall >= current_recall - 0.05`, cho cả 3 phân khúc (all-or-nothing). Unit test với các case: cả 3 pass, 1 phân khúc fail, biên đúng ngưỡng (3.0%/5.0%).
    - Backtest 2 mốc thời gian (-40d, -80d) trên dữ liệu synthetic.
    
    **Học:** MLflow Model Registry alias API (phiên bản MLflow gần đây dùng alias thay stage), viết unit test cho logic quyết định.
    
    **Deliverable:** MLflow có ≥2 model version, hàm promotion có unit test pass.
    
    ---
    
    ## Tuần 2 — Serving, tự động hóa, monitoring, báo cáo
    
    ### Ngày 8: KServe setup (RawDeployment)

    **Vai trò trong tổng thể:** dựng bộ phận thực thi model của luồng 4/5. Chuyển artifact trong MinIO thành một predictor chạy trên Kubernetes, nhận feature vector và trả score.

    **Đầu vào → bàn giao:** cluster ngày 1 + artifact/signature ngày 7 → `InferenceService` được triển khai thủ công và endpoint nội bộ. Ngày 9 sẽ gọi endpoint này từ gateway và tự động hóa việc cập nhật version.

    **Tự kiểm tra / mốc đạt:** service Ready, tải đúng artifact, nhận payload theo signature và trả kết quả khớp mẫu tham chiếu. Đến đây có model server; API nhận `master_account` và lấy feature là phần của ngày 9.
    
    **Làm:**
    
    - Cài cert-manager + KServe controller (RawDeployment mode, không Knative).
    - Deploy thử 1 `InferenceService` thủ công (`kubectl apply`) trỏ `storageUri` vào MinIO, verify predict endpoint hoạt động.
    
    **Học:** KServe CRD schema, MLServer sklearn/lightgbm runtime, debug lỗi pull artifact từ MinIO (thường do IAM/secret).
    
    **Deliverable:** 1 InferenceService chạy thủ công, nhận feature vector và trả kết quả đúng qua endpoint nội bộ.

    **Ghi chú tài nguyên:** mỗi `InferenceService` là một pod MLServer. Ba model segment của loan là phần bắt buộc; thêm model của use case phụ chỉ khi RAM còn đủ trong ngân sách ~4,5–5GB của toàn hạ tầng. Giai đoạn 1 kiểm tra bằng feature vector mẫu lấy từ tập validation, không đi qua gateway.
    
    > ⚠️ Điểm rủi ro thứ hai — dành cả ngày cho việc này, nếu chiều vẫn chưa xong, tối làm tiếp, không dồn sang ngày 9.
    > 
    
    ---
    
    ### Ngày 9: Webhook deployer (auto-deploy)

    **Vai trò trong tổng thể:** xây luồng 4. Deployer nhận thay đổi alias trong MLflow và cập nhật KServe, để khâu "duyệt model" nối thẳng tới "model đang phục vụ" mà không cần thao tác Kubernetes thủ công.

    **Đầu vào → bàn giao:** alias/artifact ngày 7 + predictor ngày 8 → đường cập nhật model tự động. Ngày 10 bổ sung khả năng tự sửa lệch và rollback.

    **Tự kiểm tra / mốc đạt:** đổi alias `@production` khiến `InferenceService` cập nhật đúng version; gửi lại cùng event không tạo resource trùng; chỉ alias `production` mới kích hoạt, `staging` thì không; endpoint nội bộ trả kết quả khớp mẫu tham chiếu sau khi cập nhật.

    **Làm:**

    - Viết **FastAPI deployer** nhận sự kiện (webhook thật nếu MLflow version hỗ trợ, hoặc polling alias mỗi phút nếu không — polling đơn giản hơn, vẫn đạt tinh thần "tự động", chỉ khác cơ chế trigger).
    - Logic: resolve model version + `storageUri`, lọc đúng alias `production`, apply `InferenceService` CRD qua K8s Python client; một `InferenceService` cho mỗi (use case, segment) theo quy ước đặt tên.
    - Test idempotency: gửi lại cùng sự kiện, không tạo resource trùng.
    - Viết script kiểm tra: gọi endpoint KServe nội bộ bằng feature vector mẫu trước và sau khi đổi alias, đối chiếu `model_version`/kết quả.

    **Học:** MLflow webhook registration (hoặc polling registry API), Kubernetes Python client (`apply`), idempotency check pattern.

    **Deliverable:** Đổi alias `@production` → InferenceService tự cập nhật, không cần `kubectl apply` thủ công. Gateway nhận `master_account` thuộc giai đoạn 2.

    ---

    ### Ngày 10: Reconcile loop + rollback

    **Vai trò trong tổng thể:** tăng khả năng phục hồi cho luồng 4, bảo vệ endpoint khỏi việc phục vụ sai version sau sự kiện bị lỡ hoặc deployment bị sửa lệch.

    **Đầu vào → bàn giao:** deployer ngày 9 + lịch sử version ngày 7 → vòng đối soát giữa alias và deployment, cùng quy trình đưa endpoint về model cũ. Đây là nền vận hành cho các lần retrain/deploy sau này.

    **Tự kiểm tra / mốc đạt:** bỏ lỡ một event hoặc sửa sai version thì reconcile phát hiện và sửa lại khi hạ tầng khả dụng; chuyển alias về bản trước thì endpoint thực sự phục vụ bản đó. Chu kỳ kiểm tra 600s không bao gồm thời gian tải model và chờ pod Ready; ngày 13 sẽ đo thời gian phục hồi thực tế.
    
    **Làm:**
    
    - Viết vòng lặp định kỳ 600s: so sánh alias hiện tại vs InferenceService đang chạy, tự sửa nếu lệch.
    - Test rollback: chuyển alias về version cũ, verify endpoint quay lại đúng version.
    
    **Học:** Control loop pattern (giống Kubernetes controller), cách test race condition/idempotency có chủ đích (gửi 2 event gần nhau).
    
    **Deliverable:** Demo rollback thành công, reconcile loop tự sửa khi sửa `InferenceService` thủ công.
    
    ---
    
    ### Ngày 11: Airflow standalone + DAG orchestration

    **Vai trò trong tổng thể:** đưa các script đã chạy riêng lẻ vào lịch vận hành có dependency, log và retry cho luồng 1/3/6. Airflow gọi lại logic xử lý đã xây, chịu trách nhiệm thứ tự và trạng thái chạy.

    **Đầu vào → bàn giao:** pipeline feature ngày 4, materialize ngày 5 và training ngày 6–7 → DAG chạy được và khung batch predict cho ngày 12. Quality gate phải đạt trước khi xuất bản feature; training chỉ dùng dữ liệu được duyệt và không tự bỏ qua promotion gate.

    **Tự kiểm tra / mốc đạt:** chạy lại cùng mốc không tạo dữ liệu trùng hoặc promote sai; log chỉ rõ task lỗi và retry; feature lỗi chặn bước downstream. Với phạm vi ba DAG, `feature_store_daily` gồm tính feature → quality gate → xuất bản. Materialization (`feast_materialize_daily`) thuộc giai đoạn 2; lịch evaluate và maintenance bổ sung sau.
    
    **Làm:**
    
    - Cài Airflow standalone mode.
    - Viết 3 DAG: `feature_store_daily` (tính feature → quality gate → xuất bản), `<model>_train`, `<model>_predict` (batch; hoàn thiện logic ở ngày 12).
    - Verify chạy lại pipeline không hỏng dữ liệu, không tạo alias sai.
    
    **Học:** Airflow standalone setup, DAG authoring cơ bản (PythonOperator đủ dùng, không cần KubernetesPodOperator).
    
    **Deliverable:** 3 DAG chạy được từ Airflow UI, có log/retry.
    
    ---
    
    ### Ngày 12: Batch predict + self-healing + Evidently

    **Vai trò trong tổng thể:** xây luồng 6/7 và đóng đường phản hồi từ vận hành về training. Batch tạo điểm cho toàn bộ tài khoản; drift cảnh báo sớm; đánh giá với nhãn đã đủ cửa sổ quan sát mới đo được chất lượng dự báo thực tế.

    **Đầu vào → bàn giao:** DAG ngày 11 + feature tại mốc batch + model production ngày 7–10 + logic nhãn ngày 4 → bảng `pred_*`, drift report, metric khi nhãn đã đủ và trigger retrain. Kết quả quay về pipeline ngày 6–7, sau đó chỉ deploy qua ngày 9–10 khi model mới được duyệt.

    **Tự kiểm tra / mốc đạt:** mỗi dự báo truy được tài khoản, thời điểm và model version; giả lập drift kích hoạt đúng hành động theo mục 10; ghép dự báo lịch sử với nhãn đủ 30 ngày để demo weekly evaluate. Chỉ so sánh hai phân phối feature thì mới hoàn thành phần data drift, chưa hoàn thành luồng 7. Dùng các mốc synthetic sẵn có để demo, không cần chờ thêm 30 ngày thực.
    
    **Làm:**
    
    - DAG batch predict: chấm điểm toàn bộ tài khoản, ghi bảng `pred_*`. Batch dùng model `@production` của từng use case đã có.
    - Tính Drift Ratio từ Evidently column-level drift result (số feature drifted / tổng feature), xử lý theo mục 10: high → cảnh báo/gắn tag; critical → tự động trigger DAG train (gọi Airflow API hoặc `TriggerDagRunOperator`).
    - Tích hợp Evidently: sinh report so sánh 2 snapshot dữ liệu khác thời điểm để demo data drift.
    - Bổ sung luồng `<model>_evaluate` chạy theo lịch tuần: ghép dự báo lịch sử với nhãn đủ cửa sổ quan sát, tính metric thực tế và xử lý ngưỡng giảm AUC theo mục 10. Demo bằng các mốc dữ liệu có sẵn; đây là phần hoàn thiện luồng 7 ngoài ba DAG nền ngày 11.
    
    **Học:** Evidently `Report`/`TestSuite` API cơ bản, cách trigger DAG khác từ trong 1 DAG (`TriggerDagRunOperator`).
    
    **Deliverable:** Batch predict ghi được `pred_*`, có report drift và metric đánh giá với nhãn đã đủ; demo được trigger retrain đúng điều kiện và model mới vẫn đi qua promotion gate/quy trình duyệt.
    
    ---
    
    ### Ngày 13: Kiểm thử lỗi + đo lường

    **Vai trò trong tổng thể:** kiểm chứng các luồng đã nối với nhau có hành vi đúng khi dữ liệu/service/model gặp lỗi. Thay các kỳ vọng trong kiến trúc bằng bằng chứng thực nghiệm.

    **Đầu vào → bàn giao:** hệ thống ngày 1–12 + tình huống lỗi có kiểm soát → kết quả pass/fail, thời gian đo và giới hạn thực tế cho báo cáo ngày 14. Khi một kiểm tra fail, sửa phần liên quan rồi chạy lại kiểm tra đó.

    **Tự kiểm tra / mốc đạt:** biết lỗi được phát hiện ở đâu, API/pipeline phản hồi thế nào và có phục hồi đúng version hay không; số đo ghi rõ cấu hình máy, quy mô dữ liệu và điều kiện chạy. Các mốc latency trong sơ đồ kiến trúc là mục tiêu cho tới khi có số đo xác nhận.
    
    **Làm:**
    
    - Mô phỏng các tình huống lỗi: model version sai schema, webhook bị lỡ event, quality gate FAIL chặn xuất bản, promotion gate không đạt giữ nguyên alias — verify hệ thống phát hiện/phục hồi đúng như thiết kế. (Tình huống Redis chưa materialize thuộc giai đoạn 2.)
    - Đo và ghi lại: materialization time, training time, thời gian từ promote đến InferenceService sẵn sàng, inference latency, rollback time.
    
    **Học:** Không có kiến thức mới — đây là ngày kiểm thử, tập trung viết test case và đo đạc.
    
    **Deliverable:** Bảng số liệu đo lường đầy đủ, điền vào mục 9 (Experiment/Result) trong tài liệu kỹ thuật.
    
    ---
    
    ### Ngày 14: Hoàn thiện tài liệu, slide, demo rehearsal

    **Vai trò trong tổng thể:** đóng gói toàn bộ bảy luồng thành kết quả có thể giải thích, chạy lại và bàn giao. Báo cáo chỉ rõ phần đã kiểm chứng, phần dùng fallback và phần còn là hướng phát triển.

    **Đầu vào → bàn giao:** code/config, run/model version, sơ đồ và số đo ngày 13 → tài liệu kỹ thuật, slide và kịch bản demo từ dữ liệu đến API, monitoring và rollback.

    **Tự kiểm tra / mốc đạt:** người đọc lần được từ sơ đồ đến script/service tương ứng; demo có chuẩn bị feature và materialize trước khi gọi online, có model được duyệt trước deploy, có dữ liệu lịch sử/nhãn phù hợp trước evaluate. Đến đây có bằng chứng cho vòng đời MLOps hoàn chỉnh trong phạm vi demo đã chọn.
    
    **Làm:**
    
    - Điền toàn bộ `[TODO]` trong `tai-lieu-ky-thuat-mlops-margin.md` bằng số liệu thật từ Ngày 13.
    - Render mermaid diagram thành ảnh, chèn vào báo cáo/slide.
    - Chuẩn bị script demo end-to-end (đúng thứ tự: ingest → feature/nhãn + quality gate → train + tracking → gate/duyệt/promote → webhook deploy → gọi endpoint KServe nội bộ bằng feature vector mẫu → batch/drift/evaluate → rollback).
    - Rehearsal demo ít nhất 1 lần, canh thời gian.
    
    **Deliverable:** Báo cáo hoàn chỉnh, slide/poster, demo chạy trơn tru trong thời gian quy định.
    
    ---
    
    ## Giai đoạn 2 — Phục vụ real-time theo `master_account`

    Điều kiện bắt đầu: giai đoạn 1 bàn giao, model `@production` tự deploy lên KServe, batch predict ổn định.

    | Mục | Luồng | Nội dung |
    | --- | --- | --- |
    | GĐ2-A | 2 | Feast online store: materialize `fs_*` từ offline sang Redis, kiểm tra lookup khớp nguồn; DAG `feast_materialize_daily`; yêu cầu feature scoring mới nhất đã tách khỏi nhãn (ngày 5) |
    | GĐ2-B | 5 | **FastAPI inference gateway** nhận `master_account`, gọi Feast Online Store, tính feature on-demand (dùng chung code với train), chọn segment/model, gọi KServe nội bộ, trả score và model version; một endpoint cho mỗi use case |
    | GĐ2-C | 5 | Timeout, mapping lỗi (không có account/feature, KServe chưa ready), health endpoint, test gọi API với tài khoản hợp lệ và thiếu feature |
    | GĐ2-D | 2, 5 | Đo latency end-to-end; kiểm thử Redis chưa materialize; bổ sung mục 8.2 (OpenAPI) của tài liệu kỹ thuật |

    Phần KServe, auto-deploy và reconcile đã xong trong giai đoạn 1, nên giai đoạn 2 chỉ thêm lớp phía trước.

    ---


    ## Rủi ro lớn nhất cần theo dõi sát

    1. **Ngày 8 (KServe setup)** là điểm dễ trễ nhất (Ngày 5, Feast, đã xong và không nằm trong luồng chính giai đoạn 1). Ngày 8: dành cả ngày, nếu chiều chưa xong thì tối làm tiếp, không dồn sang ngày 9.
    2. **Thứ tự cắt khi trễ (từ đầu danh sách):** (a) `campaign_response` và `overdue_risk` dừng ở mức train + đăng ký, không deploy và không có DAG riêng; (b) bỏ tự trigger retrain ở ngày 12, giữ drift + report, trigger thủ công qua Airflow UI; (c) dùng ngày 14 làm đệm.
    3. **Không nên cắt** ngày 7 (promotion logic) và ngày 9–10 (webhook + reconcile): đây là phần MLOps logic cốt lõi.
    4. **RAM:** mỗi `InferenceService` là một pod; chỉ deploy model use case phụ khi còn trong ngân sách ~4,5–5GB của toàn hạ tầng.
    5. **Nhãn use case phụ** là phần mới của dữ liệu, chưa chạy full pipeline. Nếu quality gate FAIL hoặc lift campaign không đạt, chỉnh generator rồi sinh lại; không sửa nhãn sau khi sinh.
    6. **Khi trình bày:** Redis online và FastAPI gateway nằm ngoài giai đoạn 1; slide phải đánh dấu "giai đoạn 2".

