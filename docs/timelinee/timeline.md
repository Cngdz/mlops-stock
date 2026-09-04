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
        
        **Reconcile loop** là phần quan trọng nhất về mặt kỹ thuật: kể cả khi webhook bị lỡ một sự kiện (mạng lỗi, service down tạm thời), vòng lặp định kỳ vẫn tự phát hiện và sửa sai lệch — hệ thống không bao giờ "đứng yên ở trạng thái sai" quá 600 giây.
        
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
            C --> D["Tính Drift nhanh<br/>gán severity: none/low/high/critical"]
            D --> E{"severity == high/critical?"}
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
    
- Timeline
    
    ## Tuần 1 — Nền tảng dữ liệu, feature, training, registry
    
    ### Ngày 1: Setup hạ tầng cơ bản
    
    **Làm:**
    
    - Cài kind/minikube, Docker.
    - Deploy PostgreSQL, Redis, MinIO qua Helm chart có sẵn (bitnami hoặc tương đương).
    - Deploy MLflow (backend Postgres, artifact MinIO), verify UI truy cập được.
    
    **Học:** Helm cơ bản (`helm install`, `values.yaml`), khái niệm Deployment/Service/PVC/Secret trong K8s.
    
    **Deliverable cuối ngày:** 4 service chạy healthy, MLflow UI mở được.
    
    ---
    
    ### Ngày 2: Helmfile hoá + dữ liệu synthetic
    
    **Làm:**
    
    - Gom các Helm release ở Ngày 1 vào 1 `helmfile.yaml` để quản lý tập trung.
    - Viết script sinh dữ liệu synthetic: `customer_account`, `stock_transaction`, `margin_balance_daily`, `margin_cash_flow` (bảng sự kiện giải ngân riêng, mirror `agg_fact_ma_debt_cash_flow`, dùng để sinh `loan_label_next` theo 2 tổ hợp MARGIN_MBS/BUY_SHARE và MBLINK/BUY) (~5.000-10.000 tài khoản, 6 tháng lịch sử).
    
    **Học:** Helmfile syntax, thiết kế synthetic data có quan hệ nghiệp vụ hợp lý (correlation giữa turnover và margin usage).
    
    **Deliverable:** 4 bảng nguồn ở dạng Parquet (`customer_account`, `stock_transaction`, `margin_balance_daily`, `margin_cash_flow`), kiểm tra được bằng pandas/DuckDB.
    
    ---
    
    ### Ngày 3: Ghi Iceberg + PyIceberg/DuckDB
    
    **Làm:**
    
    - Setup Iceberg catalog local (SQLite catalog là nhanh nhất).
    - Ghi 4 bảng nguồn vào Iceberg qua PyIceberg.
    - Viết vài query DuckDB đọc thẳng Iceberg table để verify.
    
    **Học:** PyIceberg API (`catalog.create_table`, `append`), DuckDB `iceberg_scan` hoặc extension tương ứng.
    
    **Deliverable:** 4 bảng Iceberg query được qua DuckDB.
    
    ---
    
    ### Ngày 4: Feature engineering + nhãn
    
    **Làm:**
    
    - Xây dựng feature snapshot theo bốn nhóm: `fs_demographic`, `fs_trading_behavior`, `fs_margin_balance`, `fs_asset_balance`.
    - Tạo `loan_label_next` theo cửa sổ 30 ngày sau `report_date`, đúng logic nghiệp vụ Margin MBS/MBLink và bảo đảm point-in-time, không leakage.
    - Chạy data-quality gate, kiểm tra positive rate theo `nu/lu/au`, và chốt cách xử lý mất cân bằng nhãn.
    - Chuẩn bị time-based train/validation/test split với embargo 30 ngày.
    
    **Học:** Rolling window aggregation, point-in-time correctness, event-based labeling và xử lý class imbalance.
    
    **Deliverable:** Bốn bảng `fs_*` trên Iceberg, `training_dataset` có label và split, class weights và báo cáo chất lượng; chỉ dùng training khi quality gate đạt.
    
    ---
    
    ### Ngày 5: Feast setup
    
    **Làm:**
    
    - Cài Feast, khai báo Entity (`master_account`), Data Source trỏ vào Iceberg/DuckDB, Feature View.
    - Chạy `feast apply`, test historical retrieval (point-in-time correctness).
    - Materialize sang Redis, test online feature lookup.
    
    **Học:** Feast concepts (Entity/FeatureView/OfflineStore/OnlineStore), cách viết custom offline store nếu Feast không hỗ trợ sẵn DuckDB (kiểm tra trước — nếu tốn quá nửa ngày để viết custom provider, fallback: dùng Feast **File offline store** trỏ vào Parquet export từ Iceberg, đơn giản hơn nhiều).
    
    **Deliverable:** Historical feature retrieval chạy được, online feature trong Redis truy vấn được.
    
    ---
    
    ### Ngày 6: Training pipeline
    
    **Làm:**
    
    - Training pipeline đọc feature từ Feast, train Logistic Regression (baseline) + LightGBM cho 3 phân khúc (`nu`/`lu`/`au`).
    - Tính metric: ROC-AUC, precision, recall, F1, confusion matrix.
    - Cố định random seed.
    
    **Học:** LightGBM multi-class/multi-model theo segment, xử lý class weight trong LightGBM.
    
    **Deliverable:** Model train xong, metric in ra console/notebook.
    
    ---
    
    ### Ngày 7: MLflow tracking + registry + promotion logic
    
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
    
    **Làm:**
    
    - Cài cert-manager + KServe controller (RawDeployment mode, không Knative).
    - Deploy thử 1 `InferenceService` thủ công (`kubectl apply`) trỏ `storageUri` vào MinIO, verify predict endpoint hoạt động.
    
    **Học:** KServe CRD schema, MLServer sklearn/lightgbm runtime, debug lỗi pull artifact từ MinIO (thường do IAM/secret).
    
    **Deliverable:** 1 InferenceService chạy thủ công, nhận feature vector và trả kết quả đúng qua endpoint nội bộ.
    
    > ⚠️ Điểm rủi ro thứ hai — dành cả ngày cho việc này, nếu chiều vẫn chưa xong, tối làm tiếp, không dồn sang ngày 9.
    > 
    
    ---
    
    ### Ngày 9: Webhook deployer và FastAPI inference gateway
    
    **Làm:**
    
    - Viết **FastAPI deployer** nhận sự kiện (webhook thật nếu MLflow version hỗ trợ, hoặc polling alias mỗi phút nếu không — polling đơn giản hơn, vẫn đạt tinh thần "tự động", chỉ khác cơ chế trigger).
    - Logic: resolve model version + storageUri, filter đúng alias `production`, apply `InferenceService` CRD qua K8s Python client.
    - Test idempotency: gửi lại cùng sự kiện, không được tạo resource trùng.
    - Viết **FastAPI inference gateway** riêng cho luồng nghiệp vụ: nhận `master_account`, gọi Feast Online Store, chọn segment/model, gọi KServe nội bộ và trả response ổn định cho client.
    - Bổ sung timeout, mapping lỗi (không tìm thấy account/feature, KServe chưa ready) và health endpoint cho gateway.
    
    **Học:** MLflow webhook registration (hoặc polling registry API), Kubernetes Python client (`apply`), idempotency check pattern, FastAPI service-to-service call và error handling.
    
    **Deliverable:** Đổi alias `@production` → InferenceService tự cập nhật, không cần `kubectl apply` thủ công.
    
    ---
    
    ### Ngày 10: Reconcile loop + rollback
    
    **Làm:**
    
    - Viết vòng lặp định kỳ 600s: so sánh alias hiện tại vs InferenceService đang chạy, tự sửa nếu lệch.
    - Test rollback: chuyển alias về version cũ, verify endpoint quay lại đúng version.
    
    **Học:** Control loop pattern (giống Kubernetes controller), cách test race condition/idempotency có chủ đích (gửi 2 event gần nhau).
    
    **Deliverable:** Demo rollback thành công, reconcile loop tự sửa khi sửa `InferenceService` thủ công.
    
    ---
    
    ### Ngày 11: Airflow standalone + DAG orchestration
    
    **Làm:**
    
    - Cài Airflow standalone mode.
    - Viết 3 DAG: `feature_store_daily` (materialize), `<model>_train`, `<model>_predict` (batch).
    - Verify chạy lại pipeline không hỏng dữ liệu, không tạo alias sai.
    
    **Học:** Airflow standalone setup, DAG authoring cơ bản (PythonOperator đủ dùng, không cần KubernetesPodOperator).
    
    **Deliverable:** 3 DAG chạy được từ Airflow UI, có log/retry.
    
    ---
    
    ### Ngày 12: Batch predict + self-healing + Evidently
    
    **Làm:**
    
    - DAG batch predict: chấm điểm toàn bộ tài khoản, ghi bảng `pred_*`.
    - Tính Drift Ratio từ Evidently column-level drift result (số feature drifted / tổng feature), gán severity theo bảng ở mục 10, nếu high/critical → trigger DAG train (gọi Airflow API hoặc `TriggerDagRunOperator`).
    - Tích hợp Evidently: sinh report so sánh 2 snapshot dữ liệu khác thời điểm (mô phỏng "weekly evaluate" bằng dữ liệu có sẵn thay vì đợi thời gian thật).
    
    **Học:** Evidently `Report`/`TestSuite` API cơ bản, cách trigger DAG khác từ trong 1 DAG (`TriggerDagRunOperator`).
    
    **Deliverable:** Batch predict chạy xong, có report drift, self-healing loop demo được (giả lập drift bằng cách shift phân phối dữ liệu test).
    
    ---
    
    ### Ngày 13: Kiểm thử lỗi + đo lường
    
    **Làm:**
    
    - Mô phỏng 3 tình huống lỗi: Redis chưa materialize, model version sai schema, webhook bị lỡ event — verify hệ thống phát hiện/phục hồi đúng như thiết kế.
    - Đo và ghi lại: materialization time, training time, thời gian từ promote đến InferenceService sẵn sàng, inference latency, rollback time.
    
    **Học:** Không có kiến thức mới — đây là ngày kiểm thử, tập trung viết test case và đo đạc.
    
    **Deliverable:** Bảng số liệu đo lường đầy đủ, điền vào mục 9 (Experiment/Result) trong tài liệu kỹ thuật.
    
    ---
    
    ### Ngày 14: Hoàn thiện tài liệu, slide, demo rehearsal
    
    **Làm:**
    
    - Điền toàn bộ `[TODO]` trong `tai-lieu-ky-thuat-mlops-margin.md` bằng số liệu thật từ Ngày 13.
    - Render mermaid diagram thành ảnh, chèn vào báo cáo/slide.
    - Chuẩn bị script demo end-to-end (đúng thứ tự: ingest → feast apply → train → promote → webhook deploy → gọi FastAPI gateway bằng `master_account` → gateway lấy feature từ Feast và gọi KServe → drift report → rollback).
    - Rehearsal demo ít nhất 1 lần, canh thời gian.
    
    **Deliverable:** Báo cáo hoàn chỉnh, slide/poster, demo chạy trơn tru trong thời gian quy định.
    
    ---
    
    ## Rủi ro lớn nhất cần theo dõi sát
    
    1. **Ngày 5 (Feast offline store)** và **Ngày 8 (KServe setup)** là 2 điểm dễ trễ tiến độ nhất — đã ghi rõ fallback ở trên, đừng cố gắng "làm cho đúng ý tưởng ban đầu" nếu quá nửa ngày vẫn chưa chạy.
    2. Nếu trễ 1-2 ngày ở tuần 1, cắt tiếp **Ngày 12 phần self-healing tự động trigger** — giữ phần tính drift + report, bỏ phần tự trigger retrain, thay bằng "trigger thủ công qua Airflow UI" và ghi rõ trong báo cáo đây là giới hạn do thời gian.
    3. Không nên cắt **Ngày 7 (promotion logic)** hay **Ngày 9-10 (webhook + reconcile)** dù có trễ — đây là phần "MLOps logic thật" tạo giá trị điểm số cao nhất, đã phân tích ở đầu cuộc trò chuyện.
