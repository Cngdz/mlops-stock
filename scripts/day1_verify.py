import os
import mlflow
import mlflow.sklearn
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# 1. Cấu hình kết nối tới MLflow và MinIO local
os.environ["MLFLOW_TRACKING_URI"] = "http://127.0.0.1:5050"
os.environ["MLFLOW_S3_ENDPOINT_URL"] = "http://127.0.0.1:9000"
os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"

print("[1/4] Đang nạp dữ liệu và huấn luyện mô hình thử nghiệm...")
X, y = load_iris(return_X_y=True)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

clf = RandomForestClassifier(n_estimators=100, max_depth=4, random_state=42)
clf.fit(X_train, y_train)

preds = clf.predict(X_test)
acc = accuracy_score(y_test, preds)
print(f"[2/4] Độ chính xác (Accuracy): {acc:.4f}")

# 2. Log vào MLflow Tracking & MinIO S3
mlflow.set_experiment("day-1-baseline-verification")

with mlflow.start_run(run_name="init_smoke_test") as run:
    print(f"[3/4] Đang log params, metrics và model artifact lên MinIO...")
    mlflow.log_param("n_estimators", 100)
    mlflow.log_param("max_depth", 4)
    mlflow.log_metric("accuracy", acc)

    # Đăng ký trực tiếp vào Model Registry
    mlflow.sklearn.log_model(
        sk_model=clf,
        artifact_path="model",
        registered_model_name="iris-classifier-baseline"
    )

print("\n=======================================================")
print("[4/4] CHÚC MỪNG: Hoàn thành toàn bộ nhiệm vụ Ngày 1!")
print("=======================================================")