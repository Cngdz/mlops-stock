# VDT GD2

**Nghiên cứu và xây dựng nền tảng MLOps trên Viettel Data Platform phục vụ phân tích và dự báo dữ liệu chứng khoán trong lĩnh vực ngân hàng**

- Tóm tắt
    
    ## 1. Overview
    
    - **Đề tài**: Nghiên cứu và xây dựng nền tảng MLOps phục vụ phân tích và dự báo dữ liệu chứng khoán trong lĩnh vực ngân hàng, triển khai trên hạ tầng Kubernetes single-node (laptop).
    - **Mục tiêu**: Chứng minh khả năng thiết kế, tích hợp, vận hành một vòng đời Machine Learning hoàn chỉnh — có khả năng tái lập, quản lý phiên bản, tự động triển khai và tự phục hồi khi có drift — không chỉ dừng ở việc train một mô hình đơn lẻ.
    - **Phạm vi**:
        - Trong phạm vi: feature store, experiment tracking, model registry với gated promotion, auto-deploy qua webhook, reconcile loop, batch + real-time serving qua FastAPI inference gateway, monitoring & self-healing retrain.
        - Ngoài phạm vi: streaming feature (Kafka/Spark), CI/CD build image riêng (Harbor/Kaniko/ArgoCD), distributed hyperparameter tuning, backup/registry GC vận hành trưởng thành — lý do cắt giảm: [xem mục 5, Solution/Approach].
    - **Thời gian thực hiện: 2 tuần**
    
    ## 2. Business Problem
    
    - **Bài toán**: Dự báo xác suất một tài khoản chứng khoán phát sinh hoặc gia tăng nhu cầu sử dụng margin/MBLink trong 30 ngày tới.
    - **Nhãn dự báo**: 
    Nhãn dự báo: `loan_label_next` = 1 nếu tài khoản phát sinh ít nhất 1 sự kiện giải ngân mới trong 30 ngày tới (từ report_date+1 đến report_date+30), thỏa mãn một trong hai tổ hợp: (fk_product=MARGIN_MBS, fk_cash_flow_type=INTERM_DELIVER, fk_deliver_type=BUY_SHARE) HOẶC (fk_product=MBLINK, fk_cash_flow_type=TLO_DELIVER_CASH, fk_deliver_type=BUY); = 0 nếu ngược lại. Logic mirror theo `model_margin_propensity/features/label.py` của hệ thống production tham khảo, áp dụng trên dữ liệu synthetic được mở rộng để mô phỏng cấu trúc bảng cash-flow gốc (`agg_fact_ma_debt_cash_flow`).
    - **Giá trị nghiệp vụ**: Cho phép cá nhân hóa ưu đãi (lãi suất margin) đúng thời điểm khách hàng có nhu cầu, thay vì gửi thông báo đại trà.
    - **Đối tượng dự báo**: 3 phân khúc khách hàng — `nu` (non-user), `lu` (từng dùng margin, hiện hết dư nợ), `au` (active user) — mỗi phân khúc có model riêng do hành vi khác biệt.
    
    ## 3. Data
    
    ### 3.1 Nguồn dữ liệu
    
    Dữ liệu tự sinh (synthetic), phản ánh quan hệ nghiệp vụ hợp lý; **không dùng kết quả trên dữ liệu tổng hợp để kết luận kinh doanh thực tế**.
    
    ### 3.2 Bảng nguồn (Gold layer, Iceberg)
    
    | Bảng | Vai trò | Cột chính |
    | --- | --- | --- |
    | `customer_account` | Thông tin tài khoản/khách hàng | `master_account`, ngày mở tài khoản, trạng thái, nhóm khách hàng |
    | `stock_transaction` | Lịch sử giao dịch | `transaction_id`, `master_account`, `symbol`, `transaction_time`, loại mua/bán, khối lượng, giá trị |
    | `margin_balance_daily` | Số liệu margin theo ngày | `master_account`, `business_date`, dư nợ, hạn mức, giá trị tài sản, số dư tiền |
    | `margin_cash_flow` | Sự kiện giải ngân margin | `master_account`, `event_date`, `fk_product`, `fk_cash_flow_type`, `fk_deliver_type`, `amount` |
    
    ### 3.3 Feature tables (`fs_*`, Iceberg — offline store)
    
    Rút gọn còn nhóm đại diện đủ category thay vì đầy đủ 12 nhóm như hệ thống production tham khảo:
    
    | Feature group | Ví dụ cột |
    | --- | --- |
    | `fs_demographic` | `account_age_days`, loại tài khoản |
    | `fs_trading_behavior` | `total_trading_amount_7d/30d`, `trade_count_30d` |
    | `fs_margin_balance` | `margin_debt`, `margin_utilization_ratio` |
    | `fs_asset_balance` | `cash_balance`, NAV |
    
    ### 3.4 Quy mô & split
    
    - Quy mô: ~5.000–20.000 tài khoản, 6–12 tháng lịch sử.
    - Time-based split (train/validation/test theo thời gian, không random split) để tránh leakage.
    - Point-in-time correctness: feature tại thời điểm dự báo không được chứa dữ liệu phát sinh sau đó.
    
    Output hiện tại gồm `fs_*` và `training_dataset` với time-based train/validation/test split và embargo 30 ngày.
    
    ## 4. Solution
    
    Vòng đời ML end-to-end, 8 giai đoạn:
    
    1. Sinh dữ liệu synthetic + mô tả nghiệp vụ, ghi vào Iceberg.
    2. Xây dựng Feature Store (Feast: entity, data source, feature view).
    3. Materialize feature offline → online (Redis) định kỳ.
    4. Training pipeline: baseline (Logistic Regression) + model so sánh (LightGBM/XGBoost) cho từng phân khúc.
    5. Experiment tracking + model registry (MLflow), gán alias `@staging` trước, `@production` sau khi qua gate.
    6. Auto-deploy: webhook lắng nghe alias đổi → tạo/cập nhật KServe `InferenceService` trỏ thẳng `storageUri` của model (không build image riêng cho model runtime).
    7. Batch predict hàng ngày (cảnh báo sớm qua drift proxy) + real-time serving cho client qua FastAPI inference gateway.
    8. Monitoring: Evidently theo dõi drift, đánh giá tuần dựa trên ground truth thật, tự động trigger retrain khi cần.
    
    ## 5. Architecture
    
    - `mlops-architecture`
        
        Toàn hệ thống được vẽ trong 1 ảnh tổng quan, sau đó tách thành 7 luồng riêng biệt vì mỗi luồng phục vụ mục đích nghiệp vụ khác nhau và chạy độc lập (khác trigger, khác tần suất) 
        
        ## 0. Kiến trúc tổng quan (all-in-one)
        
        **Giải thích tổng quan**: 5 khối chính (Data → Feature Store → Training/Registry → Serving → Monitoring) nối thành một vòng khép kín — Monitoring phát hiện drift sẽ quay lại kích hoạt Training, biến hệ thống từ "chạy một lần" thành "tự thích nghi". Airflow không nằm trong luồng chính mà đứng ngoài, đóng vai trò lên lịch cho các bước batch (feature materialize, train định kỳ, đánh giá drift).
        
        ![image.png](image.png)
        
        ---
        
        ## 1. Luồng Batch Feature Pipeline (`dag_feature_store_daily`)
        
        **Mục đích nghiệp vụ**: mỗi đêm, tính lại toàn bộ đặc trưng hành vi khách hàng (giao dịch, margin, tài sản) từ dữ liệu thô, đảm bảo dữ liệu sạch trước khi đưa vào cả training lẫn serving.
        
        ```mermaid
        flowchart TD
            A["Gold DWH<br/>dim_customer, fact_trading, fact_margin"] --> B["Tầng trung gian<br/>customer_base, trading_daily, margin_history"]
            B --> C["Xuất bản feature tables<br/>fs_demographic, fs_trading_behavior, fs_margin_balance..."]
            C --> D{"Data Quality Gate<br/>Great Expectations"}
            D -- đạt --> E["Ghi vào Iceberg<br/>fs_* tables"]
            D -- lỗi --> F(["Fail pipeline<br/>cảnh báo"])
            E --> G["Tagging & Profiles<br/>fs_customer_tags, fs_customer_profiles"]
            G --> H["feast apply<br/>đăng ký FeatureView vào Registry"]
        ```
        
        Đây là luồng nền tảng — nếu bước Data Quality Gate không đạt, toàn bộ pipeline dừng ngay, tránh việc feature bẩn lọt vào training hoặc serving.
        
        ---
        
        ## 2. Luồng Feature Materialization (`dag_feast_materialize_daily`)
        
        **Mục đích nghiệp vụ**: đồng bộ giá trị feature mới nhất từ kho lưu trữ lớn (Iceberg) sang bộ nhớ nhanh (Redis), để API dự báo real-time trả lời trong dưới 10ms thay vì phải quét cả kho dữ liệu.
        
        ```mermaid
        flowchart LR
            A[("Offline Store<br/>Iceberg fs_*")] -->|"feast materialize<br/>START_TS END_TS"| B["Materialize Job"]
            B -->|ghi theo key master_account| C[("Online Store<br/>Redis")]
            C --> D["FastAPI Inference Gateway<br/>Feast lookup"]
            D --> E["KServe Predictor<br/>model inference"]
        ```
        
        Chạy tách biệt khỏi luồng training — vì mục đích khác nhau: luồng 1 phục vụ *lưu trữ lịch sử để train*, luồng này phục vụ *tốc độ cho serving*.
        
        ---
        
        ## 3. Luồng Huấn luyện & Đăng ký mô hình (`model_train`)
        
        **Mục đích nghiệp vụ**: huấn luyện lại mô hình định kỳ (hoặc khi có drift), đảm bảo mô hình mới thực sự tốt hơn mô hình đang chạy trước khi cho phép lên production.
        
        ```mermaid
        flowchart TD
            A{"check_data_ready<br/>Features & Labels đủ chưa?"} -- hợp lệ --> B["Feast Retrieval<br/>lấy snapshot theo mốc thời gian"]
            B --> C["Train Multi-Segment Model<br/>phân khúc nu / lu / au"]
            C --> D["MLflow Logging<br/>run, metrics, artifact, baseline profile"]
            D --> E["Gán alias tạm: @staging"]
            E --> F["Backtest đa mốc<br/>-40d, -80d"]
            F --> G["So sánh Champion vs Challenger<br/>@staging vs @production"]
            G --> H["cleanup_registry<br/>giữ N version gần nhất"]
            H --> I["summarize<br/>báo cáo metric, khuyến nghị promote"]
            I --> J{"Con người duyệt?<br/>Manual / Governance"}
            J -- đạt tiêu chí --> K["Chuyển alias @production"]
            J -- chưa đạt --> L(["Giữ nguyên model cũ"])
        ```
        
        Điểm mấu chốt: alias `@staging` và `@production` tách biệt — model mới train xong **không tự động lên production**, phải qua so sánh Champion-Challenger và governance step. Đây chính là logic promotion đã bàn ở phần trước.
        
        ---
        
        ## 4. Luồng Tự động triển khai theo sự kiện (Event-driven Auto-deploy)
        
        **Mục đích nghiệp vụ**: khi model được duyệt lên production, hệ thống tự đưa model vào phục vụ mà không cần kỹ sư thao tác thủ công trên Kubernetes — giảm thời gian từ "duyệt model" đến "model chạy thật" từ hàng giờ xuống vài giây.
        
        ```mermaid
        sequenceDiagram
            participant DS as Data Scientist
            participant MLR as MLflow Registry
            participant WH as Webhook Deployer
            participant K8s as K8s API Server
            participant KS as KServe Controller
            participant Pod as MLServer Pod
        
            DS->>MLR: promote model (gán alias @production)
            MLR->>WH: webhook event (signature verified)
            WH->>WH: phân giải storageUri model version N
            WH->>K8s: apply InferenceService CRD
            K8s->>KS: tạo/cập nhật resource
            KS->>Pod: kéo model artifact từ MinIO, khởi động pod
            Pod-->>KS: ready
        
            loop mỗi 600s
                WH->>K8s: reconcile - so sánh alias vs InferenceService hiện tại
                alt lệch trạng thái
                    WH->>K8s: tự sửa lại đúng version
                end
            end
        ```
        
        **Reconcile loop** đối soát định kỳ để phát hiện và sửa sai lệch kể cả khi webhook bị lỡ một sự kiện. Chu kỳ 600 giây là khoảng giữa các lần kiểm tra khi service hoạt động; thời gian phục hồi thực tế còn phụ thuộc kết nối, tải artifact và pod Ready, cần đo ở ngày 13.
        
        ---
        
        ## 5. Luồng Phục vụ Dự báo Real-time (Online Inference)
        
        **Mục đích nghiệp vụ**: khi khách hàng mở app, hệ thống trả về xác suất họ sẽ vay margin trong thời gian thực để app hiển thị ưu đãi cá nhân hóa.
        
        ```mermaid
        sequenceDiagram
            participant App as Client App
            participant GW as FastAPI Inference Gateway
            participant Feast as Feast Feature Server
            participant Redis as Redis Online Store
            participant KS as KServe Predictor
        
            App->>GW: POST /v1/margin-propensity/predict<br/>{master_account: "0001234567"}
            GW->>Feast: get_online_features(entity=master_account)
            Feast->>Redis: tra cứu key
            Redis-->>Feast: feature vector (dưới 5ms)
            Feast-->>GW: features (dưới 10ms)
            GW->>GW: tính on-demand feature và chọn model theo phân khúc (nu/lu/au)
            GW->>KS: POST /v2/models/{segment}/infer<br/>{feature_vector: [...]}
            KS-->>GW: model score
            GW-->>App: {score: 0.87, segment: "high_propensity"}
        ```
        
        FastAPI inference gateway là lớp phục vụ nghiệp vụ: nhận `master_account`, gọi Feast Online Store, tính các feature on-demand, chọn model theo phân khúc rồi gọi KServe. KServe/MLServer chỉ tập trung chạy model với feature vector đã chuẩn hóa; nhờ vậy không ép model runtime phải biết gọi Feast. Logic tính feature on-demand (ví dụ tỷ lệ đòn bẩy) phải **dùng chung code** giữa lúc train và lúc serve — tránh train/serve skew.
        
        ---
        
        ## 6. Luồng Dự báo Hàng loạt & Tự phục hồi (`model_predict` + self-healing)
        
        **Mục đích nghiệp vụ**: chạy hàng ngày để chấm điểm toàn bộ khách hàng (phục vụ báo cáo/CRM, không cần real-time), đồng thời tự động phát hiện khi mô hình bắt đầu "lệch" và tự kích hoạt huấn luyện lại — không cần con người theo dõi liên tục.
        
        ```mermaid
        flowchart TD
            A["Trigger hàng ngày 06:00"] --> B["Batch Inference<br/>ghép feature toàn bộ khách hàng"]
            B --> C["Ghi bảng pred_*<br/>master_account, score, segment"]
            C --> D["Tính Drift nhanh<br/>gán severity theo mục 10; high thì cảnh báo"]
            D --> E{"severity == critical?"}
            E -- có --> F(["trigger_retrain<br/>kích hoạt DAG model_train"])
            E -- không --> G(["Kết thúc bình thường"])
        ```
        
        Đây là vòng lặp "self-healing" — khác với luồng Evidently (đánh giá sâu, hàng tuần), luồng này là **cảnh báo sớm hàng ngày**, phản ứng nhanh hơn khi thị trường biến động mạnh.
        
        ---
        
        ## 7. Luồng Giám sát & Đánh giá độ trôi (`model_evaluate`, hàng tuần)
        
        **Mục đích nghiệp vụ**: sau khi nhãn thực tế đã "chín" (biết chắc khách hàng có vay margin hay không sau 31 ngày), đối chiếu lại dự báo cũ với thực tế để đo độ chính xác thật ngoài production — con số này đáng tin hơn số liệu lúc train rất nhiều.
        
        ```mermaid
        flowchart TD
            A["Lấy điểm dự báo lịch sử<br/>bảng pred_* mốc T-31"] --> C["Ghép cặp dự báo ↔ nhãn thực tế"]
            B["Lấy nhãn thực tế đã phát sinh<br/>mốc T"] --> C
            C --> D["Tính Realised Metrics<br/>AUC thực tế, Precision@TopK, độ sụt so với lúc train"]
            D --> E["Evidently Drift Evaluation<br/>data drift & concept drift"]
            E --> F["Ghi report vào MLflow"]
            F --> G{"Vi phạm ngưỡng?<br/>ΔAUC quá lớn hoặc drift fail"}
            G -- có --> H(["Gửi cảnh báo, yêu cầu xem xét retrain"])
            G -- không --> I(["Mô hình hoạt động ổn định"])
        ```
        
        Khác với luồng 6 (nhanh, dùng proxy drift để cảnh báo sớm), luồng này **chậm nhưng chính xác** — dùng ground truth thật, là căn cứ cuối cùng để quyết định có retrain hay không.
        
        ---
        
        ## Tóm tắt: vì sao tách 7 luồng thay vì 1 sơ đồ
        
        | Luồng | Trigger | Tần suất | Mục đích |
        | --- | --- | --- | --- |
        | 1. Feature pipeline | Lịch (Airflow) | Hàng đêm | Chuẩn hóa dữ liệu đặc trưng |
        | 2. Materialization | Lịch (Airflow) | Hàng đêm | Đồng bộ tốc độ cho serving |
        | 3. Training | Lịch hoặc trigger drift | Định kỳ / khi cần | Tạo model version mới, có gate |
        | 4. Auto-deploy | Sự kiện (alias đổi) | Bất kỳ lúc nào | Đưa model vào phục vụ tự động |
        | 5. Real-time inference | Request từ client | Liên tục | Trả kết quả cho người dùng cuối |
        | 6. Batch predict + self-heal | Lịch (Airflow) | Hàng ngày | Chấm điểm hàng loạt + cảnh báo sớm |
        | 7. Weekly evaluate | Lịch (Airflow) | Hàng tuần | Đo chính xác thật, quyết định retrain |
        
        Mỗi luồng khác nhau ở **trigger** và **tần suất** — đây chính là lý do không nên gộp vào 1 sơ đồ duy nhất, vì bản chất chúng là các tiến trình độc lập chạy song song, chỉ giao nhau tại vài điểm chung (Iceberg, MLflow Registry).
        
    
    Xem chi tiết trong `mlops-architecture` — gồm sơ đồ tổng quan và 7 luồng tách riêng:
    
    1. Batch feature pipeline (hàng đêm)
    2. Feature materialization (hàng đêm)
    3. Training & registry với gated promotion
    4. Auto-deploy theo sự kiện + reconcile loop
    5. Real-time inference
    6. Batch predict + self-healing (cảnh báo sớm hàng ngày)
    7. Weekly evaluate (ground truth thật)
    
    **Component chính**: PostgreSQL (metadata), Redis (online store), MLflow (tracking + registry), MinIO (artifact storage), Feast (feature store), KServe (serving), Evidently (monitoring), Airflow (orchestration), Helm/Helmfile (deploy).
    
    ## 6. Model
    
    - **Thuật toán**: Logistic Regression (baseline) và LightGBM/XGBoost (model chính), huấn luyện riêng cho từng phân khúc (`nu`/`lu`/`au`).
    - **Feature**: theo mục 3.3, đọc qua Feast historical retrieval (point-in-time correct).
    - **Xử lý mất cân bằng nhãn**: class weight hoặc threshold tuning theo precision/recall nghiệp vụ (ưu tiên, giữ phân phối gốc); SMOTE chỉ khi hai phương án trên không đủ.
    - **Metric đánh giá**: ROC-AUC, precision, recall, F1-score, confusion matrix.
    - **Điều kiện promotion** (logic có thể unit test):  ROC-AUC không được giảm quá **3% tuyệt đối**, Recall không được giảm quá **5% tuyệt đối**, so với bản `@production` hiện tại; phải qua schema-compatibility check. Đơn giản hóa từ quality-gate đa tiêu chí (top-k lift, calibration, composite score theo phân khúc) của hệ thống production tham khảo, do quy mô dữ liệu synthetic không đủ lớn để calibrate ổn định theo từng phân khúc trong 2 tuần; cơ chế gate (all-or-nothing 3 phân khúc, challenger phải thắng champion) vẫn giữ nguyên.
    - **Backtest đa mốc**: đánh giá trên các mốc snapshot quá khứ (ví dụ -40d, -80d) trước khi so sánh Champion vs Challenger.
    - [TODO] Giá trị metric thực tế sau khi train, bảng so sánh baseline vs model chính.
    - [TODO — tùy chọn nếu còn thời gian] SHAP/feature importance để tăng tính diễn giải.
    
    ---
    
    ## 7. Infrastructure / Deployment
    
    - **Nền tảng**: Kubernetes single-node (kind/minikube), Helm/Helmfile để triển khai.
    - **Serving**: KServe RawDeployment mode (không qua Knative/Istio) — giảm tải tài nguyên, phù hợp laptop; KServe nhận feature vector và thực hiện model inference.
    - **Business API**: FastAPI inference gateway nhận `master_account`, truy vấn Feast Online Store/Redis, tính feature on-demand, chọn model theo phân khúc và gọi endpoint nội bộ của KServe.
    - **Auto-deploy**: MLflow webhook → FastAPI deployer → resolve `storageUri` → apply `InferenceService` CRD. Reconcile loop chạy mỗi 600s để tự sửa lệch trạng thái (idempotent).
    - **Orchestration**: Airflow standalone mode, các DAG: `feature_store_daily`, `feast_materialize_daily`, `iceberg_maintenance_weekly`, `<model>_train`, `<model>_predict`, `<model>_evaluate`.
    - **Tài nguyên ước tính**: ~4.5–5GB RAM cho toàn bộ hạ tầng (khuyến nghị laptop ≥16GB RAM).
    - [TODO] Thông số máy thực tế đã dùng, thời gian đo được cho từng bước (materialization, training, deploy latency, inference latency, rollback time).
    
    ---
    
    ## 8. API / Interface
    
    ### 8.1 Batch prediction output (bảng Iceberg)
    
    | Cột | Ý nghĩa |
    | --- | --- |
    | `master_account_number` | Mã tài khoản |
    | `margin_segment` | Phân khúc (`nu`/`lu`/`au`) |
    | `margin_score` | Xác suất phát sinh nhu cầu vay margin (0–1) |
    | `propensity_binary_pred` | Nhãn dự báo nhị phân |
    | `report_date` | Ngày chấm điểm |
    
    ### 8.2 Real-time inference API
    
    - **Client request**: `POST /v1/margin-propensity/predict` — payload `{ "master_account": "<id>" }`
    - **Gateway-to-KServe request**: `POST /v2/models/<segment>/infer` — payload chứa feature vector theo model signature đã log trong MLflow.
    - **Client response**: `{ "score": 0.87, "segment": "high_propensity", "model_version": "<version>" }`
    - Payload inference **không được chứa** cột nhãn `loan_label_next`.
    - KServe endpoint là endpoint nội bộ; client không gọi trực tiếp KServe và không cần biết cấu trúc feature.
    
    [TODO] OpenAPI spec đầy đủ hoặc file `.proto` nếu dùng gRPC.
    
    ---
    
    ## 9. Experiment / Result
    
    [TODO — điền sau khi chạy thực nghiệm]
    
    - Bảng so sánh metric giữa các phiên bản model (baseline vs model chính, theo từng phân khúc).
    - Kết quả backtest đa mốc thời gian.
    - Thời gian đo được: materialization time, training time, thời gian từ promote đến khi `InferenceService` sẵn sàng, inference latency, rollback time.
    - Kết quả demo: rollback từ version mới về version cũ, xác nhận API tiếp tục hoạt động.
    - Kết quả kiểm thử các tình huống lỗi mô phỏng (Redis chưa materialize, model version lỗi schema, webhook bị lỡ sự kiện) — mô tả cách phát hiện và phục hồi.
    
    ---
    
    ## 10. Monitoring & Maintenance
    
    - **Data/model drift**: Evidently, chạy đánh giá tuần dựa trên ground truth thật (đối chiếu dự báo T-31 với nhãn thực tế tại T).
    - **Cảnh báo sớm**: batch predict hàng ngày tính **Drift Ratio** = số feature bị lệch phân phối / tổng số feature (lấy trực tiếp từ Evidently column-level drift result). Severity: none = 0%, medium ≤ 20% (chỉ log), high = 20–50% (alert + gắn tag `monitoring.driftSeverity=high`  lên MLflow Model Version), critical > 50% (cảnh báo khẩn + tự động trigger DAG train lại). Weekly evaluate: nếu ΔAUC thật giảm >5% → cảnh báo xem xét retrain; giảm >10% → bắt buộc trigger retrain.
    - **Reconcile loop**: đối soát định kỳ 600s giữa alias `@production` và trạng thái `InferenceService` thực tế trên cluster, tự sửa nếu lệch.
    - **Rollback**: chuyển alias về version trước; xác nhận artifact hợp lệ và health check pass trước khi cutover.
    - **Retraining trigger**: kết hợp 2 tín hiệu — cảnh báo sớm (hàng ngày, proxy) và đánh giá chính xác (hàng tuần, ground truth thật) — tránh retrain quá thường xuyên vì proxy sai, nhưng vẫn phản ứng nhanh khi cần.
    - [TODO] Ngưỡng cụ thể cho severity/ΔAUC cần mentor xác nhận trước khi áp dụng.
    
    ---
    
    ## 11. Hạn chế & Hướng phát triển