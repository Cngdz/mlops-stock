# Hiểu bản chất dự án MLOps (ngày 1–8)

Tài liệu này không hướng dẫn gõ lệnh. Nó giúp bạn nhìn ra **bộ khung** đứng sau hơn 50 file, hơn 10 công cụ và 8 ngày làm việc: mỗi thứ tồn tại để trả lời câu hỏi gì, phụ thuộc vào cái gì, được viết ra sao, và vì sao lại viết như vậy. Mục tiêu cuối cùng là bạn tự giải thích, tự dựng lại, tự gỡ lỗi và tự thay đổi được hệ thống của ngày 1–8.

Phạm vi: chỉ những gì đã làm trong ngày 1–8. Ngày 9–14 sẽ được học theo cùng khung này khi làm tới.

**Cách đọc.** Đọc theo thứ tự, vì phần sau dùng khái niệm của phần trước. Mỗi phần kết thúc bằng vài câu hỏi tự kiểm tra; trả lời được bằng lời của mình rồi mới sang phần sau. Các liên kết tới file trong repo bấm vào là mở thẳng file đó. Xem dạng đã định dạng trong VS Code bằng `Ctrl+Shift+V`.

## Mục lục

| Phần | Nội dung | Trạng thái |
|---|---|---|
| [0](#phần-0-vì-sao-thấy-rối-và-ba-câu-hỏi-để-định-vị-một-file-bất-kỳ) | Vì sao thấy rối, và ba câu hỏi để định vị một file bất kỳ | Đã viết |
| [1](#phần-1-khung-tư-duy-mlops-làm-gì-trước-làm-gì-sau-và-vì-sao) | Khung tư duy MLOps: 7 lớp, 5 nguyên tắc, bản đồ đầy đủ, công thức chung | Đã viết |
| [2](#phần-2-đặt-ngày-18-vào-khung-và-lần-ngược-một-dự-đoán) | Đặt ngày 1–8 vào khung, bài truy vết ngược một dự đoán | Đã viết |
| [3](#phần-3-bản-đồ-phụ-thuộc-và-cơ-chế-bên-trong) | Bản đồ phụ thuộc và cơ chế bên trong | Đã viết |
| [4](#phần-4-tư-duy-tổ-chức-code) | Tư duy tổ chức code | Đã viết |
| [5](#phần-5-tư-duy-yaml-từ-bản-chất-đến-từng-dòng) | Tư duy YAML: từ bản chất đến từng dòng | Đã viết |
| 6 | Quy trình viết một file cho chuẩn, áp vào ví dụ thật | Chưa viết |
| 7 | Vận hành và gỡ lỗi theo lớp | Chưa viết |
| 8 | Tổng kết, câu hỏi kiểu phỏng vấn, bài kiểm tra mức nắm vững | Chưa viết |

Tài liệu liên quan trong repo: [timeline 14 ngày](../timelinee/timeline.md), [feature contract](../feature_contract.md), [quyết định sinh dữ liệu](../data_generation_decisions.md), [đặc tả nghiệp vụ](../data_generation_business_spec.md), [runbook hạ tầng](../../infra/README.md).

---

## Phần 0. Vì sao thấy rối, và ba câu hỏi để định vị một file bất kỳ


### Cảm giác rối đến từ đâu

Sau tám ngày, repo của bạn có khoảng 60 file được git theo dõi, trải trên bảy thư mục, viết bằng bốn thứ ngôn ngữ (Python, SQL, YAML, PowerShell), và chạm tới hơn mười công cụ: Docker, kind, Helm, Postgres, MinIO, MLflow, PyIceberg, DuckDB, Feast, scikit-learn, LightGBM, KServe, cert-manager, MLServer. Mỗi ngày bạn học một công cụ mới, viết thêm vài file, chạy thêm vài lệnh. Khi nhìn lại, mọi thứ hiện ra như một đống mảnh ghép không có tranh mẫu.

Cảm giác đó không phải do bạn thiếu khả năng, mà do **cách bạn đã tiếp nhận kiến thức**. Bạn học theo **trình tự thời gian** (ngày 1, ngày 2…) và theo **công cụ** (hôm nay MLflow, hôm sau KServe). Nhưng hệ thống không được tổ chức theo thời gian hay theo công cụ. Nó được tổ chức theo **những câu hỏi mà một hệ thống ML vận hành phải trả lời được**: dữ liệu ở đâu, feature tại một thời điểm có đúng không, model nào được phép phục vụ, phục vụ bằng cách nào. Mỗi công cụ chỉ là **một câu trả lời** cho một câu hỏi, và nhiều file cùng phục vụ một câu hỏi. Học theo ngày giống như đọc một cuốn sách bằng cách xem các trang theo thứ tự chúng được in, thay vì theo mục lục.

Tin tốt là số câu hỏi ít hơn nhiều so với số file. Toàn bộ ngày 1–8 xoay quanh **7 lớp** và **5 nguyên tắc** lặp đi lặp lại. Khi đã thấy chúng, sáu mươi file thu về thành vài nhóm, và mỗi file mới gặp đều có chỗ để đặt vào.

### Ba câu hỏi để định vị một file bất kỳ

Trước khi học bất kỳ phần nào, hãy làm quen với thói quen này: mỗi khi mở một file, đừng đọc từ dòng đầu. Hãy trả lời ba câu hỏi trước, vì chúng cho biết file đó **quan trọng thế nào** và **nên đọc ra sao**.

**Câu thứ nhất: file này thuộc lớp nào của hệ thống?** Nó đang giải quyết chuyện hạ tầng, dữ liệu nguồn, lưu trữ, feature, huấn luyện, quản lý model, hay phục vụ? Biết lớp là biết nó nhận gì từ lớp trước và bàn giao gì cho lớp sau. Phần 1 sẽ định nghĩa bảy lớp này.

**Câu thứ hai: file này thuộc loại gì?** Trong dự án chỉ có vài loại file, và mỗi loại có vai trò khác hẳn nhau. Có file là **cấu hình**, chỉ mô tả "muốn gì" mà không chứa logic. Có file là **logic thuần**, nhận dữ liệu và trả kết quả, không chạm vào thế giới bên ngoài. Có file là **cửa ra thế giới ngoài**, đọc ghi file, gọi MLflow, gọi Kubernetes. Có file là **điểm chạy**, nơi bạn gõ lệnh để kích hoạt mọi thứ. Và có file chỉ để **kiểm chứng**: test, hoặc các script `dayN_verify`, `dayN_check`. Một file kiểm chứng mà hỏng thì hệ thống vẫn chạy; một file logic mà sai thì kết quả sai. Phần 4 đi sâu vào cách phân loại này.

**Câu thứ ba: ai đọc file này?** Câu này đặc biệt quan trọng với YAML. Một file YAML tự nó không làm gì cả; ý nghĩa của nó hoàn toàn do **chương trình đọc nó** quyết định. Cùng là YAML, nhưng `training/usecases.yaml` do code Python của bạn đọc, `infra/helm-values/mlflow-values.yaml` do Helm đọc, còn `serving/k8s/30-isvc-loan-propensity-au.yaml` do API server của Kubernetes rồi controller của KServe đọc. Ba người đọc khác nhau thì luật viết khác nhau. Phần 5 đi sâu vào điều này.

Thử áp ba câu hỏi vào bốn file quen thuộc:

| File | Lớp | Loại | Ai đọc / ai chạy |
|---|---|---|---|
| [training/promotion.py](../../training/promotion.py) | Quản lý model | Logic thuần | Được `registry.py` và test gọi |
| [training/registry.py](../../training/registry.py) | Quản lý model | Cửa ra thế giới ngoài (MLflow) | Được `train.py` và `promote.py` gọi |
| [serving/k8s/20-servingruntime.yaml](../../serving/k8s/20-servingruntime.yaml) | Phục vụ | Cấu hình (khai báo Kubernetes) | API server, rồi controller KServe |
| [scripts/day8_predict_check.py](../../scripts/day8_predict_check.py) | Phục vụ | Kiểm chứng | Bạn chạy bằng tay sau khi deploy |

Chỉ với ba cột này, bạn đã biết ngay: muốn hiểu **luật** của promotion gate thì đọc `promotion.py` (ngắn, không phụ thuộc gì); muốn biết model **được lưu ở đâu** thì đọc `registry.py`; còn `day8_predict_check.py` hỏng thì model vẫn phục vụ bình thường, chỉ là mất đi một bằng chứng.

### Bộ tài liệu này sẽ đi thế nào

Phần 1 dựng bộ khung: bảy lớp, năm nguyên tắc, và bản đồ MLOps đầy đủ để thấy dự án đang đứng đâu. Phần 2 đặt tám ngày vào khung, kèm một bài lần ngược từ một xác suất mà KServe trả ra về tới dữ liệu gốc. Phần 3 giải thích vì sao các thành phần phải có theo một thứ tự nhất định, bằng cơ chế bên trong của chúng. Phần 4 và 5 là cách tổ chức code và cách đọc YAML tới từng dòng. Phần 6 là quy trình tự viết một file mới cho chuẩn. Phần 7 là vận hành và gỡ lỗi. Phần 8 tổng kết và cho bạn các bài kiểm tra để tự đo mức độ nắm vững.

### Tự kiểm tra

1. Vì sao học theo ngày làm bạn thấy rối, trong khi hệ thống thực ra có cấu trúc rõ ràng?
2. Chọn một file bất kỳ trong [training/](../../training/) mà bảng trên chưa nhắc tới (ví dụ `config.py` hoặc `promote.py`) và tự trả lời ba câu hỏi định vị cho nó.
3. Vì sao với YAML, câu hỏi "ai đọc file này" lại quan trọng hơn với Python?

---

## Phần 1. Khung tư duy MLOps: làm gì trước, làm gì sau, và vì sao


### 1.1 Câu hỏi gốc

Mọi hệ thống MLOps, dù dùng công cụ gì, đều sinh ra từ cùng một câu hỏi: **làm sao để một dự đoán đáng tin cậy đến được tay người cần nó, hôm nay, ngày mai và cả năm sau?** Chữ "đáng tin cậy" là chỗ toàn bộ độ phức tạp nằm. Train một model trong notebook rồi in ra AUC thì một buổi chiều là xong. Nhưng để một xác suất do model trả ra lúc 10 giờ sáng nay được tin, ta phải trả lời được: model đó là bản nào, học từ dữ liệu nào, dữ liệu đó có dùng nhầm thông tin của tương lai không, ai cho phép model đó được phục vụ, và nó có đang chạy đúng trong môi trường mà nó được tạo ra không.

Cách tốt nhất để thấy hệ thống cần những gì là **đi ngược từ dự đoán về dữ liệu**. Muốn có dự đoán, cần một model đang được phục vụ. Muốn phục vụ đúng model, cần biết model nào đã được duyệt. Muốn duyệt, cần model được huấn luyện có thể tái lập. Muốn huấn luyện, cần feature và nhãn đúng thời điểm. Muốn có feature, cần dữ liệu được lưu sao cho đọc lại được đúng như lúc trước. Muốn lưu, cần có dữ liệu nguồn. Và muốn làm bất cứ điều gì ở trên, cần một nơi để chạy và một nơi để chứa. Mỗi điều kiện trong chuỗi này là một **lớp** của hệ thống. Đọc chuỗi đó theo chiều xuôi, ta có luôn **thứ tự xây dựng**: lớp nào là điều kiện của lớp khác thì phải có trước.

```
  1. Nền chạy  →  2. Dữ liệu nguồn  →  3. Lưu trữ có phiên bản  →  4. Feature và nhãn
                                                                         │
  7. Phục vụ  ←  6. Quản lý và duyệt model  ←  5. Huấn luyện  ←──────────┘
```

Mỗi lớp dưới đây được trình bày theo cùng một khuôn: câu hỏi cốt lõi của lớp, điều gì xảy ra nếu bỏ qua nó, lớp đó phải **bàn giao** gì cho lớp sau, và dự án chọn công cụ nào, vì sao. Hãy để ý cụm "bàn giao": đó là sợi dây nối các lớp, và cũng là thứ bạn sẽ đi tìm khi gỡ lỗi.

### 1.2 Bảy lớp

#### Lớp 1. Nền chạy: chạy ở đâu, chứa ở đâu?

Mọi chương trình cần một nơi để chạy, và mọi kết quả cần một nơi để nằm lại sau khi chương trình tắt. Ở máy cá nhân, hai thứ này là CPU và ổ cứng của bạn. Nhưng một hệ thống MLOps có nhiều thành phần chạy liên tục (máy chủ MLflow, kho file, model server), cần sống sót khi khởi động lại máy, và cần dựng lại được y hệt ở nơi khác. Bỏ qua lớp này, nghĩa là cài mỗi thứ một kiểu bằng tay lên máy, thì đến ngày thứ năm sẽ không ai nhớ đã cài những gì, phiên bản nào, cấu hình ra sao, và không thể dựng lại khi máy hỏng.

Lớp này bàn giao cho các lớp sau **những địa chỉ để gọi và những chỗ để chứa**: một cụm Kubernetes để chạy các dịch vụ, một kho file dạng S3 (MinIO) để chứa model và artifact, một cơ sở dữ liệu (Postgres) để chứa thông tin mô tả của MLflow, và một máy chủ MLflow để ghi lại các lần train. Dự án dùng **kind** để có một cụm Kubernetes chạy ngay trong Docker trên máy, và dùng **Helm** cùng **helmfile** để cài các dịch vụ theo khai báo trong [infra/helmfile.yaml](../../infra/helmfile.yaml). Ngoài đời, cùng lớp này thường là một cụm Kubernetes trên đám mây cộng với các dịch vụ có sẵn (S3, RDS), nhưng vai trò y hệt. Đây là ngày 1, và phần làm cho nó dựng lại được ở ngày 2 và ngày 7.

#### Lớp 2. Dữ liệu nguồn: dữ liệu đến từ đâu, có đúng nghiệp vụ không?

Model chỉ giỏi bằng dữ liệu nó học. Trong doanh nghiệp, dữ liệu nguồn đến từ hệ thống giao dịch, hệ thống core banking. Dự án không có nguồn thật, nên tự **sinh dữ liệu synthetic**. Điều đáng học ở đây không phải "sinh dữ liệu ngẫu nhiên", mà là sinh dữ liệu **có quan hệ nghiệp vụ**: khách giao dịch nhiều thì dễ dùng margin hơn, khách được gửi chiến dịch thì xác suất vay tăng trong 14 ngày, dư nợ vượt hạn mức kéo dài thì bị quá hạn. Nếu bỏ qua quan hệ nghiệp vụ, model sẽ học trên nhiễu thuần tuý, mọi chỉ số đều vô nghĩa, và không kiểm thử được những tình huống mình quan tâm.

Lớp này bàn giao **tám bảng nguồn** dạng Parquet: bốn bảng nghiệp vụ cốt lõi (tài khoản, giao dịch chứng khoán, dòng tiền margin, số dư margin hằng ngày) và bốn bảng mở rộng (giá cổ phiếu, danh mục mã, danh mục nắm giữ, chiến dịch). Một điểm thiết kế cần nắm: generator dùng các **biến ẩn** cho mỗi khách (`margin_affinity`, `wealth_level`, `risk_appetite`…) để quyết định hành vi, nhưng những biến này **không bao giờ** được xuất ra làm feature, giống như ngoài đời ta không đo được "độ thích vay" của khách. Generator chạy với seed cố định và có số phiên bản, nên cùng tham số luôn sinh ra cùng dữ liệu. Code nằm trong [data_generation/](../../data_generation/), quyết định thiết kế ghi trong [data_generation_decisions.md](../data_generation_decisions.md). Đây là ngày 2.

#### Lớp 3. Lưu trữ có phiên bản: đọc lại được đúng dữ liệu của một thời điểm không?

Có dữ liệu rồi, cách đơn giản nhất là để nguyên các file Parquet trong một thư mục. Cách này vỡ khi dữ liệu thay đổi. Ngày mai sinh lại hay bổ sung dữ liệu, file cũ bị ghi đè, và model đã train hôm qua không còn truy được về đúng dữ liệu nó học. Thư mục file cũng không có **schema** được ràng buộc (ai đó ghi một cột sai kiểu là hỏng âm thầm) và không có khái niệm ghi "trọn vẹn hoặc không ghi gì" (ghi dở giữa chừng là để lại dữ liệu nửa vời).

Lớp này bàn giao **những bảng có tên, có schema, có lịch sử**, mà các bước sau đọc theo tên thay vì theo đường dẫn file. Dự án dùng **Apache Iceberg**, một định dạng bảng đặt lên trên các file Parquet, ghi kèm metadata mô tả schema và mỗi lần ghi là một **snapshot**. Danh mục các bảng được lưu trong một **catalog** (ở đây là file SQLite cục bộ). Bảng được ghi bằng **PyIceberg** và truy vấn bằng **DuckDB**. Bộ dữ liệu nguồn hiện tại nằm trong namespace `raw_day4_v3e`. Lựa chọn tương tự gồm Delta Lake và Apache Hudi; ở quy mô doanh nghiệp, catalog thường là Hive, Glue hay Nessie. Đây là ngày 3, code ở [scripts/day3_write_iceberg.py](../../scripts/day3_write_iceberg.py).

#### Lớp 4. Feature và nhãn: dữ liệu đưa cho model có đúng thời điểm không?

Đây là lớp mà sai sót **nguy hiểm nhất**, vì sai ở đây không làm chương trình lỗi, mà làm model trông tốt một cách giả tạo. Model cần **feature**, tức những con số mô tả khách tại một ngày D (số lệnh 30 ngày qua, tỷ lệ dư nợ trên hạn mức…), và **nhãn**, tức điều xảy ra sau ngày D (khách có vay margin trong 30 ngày tới không). Nguyên tắc sống còn gọi là **point-in-time correctness**: feature tại ngày D chỉ được dùng thông tin có đến hết ngày D. Chỉ cần lỡ dùng một chút dữ liệu của ngày D+1, model sẽ "nhìn trộm tương lai", đạt AUC rất cao khi kiểm tra, rồi sụp đổ khi chạy thật vì ngoài đời không ai có dữ liệu tương lai. Lỗi này gọi là **rò rỉ dữ liệu** (data leakage).

Lớp này bàn giao ba thứ, và cả ba phải đi qua một **cổng chất lượng** (quality gate) trước khi được dùng. Thứ nhất là sáu bảng feature `fs_*` chia theo nhóm (thông tin tài khoản, giao dịch, margin, tài sản, danh mục, chiến dịch), có cho **mọi** ngày đến ngày dữ liệu cuối cùng, kể cả những ngày chưa biết nhãn, để còn chấm điểm cho hôm nay. Thứ hai là `training_dataset`: feature nối với nhãn, chỉ gồm những ngày đã đủ 30 ngày để biết kết quả, kèm cột `split` chia train, validation và test **theo thời gian**, có khoảng đệm (embargo) 30 ngày giữa các phần. Thứ ba là `class_weights.json` để xử lý việc số khách vay ít hơn hẳn số khách không vay. Mỗi lần chạy tạo ra một thư mục riêng có mã run, và file `data/features/current.json` đóng vai **con trỏ** trỏ tới run đã được duyệt; các bước sau luôn đi qua con trỏ này. Code ở [scripts/day4_feature_engineering.py](../../scripts/day4_feature_engineering.py) và [scripts/day4_features.sql](../../scripts/day4_features.sql), hợp đồng dữ liệu ghi trong [feature_contract.md](../feature_contract.md). Đây là ngày 4.

Ngày 5 thêm vào lớp này một thành phần: **feature store**, ở đây là **Feast**. Feast đăng ký các bảng `fs_*` dưới dạng định nghĩa có tên (entity là `master_account`, mỗi bảng là một feature view, mỗi use case là một feature service), và biết cách lấy feature **đúng thời điểm** cho một danh sách (tài khoản, thời điểm) bất kỳ. Ở giai đoạn 1, Feast chỉ dùng để **kiểm chứng** rằng cách lấy feature của nó cho kết quả trùng khớp với `training_dataset` (kiểm tra "parity"), nhằm chuẩn bị cho giai đoạn 2, khi feature phải được phục vụ online qua Redis. Train và chấm điểm ở giai đoạn 1 vẫn đọc thẳng `training_dataset` và `fs_*`.

#### Lớp 5. Huấn luyện: từ dữ liệu ra model, và có làm lại được y hệt không?

Huấn luyện là phần quen thuộc nhất, nhưng trong MLOps câu hỏi chính không phải "AUC bao nhiêu" mà là **"làm lại có ra y hệt không, và con số đó có đáng tin không"**. Bỏ qua chuyện tái lập, nghĩa là chạy hai lần ra hai model khác nhau, thì không thể so sánh model mới với model cũ một cách công bằng. Bỏ qua kỷ luật chia dữ liệu, nghĩa là dùng tập test để chọn model hay chọn ngưỡng, thì con số báo cáo cao hơn thực tế, vì model đã gián tiếp "học" tập test.

Lớp này bàn giao **model kèm bằng chứng**: mỗi (use case, phân khúc) có một model, kèm metric trên validation và test, ngưỡng phân loại, và thông tin truy vết (dùng feature run nào, code commit nào, thư viện phiên bản nào). Dự án train sáu model: ba cho `loan_propensity` (phân khúc `nu`, `lu`, `au`), hai cho `overdue_risk` (`lu`, `au`), một chung cho `campaign_response`. Mỗi phân khúc thử Logistic Regression làm mốc so sánh và LightGBM, chọn model và ngưỡng bằng validation, chấm test đúng một lần. Model được đóng gói thành một sklearn `Pipeline` gồm cả tiền xử lý, để nơi phục vụ chỉ cần đưa vào feature thô. Code nằm trong [training/](../../training/), cấu hình trong [training/usecases.yaml](../../training/usecases.yaml). Đây là ngày 6.

#### Lớp 6. Quản lý và duyệt model: có những model nào, và model nào được phép phục vụ?

Sau vài lần train, bạn có nhiều model. Không có lớp này, model là các file nằm rải rác, không ai biết file nào đang chạy production, và model mới được đưa lên chỉ vì "nó mới hơn". Lớp này trả lời hai câu: **đã có những model nào**, mỗi cái học từ đâu, tốt cỡ nào (sổ đăng ký), và **model nào được phép phục vụ**, do ai quyết, theo tiêu chí gì (cổng duyệt).

Lớp này bàn giao một **con trỏ có thẩm quyền**: alias `@production` trên mỗi model đã đăng ký, trỏ tới đúng một version. Dự án dùng **MLflow**: phần Tracking ghi lại mỗi lần train (tham số, metric, artifact), phần Model Registry đánh số version và quản lý alias. Model mới train xong chỉ được gắn `@staging`. **Promotion gate** so model mới với model đang production trên cùng tập test (AUC không được tụt quá 0,03, recall ở cùng mức cảnh báo không được tụt quá 0,05, và mọi phân khúc phải cùng đạt), rồi ghi kết quả vào tag. Chỉ khi có người chạy bước duyệt ([training/promote.py](../../training/promote.py) với `--approve`) thì `@production` mới dời sang version mới. Lựa chọn tương tự gồm Weights & Biases, Neptune, hay registry của các nền tảng đám mây. Đây là ngày 7.

#### Lớp 7. Phục vụ: biến model thành dịch vụ chạy đúng môi trường

Model đã được duyệt vẫn chỉ là một file trong MinIO. Lớp cuối biến nó thành **một dịch vụ chạy liên tục**, nhận feature qua HTTP và trả xác suất trong vài mili-giây. Bỏ qua lớp này nghĩa là mỗi ứng dụng tự nạp file model, với đủ hệ luỵ: chậm, phụ thuộc thư viện, gắn chặt vào ứng dụng, không kiểm tra được đầu vào. Còn làm lớp này mà không cẩn thận về môi trường thì model có thể sập, như model LR đã sập trên image có sklearn khác phiên bản.

Lớp này bàn giao **một địa chỉ để gọi**: Service `loan-propensity-au-predictor` trong cluster, nói theo giao thức V2 chuẩn. Dự án dùng **KServe** ở chế độ RawDeployment để biến một khai báo `InferenceService` ngắn thành Deployment và Service, **cert-manager** để cấp chứng chỉ cho webhook của KServe, và **MLServer** chạy trong một image tự build có đúng phiên bản thư viện như lúc train. Các khai báo nằm trong [serving/](../../serving/). Lý thuyết đầy đủ của lớp này là bài 8 bước đã học ở ngày 8. Đây là ngày 8.

### 1.3 Năm nguyên tắc xuyên suốt

Đọc lại bảy lớp, bạn sẽ thấy một số ý tưởng xuất hiện lặp đi lặp lại dưới những cái tên khác nhau. Đó không phải trùng hợp. Chúng là **năm nguyên tắc** làm nên chữ "đáng tin cậy" trong câu hỏi gốc, và khi hiểu chúng, bạn sẽ nhận ra mỗi file trong dự án đang thực thi nguyên tắc nào.

**Nguyên tắc 1: Tái lập (reproducibility).** Cùng đầu vào phải cho cùng đầu ra, hôm nay hay năm sau, máy này hay máy khác. Không có tái lập thì không so sánh được gì, vì mỗi lần chạy khác nhau có thể do thay đổi thật, cũng có thể do ngẫu nhiên. Nguyên tắc này hiện diện khắp nơi: seed cố định và số phiên bản của generator (ngày 2), snapshot của Iceberg (ngày 3), mã run của ngày 4, `random_state` và `deterministic=True` của LightGBM (ngày 6), phiên bản chart được ghim trong helmfile (ngày 1), và các phiên bản thư viện được ghim chính xác trong image serving (ngày 8).

**Nguyên tắc 2: Hợp đồng (contract).** Mỗi chỗ một lớp bàn giao cho lớp sau đều cần một thoả thuận rõ ràng, viết ra và kiểm tra được, về hình dạng của thứ được bàn giao. Không có hợp đồng thì mọi thay đổi ở lớp trước đều có thể làm vỡ lớp sau một cách âm thầm. Trong dự án: schema của các bảng Iceberg (ngày 3), [feature_contract.md](../feature_contract.md) với phiên bản `day4-v5` (ngày 4), allowlist feature trong `usecases.yaml` (ngày 6), **signature** 24 cột mà MLflow lưu cùng model (ngày 7), và giao thức V2 giữa client và model server (ngày 8).

**Nguyên tắc 3: Cổng kiểm soát (gate).** Thứ gì đi từ lớp này sang lớp sau đều phải qua một bài kiểm tra tự động, và **không đạt thì chặn lại**, chứ không chỉ cảnh báo. Cổng đặt ở những chỗ mà sai sót sẽ lan rộng nếu để lọt qua. Dự án có quality gate của ngày 4 (không PASS thì không ghi bảng feature, và `training/data.py` từ chối train), promotion gate của ngày 7 (không đạt thì `promote.py` từ chối dời alias), signature của ngày 8 (payload sai thì model server trả lỗi). Các script kiểm chứng như `day5_feast_check.py` và `day8_predict_check.py` là cổng do con người chủ động chạy.

**Nguyên tắc 4: Truy vết (lineage).** Từ bất kỳ kết quả nào phải lần ngược được về mọi thứ đã tạo ra nó. Khi một dự đoán sai, câu hỏi đầu tiên là "model nào, học từ dữ liệu nào". Trong dự án, sợi chỉ đó đi qua: annotation `mlops/model-version` trên InferenceService → version trong MLflow → tag `train_run_id`, `feature_run_id`, `git_commit` → thư mục run ngày 4 với `quality_report.json` → namespace nguồn `raw_day4_v3e`. Phần 2 sẽ cho bạn tự đi hết sợi chỉ này.

**Nguyên tắc 5: Tách "mong muốn" khỏi "thực tế".** Thay vì ra lệnh trực tiếp "làm việc này", ta ghi lại **trạng thái mong muốn** ở một nơi đáng tin, và để một cơ chế khác làm cho thực tế khớp với nó. Nhờ vậy, việc đổi ý chỉ là sửa chỗ ghi mong muốn, và việc kiểm tra chỉ là so hai bên. Trong dự án: `current.json` là con trỏ "run feature nào được dùng" (ngày 4), alias `@production` là con trỏ "model nào được phục vụ" (ngày 7), và mọi file YAML Kubernetes là bản khai báo mà các controller liên tục đối soát với cluster (ngày 8). Nguyên tắc này sẽ là trung tâm của ngày 9–10, khi bạn tự viết vòng đối soát giữa alias và InferenceService.

### 1.4 Bản đồ MLOps đầy đủ: dự án đang đứng ở đâu

Bảy lớp trên là phần **đường đi** của một dự đoán. Một hệ thống MLOps hoàn chỉnh còn có những lớp **vận hành** bao quanh, giữ cho đường đi đó chạy đúng theo thời gian. Bảng dưới cho bạn thấy toàn cảnh, và vị trí của dự án trong đó. Bộ tài liệu này chỉ đi sâu các dòng "Đã làm".

| Lớp | Câu hỏi cốt lõi | Trong dự án | Công cụ phổ biến |
|---|---|---|---|
| Nền chạy | Chạy ở đâu, chứa ở đâu, dựng lại được không? | **Đã làm** (ngày 1–2) | Kubernetes, Terraform, Helm |
| Dữ liệu nguồn | Dữ liệu từ đâu, đúng nghiệp vụ không? | **Đã làm** (ngày 2), dạng synthetic | Kafka, CDC, ETL |
| Lưu trữ có phiên bản | Đọc lại được dữ liệu của một thời điểm không? | **Đã làm** (ngày 3) | Iceberg, Delta Lake, lakeFS, DVC |
| Feature và nhãn | Feature đúng thời điểm không, có cổng chất lượng không? | **Đã làm** (ngày 4–5), Feast chỉ offline | Feast, Tecton, dbt, Great Expectations |
| Huấn luyện | Làm lại có y hệt không, con số có đáng tin không? | **Đã làm** (ngày 6) | scikit-learn, LightGBM, XGBoost, PyTorch |
| Quản lý và duyệt model | Có những model nào, model nào được phục vụ? | **Đã làm** (ngày 7) | MLflow, Weights & Biases |
| Phục vụ | Model thành dịch vụ chạy đúng môi trường không? | **Đã làm** (ngày 8), mới 1 model, deploy tay | KServe, Seldon, BentoML, Triton |
| Tự động deploy và đối soát | Model được duyệt có tự lên, tự sửa lệch, rollback được không? | Sẽ làm (ngày 9–10) | Argo CD, controller tự viết |
| Điều phối pipeline | Các bước chạy theo lịch, đúng thứ tự, có retry không? | Sẽ làm (ngày 11) | Airflow, Prefect, Dagster, Kubeflow |
| Giám sát và đánh giá | Dữ liệu có trôi không, model còn tốt không, khi nào train lại? | Sẽ làm (ngày 12) | Evidently, Prometheus, Grafana |
| Kiểm thử lỗi và đo lường | Hệ thống hành xử thế nào khi có lỗi, nhanh chậm ra sao? | Sẽ làm (ngày 13) | Chaos testing, load test |
| Phục vụ online với feature store | Lấy feature mới nhất trong mili-giây cho từng request? | Giai đoạn 2 | Feast + Redis, FastAPI |
| CI/CD cho ML | Mỗi thay đổi code có tự được test, build, triển khai không? | Không làm | GitHub Actions, GitLab CI |
| Chiến lược phát hành | Thử model mới trên một phần traffic trước khi thay hẳn? | Không làm | Canary, shadow, A/B trên Knative hoặc Istio |
| Quản trị | Ai được làm gì, giải thích được dự đoán không, tuân thủ quy định không? | Không làm | RBAC, Vault, SHAP, model card |

### 1.5 Công thức chung khi gặp một bài toán MLOps mới

Gom tất cả lại, khi cầm một bài toán ML mới cần đưa vào vận hành, bạn có thể đặt câu hỏi theo đúng thứ tự của các lớp. Thứ tự này không phải quy ước, mà là chuỗi phụ thuộc: mỗi câu trả lời là điều kiện để câu hỏi sau có nghĩa.

Đầu tiên, hãy làm rõ **quyết định nghiệp vụ** mà dự đoán phục vụ: ai dùng nó, dùng lúc nào (hằng đêm hay ngay lúc khách mở app), và sai thì thiệt hại gì. Câu trả lời quyết định bạn cần batch hay online, cần độ trễ bao nhiêu, và chỉ số nào quan trọng (bỏ sót khách rủi ro tốn kém hơn hay gọi nhầm khách tốn kém hơn). Tiếp theo là **nhãn**: điều gì xảy ra sau thời điểm dự đoán thì được coi là "có", và phải chờ bao lâu mới biết. Định nghĩa nhãn kéo theo cách chia dữ liệu theo thời gian và khoảng đệm. Rồi đến **dữ liệu nguồn và cách lưu**: có những bảng nào, đọc lại đúng một thời điểm bằng cách nào. Sau đó là **feature đúng thời điểm** cùng hợp đồng và cổng chất lượng của nó. Khi đó mới đến lượt **huấn luyện tái lập được** và **kỷ luật đánh giá**. Rồi **sổ đăng ký và tiêu chí duyệt**: model mới phải hơn model cũ ở điểm nào thì được thay. Cuối cùng là **phục vụ**, cùng môi trường khớp với lúc train. Các lớp vận hành (tự động deploy, điều phối, giám sát) đến sau, khi đường đi của một dự đoán đã chạy được trọn vẹn một lần bằng tay.

Có hai bài học đi kèm công thức này. Thứ nhất, **hãy cho đường đi chạy thông bằng tay trước rồi mới tự động hoá**: dự án của bạn cũng đi đúng như vậy, ngày 8 deploy tay rồi ngày 9 mới tự động. Tự động hoá một quy trình chưa hiểu rõ chỉ làm lỗi xảy ra nhanh hơn. Thứ hai, **ở mỗi chỗ bàn giao, hãy hỏi năm nguyên tắc**: có tái lập được không, hợp đồng là gì, cổng kiểm soát ở đâu, truy vết bằng gì, mong muốn được ghi ở đâu. Một chỗ bàn giao trả lời được cả năm câu là một chỗ bàn giao vững.

### Tự kiểm tra

1. Không nhìn tài liệu, kể tên bảy lớp theo thứ tự xây dựng, và với mỗi lớp nói một câu: nó bàn giao gì cho lớp sau.
2. Vì sao lỗi ở lớp 4 (feature và nhãn) được coi là nguy hiểm nhất, dù nó không làm chương trình báo lỗi?
3. `current.json` của ngày 4 và alias `@production` của ngày 7 cùng thể hiện một nguyên tắc. Đó là nguyên tắc nào, và nếu không có chúng thì điều gì dễ xảy ra?
4. Chọn một lớp và chỉ ra trong lớp đó có những nguyên tắc nào trong năm nguyên tắc đang được thực thi, kèm tên file cụ thể.
5. Nếu ngày mai bạn nhận một bài toán mới, ví dụ dự đoán khách rời bỏ dịch vụ, câu hỏi đầu tiên bạn sẽ đặt ra là gì, và vì sao không bắt đầu từ việc chọn model?

---

## Phần 2. Đặt ngày 1–8 vào khung, và lần ngược một dự đoán

Phần 1 cho bạn bảy lớp như những cái hộp rỗng. Phần này đặt tám ngày đã làm vào đúng hộp của chúng, để thấy mỗi ngày nhận gì, sinh ra gì, và file nào làm việc chính, file nào chỉ đứng bên cạnh để kiểm chứng. Sau đó bạn sẽ làm một bài tập quan trọng: cầm một xác suất mà KServe vừa trả ra, rồi lần ngược từng bước về tới dữ liệu gốc mà nó được sinh ra từ đó. Làm xong bài này, các file sẽ không còn là những mảnh rời, vì bạn đã tự tay đi dọc sợi chỉ nối chúng.

### 2.1 Mỗi ngày lấp một lớp

Có một cách nhìn giúp mọi ngày trở nên dễ hiểu: **mỗi ngày nhận vào một thứ do ngày trước bàn giao, và bàn giao lại một thứ cho ngày sau**. Thứ được bàn giao gọi là **artifact**: một file, một bảng, một model, một địa chỉ dịch vụ. Trong mỗi ngày, các file chia làm ba nhóm. Nhóm **làm việc chính** tạo ra artifact. Nhóm **kiểm chứng** (test, script `verify`, `check`) chứng minh artifact đúng. Nhóm **hỗ trợ** giúp chạy hoặc xem cho tiện, bỏ đi thì hệ thống vẫn đúng. Khi đọc một ngày, hãy tìm nhóm làm việc chính trước.

**Ngày 1** lấp lớp nền chạy. Đầu vào là một chiếc máy trống có Docker. Đầu ra là một cụm Kubernetes tên `lab` (chạy bằng kind) cùng bốn dịch vụ trong namespace `mlops`: Postgres, Redis, MinIO và máy chủ MLflow. Thứ được bàn giao cho các ngày sau thực chất là **địa chỉ**: MLflow ở cổng 5050, MinIO ở cổng 9000 (qua port-forward). File làm việc chính là [infra/helmfile.yaml](../../infra/helmfile.yaml) cùng bốn file trong [infra/helm-values/](../../infra/helm-values/). File kiểm chứng là [scripts/day1_verify.py](../../scripts/day1_verify.py), log thử một model lên MLflow để chứng minh cả chuỗi Postgres, MinIO, MLflow thông nhau. Hai script [infra/bootstrap.ps1](../../infra/bootstrap.ps1) và [infra/port-forward.ps1](../../infra/port-forward.ps1) được thêm sau, ở ngày 7, để dựng lại và mở đường cho tiện.

**Ngày 2** làm hai việc thuộc hai lớp. Phần thứ nhất thuộc lớp nền: gom các lệnh cài đặt thành helmfile để dựng lại được. Phần thứ hai thuộc lớp dữ liệu nguồn: sinh tám bảng synthetic. Đầu ra là thư mục `data/generated/day4_v3e/` chứa tám file Parquet cùng một file `generation_run.json` ghi lại "giấy khai sinh" của bộ dữ liệu: generator phiên bản `0.2.0`, seed `42`, 5.000 tài khoản, khoảng thời gian từ 2025-01-01 đến 2026-01-30, và các tỷ lệ mục tiêu đã hiệu chỉnh (15% cho `nu`, 25% cho `lu`, 35% cho `au`). Nhóm làm việc chính nằm trong [data_generation/](../../data_generation/): [generate_accounts.py](../../data_generation/generate_accounts.py) tạo khách hàng cùng các biến ẩn, [generate_all.py](../../data_generation/generate_all.py) mô phỏng từng ngày giao dịch và dòng tiền, [generate_extensions.py](../../data_generation/generate_extensions.py) sinh bảng danh mục và chiến dịch, [calibrate.py](../../data_generation/calibrate.py) dò hằng số để tỷ lệ dương đạt mục tiêu. Nhóm kiểm chứng là [tests/test_generator.py](../../tests/test_generator.py).

**Ngày 3** lấp lớp lưu trữ có phiên bản. Đầu vào là tám file Parquet của ngày 2. Đầu ra là tám bảng Iceberg trong namespace `raw_day4_v3e`, với danh mục bảng (catalog) nằm ở `data/catalog_full/pyiceberg.db` và file dữ liệu nằm ở `data/warehouse_full/`. File làm việc chính là [scripts/day3_write_iceberg.py](../../scripts/day3_write_iceberg.py). Nhóm kiểm chứng là [day3_verify_pyiceberg.py](../../scripts/day3_verify_pyiceberg.py), [day3_verify_duckdb.py](../../scripts/day3_verify_duckdb.py) và [tests/test_ingest.py](../../tests/test_ingest.py). File `data/source_current.json` là con trỏ ghi "namespace nguồn nào đã được dùng cho run ngày 4 được duyệt".

**Ngày 4** lấp lớp feature và nhãn, và là ngày có nhiều artifact nhất. Đầu vào là các bảng Iceberg của ngày 3. Đầu ra là một **thư mục run** `data/features/day4_runs/20261007T095923177784/` chứa: sáu bảng `fs_*`, `training_dataset` và `campaign_training_dataset` (feature nối nhãn, có cột `split`), `loan_overdue_labels` và `campaign_labels` (danh sách để Feast truy xuất), `class_weights.json`, `usecase_registry.json` (mô tả ba use case), và `quality_report.json` ghi kết quả của 90 phép kiểm tra chất lượng. Cùng nội dung đó được ghi thêm vào Iceberg dưới namespace `features_20261007t095923177784`. Cuối cùng, con trỏ `data/features/current.json` được trỏ vào run này. Nhóm làm việc chính là cặp [day4_feature_engineering.py](../../scripts/day4_feature_engineering.py) (điều phối, kiểm tra, ghi kết quả) và [day4_features.sql](../../scripts/day4_features.sql) (phép tính feature và nhãn bằng SQL). Nhóm kiểm chứng là [tests/test_day4.py](../../tests/test_day4.py), file test lớn nhất dự án. Nhóm hỗ trợ gồm [run_v3_pipeline.ps1](../../scripts/run_v3_pipeline.ps1) (chạy một mạch từ sinh dữ liệu tới kiểm tra Feast), [summarize_run.py](../../scripts/summarize_run.py) (in tóm tắt run) và [build_duckdb_views.py](../../scripts/build_duckdb_views.py) (tạo view để xem dữ liệu bằng công cụ giao diện).

**Ngày 5** bổ sung vào lớp feature một cách truy xuất có định nghĩa. Đầu vào là các bảng `fs_*` của run được trỏ bởi `current.json`. Đầu ra là registry của Feast (một entity, sáu feature view, ba feature service) và file `feast_check.json` ghi kết quả kiểm tra parity: PASS, 0 dòng lệch. Nhóm làm việc chính là [feature_repo/definitions.py](../../feature_repo/definitions.py) và [feature_repo/feature_store.yaml](../../feature_repo/feature_store.yaml). Nhóm kiểm chứng là [day5_feast_check.py](../../scripts/day5_feast_check.py) và [tests/test_feast.py](../../tests/test_feast.py). Có một điều đặc biệt: ở giai đoạn 1, **không có bước nào phía sau đọc artifact của ngày 5**. Ngày 6 đọc thẳng `training_dataset`. Ngày 5 là sự chuẩn bị cho giai đoạn 2.

**Ngày 6** lấp lớp huấn luyện. Đầu vào là `training_dataset`, `campaign_training_dataset` và `class_weights.json` của run được duyệt. Đầu ra là thư mục `data/models/day6_runs/<mã run train>/`, mỗi (use case, phân khúc) có `lr.joblib`, `lgbm.joblib` và `metrics.json`, cùng một `summary.json` cho cả lần train. Nhóm làm việc chính là package [training/](../../training/): [usecases.yaml](../../training/usecases.yaml) mô tả train cái gì, [config.py](../../training/config.py) đọc và kiểm tra cấu hình, [data.py](../../training/data.py) nạp và cắt dữ liệu, [models.py](../../training/models.py) dựng model, [evaluate.py](../../training/evaluate.py) tính metric và chọn ngưỡng, [train.py](../../training/train.py) điều phối. Nhóm kiểm chứng là [tests/test_training.py](../../tests/test_training.py).

**Ngày 7** lấp lớp quản lý và duyệt model. Đầu vào là model và metric của ngày 6. Đầu ra nằm trong MLflow: mỗi use case một experiment, mỗi phân khúc một registered model (`loan_propensity_au`…), mỗi lần train một version mới gắn `@staging`, kết quả promotion gate ghi vào tag, và `@production` trên version đã được duyệt. Nhóm làm việc chính là [promotion.py](../../training/promotion.py) (luật của gate), [registry.py](../../training/registry.py) (mọi thao tác với MLflow) và [promote.py](../../training/promote.py) (bước duyệt). Nhóm kiểm chứng là [tests/test_promotion.py](../../tests/test_promotion.py). Ngày này cũng sửa hạ tầng: nâng MLflow server từ 2.1.1 lên 3.15.2 vì bản cũ không có alias.

**Ngày 8** lấp lớp phục vụ. Đầu vào là alias `@production` và file model trong MinIO. Đầu ra là InferenceService `loan-propensity-au` cùng Service `loan-propensity-au-predictor` trong namespace `serving`. Nhóm làm việc chính là thư mục [serving/](../../serving/): [Dockerfile](../../serving/Dockerfile) và [requirements.txt](../../serving/requirements.txt) dựng môi trường, bốn file trong [serving/k8s/](../../serving/k8s/) khai báo hạ tầng. cert-manager và KServe được cài bằng lệnh Helm, chưa có file khai báo trong repo. Nhóm kiểm chứng là [day8_predict_check.py](../../scripts/day8_predict_check.py).

Gom lại thành một bảng để tra cứu:

| Ngày | Lớp | Artifact bàn giao | File làm việc chính | File kiểm chứng |
|---|---|---|---|---|
| 1 | Nền chạy | Cụm `lab`, MLflow :5050, MinIO :9000 | `infra/helmfile.yaml`, `infra/helm-values/` | `day1_verify.py` |
| 2 | Nền chạy, dữ liệu nguồn | 8 Parquet + `generation_run.json` | `data_generation/` | `test_generator.py` |
| 3 | Lưu trữ có phiên bản | 8 bảng Iceberg `raw_day4_v3e` | `day3_write_iceberg.py` | `day3_verify_*.py`, `test_ingest.py` |
| 4 | Feature và nhãn | Thư mục run + `current.json` | `day4_feature_engineering.py`, `day4_features.sql` | `test_day4.py`, `quality_report.json` |
| 5 | Feature và nhãn | Registry Feast, `feast_check.json` | `feature_repo/` | `day5_feast_check.py`, `test_feast.py` |
| 6 | Huấn luyện | `data/models/day6_runs/<run>/` | `training/` (trừ 3 file ngày 7) | `test_training.py` |
| 7 | Quản lý và duyệt | Version, alias, tag trong MLflow | `promotion.py`, `registry.py`, `promote.py` | `test_promotion.py` |
| 8 | Phục vụ | InferenceService + Service | `serving/` | `day8_predict_check.py` |

### 2.2 Dòng chảy artifact

Nếu bỏ hết tên file và chỉ giữ lại các artifact, toàn bộ ngày 1–8 là một dòng chảy duy nhất. Chú ý các **con trỏ** trên đường đi (đánh dấu `[con trỏ]` trong sơ đồ): chúng là những chỗ "mong muốn" được ghi lại, đúng nguyên tắc 5. Mỗi bước sau không đọc thẳng artifact mới nhất, mà đọc **thứ con trỏ đang chỉ vào**.

```
generation_run.json  ─┐
8 file Parquet ───────┴─▶ 8 bảng Iceberg (raw_day4_v3e, có snapshot)
                                   │   [con trỏ] source_current.json
                                   ▼
                    run ngày 4: fs_*, training_dataset, quality_report (PASS)
                                   │   [con trỏ] current.json
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
            Feast (chỉ kiểm chứng)     train ngày 6: model + metrics.json
                                                 │
                                                 ▼
                         MLflow: version mới @staging, tag promotion_gate
                                                 │   [con trỏ] alias @production (sau khi duyệt)
                                                 ▼
                         file model trong MinIO (s3://mlflow/...)
                                                 │   storageUri (ngày 8 chép tay)
                                                 ▼
                         InferenceService ─▶ pod MLServer ─▶ xác suất
```

Nhìn sơ đồ, bạn thấy ngay một chỗ khác biệt so với các con trỏ còn lại: ở bước cuối, `storageUri` được **chép tay** từ alias vào file YAML. Đây là mắt xích duy nhất trong cả chuỗi còn dựa vào con người, và đó chính là việc ngày 9 sẽ tự động hoá.

### 2.3 Bài truy vết ngược: từ một xác suất về tới dữ liệu gốc

Giả sử một ngày nào đó, bộ phận kinh doanh hỏi: "Model nói khách này có 33% khả năng vay margin. Con số đó đến từ đâu?". Một hệ thống MLOps tốt phải trả lời được câu này, và trả lời bằng bằng chứng chứ không bằng trí nhớ. Dưới đây là đường đi thật trên hệ thống của bạn. Mỗi bước đi kèm lệnh để bạn tự chạy lại (cần `.\infra\port-forward.ps1` đang chạy) và kết quả mình đã đọc được.

**Bước 1: từ dịch vụ ra model.** Xác suất đến từ InferenceService `loan-propensity-au`. Hỏi nó đang phục vụ gì:

```powershell
kubectl get isvc loan-propensity-au -n serving -o yaml | Select-String "mlops/|storageUri"
```

Kết quả: label `mlops/registered-model: loan_propensity_au`, annotation `mlops/model-version: "2"`, và `storageUri` là `s3://mlflow/1/models/m-d02adce3c18e430d9d8073014678bd6f/artifacts`. Đây là lý do bạn gắn label và annotation ở ngày 8: Kubernetes không cần chúng, nhưng **con người cần chúng để truy vết**. Không có chúng, bạn chỉ có một đường dẫn S3 khó hiểu.

**Bước 2: từ model ra lần train và quyết định duyệt.** Hỏi MLflow về version 2:

```powershell
uv run python -c "from training import registry as r; c=r.configure(); mv=c.get_model_version('loan_propensity_au','2'); print(mv.run_id); print(mv.tags)"
```

Các tag cho biết: model loại `lr` với ngưỡng 0,376; được train trong lần `train_run_id = 20261014T100254002881`, từ feature run `feature_run_id = 20261007T095923177784`; qua gate với trạng thái `BASELINE_PASS` vì lúc đó chưa có model production nào (lý do: "baseline auc 0.6323 >= floor 0.55"); được người dùng `ADMIN` duyệt lúc 10:03:51 UTC ngày 14/10; và `replaced_version = None`, tức nó là bản production đầu tiên. Chỉ từ một version, bạn đã biết ai cho phép nó phục vụ, vì sao, và nó học từ đâu.

**Bước 3: từ lần train ra cấu hình và code.** Version trỏ tới MLflow run `4fc99ace75454f91a389320a6086e23b`, tên `au-20261014T100254002881`. Các tag và tham số của run này cho biết: commit code `07d7936-dirty`, feature contract `day4-v5`, `seed = 42`, 24 feature với `feature_hash = 6e2b51b98438`, và **`train_cutoff_days = 40`**.

Chi tiết cuối rất đáng chú ý. Model đang phục vụ production **không phải** model train trên toàn bộ dữ liệu, mà là bản backtest bỏ 40 ngày cuối của tập train, được duyệt làm production đầu tiên ở ngày 7. Version 4 (train đủ dữ liệu, đã qua gate) vẫn đang chờ ở `@staging`. Nếu không có tag này, không ai biết điều đó. Còn hậu tố `-dirty` của commit cho biết lúc train, repo đang có thay đổi **chưa commit** (code ngày 7 đang viết dở). Đây là một **điểm yếu truy vết thật**: commit `07d7936` không chứa chính xác code đã sinh ra model này. Cách phòng là chỉ train để đưa lên production từ một repo sạch, và có thể cho promotion gate từ chối version mang dấu `-dirty`.

**Bước 4: từ lần train ra file trên đĩa.** Mã `train_run_id` chính là tên thư mục `data/models/day6_runs/20261014T100254002881/`, trong đó `loan_propensity/au/` có `lr.joblib`, `lgbm.joblib` và `metrics.json` ghi đủ metric của cả hai model, ngưỡng và lý do chọn. Đây là bản sao cục bộ, độc lập với MLflow.

**Bước 5: từ feature run ra cổng chất lượng.** Mã `feature_run_id` là tên thư mục `data/features/day4_runs/20261007T095923177784/`. Mở `quality_report.json`: trạng thái `PASS`, đủ **90/90** phép kiểm tra đạt (ví dụ `invalid_transaction_timestamp: observed 0, expected 0`), contract `day4-v5`, ngày dữ liệu cuối `raw_end = 2026-01-30`, và nguồn `source_namespace = raw_day4_v3e`. Nghĩa là dữ liệu mà model học đã được kiểm chứng trước khi được phép dùng.

**Bước 6: từ feature run ra đúng phiên bản dữ liệu nguồn.** Cũng trong `quality_report.json`, mục `source_snapshots` ghi cho từng bảng nguồn **mã snapshot Iceberg** đã đọc, ví dụ bảng `customer_account` ở snapshot `912592286894084918`, kèm đường dẫn file metadata. Đây là chỗ lớp lưu trữ có phiên bản phát huy tác dụng: kể cả khi bảng nguồn được ghi thêm dữ liệu sau này, snapshot đó vẫn đọc lại được đúng nội dung tại thời điểm feature được tính.

**Bước 7: từ dữ liệu nguồn ra cách nó được sinh.** Namespace `raw_day4_v3e` được nạp từ thư mục `data/generated/day4_v3e/`, mà `generation_run.json` trong đó ghi: generator `0.2.0`, seed `42`, 5.000 tài khoản, 2025-01-01 đến 2026-01-30, hiệu chỉnh với tỷ lệ mục tiêu 15%, 25%, 35%. Với chừng ấy thông tin cộng với commit code, bộ dữ liệu sinh lại được y hệt.

Bảy bước, từ một con số 33% về tới hạt giống ngẫu nhiên đã sinh ra dữ liệu. Đó là nguyên tắc truy vết hoạt động. Bài tập này cũng làm lộ ra ba **điểm yếu** đáng ghi nhớ. Thứ nhất là commit `-dirty` như đã nói. Thứ hai, toàn bộ thư mục `data/` không nằm trong git (đúng như vậy, vì dữ liệu nặng), nên các bước 4 đến 7 chỉ đi được trên **máy của bạn**; mất ổ đĩa là đứt sợi chỉ ở giữa. Hệ thống thật sẽ đặt các artifact này lên kho lưu trữ dùng chung, ví dụ MinIO. Thứ ba, `quality_report.json` ghi đường dẫn Iceberg dạng tuyệt đối của Windows, nên sang máy khác phải sửa đường dẫn. Nhận ra điểm yếu của chính hệ thống mình là một kỹ năng MLOps quan trọng không kém việc xây nó.

### Tự kiểm tra

1. Với mỗi ngày từ 1 đến 8, nói ra artifact mà ngày đó bàn giao, và ngày nào đọc artifact đó.
2. Vì sao artifact của ngày 5 không được bước nào ở giai đoạn 1 đọc, mà ngày 5 vẫn đáng làm?
3. Trong sơ đồ dòng chảy, mắt xích nào còn dựa vào thao tác tay? Nếu người làm chép nhầm `storageUri` của version 4 nhưng annotation vẫn ghi `"2"`, thì truy vết sẽ sai ở đâu và hậu quả là gì?
4. Tự chạy lại bước 1 và bước 2 của bài truy vết. Bạn có giải thích được vì sao `replaced_version` của version 2 là `None`?
5. Hậu tố `-dirty` trong `git_commit` nghĩa là gì, và vì sao nó làm yếu đi khả năng tái lập của model đang chạy production?

---

## Phần 3. Bản đồ phụ thuộc và cơ chế bên trong

Ở Phần 1 bạn đã thấy thứ tự xây dựng các lớp sinh ra từ chuỗi "lớp sau cần lớp trước". Phần này đi xuống một tầng chi tiết hơn: giữa **từng thành phần cụ thể**, cái gì phải có trước cái gì, và **cơ chế bên trong nào** buộc phải như vậy. Câu "phải cài cert-manager trước KServe" khi học thuộc lòng thì rất dễ quên. Nhưng khi bạn biết bên trong chart KServe có một tài nguyên `Certificate` mà chỉ cert-manager mới dạy được Kubernetes hiểu, thì thứ tự đó trở thành điều hiển nhiên, và bạn tự suy ra được thứ tự cho cả những hệ thống chưa từng gặp.

### 3.1 Năm kiểu phụ thuộc, và mỗi kiểu hỏng theo một cách riêng

Nhìn kỹ mọi quan hệ "X phải có trước Y" trong dự án, bạn sẽ thấy chúng chỉ thuộc về năm kiểu. Mỗi kiểu có một cơ chế riêng, và quan trọng hơn, **khi bị vi phạm thì có một kiểu triệu chứng riêng**. Nhận ra kiểu triệu chứng là đã đoán được một nửa nguyên nhân.

Kiểu thứ nhất là **phụ thuộc địa chỉ**: Y cần gọi tới X qua mạng, nên X phải đang chạy và phải có đường để tới. Ví dụ: MLflow cần Postgres, code trên máy bạn cần MLflow qua port-forward. Khi bị vi phạm, triệu chứng là **treo, hết thời gian chờ, hoặc từ chối kết nối**. Đôi khi chương trình còn tự thử lại nhiều lần trước khi báo lỗi, nên trông như "chạy mãi không xong", đúng như lần bạn chạy lệnh lấy `storageUri` khi chưa mở port-forward.

Kiểu thứ hai là **phụ thuộc từ vựng**: Y được viết bằng những "từ" mà hệ thống chỉ hiểu sau khi X dạy nó. Đó là quan hệ giữa CRD và tài nguyên tuỳ biến. Khi bị vi phạm, triệu chứng là **bị từ chối ngay lập tức**, với thông báo rõ ràng. Đây là kiểu dễ chịu nhất.

Kiểu thứ ba là **phụ thuộc tác nhân**: Y chỉ là một bản khai báo, và phải có một chương trình X (controller) đọc nó và hành động. Khi bị vi phạm, triệu chứng là **được chấp nhận nhưng không có gì xảy ra**. Không lỗi, không cảnh báo, chỉ là im lặng. Đây là kiểu khó nhận ra nhất, vì mọi lệnh đều báo thành công. Bạn đã gặp đúng triệu chứng này khi `apply` InferenceService lúc chưa cài controller KServe: lệnh thành công, cột `READY` trống, và không có Service nào được tạo.

Kiểu thứ tư là **phụ thuộc artifact**: Y cần một thứ do X tạo ra và đã qua cổng kiểm tra, ví dụ bảng feature của run đã PASS, hay version model đã được duyệt. Khi bị vi phạm, triệu chứng thường là **lỗi rõ ràng ở bước đọc**, nếu code được viết để kiểm tra; còn nếu code không kiểm tra, nó sẽ dùng nhầm thứ cũ hoặc thứ chưa được duyệt mà không ai biết. Đó là lý do dự án đặt các cổng kiểm soát ở đúng những chỗ này.

Kiểu thứ năm là **phụ thuộc môi trường**: Y chỉ chạy đúng khi môi trường của nó khớp với môi trường mà X được tạo ra. Ví dụ model chỉ chạy đúng với đúng phiên bản sklearn đã tạo ra nó. Khi bị vi phạm, triệu chứng **nguy hiểm nhất**: mọi thứ khởi động bình thường, báo sẵn sàng, rồi hỏng lúc được dùng, hoặc tệ hơn, chạy ra kết quả sai mà không báo gì. Model LR trên image sklearn 1.7 nạp thành công, báo sẵn sàng, rồi mọi request đều lỗi.

| Kiểu phụ thuộc | Cơ chế | Triệu chứng khi vi phạm | Ví dụ thật trong dự án |
|---|---|---|---|
| Địa chỉ | Gọi qua mạng | Treo, timeout, từ chối kết nối | Lệnh Python chạy mãi khi chưa port-forward |
| Từ vựng | CRD dạy API server loại tài nguyên mới | Bị từ chối ngay, lỗi rõ | `no matches for kind ... ensure CRDs are installed first` |
| Tác nhân | Controller đọc khai báo rồi hành động | Được chấp nhận, rồi im lặng không có gì xảy ra | ISVC có mặt nhưng `READY` trống |
| Artifact | Cần sản phẩm đã qua cổng | Lỗi ở bước đọc, hoặc dùng nhầm âm thầm | `check_run` từ chối run chưa PASS |
| Môi trường | Phải khớp phiên bản lúc tạo | Khởi động được, hỏng hoặc sai lúc dùng | `'LogisticRegression' object has no attribute 'multi_class'` |

### 3.2 Đồ thị phụ thuộc của toàn hệ thống

Đây là toàn bộ quan hệ phụ thuộc trong ngày 1–8, gom vào một đồ thị. Mũi tên `A ──▶ B` đọc là "A phải có trước B". Nhãn trong ngoặc là kiểu phụ thuộc.

```
NỀN CHẠY
  Docker ──▶ cụm kind "lab" ──▶ mọi pod
  Postgres ──(địa chỉ)──▶ MLflow server
  MinIO + bucket "mlflow" ──(địa chỉ, artifact)──▶ MLflow server lưu được model
  image có trong node kind ──(môi trường)──▶ pod khởi động được
  port-forward ──(địa chỉ)──▶ mọi lệnh Python trên máy gọi MLflow/MinIO

CHUỖI DỮ LIỆU
  generator + seed ──▶ 8 Parquet ──▶ bảng Iceberg (catalog + snapshot)
  bảng Iceberg ──(artifact)──▶ run ngày 4 ──(cổng: quality PASS)──▶ current.json
  current.json ──(artifact)──▶ Feast (definitions.py) ──▶ feast apply
  current.json ──(artifact)──▶ train ngày 6

CHUỖI MODEL
  MLflow server ──(địa chỉ)──▶ train ghi run, đăng ký version @staging
  version @staging + tag gate PASS ──(cổng: promote --approve)──▶ alias @production
  alias @production ──(artifact, chép tay)──▶ storageUri trong InferenceService

CHUỖI PHỤC VỤ
  CRD cert-manager ──(từ vựng)──▶ chart KServe (chứa Issuer, Certificate)
  cert-manager chạy ──(tác nhân)──▶ chứng chỉ webhook + CA được tiêm
  CRD KServe ──(từ vựng)──▶ ServingRuntime, InferenceService được lưu
  webhook KServe có chứng chỉ ──(địa chỉ)──▶ apply InferenceService
  controller KServe chạy ──(tác nhân)──▶ InferenceService sinh ra Deployment, Service
  ServingRuntime, Secret, ServiceAccount ──(artifact)──▶ pod predictor đúng cấu hình
  image serving đúng phiên bản ──(môi trường)──▶ model nạp và tính đúng
```

### 3.3 Cơ chế bên trong từng nhóm phụ thuộc

#### Nền chạy

**Postgres phải có trước MLflow** vì MLflow ghi toàn bộ thông tin mô tả (experiment, run, metric, version, alias) vào Postgres. Chart MLflow xử lý thứ tự này bằng hai **init container** chạy trước máy chủ chính: `dbchecker` đợi tới khi kết nối được Postgres, rồi `mlflow-db-migration` tạo hoặc nâng cấp các bảng mà MLflow cần. Nghĩa là nếu Postgres chưa lên, pod MLflow không sập mà **đứng chờ** ở trạng thái `Init`. Cũng vì cần các bảng đúng phiên bản, khi nâng MLflow từ 2.1.1 lên 3.15.2 ở ngày 7, bước migration đã tự cập nhật cấu trúc bảng. Trong [infra/helmfile.yaml](../../infra/helmfile.yaml), khoá `needs` của release MLflow ghi rõ phụ thuộc này, để helmfile cài Postgres và MinIO trước.

**MinIO và bucket `mlflow` phải có trước khi MLflow lưu được model.** Máy chủ MLflow được khởi động với tham số `--default-artifact-root=s3://mlflow/`, tức mọi artifact sẽ nằm trong bucket `mlflow`. Nhưng bucket không tự sinh ra: nó được tạo bởi một **Job** tên `minio-post-job`, chạy lệnh `mc` (công cụ dòng lệnh của MinIO) ngay sau khi chart MinIO cài xong. Đó là lý do có khoá `buckets` trong [minio-values.yaml](../../infra/helm-values/minio-values.yaml). Còn một chi tiết quan trọng: khi bạn log model, **chính code Python trên máy bạn** upload file thẳng lên MinIO, không đi qua máy chủ MLflow. Vì vậy máy bạn cần cả địa chỉ MinIO (`MLFLOW_S3_ENDPOINT_URL`) lẫn mật khẩu, và đó là lý do [registry.py](../../training/registry.py) đặt các biến môi trường này trong hàm `configure()`.

**Image phải có trong node trước khi pod khởi động được.** Kubelet trên node đọc trường `image` của container, tìm trong kho image của node, nếu không có thì tải từ registry. Với `imagePullPolicy: Never`, nó **không** tải, nên thiếu image là pod dừng ở `ErrImageNeverPull`. Với image cần tải mà registry từ chối, pod dừng ở `ImagePullBackOff`. Bạn đã gặp cả hai biến thể: MinIO ở ngày 7 bị quay.io trả 401, và image serving ở ngày 8 phải `kind load` thì mới dùng được.

**Port-forward phải mở trước mọi lệnh Python gọi MLflow hay MinIO.** Địa chỉ `127.0.0.1:5050` trên máy bạn chỉ có ai lắng nghe khi `kubectl port-forward` đang chạy và giữ đường ống tới Service trong cluster. Không có đường ống, kết nối bị từ chối, và thư viện MLflow tự thử lại với thời gian chờ tăng dần, nên lệnh treo vài phút trước khi báo lỗi. Đây là phụ thuộc **lúc chạy**, khác với các phụ thuộc **lúc cài** ở trên: nó phải được thoả mãn **mỗi lần** bạn làm việc, vì port-forward chết khi đóng cửa sổ hay khởi động lại máy.

#### Chuỗi dữ liệu

**Dữ liệu nguồn phải được nạp vào Iceberg trước khi ngày 4 chạy**, và cách ngày 4 tìm thấy dữ liệu là qua **catalog**. Khi [day3_write_iceberg.py](../../scripts/day3_write_iceberg.py) ghi một bảng, nó làm hai việc: ghi các file Parquet và file metadata vào thư mục warehouse, rồi ghi vào catalog (file SQLite) một dòng "bảng `raw_day4_v3e.customer_account` có metadata hiện tại nằm ở đường dẫn này". Ngày 4 không đi tìm file, mà hỏi catalog theo tên bảng, nên chỉ cần tên namespace là đủ. Khi đọc, ngày 4 ghi lại mã snapshot của từng bảng vào `quality_report.json`, đúng như bạn đã thấy ở bài truy vết.

**Run ngày 4 phải PASS và được con trỏ chỉ vào trước khi train.** Phụ thuộc này được **thực thi bằng code**, không chỉ bằng quy ước. Mọi lệnh train đi qua `resolve_run_dir()` để đọc `current.json`, rồi qua `check_run()` trong [training/data.py](../../training/data.py):

```python
def check_run(run_dir: Path) -> dict:
    """Refuse to train on a run that did not pass the Day 4 quality gate."""
    quality = json.loads((run_dir / "quality_report.json").read_text(encoding="utf-8"))
    if quality.get("status") != "PASS":
        raise RuntimeError(f"{run_dir.name}: quality gate is {quality.get('status')}, not PASS")
    weights = json.loads((run_dir / "class_weights.json").read_text(encoding="utf-8"))
    if not weights.get("approved_for_training"):
        raise RuntimeError(f"{run_dir.name}: class_weights.json not approved_for_training")
    ...
```

Đây là ví dụ mẫu của một phụ thuộc artifact được bảo vệ đúng cách: thiếu điều kiện thì dừng hẳn với thông báo rõ, chứ không train tiếp trên dữ liệu chưa được duyệt.

**Feast phụ thuộc vào `current.json` ngay lúc nạp định nghĩa.** [feature_repo/definitions.py](../../feature_repo/definitions.py) đọc `current.json` khi được import, rồi trỏ mỗi feature view vào file Parquet của run đó. Kết quả được ghi vào registry của Feast khi chạy `feast apply`. Hệ quả là khi có run ngày 4 mới, **phải chạy lại `feast apply`**, nếu không registry vẫn trỏ vào file của run cũ. Đây là một phụ thuộc artifact **không** được code tự bảo vệ, mà được ghi thành quy tắc trong [feature_contract.md](../feature_contract.md).

#### Chuỗi model

**MLflow phải chạy trước khi train ở chế độ có theo dõi.** `train.py` gọi `registry.configure()` ngay từ đầu, rồi với mỗi phân khúc gọi MLflow để chấm lại model production và đăng ký version mới. Muốn train không cần MLflow thì dùng `--no-mlflow` (chế độ ngày 6).

**`@staging` và tag gate phải có trước `@production`.** Bước duyệt [promote.py](../../training/promote.py) đọc version mà `@staging` trỏ tới, kiểm tra tag `promotion_gate` là `PASS` hoặc `BASELINE_PASS` và mọi phân khúc đến từ cùng một lần train, rồi mới dời `@production`. Đây là phụ thuộc artifact, cũng được code bảo vệ: thiếu điều kiện thì in `REFUSED` và thoát với mã lỗi.

**`@production` phải có trước InferenceService**, vì `storageUri` trong InferenceService là đường dẫn file của version mà alias trỏ tới. Ở ngày 8, phụ thuộc này được thoả mãn **bằng tay**: bạn tra và chép. Không có cơ chế nào đảm bảo hai bên khớp nhau sau đó, và đây chính là lỗ hổng mà ngày 9–10 sẽ bịt.

#### Chuỗi phục vụ

Đây là chuỗi dài nhất và nhiều kiểu phụ thuộc đan xen nhất, nên đi chậm từng mắt xích.

**CRD phải có trước tài nguyên tuỳ biến.** Khi bạn `apply` một file, API server tra trường `apiVersion` và `kind` trong danh mục các loại tài nguyên nó biết. Loại nào chưa được CRD đăng ký thì không có chỗ để lưu, nên bị từ chối ngay. Thông báo thật khi gửi một loại không tồn tại:

```
error: resource mapping not found for name: "t" namespace: "serving" from "fake.yaml":
no matches for kind "InferenceServiceX" in version "serving.kserve.io/v1beta1"
ensure CRDs are installed first
```

**cert-manager phải có trước KServe**, và có tới hai lý do nằm ở hai kiểu phụ thuộc khác nhau. Lý do thứ nhất là **từ vựng**: chart `kserve-resources` chứa một tài nguyên `Issuer` tên `selfsigned-issuer` và một `Certificate` tên `serving-cert`. Hai loại này thuộc nhóm `cert-manager.io`, chỉ tồn tại khi CRD của cert-manager đã được cài; thiếu chúng thì Helm không cài được chart KServe. Lý do thứ hai là **tác nhân**: khai báo `Certificate` chỉ là mong muốn; phải có controller của cert-manager đọc nó, sinh ra chứng chỉ thật, và lưu vào Secret `kserve-webhook-server-cert`. Trên cluster của bạn, chứng chỉ đó mang tên `kserve-webhook-server-service.kserve.svc`, tự ký, và **có hạn 90 ngày, từ 20/10/2026 đến 18/01/2027**. cert-manager sẽ tự gia hạn trước ngày đó. Nếu chứng chỉ được tạo bằng tay, đúng ngày 18/01/2027 mọi lệnh `apply` InferenceService sẽ bắt đầu lỗi.

Còn một tác nhân thứ ba, ít người để ý: **cainjector**. API server chỉ chịu nói chuyện với webhook nếu nó tin CA đã ký chứng chỉ của webhook. Danh sách CA đáng tin của mỗi webhook nằm trong trường `caBundle` của cấu hình webhook. Các cấu hình webhook của KServe mang annotation `cert-manager.io/inject-ca-from: kserve/serving-cert`, và cainjector thấy annotation đó thì chép CA của `serving-cert` vào `caBundle`. Trên cluster của bạn, trường đó đã được điền. Thiếu bước này, webhook có chứng chỉ nhưng API server không tin nó, và mọi `apply` đều lỗi `failed calling webhook`.

**Webhook KServe phải sẵn sàng trước khi apply InferenceService.** API server gửi mỗi InferenceService tới webhook để kiểm tra trước khi lưu. Cần hiểu đúng webhook kiểm tra **cái gì**. Nó chặn các lỗi về **hình thức**: ví dụ tên `Loan_AU` bị chặn ngay vì tên Kubernetes chỉ được chứa chữ thường, số và dấu gạch ngang:

```
The InferenceService "Loan_AU" is invalid: metadata.name: Invalid value: "Loan_AU":
a lowercase RFC 1123 subdomain must consist of lower case alphanumeric characters, '-' or '.' ...
```

Nhưng nó **không** kiểm tra các tài nguyên khác có tồn tại hay không. Một InferenceService trỏ tới runtime `khong-ton-tai` vẫn được chấp nhận và lưu bình thường. Lỗi chỉ xuất hiện sau đó, khi controller cố dựng hạ tầng, và nằm trong **Events** chứ không nằm trong cột `READY`:

```
InternalError: No ServingRuntimes or ClusterServingRuntimes with the name: khong-ton-tai
```

Bài học rộng hơn: **cổng ở cửa chỉ bắt được lỗi hình thức**. Lỗi về quan hệ giữa các tài nguyên chỉ lộ ra khi có tác nhân thực sự làm việc, nên khi `READY` không lên, luôn đọc thêm Events bằng `kubectl describe` hoặc `kubectl get events`.

**Controller KServe phải chạy để InferenceService có tác dụng.** Đây là phụ thuộc tác nhân thuần tuý. Có CRD, InferenceService được lưu vào etcd, nhưng không có vòng đối soát nào đọc nó. Đây chính là tình huống bạn đã gặp: `kserve-crd` đã cài, `kserve` (controller) chưa cài, và InferenceService nằm im với cột `READY` trống.

**ServingRuntime, Secret và ServiceAccount phải có trước khi pod predictor chạy đúng.** Khi dựng pod, controller ghép thông tin từ ba nơi. Từ ServingRuntime, nó lấy image, lệnh khởi động và biến môi trường. Từ ServiceAccount mà InferenceService khai báo, nó tìm ra Secret được gắn vào, rồi đọc các annotation `serving.kserve.io/s3-*` để biết địa chỉ MinIO và đưa mật khẩu vào init container `storage-initializer` dưới dạng biến môi trường. Thiếu runtime thì như trên, không có pod nào. Thiếu Secret hay sai mật khẩu thì pod có, nhưng kẹt ở init container vì không tải được model.

**Image serving phải khớp môi trường lúc train.** Đây là phụ thuộc môi trường, mắt xích cuối và nguy hiểm nhất, đã phân tích kỹ trong bài ngày 8: pickle chỉ lưu dữ liệu của object, code của class được lấy từ thư viện đang cài. Image `seldonio/mlserver:1.7.1` có sklearn 1.7.0, model được tạo bằng sklearn 1.9.0, nên nạp được nhưng tính thì hỏng. Không có cổng tự động nào bắt được lỗi này lúc deploy; chỉ có [day8_predict_check.py](../../scripts/day8_predict_check.py), so kết quả với model gốc, mới bắt được.

### 3.4 Thứ tự dựng từ máy trắng, và thứ tự gỡ

Gom đồ thị lại, thứ tự dựng toàn bộ hệ thống ngày 1–8 trên một máy trống là duy nhất về cơ bản, chỉ trừ vài bước độc lập có thể đổi chỗ cho nhau. Mỗi bước dưới đây là điều kiện của các bước sau nó:

1. Bật Docker, tạo cụm kind. Mọi thứ khác chạy trong đó.
2. Nạp image MinIO vào node, chạy `helmfile sync`: Postgres và MinIO trước, rồi MLflow (helmfile tự lo nhờ `needs`). Redis có thể lên bất kỳ lúc nào vì chưa ai dùng.
3. Mở port-forward. Từ đây code trên máy mới gọi được MLflow và MinIO.
4. Sinh dữ liệu (ngày 2), nạp vào Iceberg (ngày 3), chạy ngày 4 tới khi PASS và có `current.json`. Bước này không phụ thuộc cluster, có thể làm song song với bước 1–3.
5. `feast apply` và kiểm tra parity (ngày 5), sau khi có `current.json`.
6. Train có MLflow (ngày 6–7), sau khi có cả `current.json` lẫn MLflow.
7. Duyệt để có `@production`.
8. Cài cert-manager, đợi ba pod sẵn sàng.
9. Cài CRD KServe, rồi controller KServe, đợi controller sẵn sàng.
10. Build image serving, nạp vào node. Bước này có thể làm sớm hơn, bất kỳ lúc nào sau bước 1.
11. Apply namespace, Secret và ServiceAccount, ServingRuntime, cuối cùng là InferenceService với `storageUri` của version `@production`.
12. Kiểm chứng bằng `day8_predict_check.py`.

Thứ tự **gỡ** là đảo ngược, và có những chỗ làm sai sẽ để lại rác khó dọn. InferenceService phải xoá **trước** khi gỡ controller KServe, để controller kịp dọn Deployment và Service mà nó đã tạo. Gỡ CRD KServe thì **mọi** InferenceService và ServingRuntime trong cluster bị xoá theo, nên đây là bước nguy hiểm nhất. Còn cert-manager có một bẫy: lệnh `helm uninstall` **không** xoá CRD của nó (chart cố ý giữ lại để tránh xoá nhầm chứng chỉ), nên muốn sạch hoàn toàn phải xoá các CRD `*.cert-manager.io` bằng tay. Đó là việc mình đã làm khi dọn cluster cho bạn cài lại từ đầu ở ngày 8.

### 3.5 Kiểm tra một thành phần đã sẵn sàng chưa

Trước mỗi bước, thay vì đoán, hãy kiểm tra điều kiện của nó. Bảng sau cho lệnh kiểm tra và kết quả mong đợi của từng thành phần:

| Thành phần | Lệnh kiểm tra | Sẵn sàng khi |
|---|---|---|
| Cụm kind | `kubectl get nodes` | node báo `Ready` |
| Dịch vụ nền | `kubectl get pods -n mlops` | 4 pod `1/1 Running` |
| Port-forward | `curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:5050/health` | `200` |
| Run ngày 4 | đọc `status` trong `quality_report.json` của run trong `current.json` | `PASS` |
| Alias production | `python -m training.promote --usecase <uc>` (không `--approve`) | in ra version `@production` |
| cert-manager | `kubectl get pods -n cert-manager` | 3 pod `1/1 Running` |
| Chứng chỉ webhook | `kubectl get certificate -n kserve` | `serving-cert` báo `READY True` |
| Controller KServe | `kubectl get pods -n kserve` | `kserve-controller-manager` `2/2 Running` |
| Image trong node | `docker exec lab-control-plane crictl images` | có dòng `mlserver-mlflow` |
| InferenceService | `kubectl get isvc -n serving` | `READY True`; nếu không, đọc `kubectl describe isvc` phần Events |

### Tự kiểm tra

1. Kể năm kiểu phụ thuộc, và với mỗi kiểu nói triệu chứng điển hình khi bị vi phạm. Vì sao kiểu "tác nhân" khó phát hiện hơn kiểu "từ vựng"?
2. Giải thích bằng cơ chế bên trong, không học thuộc: vì sao phải cài cert-manager trước KServe? Có mấy lý do, mỗi lý do thuộc kiểu phụ thuộc nào?
3. Vì sao một InferenceService trỏ tới runtime không tồn tại vẫn được chấp nhận khi `apply`? Lỗi sẽ hiện ở đâu?
4. Port-forward khác các phụ thuộc như "Postgres trước MLflow" ở điểm nào, và điều đó ảnh hưởng gì tới thói quen làm việc hằng ngày của bạn?
5. Khi có một run ngày 4 mới được duyệt, những bước nào phía sau phải chạy lại, và bước nào được code tự bảo vệ, bước nào chỉ dựa vào quy tắc?
6. Nếu phải gỡ toàn bộ phần phục vụ để cài lại, bạn sẽ gỡ theo thứ tự nào, và vì sao không được gỡ CRD trước?

---

## Phần 4. Tư duy tổ chức code

Các phần trước giúp bạn thấy hệ thống từ trên cao. Phần này đi vào nơi bạn thấy rối nhất: chính các file Python. Mục tiêu không phải giải thích từng dòng, mà là cho bạn **một cách nhìn** để khi mở bất kỳ file nào, bạn biết nó đang làm loại việc gì, nên đọc từ đâu, và vì sao nó được viết tách ra như vậy. Cuối phần, mình chỉ ra những chỗ trong chính dự án của bạn chưa tuân theo cách nhìn này, vì nhận ra code chưa tốt cũng quan trọng như viết code tốt.

### 4.1 Vì sao code dễ thành "loạn"

Mọi dòng code, xét đến cùng, chỉ làm một trong hai loại việc. Loại thứ nhất là **tính toán**: nhận vào vài giá trị và trả ra một giá trị khác, ví dụ so AUC của model mới với model cũ để ra quyết định "đạt" hay "không đạt". Loại việc này có một tính chất rất quý: cùng đầu vào luôn cho cùng đầu ra, không phụ thuộc thời điểm chạy hay máy nào chạy. Loại thứ hai là **tác động**: đọc một file, ghi một bảng, gọi MLflow qua mạng, in ra màn hình, lấy giờ hiện tại, sinh số ngẫu nhiên. Loại này phụ thuộc vào thế giới bên ngoài: file có tồn tại không, server có đang chạy không, bây giờ là mấy giờ. Trong lập trình, việc tác động lên hay phụ thuộc vào thế giới bên ngoài gọi là **side effect** (tác dụng phụ), và đoạn code không có side effect gọi là **hàm thuần** (pure function).

Code trở nên "loạn" khi hai loại việc này **trộn lẫn trong cùng một hàm**. Hãy tưởng tượng hàm `should_promote()` của ngày 7 được viết theo cách tự nhiên nhất: hàm tự gọi MLflow để lấy metric của model production, tự nạp model mới, tự chấm điểm, rồi tự so sánh. Đọc thì thấy gọn, nhưng hậu quả xuất hiện ngay khi bạn muốn kiểm tra nó. Muốn test trường hợp "model mới tụt AUC đúng 0,03", bạn phải dựng một máy chủ MLflow, đăng ký sẵn hai model có đúng những con số đó, rồi mới gọi được hàm. Một phép so sánh mất vài micro-giây bây giờ cần cả hạ tầng để kiểm tra. Hơn nữa, khi test thất bại, bạn không biết lỗi do **luật so sánh** sai hay do **MLflow** trả dữ liệu lạ. Và nếu ngày mai muốn dùng lại luật đó ở chỗ khác, ví dụ trong vòng đối soát ngày 10, bạn phải kéo theo cả phần gọi MLflow.

Cách chữa là **tách theo loại việc**. Luật so sánh được viết thành hàm thuần, nhận vào các con số và trả ra quyết định. Phần lấy con số từ MLflow được viết riêng. Một đoạn code thứ ba ghép hai phần lại. Đó chính xác là cách dự án làm: [training/promotion.py](../../training/promotion.py) chứa luật, [training/registry.py](../../training/registry.py) lấy số từ MLflow, [training/train.py](../../training/train.py) ghép lại. Kết quả đo được trên máy bạn: **15 test của promotion gate chạy hết trong 0,036 giây**, không cần MLflow, không cần cluster, không cần dữ liệu thật. Mỗi lần sửa luật, bạn biết ngay nó đúng hay sai.

Nói gọn, "loạn" không phải do code dài hay nhiều file. Nó do **mỗi đoạn code phụ thuộc vào quá nhiều thứ**. Tổ chức code tốt là sắp xếp sao cho phần quan trọng nhất (luật, phép tính) phụ thuộc vào ít thứ nhất.

### 4.2 Năm loại code, mỗi loại một quy tắc

Từ ý tưởng "tách theo loại việc", mọi file trong dự án rơi vào năm loại. Mỗi loại có một vai trò và một quy tắc riêng. Khi bạn biết một file thuộc loại nào, bạn biết luôn nên kỳ vọng gì ở nó.

**Loại 1: Cấu hình.** Đây là dữ liệu mô tả "muốn làm gì", không chứa logic. Ví dụ [training/usecases.yaml](../../training/usecases.yaml) liệt kê ba use case, nhãn, danh sách feature được phép dùng, tham số của LightGBM và ngưỡng của promotion gate. Các hằng số đầu file [generate_all.py](../../data_generation/generate_all.py) như `SEED = 42`, `DEFAULT_INTERCEPTS` cũng là cấu hình, chỉ là viết thẳng trong Python. Quy tắc của loại này: **thay đổi hành vi bằng cách sửa cấu hình, không phải sửa code**. Muốn thêm một feature vào model, bạn sửa allowlist trong yaml chứ không sửa `train.py`. Quy tắc phụ: cấu hình phải được **kiểm tra ngay khi nạp**, để lỗi lộ ra sớm. Hàm `validate()` trong [training/config.py](../../training/config.py) làm đúng việc này: nó từ chối ngay mọi allowlist chứa tên nhãn, tên khoá hay cột `split`, trước khi có một dòng dữ liệu nào được đọc.

**Loại 2: Logic thuần.** Đây là trái tim của hệ thống: các luật và phép tính. [training/promotion.py](../../training/promotion.py) (luật gate) và [training/evaluate.py](../../training/evaluate.py) (metric, chọn ngưỡng, recall theo mức cảnh báo) là hai ví dụ rõ nhất. Hàm `check_splits()` trong `data.py` và `check()` trong `promote.py` cũng thuộc loại này. Quy tắc: **không import thư viện chạm ra ngoài** (MLflow, boto3, kubernetes), không đọc ghi file, không in. Nhìn phần import của `evaluate.py` sẽ thấy chỉ có `numpy` và `sklearn.metrics`. Nhờ vậy loại này test được nhanh, và là nơi bạn nên viết nhiều test nhất.

**Loại 3: Cửa ra thế giới ngoài.** Đây là code làm việc với những thứ nằm ngoài chương trình: ổ đĩa, MLflow, MinIO, Iceberg. [training/registry.py](../../training/registry.py) là cửa ra tới MLflow; [training/data.py](../../training/data.py) là cửa ra tới các file Parquet và JSON của ngày 4. Quy tắc: **chỉ lo việc lấy vào và đưa ra, không chứa luật nghiệp vụ**. `registry.py` lấy metric của model production và đưa cho `evaluate_gate()` quyết định, chứ không tự quyết. Lợi ích là khi thay công cụ, ví dụ đổi MLflow sang một registry khác, chỉ có một file phải viết lại, còn luật vẫn giữ nguyên.

**Loại 4: Điểm chạy.** Đây là nơi bạn gõ lệnh: hàm `main()` đọc tham số dòng lệnh, rồi gọi các phần khác theo đúng thứ tự. [training/train.py](../../training/train.py) và [training/promote.py](../../training/promote.py) là điểm chạy của ngày 6–7. Quy tắc: **chỉ ghép, không tính**. Điểm chạy nên đọc giống một mục lục: bước 1 nạp cấu hình, bước 2 kiểm tra run, bước 3 với mỗi phân khúc thì train và đăng ký, bước 4 chạy gate. Một quy tắc nữa ít được để ý: điểm chạy phải **báo kết quả bằng mã thoát** (exit code). Script ngày 4 trả `0` khi PASS và `2` khi quality gate FAIL; `promote.py` trả `1` khi từ chối duyệt. Đây là hợp đồng với bất kỳ thứ gì gọi script này, và ở ngày 11 Airflow sẽ dựa vào mã thoát để biết một bước thành công hay thất bại.

**Loại 5: Kiểm chứng.** Gồm các test trong [tests/](../../tests/) và các script `verify`, `check`. Quy tắc: **kiểm chứng không được là đường đi bắt buộc của hệ thống**. Xoá `day8_predict_check.py` thì model vẫn phục vụ, chỉ mất bằng chứng. Ngược lại, kiểm chứng phải dùng **dữ liệu nhỏ, tự dựng**, để chạy nhanh và cho cùng kết quả mỗi lần. Hàm `synthetic()` trong [tests/test_training.py](../../tests/test_training.py) tạo vài nghìn dòng giả, trong đó nhãn được sinh **có chủ đích** từ hai feature đầu tiên, để test biết chắc model phải học được tín hiệu đó.

| Loại | Vai trò | Quy tắc chính | Ví dụ |
|---|---|---|---|
| Cấu hình | Mô tả "muốn gì" | Đổi hành vi bằng sửa cấu hình; kiểm tra ngay khi nạp | `usecases.yaml`, hằng số đầu `generate_all.py` |
| Logic thuần | Luật, phép tính | Không chạm bên ngoài; test nhiều nhất | `promotion.py`, `evaluate.py`, `check_splits()` |
| Cửa ra | Lấy vào, đưa ra | Không chứa luật nghiệp vụ | `registry.py`, `data.py` |
| Điểm chạy | Ghép các phần | Chỉ ghép; báo kết quả bằng mã thoát | `train.py`, `promote.py`, các `main()` |
| Kiểm chứng | Chứng minh đúng | Không nằm trên đường đi bắt buộc; dữ liệu nhỏ tự dựng | `tests/`, `day8_predict_check.py` |

### 4.3 Hướng phụ thuộc: package `training/` làm ví dụ

Biết năm loại rồi, câu hỏi tiếp theo là **chúng được phép gọi nhau theo hướng nào**. Quy tắc chung rất đơn giản: **phần "bẩn" (chạm bên ngoài) được phép gọi phần "sạch" (thuần), không bao giờ ngược lại**. Logic thuần là tầng đáy; cửa ra và điểm chạy đứng trên và dùng nó. Đây là sơ đồ import thật của package `training/` (mũi tên `A ──▶ B` nghĩa là A import B):

```
                    promote.py ─────────┐                (điểm chạy, ngày 7)
                         │              │
   train.py ─────────────┼──────┐       │                (điểm chạy, ngày 6-7)
     │   │   │           ▼      ▼       ▼
     │   │   └──▶ registry.py ─────▶ promotion.py         (cửa ra MLflow  ─▶ logic thuần)
     │   │             │   └──────▶ evaluate.py           (               ─▶ logic thuần)
     │   └──▶ models.py      │                            (dựng model)
     └──▶ data.py ◀──────────┘                            (cửa ra file)
              │
              ▼
          config.py ◀── usecases.yaml                      (cấu hình)
```

Hãy nhìn vào hai điểm. Thứ nhất, `promotion.py` và `evaluate.py` nằm ở **đáy**, không import gì của MLflow; bất kỳ ai cũng dùng được chúng. Thứ hai, `train.py` **không import `registry.py` ở đầu file**. Nó chỉ import bên trong hàm `run()`, và chỉ khi chạy ở chế độ có theo dõi:

```python
if track:
    from training import registry
    from training.promotion import load_gate_config
    client, gate_cfg = registry.configure(), ...
```

Đây là một kỹ thuật nhỏ có tên **import trễ** (lazy import). Nhờ nó, lệnh `python -m training.train --no-mlflow` chạy được ngay cả khi máy chủ MLflow không tồn tại, và các test của ngày 6 không đụng tới MLflow. Phụ thuộc vào thế giới bên ngoài chỉ xuất hiện khi thực sự cần.

### 4.4 Các mẫu lặp lại trong code của bạn

Đọc kỹ dự án, bạn sẽ thấy một số cách giải quyết xuất hiện ở nhiều nơi. Chúng là những **mẫu** (pattern) đáng mang theo sang mọi dự án sau, nên mỗi mẫu được giới thiệu cùng vị trí thật của nó.

**Thư mục run cộng con trỏ.** Mỗi lần chạy ngày 4 hay ngày 6 không ghi đè lên kết quả cũ, mà tạo một thư mục mới đặt tên theo thời điểm, ví dụ `day4_runs/20261007T095923177784/`. Một file nhỏ (`current.json`) trỏ tới run đang được dùng. Nhờ vậy mọi kết quả cũ còn nguyên để so sánh và truy vết, và việc "chuyển sang run mới" chỉ là sửa con trỏ. Đây là nguyên tắc tách mong muốn khỏi thực tế, thể hiện bằng code.

**Ghi con trỏ sau cùng.** Trong hàm `run()` của [day4_feature_engineering.py](../../scripts/day4_feature_engineering.py), thứ tự là: kiểm tra nguồn, tính feature, chạy quality gate, ghi mọi artifact, **đọc lại** từng bảng Iceberg để so với file Parquet vừa ghi, ghi báo cáo, và chỉ **dòng cuối cùng** mới cập nhật `current.json`. Nếu chương trình chết ở bất kỳ bước nào trước đó, con trỏ vẫn chỉ vào run cũ đã được duyệt, và không bước nào phía sau dùng nhầm một run ghi dở. Đây là cách đơn giản để làm một thao tác gồm nhiều bước trông như "trọn vẹn hoặc không có gì".

**Kết quả có cấu trúc bằng `dataclass`.** Thay vì trả về một bộ giá trị khó nhớ thứ tự, hàm trả về một object có tên trường. `SegmentResult` trong `train.py` gom model, metric và lựa chọn của một phân khúc; `GateDecision` trong `promotion.py` gom quyết định, trạng thái và lý do. Đọc `decision.status` dễ hiểu hơn nhiều so với `result[1]`.

**Quyết định kèm lý do.** Promotion gate không chỉ trả `True` hay `False`. `evaluate_gate()` trả về trạng thái (`PASS`, `BASELINE_PASS`, `FAIL`) cùng một câu lý do cho từng phân khúc, ví dụ "auc 0.8000 vs prod 0.7714 (ok), recall 0.5100 vs prod 0.4670 (ok)". Lý do này được ghi vào tag của version trong MLflow. Khi một model bị từ chối, người vận hành biết ngay vì sao mà không cần chạy lại gì. Mọi cổng kiểm soát nên được viết theo cách này.

**Kiểm tra sớm, thoát sớm.** Thay vì lồng nhiều tầng `if`, hàm kiểm tra các trường hợp xấu trước và dừng ngay, phần còn lại của hàm chỉ còn trường hợp bình thường. `check_run()` trong `data.py` là ví dụ: run chưa PASS thì ném lỗi ngay ở dòng đầu. Kỹ thuật này có tên **guard clause**.

**Tách `run()` khỏi `main()`.** Trong `train.py`, hàm `main()` chỉ đọc tham số dòng lệnh rồi gọi `run(...)`. Mọi công việc thật nằm trong `run()`, nhận tham số Python bình thường. Nhờ đó test có thể gọi thẳng `run(...)` với một thư mục dữ liệu giả, và Airflow ở ngày 11 cũng có thể gọi nó mà không phải giả lập dòng lệnh.

**Luồng ngẫu nhiên độc lập.** Trong [generate_all.py](../../data_generation/generate_all.py), mỗi tài khoản có **bốn** bộ sinh số ngẫu nhiên riêng cho giao dịch, dòng tiền, số dư và chiến dịch, mỗi bộ được khởi tạo từ `SeedSequence([seed, mã tài khoản, số thứ tự])`. Lý do được ghi ngay trong comment: thêm hay bớt chiến dịch **không được** làm thay đổi chuỗi số ngẫu nhiên của giao dịch. Nếu dùng chung một bộ sinh, chỉ cần thêm một lần rút số ở phần chiến dịch là toàn bộ giao dịch phía sau thay đổi theo, và không thể so sánh hai phiên bản dữ liệu. Đây là cách giữ tái lập khi code tiến hoá.

### 4.5 Bản đồ đọc hai file lớn nhất

Hai file sau là nơi dễ lạc nhất, vì chúng dài và làm nhiều việc. Với file dài, đừng đọc từ trên xuống. Hãy tìm **hàm điều phối** trước, vì nó đóng vai mục lục, rồi mới đọc các hàm nó gọi.

**[scripts/day4_feature_engineering.py](../../scripts/day4_feature_engineering.py) (khoảng 600 dòng) và [scripts/day4_features.sql](../../scripts/day4_features.sql).** Bắt đầu từ hàm `run()` (khoảng dòng 416), đọc nó như một danh sách các bước:

1. Mở DuckDB, đặt múi giờ `Asia/Ho_Chi_Minh`, mở catalog Iceberg.
2. Với mỗi bảng nguồn: đọc **snapshot hiện tại** từ Iceberg vào DuckDB và ghi lại mã snapshot.
3. `validate_sources()`: kiểm tra dữ liệu nguồn. Không đạt thì ghi `source_validation.json` và **trả 2**, không tạo gì thêm.
4. `normalize()`: chuẩn hoá dữ liệu nguồn thành các bảng trung gian (sự kiện margin hợp lệ, giao dịch theo ngày địa phương…).
5. `build()`: chạy toàn bộ file SQL. Đây là nơi feature và nhãn được tính.
6. `assess()`: **quality gate**, chạy 90 phép kiểm tra. Không đạt thì ghi `rejected_quality_report.json` và trả 2.
7. Ghi từng bảng đầu ra (định nghĩa trong `output_queries()`) ra Parquet và Iceberg, rồi đọc lại để xác minh.
8. Ghi `usecase_registry.json`, `class_weights.json`, `quality_report.json`, báo cáo Markdown.
9. Cuối cùng mới ghi `current.json` và `source_current.json`.

Phần đầu file (dòng 25–70) là **hợp đồng** viết bằng code: `FEATURE_CONTRACT = "day4-v5"`, các nhóm feature (`GROUPS`), khoá chính của từng bảng nguồn, và schema mong đợi. Các hàm nhỏ như `scalar()`, `records()`, `write_json()` chỉ là tiện ích, bỏ qua được.

File SQL được đọc theo thứ tự **xây từ dưới lên**: mỗi câu `CREATE TABLE` tạo một bảng dựa trên các bảng trước. `daily_trades` và `daily_events` gom giao dịch và sự kiện theo ngày. `panel_base` nối thành một "tấm lưới" mỗi tài khoản mỗi ngày một dòng. `panel` thêm số ngày vượt hạn mức liên tiếp. `windowed` tính các cửa sổ thời gian: 7 ngày và 30 ngày **về trước** (feature), và 1–30 ngày **về sau** (dùng cho nhãn). `scoring_features` là feature cho mọi ngày, không có nhãn. `snapshots` nối feature với nhãn và gán `split`. `candidate` giữ lại các dòng có split. `campaign_candidate` là dữ liệu cho bài toán chiến dịch. Cuối cùng là các bảng nhãn cho Feast. Khi đọc SQL, hãy luôn hỏi: **cột này nhìn về quá khứ hay về tương lai của ngày D?** Feature chỉ được nhìn về quá khứ; chỉ nhãn được nhìn về tương lai.

**[data_generation/generate_all.py](../../data_generation/generate_all.py) (khoảng 330 dòng).** Bắt đầu từ `main()` ở cuối file: đọc tham số, nạp kết quả hiệu chỉnh (chỉ chấp nhận khi `status` là `PASS`), sinh tài khoản, sinh giá, gọi `generate_events()`, rồi ghi tám file. Bảng nắm giữ danh mục được ghi **theo từng lô** vì có khoảng 20 triệu dòng, không thể giữ hết trong RAM. Sau đó đọc `generate_events()`: một vòng lặp qua từng tài khoản, mỗi tài khoản lại lặp qua từng ngày, mô phỏng giao dịch, dòng tiền margin, số dư và chiến dịch theo các xác suất. Phần đầu file là các hằng số đã được hiệu chỉnh, và các hàm nhỏ như `sigmoid()`, `status_at()`.

### 4.6 Quy trình đọc một file lạ

Gom các ý trên thành bốn bước, áp dụng cho bất kỳ file Python nào:

Bước một, **đoán loại file từ tên và phần import**. Import `mlflow`, `boto3`, `pyiceberg` nghĩa là cửa ra. Chỉ import `numpy`, `sklearn.metrics` nghĩa là logic thuần. Có `argparse` và hàm `main()` nghĩa là điểm chạy. Bước hai, **đọc docstring đầu file**. Trong dự án, gần như mọi file đều mở đầu bằng vài dòng mô tả việc nó làm, cách chạy, và điều gì xảy ra khi thất bại. Bước ba, **tìm điểm vào**: hàm `main()`, hàm `run()`, hay các hàm không có dấu gạch dưới đầu tên (hàm công khai). Bước bốn, **lần theo các hàm được gọi**, theo chiều sâu chỉ khi cần. Phần lớn thời gian, đọc tên hàm và docstring của nó là đủ để biết nó làm gì.

Thử áp bốn bước vào [scripts/day5_feast_check.py](../../scripts/day5_feast_check.py), một file bạn chưa đọc kỹ. Phần import có `feast` và `pandas`, nên đây là một file chạm bên ngoài. Docstring liệt kê sáu phép kiểm tra và nói file thoát với mã 1 nếu có kiểm tra nào thất bại, nên đây là một script kiểm chứng. Điểm vào là `main()`. Phần còn lại là các hàm phục vụ từng phép kiểm tra. Chỉ sau vài phút, bạn đã biết file này làm gì và nằm ở đâu trong hệ thống, mà chưa cần hiểu từng dòng.

### 4.7 Nợ kỹ thuật của chính dự án

Không dự án nào sạch hoàn toàn, và nhận ra chỗ chưa tốt là một kỹ năng. Dưới đây là những chỗ trong dự án **vi phạm** các quy tắc ở trên. Chúng không phải lỗi phải sửa ngay; nhưng khi gặp, bạn nên biết vì sao chúng đáng chú ý.

Hàm `run()` của ngày 4 dài khoảng 95 dòng và trộn cả ba loại việc: đọc Iceberg, ra quyết định qua cổng, ghi kết quả. Đáng chú ý hơn, nó **chứa cứng** nội dung `usecase_registry.json`, mô tả nhãn và dataset của ba use case, trong khi [training/usecases.yaml](../../training/usecases.yaml) cũng mô tả đúng những điều đó. Hai nguồn sự thật cho cùng một thông tin là chỗ dễ lệch nhau nhất: đổi tên nhãn ở một nơi mà quên nơi kia.

Hàm `build()` chạy file SQL bằng cách **cắt chuỗi theo dấu chấm phẩy**. Cách này chạy tốt chừng nào trong comment hay chuỗi ký tự của SQL không có dấu `;`. Một ngày ai đó viết comment có dấu chấm phẩy, file SQL sẽ bị cắt sai mà không có thông báo rõ ràng.

[feature_repo/definitions.py](../../feature_repo/definitions.py) đọc `current.json` **ngay khi được import**. Import một module đáng lẽ không nên có tác dụng phụ; ở đây chỉ cần `import` là đã phụ thuộc vào một file trên đĩa. Đó là lý do test của Feast phải đặt biến môi trường `FEAST_RUN_DIR` trước khi import.

`registry.configure()` thay đổi **trạng thái toàn cục** của chương trình: đặt biến môi trường và đổi bảng mã của màn hình, kèm mật khẩu MinIO viết sẵn trong code làm giá trị mặc định. Cho môi trường học thì chấp nhận được, nhưng ở hệ thống thật, mật khẩu phải đến từ bên ngoài (biến môi trường, Secret), không bao giờ nằm trong code.

Hàm `plan()` trong `promote.py` gọi `SystemExit` khi không có `@staging`. Thoát chương trình là việc của điểm chạy; một hàm hỗ trợ nên ném lỗi và để `main()` quyết định có thoát hay không. Vi phạm nhỏ, nhưng nó làm hàm khó dùng lại từ chỗ khác, ví dụ từ deployer ngày 9.

Cuối cùng, `train.run()` có ba khối `if track:` rải ở ba chỗ khác nhau. Khi thêm chức năng thứ tư cần MLflow, rất dễ quên một khối. Một cách tốt hơn là gom toàn bộ phần theo dõi vào một object riêng, và trong chế độ không theo dõi thì dùng một object "không làm gì".

### Tự kiểm tra

1. Giải thích bằng lời của bạn: side effect là gì, và vì sao trộn tính toán với side effect trong cùng một hàm làm code khó test?
2. Đặt các file sau vào đúng loại trong năm loại, kèm lý do: `config.py`, `data.py`, `models.py`, `day1_verify.py`, `feature_repo/definitions.py`.
3. Vì sao `promotion.py` không được import `mlflow`? Nếu ai đó thêm một dòng `import mlflow` vào đó, điều gì sẽ xấu đi, dù code vẫn chạy?
4. Trong hàm `run()` của ngày 4, vì sao `current.json` được ghi ở dòng cuối cùng chứ không phải ngay sau khi tính xong feature?
5. Áp quy trình bốn bước vào [training/promote.py](../../training/promote.py): file này thuộc loại gì, điểm vào ở đâu, và nó gọi những hàm nào của file khác?
6. Chọn một chỗ nợ kỹ thuật ở mục 4.7 và đề xuất cách sửa. Việc sửa đó giúp ích gì cho ngày 9–11?

---

## Phần 5. Tư duy YAML: từ bản chất đến từng dòng

Dự án có mười mấy file YAML, và chúng trông na ná nhau: các dòng `tên: giá trị`, thụt lề, gạch đầu dòng. Nhưng file thì do code Python của bạn đọc, file thì do Helm đọc, file thì do Kubernetes đọc, và cùng một chữ như `image` hay `resources` mang ý nghĩa khác nhau ở mỗi nơi. Phần này đi từ bản chất của YAML, qua bốn "họ" YAML trong dự án, rồi mổ xẻ từng dòng của các file quan trọng nhất. Mỗi dòng được trả lời ba câu: **nó nghĩa là gì**, **ai đọc nó**, và **bên trong hệ thống chuyện gì xảy ra với nó**. Các kết quả "bên trong" trong phần này đều lấy thật từ cluster của bạn.

### 5.1 Bản chất: YAML chỉ là dữ liệu

YAML không phải một ngôn ngữ lập trình. Nó không có `if`, không có vòng lặp, không chạy được. Nó chỉ là **một cách viết dữ liệu ra văn bản** để con người đọc và sửa cho dễ. Mọi file YAML, dù dài đến đâu, đều được dựng từ đúng ba loại khối: **từ điển** (map, các cặp `khoá: giá trị`), **danh sách** (list, các phần tử có thứ tự), và **giá trị đơn** (scalar: chuỗi, số, true/false, null). Ba loại này lồng vào nhau tuỳ ý. Đó là lý do YAML tương đương với JSON: mọi file YAML bạn viết đều có thể chuyển thành JSON mà không mất gì, và thực tế Kubernetes làm đúng như vậy trước khi xử lý.

Điều quan trọng nhất cần nắm: **YAML tự nó không mang ý nghĩa**. Dòng `image: mlserver-mlflow:v1` chỉ là một cặp khoá–giá trị. Nó trở thành "chạy container từ image này" là vì **có một chương trình đọc nó và quyết định làm như vậy**. Hành trình của mọi file YAML đều giống nhau:

```
văn bản YAML ──(bộ phân tích cú pháp)──▶ cấu trúc dữ liệu (dict, list, giá trị)
             ──(chương trình đọc)──▶ kiểm tra theo luật của chương trình đó
             ──▶ hành động (tạo object Python, sinh manifest, tạo pod...)
```

Vì vậy, khi gặp một dòng YAML không hiểu, câu hỏi đúng không phải "YAML này nghĩa là gì", mà là **"chương trình nào đọc dòng này, và chương trình đó hiểu nó ra sao"**. Toàn bộ phần này xoay quanh câu hỏi đó.

### 5.2 Cú pháp đủ dùng, kèm những bẫy có thật

**Từ điển** viết bằng `khoá: giá trị`, và độ lồng được thể hiện **chỉ bằng thụt lề**:

```yaml
metadata:
  name: minio-s3
  namespace: serving
```

Ở đây `metadata` là một từ điển chứa hai khoá. Thụt lề phải dùng **dấu cách, không dùng tab**, và các khoá cùng cấp phải thẳng hàng tuyệt đối. Lệch một dấu cách là cả cấu trúc đổi nghĩa hoặc vỡ. Lỗi thật khi một dòng thụt thừa một dấu cách:

```
error: error parsing indent.yaml: error converting YAML to JSON: yaml: line 7: did not find expected key
```

**Danh sách** có hai cách viết. Dạng khối dùng gạch đầu dòng, dạng gọn dùng ngoặc vuông. Hai cách này hoàn toàn tương đương:

```yaml
segments: [nu, lu, au]        # dạng gọn
segments:                     # dạng khối, cùng nghĩa
  - nu
  - lu
  - au
```

Từ điển cũng có dạng gọn dùng ngoặc nhọn, mà bạn thấy trong `20-servingruntime.yaml`: `{name: MLSERVER_HTTP_PORT, value: "8080"}` đúng bằng một từ điển hai khoá viết trên một dòng. Một phần tử danh sách có thể là một từ điển, và đây là dạng gặp nhiều nhất trong Kubernetes: `env:` là danh sách, mỗi phần tử là một từ điển có `name` và `value`.

**Giá trị đơn và chuyện đoán kiểu.** Đây là chỗ nhiều người vấp nhất. YAML **tự đoán kiểu** của giá trị không có dấu nháy. Mình chạy thử bộ phân tích YAML của Python trên vài giá trị:

| Bạn viết | YAML hiểu thành |
|---|---|
| `a: 0` | số nguyên `0` |
| `b: "0"` | chuỗi `"0"` |
| `c: no` | `False` |
| `h: on` | `True` |
| `e: 2026-10-07` | một **ngày**, không phải chuỗi |
| `f: 0.10` | số thực `0.1` |
| `g: 1Gi` | chuỗi `"1Gi"` |

Bẫy này gây lỗi thật. Kubernetes yêu cầu giá trị của biến môi trường **phải là chuỗi**, vì biến môi trường của hệ điều hành luôn là chuỗi. Viết `value: 8080` không có nháy, YAML hiểu là số nguyên, và Kubernetes từ chối:

```
The ServingRuntime "dryrun-rt" is invalid: spec.containers[0].env[3].value: Invalid value: "integer":
spec.containers[0].env[3].value in body must be of type string: "integer"
```

Còn viết `flag: no` vào một chỗ cần chuỗi thì YAML biến nó thành `false`, và Kubernetes báo `cannot unmarshal bool into Go struct field ConfigMap.data of type string`. Đó là lý do trong dự án, mọi giá trị cần là chuỗi mà trông giống số hay true/false đều được đặt trong nháy: `"8080"`, `"0"` (của `s3-usehttps`), `"2"` (của `mlops/model-version`), `"3"` (của phiên bản model format). **Quy tắc thực hành: nếu một giá trị là chuỗi mà trông giống số, ngày hay chữ yes/no, hãy đặt nháy.**

**Comment** bắt đầu bằng `#` và bị bỏ qua hoàn toàn. Hãy dùng chúng để ghi **lý do**, như các comment trong `helmfile.yaml` giải thích vì sao ghim MLflow ở bản `1.11.6`.

**Nhiều tài liệu trong một file.** Dấu `---` trên một dòng riêng ngăn cách các tài liệu YAML độc lập. File `10-minio-access.yaml` chứa hai tài nguyên Kubernetes, Secret và ServiceAccount, nhờ dấu này.

**Neo và tham chiếu** (anchor và alias). YAML cho phép đặt tên một khối bằng `&tên` rồi dùng lại ở nơi khác bằng `*tên`. Trong [training/usecases.yaml](../../training/usecases.yaml), danh sách 24 feature được đặt tên `&account_features` một lần, rồi `loan_propensity` và `overdue_risk` cùng dùng `numeric_features: *account_features`. Khi chạy thử, bộ phân tích trả về **cùng một object danh sách** cho cả hai use case. Nhờ vậy sửa danh sách feature ở một chỗ là hai use case cùng đổi, không bao giờ lệch nhau. Đây là cách YAML hỗ trợ nguyên tắc "một nguồn sự thật".

**Chỗ trống cho chương trình khác điền.** Các chuỗi dạng `{{ ... }}` không phải cú pháp YAML. Với YAML, `"{{.Name}}"` chỉ là một chuỗi ký tự bình thường. Chúng là **khuôn mẫu** (template) mà một chương trình khác sẽ thay giá trị vào: Helm thay các chỗ `{{ .Values... }}` trong chart, còn KServe thay `{{.Name}}` trong ServingRuntime bằng tên InferenceService. Lưu ý chúng thường phải nằm trong dấu nháy, vì dấu `{` ở đầu giá trị sẽ khiến YAML hiểu nhầm là từ điển dạng gọn.

### 5.3 Bốn họ YAML trong dự án

Áp câu hỏi "ai đọc file này" vào toàn bộ dự án, các file YAML chia thành bốn họ. Mỗi họ có người đọc khác nhau, nên có luật viết khác nhau.

| Họ | File | Ai đọc | Rồi thành gì |
|---|---|---|---|
| 1. Cấu hình của chính bạn | [training/usecases.yaml](../../training/usecases.yaml) | `training/config.py` | object Python `UseCase`, `GateConfig` |
| 2. Cài đặt phần mềm | [infra/helmfile.yaml](../../infra/helmfile.yaml), [infra/helm-values/](../../infra/helm-values/) | helmfile, rồi Helm | các manifest Kubernetes do chart sinh ra |
| 3. Khai báo Kubernetes | [serving/k8s/](../../serving/k8s/) | API server, rồi các controller | object trong etcd, rồi pod, Service... |
| 4. Cấu hình công cụ và file sinh tự động | [feature_repo/feature_store.yaml](../../feature_repo/feature_store.yaml), file `MLmodel` | Feast, MLflow, MLServer | bạn chỉ cần đọc hiểu |

Sự khác biệt lớn nhất giữa các họ là **luật đến từ đâu**. Với họ 1, luật do chính bạn viết trong `config.py`, nên bạn quyết định khoá nào hợp lệ. Với họ 2, luật là danh sách tham số của từng chart, mỗi chart một kiểu. Với họ 3, luật là schema của Kubernetes và của các CRD, rất chặt và tra cứu được. Với họ 4, luật thuộc về công cụ, và bạn hiếm khi phải sửa.

### 5.4 Họ 1: `usecases.yaml`, cấu hình do chính bạn đặt luật

Bên trong, hành trình của file này rất ngắn và nằm gọn trong hàm `load_usecases()` của [training/config.py](../../training/config.py). Bước đầu, `yaml.safe_load()` biến văn bản thành một từ điển Python lồng nhau; chữ `safe` nghĩa là bộ phân tích chỉ tạo các kiểu dữ liệu cơ bản, không bao giờ tạo object tuỳ ý, nên một file YAML độc hại không thể chạy code trên máy bạn. Bước hai, với mỗi use case, hàm **trộn** khối `defaults` với khối riêng của use case bằng biểu thức `{**defaults, **spec}`: khoá nào use case tự khai thì dùng giá trị của nó, khoá nào không khai thì lấy từ `defaults`. Đó là lý do `seed: 42`, `n_jobs: 4`, tham số `lgbm` và `lr` chỉ viết một lần ở đầu file. Bước ba, từ điển đã trộn được truyền vào `UseCase(...)`. Vì `UseCase` là một dataclass có danh sách trường cố định, **gõ sai tên khoá** (ví dụ `segment` thay vì `segments`) sẽ báo lỗi ngay lúc nạp, chứ không bị bỏ qua âm thầm. Bước bốn, `validate()` kiểm tra các luật nghiệp vụ: allowlist không được chứa nhãn, khoá hay cột `split`; không được trùng feature; cột phân khúc không được nằm trong feature của model theo phân khúc; quy tắc ngưỡng phải là `max_f1` hoặc `min_recall`.

Ý nghĩa từng khoá của một use case:

| Khoá | Ví dụ | Ý nghĩa và ai dùng |
|---|---|---|
| `dataset` | `training_dataset` | Tên file Parquet trong thư mục run ngày 4; `data.py` đọc `<dataset>.parquet` |
| `label` | `loan_label_next` | Cột nhãn; phải là 0 hoặc 1, không được null |
| `row_filter` | `overdue_eligible == 1` | Biểu thức lọc dòng của pandas, chạy bằng `df.query()` |
| `segment_column`, `segments` | `margin_segment`, `[nu, lu, au]` | Mỗi giá trị trong `segments` là một model riêng; không có `segments` thì một model chung |
| `numeric_features` | `*account_features` | **Allowlist** cột số; cột không có tên ở đây không bao giờ vào model |
| `categorical_features` | `[channel, offer_type, margin_segment]` | Cột phân loại, được mã hoá one-hot trong Pipeline |
| `class_weights` | `overdue_risk.segments` | Đường dẫn có dấu chấm vào bên trong `class_weights.json` của ngày 4 |
| `threshold` | `{rule: max_f1}` | Cách chọn ngưỡng trên validation |

Khối `promotion` ở cấp cao nhất được đọc riêng bởi `load_gate_config()` trong `promotion.py`, thành `GateConfig` với ba dung sai của gate. Nhìn lại cả file, bạn sẽ thấy nó thể hiện quy tắc của loại "cấu hình" ở Phần 4: muốn thêm feature, đổi ngưỡng gate hay đổi tham số model, bạn sửa ở đây mà không đụng tới code.

### 5.5 Họ 2: Helm, khuôn mẫu có chỗ trống

#### `helmfile.yaml`: danh sách những gì cần cài

File này do **helmfile** đọc. helmfile không tự cài gì; nó chỉ đọc danh sách rồi gọi Helm cho từng mục, theo đúng thứ tự phụ thuộc. Mục `repositories` khai báo các kho chart (tương đương `helm repo add`). Mục `helmDefaults` là giá trị mặc định cho mọi lần cài: `wait: true` bắt Helm **chờ tới khi các pod sẵn sàng** mới báo xong, `timeout: 1200` cho phép chờ tối đa 20 phút (image MLflow 3 nặng), `createNamespace: true` tự tạo namespace nếu chưa có. Mục `releases` là danh sách các bản cài, mỗi bản có:

- `name`: tên **release**, tức tên của lần cài này trong Helm. Đây là tên bạn thấy trong `helm list` và dùng khi gỡ.
- `namespace`: cài vào namespace nào.
- `chart`: chart nào, dạng `<kho>/<tên chart>`.
- `version`: phiên bản chart. Dấu ngã ở `~15.5.0` nghĩa là "chấp nhận các bản vá 15.5.x, không lên 15.6". Đó là lý do cluster của bạn có bản `15.5.38`. MLflow thì ghim cứng `1.11.6` vì phiên bản server phải khớp đúng phiên bản client trong `pyproject.toml`.
- `needs`: thứ tự phụ thuộc. MLflow ghi `needs: [mlops/postgres, mlops/minio]`, nên helmfile cài hai thứ đó trước.
- `values`: danh sách file values truyền cho chart.

#### Values file: chỉ ghi đè những gì cần

Để hiểu values file, phải hiểu chart. Một **chart** là một thư mục gồm các **template**, tức những file manifest Kubernetes có chừa chỗ trống, và một file `values.yaml` chứa **giá trị mặc định** cho mọi chỗ trống. Khi cài, Helm trộn values mặc định của chart với values của bạn (của bạn thắng), điền vào template, và gửi kết quả lên Kubernetes. Bước điền này gọi là **render**.

Hãy theo một dòng đi hết hành trình. Template `deployment.yaml` của chart MinIO có dòng:

```yaml
image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
imagePullPolicy: {{ .Values.image.pullPolicy }}
```

Values mặc định của chart (trong `values.yaml` của nó) là `repository: quay.io/minio/minio`, `tag: RELEASE.2024-04-18T19-09-19Z`, `pullPolicy: IfNotPresent`. Đây chính là image đã bị quay.io trả lỗi 401 ở ngày 7. File [minio-values.yaml](../../infra/helm-values/minio-values.yaml) của bạn ghi đè ba giá trị đó. Kết quả render thật mà Helm đã gửi lên cluster (lấy bằng `helm get manifest minio -n mlops`) là:

```yaml
image: "minio/minio:RELEASE.2024-12-18T13-15-44Z"
imagePullPolicy: Never
```

Như vậy, sửa image của MinIO không phải là sửa Deployment, mà là **đổi giá trị cho một chỗ trống**. Điều này cũng giải thích vì sao values file của bạn ngắn: file `values.yaml` mặc định của chart MinIO dài **582 dòng**, của chart MLflow dài **790 dòng**, còn file của bạn chỉ khoảng 35 và 50 dòng. Bạn chỉ ghi những gì **khác** với mặc định.

Một dòng values có thể đi tới những nơi bạn không ngờ. Hai ví dụ từ MinIO:

- `rootUser: minioadmin` được chart đưa vào một **Secret**, lưu dạng base64 là `bWluaW9hZG1pbg==`. Deployment không chứa mật khẩu trực tiếp mà tham chiếu tới Secret đó (`secretKeyRef`, `key: rootUser`), và một ConfigMap chứa script đọc mật khẩu từ file `/config/rootUser`. Một dòng của bạn thành ba chỗ trong ba tài nguyên khác nhau.
- `buckets: [{name: mlflow, policy: none, purge: false}]` được template biến thành một dòng trong script của ConfigMap: `createBucket mlflow "none" false false false`. Script này được Job `minio-post-job` chạy ngay sau khi cài. Khoá `buckets` có tồn tại hay không cũng quyết định Job đó có được tạo hay không, vì template mở đầu bằng điều kiện `{{- if or .Values.buckets ... }}`.

Với [mlflow-values.yaml](../../infra/helm-values/mlflow-values.yaml), các khối giá trị cuối cùng biến thành **tham số dòng lệnh** của máy chủ MLflow. Trên cluster, container MLflow được khởi động với `--backend-store-uri=postgresql://` (thông tin kết nối Postgres được đưa qua biến môi trường từ khối `backendStore.postgres`) và `--default-artifact-root=s3://mlflow/` (từ `artifactRoot.s3.bucket`). Khối `extraEnvVars` thành biến môi trường `MLFLOW_S3_ENDPOINT_URL` của container. `databaseConnectionCheck: true` và `databaseMigration: true` thành hai init container `dbchecker` và `mlflow-db-migration` mà Phần 3 đã nói. Các khối `livenessProbe`, `readinessProbe`, `resources` đi thẳng vào phần tương ứng của container.

Bài học chung cho họ 2: **ý nghĩa của một khoá values do template của chart quyết định**, và mỗi chart đặt tên khác nhau. Cùng là "image", chart MinIO dùng `image.repository` và `image.tag`, chart khác có thể dùng `image.registry`. Không có cách nào đoán; phải tra.

### 5.6 Họ 3: manifest Kubernetes, từng dòng đi đâu

#### Khung chung của mọi manifest

Mọi tài nguyên Kubernetes đều có cùng một khung bốn phần, và hiểu khung này là đọc được mọi manifest:

```yaml
apiVersion: serving.kserve.io/v1beta1   # nhóm API và phiên bản: "từ điển" nào định nghĩa loại này
kind: InferenceService                  # loại tài nguyên
metadata:                               # danh tính: tên, namespace, nhãn, chú thích
  name: loan-propensity-au
  namespace: serving
spec:                                   # trạng thái MONG MUỐN: do bạn viết
  ...
# status:                               # trạng thái THỰC TẾ: do hệ thống ghi, bạn không viết
```

Cặp `apiVersion` và `kind` là chìa khoá để API server tra xem loại tài nguyên này có trong danh mục không (phụ thuộc từ vựng ở Phần 3). Loại có sẵn của Kubernetes dùng `v1` hoặc `apps/v1`; loại do CRD thêm vào dùng nhóm riêng như `serving.kserve.io/v1beta1`. Phần `spec` là mong muốn, phần `status` là thực tế; đây chính là nguyên tắc 5 hiện ra trong cấu trúc dữ liệu. Controller đọc `spec`, làm việc, rồi ghi kết quả vào `status`. Khi bạn chạy `kubectl get isvc` và thấy cột `READY`, đó là một trường trong `status`.

Trong `metadata`, có hai thứ hay bị nhầm: **label** và **annotation**. Cả hai đều là cặp khoá–giá trị gắn lên tài nguyên, nhưng vai trò khác nhau. **Label** dùng để **chọn**: Service tìm pod theo label, `kubectl get pod -l ...` lọc theo label. Vì vậy label bị giới hạn chặt về ký tự và độ dài. **Annotation** dùng để **ghi chú** cho chương trình hoặc con người đọc, không ai chọn theo nó, nên chứa được giá trị dài và tự do. Trong dự án, `mlops/registered-model` là label vì sau này deployer cần **lọc** các InferenceService theo model; `mlops/model-version` là annotation vì nó chỉ là thông tin để đọc. Các khoá dạng `serving.kserve.io/s3-endpoint` trên Secret cũng là annotation: chúng là lời nhắn gửi cho KServe.

Kubernetes kiểm tra tên trường rất chặt. Gõ nhầm `labelz` thay vì `labels`:

```
Error from server (BadRequest): error when creating "typo.yaml": ConfigMap in version "v1"
cannot be handled as a ConfigMap: strict decoding error: unknown field "metadata.labelz"
```

#### `00-namespace.yaml`

Tài nguyên đơn giản nhất: chỉ có `metadata.name: serving`. Bên trong, namespace là một "phạm vi tên": hai tài nguyên cùng loại có thể trùng tên nếu ở hai namespace khác nhau, và các quyền truy cập, giới hạn tài nguyên có thể đặt theo namespace. Nó cũng quyết định tên miền nội bộ: mọi Service trong namespace này có tên miền kết thúc bằng `.serving.svc.cluster.local`.

#### `10-minio-access.yaml`: Secret và ServiceAccount

```yaml
kind: Secret
metadata:
  name: minio-s3
  annotations:
    serving.kserve.io/s3-endpoint: minio.mlops.svc.cluster.local:9000
    serving.kserve.io/s3-usehttps: "0"
    serving.kserve.io/s3-region: us-east-1
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: minioadmin
  AWS_SECRET_ACCESS_KEY: minioadmin
```

`type: Opaque` nghĩa là "dữ liệu tuỳ ý, Kubernetes không cần hiểu nội dung" (khác với các loại có cấu trúc như `kubernetes.io/tls` của chứng chỉ). `stringData` cho phép bạn viết giá trị dạng chữ thường. Nhưng thứ được **lưu** không phải `stringData`: API server mã hoá base64 rồi lưu vào trường `data`. Trên cluster của bạn, `kubectl get secret minio-s3 -n serving -o jsonpath='{.data}'` trả về:

```
{"AWS_ACCESS_KEY_ID":"bWluaW9hZG1pbg==","AWS_SECRET_ACCESS_KEY":"bWluaW9hZG1pbg=="}
```

và giải mã `bWluaW9hZG1pbg==` ra ngay `minioadmin`. Base64 chỉ là **đổi cách viết** để chứa được dữ liệu nhị phân, không phải mã hoá bảo mật; ai đọc được Secret là đọc được mật khẩu. Secret tách mật khẩu ra khỏi image và khỏi code, và cho phép phân quyền ai được đọc nó, nhưng không biến nó thành bí mật.

```yaml
kind: ServiceAccount
metadata:
  name: model-puller
secrets:
  - name: minio-s3
```

ServiceAccount là danh tính của pod. Trường `secrets` ở đây không phải cơ chế chung của Kubernetes để đưa Secret vào pod, mà là **quy ước của KServe**: khi dựng pod cho một InferenceService, controller nhìn vào ServiceAccount nó dùng, đi theo danh sách `secrets`, tìm Secret có annotation `serving.kserve.io/s3-*`, rồi tự cấu hình init container. Bên dưới là kết quả thật mà KServe đã sinh ra trong init container `storage-initializer` của pod predictor. Đặt cạnh file YAML, bạn thấy rõ dòng nào biến thành gì:

```
AWS_ACCESS_KEY_ID      = secretKeyRef {name: minio-s3, key: AWS_ACCESS_KEY_ID}   ◀ từ stringData
AWS_SECRET_ACCESS_KEY  = secretKeyRef {name: minio-s3, key: AWS_SECRET_ACCESS_KEY}
S3_ENDPOINT            = minio.mlops.svc.cluster.local:9000                       ◀ từ annotation s3-endpoint
AWS_ENDPOINT_URL       = http://minio.mlops.svc.cluster.local:9000                ◀ ghép từ s3-endpoint + s3-usehttps "0"
S3_USE_HTTPS           = 0                                                         ◀ từ annotation s3-usehttps
AWS_DEFAULT_REGION     = us-east-1                                                 ◀ từ annotation s3-region
```

Chú ý: mật khẩu **không** được chép vào cấu hình pod. Pod chỉ ghi "lấy giá trị từ Secret `minio-s3`, khoá `AWS_ACCESS_KEY_ID`" (`secretKeyRef`), và kubelet đọc Secret rồi đưa giá trị vào biến môi trường **lúc container khởi động**. Ai xem cấu hình pod sẽ không thấy mật khẩu. Chú ý nữa là chữ `http://` trong `AWS_ENDPOINT_URL`: nó có được là nhờ `s3-usehttps: "0"`; nếu thiếu annotation này, init container sẽ gọi MinIO bằng HTTPS và thất bại.

#### `20-servingruntime.yaml`: công thức chạy, và nó thành gì trong pod

```yaml
spec:
  supportedModelFormats:
    - name: mlflow
      version: "3"
      autoSelect: true
  protocolVersions: [v2]
  containers:
    - name: kserve-container
      image: mlserver-mlflow:v1
      imagePullPolicy: Never
      args: ["mlserver", "start", "/mnt/models"]
      env: [...]
      resources:
        requests: {cpu: 100m, memory: 512Mi}
        limits: {cpu: "1", memory: 1Gi}
```

`supportedModelFormats` là bảng "runtime này nhận định dạng model nào". `autoSelect: true` cho phép KServe tự chọn runtime này cho mọi InferenceService khai báo định dạng `mlflow` phiên bản `"3"` mà không ghi rõ `runtime`. `protocolVersions: [v2]` khai báo runtime nói giao thức V2.

Phần `containers` là **khuôn** cho container chính của pod. Tên `kserve-container` là bắt buộc: KServe tìm container chính bằng đúng tên này để ghép thêm các thứ của nó. So với container thật trong pod predictor, gần như mọi dòng được chép nguyên: image `mlserver-mlflow:v1`, `imagePullPolicy: Never`, `args`, và sáu biến môi trường. Có hai thay đổi đáng chú ý. Thứ nhất, `MLSERVER_MODEL_NAME` có giá trị `"{{.Name}}"` trong file, nhưng trong pod là `loan-propensity-au`: KServe đã thay chỗ trống bằng tên InferenceService. Thứ hai, KServe **tự thêm** một biến không có trong file: `INFERENCE_SERVICE_NAME = loan-propensity-au`.

`imagePullPolicy` có ba giá trị, tra bằng `kubectl explain pod.spec.containers.imagePullPolicy`: `Always` (luôn tải lại), `IfNotPresent` (chỉ tải nếu node chưa có) và `Never` (không bao giờ tải, chỉ dùng image có sẵn trong node). Nếu bạn không ghi, mặc định là `Always` khi tag là `latest` và `IfNotPresent` với tag khác. Dự án dùng `Never` vì image chỉ tồn tại trong node kind, không có trên registry nào.

**`resources` đi xuống tận nhân Linux.** Đây là chỗ đáng xem nhất. Hai con số trong YAML được kubelet chuyển thành giới hạn **cgroup** của container, cơ chế của nhân Linux đã nhắc ở bài ngày 8. Đọc thẳng từ bên trong container predictor:

```
memory.max = 1073741824          ◀ limits.memory: 1Gi = 1024 × 1024 × 1024 byte
cpu.max    = 100000 100000       ◀ limits.cpu: "1" = được dùng 100.000 µs CPU trong mỗi chu kỳ 100.000 µs, tức 1 lõi
cpu.weight = 17                  ◀ suy ra từ requests.cpu: 100m, quyết định phần chia CPU khi các container tranh nhau
```

Dùng quá 1 GiB RAM, nhân Linux giết tiến trình, và pod hiện trạng thái `OOMKilled`. Dùng quá 1 lõi CPU thì không bị giết mà bị **hãm lại** (throttle). Còn `requests` thì có thêm một vai trò khác: bộ xếp lịch chỉ đặt pod lên node còn **ít nhất** 512 MiB và 100m CPU chưa bị giữ chỗ. Vì `requests` nhỏ hơn `limits`, Kubernetes xếp pod này vào hạng **QoS `Burstable`** (xem bằng trường `status.qosClass`): khi node thiếu RAM, pod hạng này bị dọn trước pod hạng `Guaranteed` (requests bằng limits). Hai dòng YAML vì thế quyết định cả chỗ đặt pod, giới hạn thật trong nhân Linux, và thứ tự bị hy sinh khi thiếu tài nguyên.

#### `30-isvc-loan-propensity-au.yaml`: đơn đặt hàng, và những gì được sinh ra

```yaml
metadata:
  name: loan-propensity-au
  labels:
    mlops/registered-model: loan_propensity_au
  annotations:
    mlops/model-version: "2"
spec:
  predictor:
    serviceAccountName: model-puller
    model:
      modelFormat: {name: mlflow, version: "3"}
      runtime: mlflow-mlserver
      protocolVersion: v2
      storageUri: s3://mlflow/1/models/m-d02adce3c18e430d9d8073014678bd6f/artifacts
```

Khoảng 15 dòng này được controller KServe biến thành một Deployment 119 dòng, và pod do Deployment tạo ra dài 294 dòng. Đây là chỗ từng dòng của bạn đi tới:

- **`metadata.name: loan-propensity-au`** trở thành gốc của mọi tên: Deployment và Service tên `loan-propensity-au-predictor`, pod mang label `app: isvc.loan-propensity-au-predictor` và `serving.kserve.io/inferenceservice: loan-propensity-au`, và giá trị của `{{.Name}}` trong runtime.
- **`labels`** được KServe **chép xuống pod**: pod predictor có label `mlops/registered-model: loan_propensity_au`. Annotation `mlops/model-version` thì nằm lại trên InferenceService. Nhờ vậy sau này có thể lọc cả pod theo model.
- **`serviceAccountName: model-puller`** được chép thẳng vào pod, và là điểm bắt đầu của chuỗi ServiceAccount → Secret → biến môi trường ở trên.
- **`modelFormat` và `runtime`** quyết định runtime nào được dùng làm khuôn. Vì đã ghi rõ `runtime`, KServe dùng đúng `mlflow-mlserver` và chỉ kiểm tra định dạng có khớp không.
- **`storageUri`** trở thành **tham số dòng lệnh** của init container: `storage-initializer` chạy với `args: [s3://mlflow/1/models/m-d02a.../artifacts, /mnt/models]`, tức "tải từ đây về kia".
- Để hai container chia nhau file model, KServe **tự thêm** một volume loại `emptyDir` tên `kserve-provision-location`, gắn vào `/mnt/models` của cả init container lẫn container chính. `emptyDir` là một thư mục trống được tạo khi pod khởi động và mất đi khi pod bị xoá; đó là lý do mỗi pod mới phải tải lại model.

Service do KServe sinh ra có `selector: {app: isvc.loan-propensity-au-predictor}` và cổng `port: 80, targetPort: 8080`. Nghĩa là Service chọn các pod mang đúng label đó, nhận request ở cổng 80, rồi chuyển tới cổng 8080 của pod, nơi MLServer lắng nghe (`MLSERVER_HTTP_PORT: "8080"`). Danh sách địa chỉ mà Service đang chuyển tới, xem bằng `kubectl get endpoints`, là `10.244.0.25:8080`, đúng IP của pod predictor. Toàn bộ đường đi của một request, mà bài ngày 8 mô tả bằng lời, ở đây hiện ra bằng các trường dữ liệu cụ thể.

Có một chi tiết cần **đính chính** so với bài lý thuyết ngày 8. Ở đó mình viết rằng Kubernetes dựa vào endpoint readiness của MLServer (`/v2/models/.../ready`) để biết pod đã nạp xong model. Đọc pod thật, readiness probe mà KServe đặt là **`tcpSocket: {port: 8080}`**: Kubernetes chỉ kiểm tra cổng 8080 **có mở** hay không, không hỏi model đã nạp xong chưa. Nếu MLServer mở cổng trước khi nạp xong model, sẽ có một khoảng ngắn pod được coi là sẵn sàng mà gọi `/infer` vẫn lỗi. Cách chặt chẽ hơn là tự khai báo `readinessProbe` loại `httpGet` trỏ vào `/v2/models/loan-propensity-au/ready` trong phần `predictor` của InferenceService. Đây cũng là một ví dụ cho thấy vì sao phải **đọc thứ hệ thống thực sự sinh ra**, chứ không chỉ tin vào mô tả.

### 5.7 Họ 4: file của công cụ, chỉ cần đọc hiểu

[feature_repo/feature_store.yaml](../../feature_repo/feature_store.yaml) do Feast đọc khi bạn tạo `FeatureStore`. `project: margin_mlops` là tên dự án Feast, gắn vào mọi định nghĩa. `provider: local` nghĩa là chạy trên máy, không dùng dịch vụ đám mây. `registry: data/registry.db` là nơi lưu các định nghĩa sau `feast apply`. `offline_store: {type: file}` nghĩa là đọc feature lịch sử từ file Parquet. `online_store` khai báo SQLite chỉ vì Feast bắt buộc phải có, và chưa có gì được nạp vào cho tới giai đoạn 2. Chú ý file này **không** chứa định nghĩa feature nào; các định nghĩa nằm trong `definitions.py`, viết bằng Python. Feast dùng YAML cho cấu hình hạ tầng và Python cho định nghĩa nghiệp vụ.

File **`MLmodel`** do MLflow tự sinh khi log model, và đã được giải thích kỹ trong bài MLflow. Nhắc lại vai trò của nó trong bức tranh YAML: đây là file mà **MLServer đọc** khi nạp model. Khoá `flavors.python_function.loader_module: mlflow.sklearn` cho biết dùng bộ nạp nào, `predict_fn: predict_proba` cho biết gọi hàm nào, và khối `signature` là hợp đồng 24 cột. Bạn không bao giờ sửa tay file này, nhưng đọc được nó giúp gỡ lỗi khi model nạp sai.

### 5.8 Cách tự tra nghĩa một khoá lạ

Không ai thuộc hết các khoá. Kỹ năng thật là **biết tra ở đâu**, và nơi tra phụ thuộc vào họ của file:

| Muốn biết | Lệnh | Dùng cho họ |
|---|---|---|
| Một trường của tài nguyên Kubernetes nghĩa là gì, kiểu gì, giá trị hợp lệ nào | `kubectl explain pod.spec.containers.resources` | 3 |
| Một chart có những khoá values nào, mặc định là gì | `helm show values minio/minio --version 5.2.0` | 2 |
| Values của mình sẽ render ra manifest nào, **trước khi cài** | `helmfile -l name=minio template` hoặc `helm template` | 2 |
| Helm đã thực sự gửi gì lên cluster | `helm get manifest minio -n mlops` | 2 |
| Kiểm tra một manifest có hợp lệ không, **không tạo gì** | `kubectl apply --dry-run=server -f file.yaml` | 3 |
| Hệ thống đã sinh ra gì từ khai báo của mình | `kubectl get deploy,pod,svc -n serving -o yaml` | 3 |
| Một khoá trong cấu hình của mình được dùng ở đâu | tìm tên khoá trong `training/` | 1 |

Với các CRD như InferenceService, `kubectl explain` cho biết **kiểu** của trường nhưng thường không có mô tả (thử `kubectl explain inferenceservice.spec.predictor.model.storageUri`, phần mô tả trống); khi đó nguồn đúng là tài liệu chính thức của KServe. Lệnh `--dry-run=server` đáng nhớ nhất: nó gửi manifest qua **đúng** các bước kiểm tra của API server, kể cả webhook, nhưng không lưu gì. Mọi lỗi YAML trong phần này đều được bắt bằng lệnh đó.

Gom các lỗi thật đã gặp thành một bảng tra nhanh:

| Thông báo lỗi | Nguyên nhân | Sửa |
|---|---|---|
| `did not find expected key` | Thụt lề sai, thường lệch một dấu cách | Căn thẳng các khoá cùng cấp, chỉ dùng dấu cách |
| `must be of type string: "integer"` | Số không có nháy ở chỗ cần chuỗi | Đặt nháy: `"8080"` |
| `cannot unmarshal bool ... of type string` | `no`, `yes`, `on`, `off` bị hiểu là true/false | Đặt nháy: `"no"` |
| `strict decoding error: unknown field` | Gõ sai tên trường | Tra bằng `kubectl explain` |
| `no matches for kind ... ensure CRDs are installed first` | Sai `apiVersion`/`kind`, hoặc CRD chưa cài | Kiểm tra `kubectl api-resources` |

### Tự kiểm tra

1. Giải thích bằng lời của bạn câu "YAML tự nó không mang ý nghĩa". Cho một ví dụ trong dự án mà cùng một chữ khoá có ý nghĩa khác nhau tuỳ người đọc.
2. Vì sao `MLSERVER_HTTP_PORT` phải viết `"8080"` có nháy, trong khi `port: 5432` trong `mlflow-values.yaml` lại không cần?
3. Khi bạn sửa `tag` trong `minio-values.yaml`, nó đi qua những bước nào để thành image của container MinIO? Lệnh nào cho bạn xem kết quả trước khi cài?
4. Mật khẩu trong `stringData` của Secret `minio-s3` đi tới biến môi trường của init container bằng con đường nào? Vì sao ai xem cấu hình pod cũng không thấy mật khẩu, mà Secret vẫn không phải là "bí mật"?
5. Kể ba thứ mà KServe **tự thêm** vào pod predictor mà không có trong bất kỳ file YAML nào của bạn, và vai trò của từng thứ.
6. `limits.memory: 1Gi` và `requests.memory: 512Mi` lần lượt ảnh hưởng tới điều gì? Nếu model dùng 1,2 GiB RAM thì chuyện gì xảy ra, và bạn sẽ thấy triệu chứng đó ở đâu?
7. Vì sao readiness probe kiểu `tcpSocket` yếu hơn kiểu `httpGet` vào `/v2/models/<tên>/ready`? Bạn sẽ thêm nó vào file nào?
