"""Iceberg -> Day 4 candidates -> quality gate -> versioned feature tables.

Exit 0: approved; exit 2: rejected, only a validation report is written.
No feature tables or training files are written when validation fails.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import duckdb
import pyarrow.parquet as pq
from pyiceberg.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]
KEYS = ["master_account", "report_date"]
GROUPS = {
    "fs_demographic": ["account_age_days", "margin_segment"],
    "fs_trading_behavior": ["trade_count_7d", "trade_count_30d", "total_trading_amount_7d", "total_trading_amount_30d", "active_trading_days_30d"],
    "fs_margin_balance": ["margin_debt", "margin_limit", "margin_utilization_ratio", "debt_change_7d"],
    "fs_asset_balance": ["cash_balance", "asset_value", "collateral_value", "cash_to_asset_ratio", "NAV"],
}
SOURCE_KEYS = {"customer_account": ["master_account"], "stock_transaction": ["transaction_id"], "margin_balance_daily": ["master_account", "business_date"], "margin_cash_flow": ["cash_flow_id"]}


def catalog():
    return load_catalog("local", **{
        "type": "sql", "uri": f"sqlite:///{(ROOT / 'data/catalog_full/pyiceberg.db').as_posix()}",
        "warehouse": str(ROOT / "data/warehouse_full"),
    })


def scalar(con, sql):
    return con.execute(sql).fetchone()[0]


def records(con, sql):
    cur = con.execute(sql)
    return [dict(zip([d[0] for d in cur.description], row)) for row in cur.fetchall()]


def validate_sources(con, raw_end):
    """Reject unsupported schemas and invalid source data before feature builds."""
    columns = {r[0] for r in con.execute("DESCRIBE margin_cash_flow").fetchall()}
    missing = sorted({"fk_cash_flow_type", "fk_deliver_type"} - columns)
    invalid_times = scalar(con, "SELECT count(*) FROM stock_transaction WHERE TRY_CAST(transaction_time AS TIMESTAMPTZ) IS NULL")
    incomplete = con.execute("""SELECT count(*) FROM (
        SELECT a.master_account FROM customer_account a LEFT JOIN margin_balance_daily b USING(master_account)
        GROUP BY a.master_account,a.account_open_date HAVING min(b.business_date)<>a.account_open_date
        OR max(b.business_date)<>? OR count(DISTINCT b.business_date)<>date_diff('day',a.account_open_date,?)+1)""",
        [raw_end, raw_end]).fetchone()[0]
    return {
        "status": "FAIL" if missing or invalid_times or incomplete else "PASS",
        "missing_cash_flow_columns": missing,
        "invalid_transaction_timestamps": invalid_times,
        "accounts_with_incomplete_balance_history": incomplete,
    }


def normalize(con):
    """Use canonical source fields only; never infer missing label semantics."""
    columns = {r[0] for r in con.execute("DESCRIBE margin_cash_flow").fetchall()}
    missing = {"fk_cash_flow_type", "fk_deliver_type"} - columns
    if missing:
        raise ValueError(f"Missing cash-flow columns: {sorted(missing)}")
    con.execute("CREATE TABLE events AS SELECT *, CAST(event_date AS DATE) AS event_day FROM margin_cash_flow")
    con.execute("""CREATE TABLE valid_events AS SELECT * FROM events WHERE status='POSTED' AND
        ((fk_product='MARGIN_MBS' AND fk_cash_flow_type='INTERM_DELIVER' AND fk_deliver_type='BUY_SHARE') OR
         (fk_product='MBLINK' AND fk_cash_flow_type='TLO_DELIVER_CASH' AND fk_deliver_type='BUY'))""")
    con.execute("""CREATE TABLE trades AS SELECT *,
        CAST(timezone('Asia/Ho_Chi_Minh', CAST(transaction_time AS TIMESTAMPTZ)) AS DATE) AS trade_date
        FROM stock_transaction""")


def build(con, raw_end):
    for statement in (ROOT / "scripts/day4_features.sql").read_text(encoding="utf-8").split(';'):
        if statement.strip():
            con.execute(statement, {"raw_end": raw_end} if '$raw_end' in statement else None)


def assess(con, raw_end):
    checks = []

    def check(name, observed, expected=0):
        checks.append({"check": name, "observed": observed, "expected": expected, "passed": bool(observed == expected)})

    check("invalid_transaction_timestamp", scalar(con, "SELECT count(*) FROM trades WHERE TRY_CAST(transaction_time AS TIMESTAMPTZ) IS NULL"))
    for table, keys in SOURCE_KEYS.items():
        check(f"{table}.duplicate_keys", scalar(con, f"SELECT count(*) FROM (SELECT {','.join(keys)} FROM {table} GROUP BY ALL HAVING count(*)>1)"))
        check(f"{table}.null_keys", scalar(con, f"SELECT count(*) FROM {table} WHERE " + " OR ".join(f"{k} IS NULL" for k in keys)))
        if table != "customer_account":
            check(f"{table}.orphan_accounts", scalar(con, f"SELECT count(*) FROM {table} s ANTI JOIN customer_account a USING(master_account)"))
    check("source_account_enums", scalar(con, "SELECT count(*) FROM customer_account WHERE risk_profile NOT IN ('LOW','MEDIUM','HIGH') OR risk_profile IS NULL OR account_status NOT IN ('ACTIVE','DORMANT','CLOSED') OR account_status IS NULL"))
    check("source_account_lifecycle_dates", scalar(con, "SELECT count(*) FROM customer_account WHERE account_open_date IS NULL OR (account_status='CLOSED' AND account_close_date IS NULL) OR (account_status='DORMANT' AND dormant_start_date IS NULL) OR account_close_date < account_open_date OR dormant_start_date < account_open_date"))
    check("invalid_trade_values", scalar(con, "SELECT count(*) FROM trades WHERE quantity IS NULL OR price IS NULL OR trade_value IS NULL OR quantity<=0 OR price<=0 OR trade_value<0 OR abs(trade_value-quantity*price)>1 OR side NOT IN ('BUY','SELL') OR side IS NULL OR trade_date IS NULL"))
    check("invalid_cash_flow", scalar(con, """SELECT count(*) FROM events WHERE amount IS NULL OR amount<0 OR event_day IS NULL
        OR status NOT IN ('POSTED','CANCELLED') OR status IS NULL
        OR fk_product IS NULL OR fk_product NOT IN ('MARGIN_MBS','MBLINK','OTHER')
        OR fk_cash_flow_type IS NULL OR fk_cash_flow_type NOT IN ('INTERM_DELIVER','TLO_DELIVER_CASH','REPAYMENT','FEE','OTHER')
        OR fk_deliver_type IS NULL OR fk_deliver_type NOT IN ('BUY_SHARE','BUY','OTHER')"""))
    for table, day in [("trades", "trade_date"), ("events", "event_day")]:
        check(f"{table}.outside_account_lifecycle", scalar(con, f"SELECT count(*) FROM {table} s JOIN customer_account a USING(master_account) WHERE {day}<account_open_date OR {day}>=account_close_date OR {day}>=dormant_start_date"))
        check(f"{table}.after_raw_end", con.execute(f"SELECT count(*) FROM {table} WHERE {day}>?", [raw_end]).fetchone()[0])
    check("invalid_balance_values", scalar(con, "SELECT count(*) FROM margin_balance_daily WHERE cash_balance IS NULL OR asset_value IS NULL OR margin_debt IS NULL OR margin_limit IS NULL OR least(cash_balance,asset_value,margin_debt,margin_limit)<0"))
    check("source_debt_reconciliation", scalar(con, """WITH deltas AS (
        SELECT master_account,event_day,sum(CASE
            WHEN status='POSTED' AND ((fk_product='MARGIN_MBS' AND fk_cash_flow_type='INTERM_DELIVER' AND fk_deliver_type='BUY_SHARE') OR
            (fk_product='MBLINK' AND fk_cash_flow_type='TLO_DELIVER_CASH' AND fk_deliver_type='BUY')) THEN amount
            WHEN status='POSTED' AND fk_cash_flow_type='REPAYMENT' THEN -amount ELSE 0 END) AS delta
        FROM events GROUP BY ALL), previous AS (
        SELECT *,coalesce(lag(margin_debt) OVER(PARTITION BY master_account ORDER BY business_date),0) AS prior_debt
        FROM margin_balance_daily)
        SELECT count(*) FROM previous b JOIN customer_account a USING(master_account)
        LEFT JOIN deltas d ON b.master_account=d.master_account AND b.business_date=d.event_day
        WHERE b.margin_debt<>CASE WHEN b.business_date>=a.account_close_date THEN 0
            ELSE greatest(0,b.prior_debt+coalesce(d.delta,0)) END"""))
    check("balance_history_incomplete", con.execute("""SELECT count(*) FROM (
        SELECT a.master_account FROM customer_account a LEFT JOIN margin_balance_daily b USING(master_account)
        GROUP BY a.master_account,a.account_open_date HAVING min(b.business_date)<>a.account_open_date
        OR max(b.business_date)<>? OR count(DISTINCT b.business_date)<>date_diff('day',a.account_open_date,?)+1)""", [raw_end, raw_end]).fetchone()[0])
    columns = KEYS + [f for values in GROUPS.values() for f in values] + ["loan_label_next", "split"]
    check("candidate.null_required_rows", scalar(con, "SELECT count(*) FROM candidate WHERE " + " OR ".join(f'"{k}" IS NULL' for k in columns)))
    check("candidate.duplicate_keys", scalar(con, "SELECT count(*) FROM (SELECT master_account,report_date FROM candidate GROUP BY ALL HAVING count(*)<>1)"))
    check("candidate.nonempty", scalar(con, "SELECT count(*) FROM candidate") > 0, True)
    check("candidate.invalid_domains", scalar(con, "SELECT count(*) FROM candidate WHERE margin_segment NOT IN ('nu','lu','au') OR split NOT IN ('train','validation','test') OR loan_label_next NOT IN (0,1) OR account_age_days<30 OR trade_count_7d>trade_count_30d OR total_trading_amount_7d>total_trading_amount_30d OR active_trading_days_30d NOT BETWEEN 0 AND 30"))
    check("candidate.incomplete_label_window", con.execute("SELECT count(*) FROM candidate WHERE report_date+INTERVAL 30 DAY>?", [raw_end]).fetchone()[0])
    check("candidate.embargo_rows", scalar(con, "SELECT count(*) FROM candidate WHERE report_date BETWEEN '2025-07-01' AND '2025-07-30' OR report_date BETWEEN '2025-10-01' AND '2025-10-30'"))
    check("candidate.balance_formulas", scalar(con, """SELECT count(*) FROM candidate WHERE
        NAV<>asset_value+cash_balance-margin_debt OR
        abs(margin_utilization_ratio-CASE WHEN margin_limit=0 THEN 0.0 ELSE margin_debt::DOUBLE/margin_limit END)>1e-10 OR
        abs(cash_to_asset_ratio-CASE WHEN asset_value=0 THEN 0.0 ELSE cash_balance::DOUBLE/asset_value END)>1e-10"""))
    con.execute("CREATE TABLE audit_sample AS SELECT * FROM candidate ORDER BY hash(master_account,report_date) LIMIT 150")
    check("independent_rolling_and_label_audit", scalar(con, """SELECT count(*) FROM audit_sample s WHERE
        trade_count_7d<>(SELECT count(*) FROM trades t WHERE t.master_account=s.master_account AND t.trade_date BETWEEN s.report_date-INTERVAL 6 DAY AND s.report_date) OR
        total_trading_amount_30d<>(SELECT coalesce(sum(trade_value),0) FROM trades t WHERE t.master_account=s.master_account AND t.trade_date BETWEEN s.report_date-INTERVAL 29 DAY AND s.report_date) OR
        loan_label_next<>CAST(EXISTS(SELECT 1 FROM valid_events e WHERE e.master_account=s.master_account AND e.event_day>s.report_date AND e.event_day<=s.report_date+INTERVAL 30 DAY) AS TINYINT)"""))
    stats = records(con, "SELECT split,margin_segment,count(*) AS rows,sum(loan_label_next) AS positives,avg(loan_label_next) AS positive_rate FROM candidate GROUP BY ALL ORDER BY 1,2")
    for split in ["train", "validation", "test"]:
        for segment in ["nu", "lu", "au"]:
            row = next((r for r in stats if r["split"] == split and r["margin_segment"] == segment), None)
            check(f"{split}.{segment}.both_classes", bool(row and 0 < row["positives"] < row["rows"]), True)
    rates = records(con, "SELECT margin_segment,count(*) AS rows,avg(loan_label_next) AS positive_rate FROM candidate GROUP BY ALL")
    overall = scalar(con, "SELECT avg(loan_label_next) FROM candidate")
    check("overall_positive_rate_10_to_35pct", overall is not None and .10 <= overall <= .35, True)
    last_shares = {}
    for seg, low, high in [("nu", .05, .25), ("lu", .10, .40), ("au", .15, .50)]:
        rate = next((r["positive_rate"] for r in rates if r["margin_segment"] == seg), None)
        check(f"{seg}.positive_rate_{low}_to_{high}", rate is not None and low <= rate <= high, True)
        share = scalar(con, f"SELECT avg(CAST(margin_segment='{seg}' AS INTEGER)) FROM candidate WHERE report_date=(SELECT max(report_date) FROM candidate)")
        last_shares[seg] = share
        check(f"{seg}.last_snapshot_share_at_least_10pct", share is not None and share >= .1, True)
    return {"status": "PASS" if all(c["passed"] for c in checks) else "FAIL", "checks": checks,
            "rows": scalar(con, "SELECT count(*) FROM candidate"), "positive_rate": overall,
            "by_segment": rates, "by_split_segment": stats,
            "last_snapshot_shares": last_shares,
            "embargo_rows_excluded": scalar(con, "SELECT count(*) FROM snapshots WHERE split IS NULL"),
            "null_required_rows": scalar(con, "SELECT count(*) FROM candidate WHERE " + " OR ".join(f'"{k}" IS NULL' for k in columns))}


def weights(con, approved):
    result = {"method": "balanced: N / (2 * N_class)", "fit_split": "train", "approved_for_training": approved, "segments": {}}
    for seg in ["nu", "lu", "au"]:
        counts = dict(con.execute("SELECT loan_label_next,count(*) FROM candidate WHERE split='train' AND margin_segment=? GROUP BY 1", [seg]).fetchall())
        result["segments"][seg] = {"counts": counts, "weights": {str(k): sum(counts.values()) / (2 * v) for k,v in counts.items()} if len(counts)==2 else None}
    return result


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def run(args):
    started = time.monotonic()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    out = ROOT / "data/features/day4_runs" / run_id
    con = duckdb.connect()
    con.execute("SET TimeZone='Asia/Ho_Chi_Minh'")
    con.execute("SET threads=4")
    cat = catalog()
    source_pointer = ROOT / 'data/source_current.json'
    source_namespace = args.source_namespace or (json.loads(source_pointer.read_text())['namespace'] if source_pointer.exists() else 'raw')
    source_versions = {}
    for name in SOURCE_KEYS:
        table = cat.load_table(f"{source_namespace}.{name}")
        source_versions[name] = {"metadata": table.metadata_location, "snapshot_id": table.current_snapshot().snapshot_id}
        con.register("source_arrow", table.scan().to_arrow())
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM source_arrow")
        con.unregister("source_arrow")
        print(f"Read {source_namespace}.{name}: {scalar(con, f'SELECT count(*) FROM {name}'):,}", flush=True)
    source_report = validate_sources(con, args.raw_end)
    source_report.update({"source_namespace": source_namespace, "source_snapshots": source_versions, "raw_end": args.raw_end})
    report_dir = ROOT / "data/features"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(report_dir / "source_validation.json", source_report)
    if source_report["status"] != "PASS":
        con.close()
        print(json.dumps(source_report, indent=2, default=str), flush=True)
        print("Source validation FAIL: no feature files or Iceberg tables created.", flush=True)
        return 2
    normalize(con)
    build(con, args.raw_end)
    report = assess(con, args.raw_end)
    if report["status"] != "PASS":
        report.update({"source_namespace": source_namespace, "source_snapshots": source_versions, "raw_end": args.raw_end})
        write_json(report_dir / "rejected_quality_report.json", report)
        con.close()
        print("Quality gate FAIL: report only, no dataset or class weights exported.", flush=True)
        return 2
    out.mkdir(parents=True)
    report.update({"run_id": run_id, "source_namespace": source_namespace, "source_snapshots": source_versions, "raw_end": args.raw_end,
                   "feature_contract": "day4-v2", "outputs": {}, "namespace": f"features_{run_id.lower()}"})
    namespace = report["namespace"]
    cat.create_namespace(namespace)
    for name, fields in {**GROUPS, "training_dataset": None}.items():
        selection = "* EXCLUDE(history_count, recent_events)" if fields is None else ",".join('"'+s+'"' for s in KEYS + fields)
        arrow = con.execute(f"SELECT {selection} FROM candidate ORDER BY master_account,report_date").to_arrow_table()
        path = out / f"{name}.parquet"
        pq.write_table(arrow, path)
        table = cat.create_table(f"{namespace}.{name}", schema=arrow.schema, properties={"quality.status": report["status"], "day4.run_id": run_id})
        table.append(arrow)
        readback = table.scan().to_arrow()
        actual_rows = readback.num_rows
        # Scan the data files, not just metadata row counts. Ignore scan order.
        sort_keys = [(k, 'ascending') for k in KEYS]
        # Iceberg widens int8 labels to int32; safe cast checks values losslessly.
        if not readback.cast(arrow.schema, safe=True).sort_by(sort_keys).equals(pq.read_table(path).sort_by(sort_keys), check_metadata=False):
            raise RuntimeError(f"Iceberg/Parquet content verification failed for {name}")
        report["outputs"][name] = {"parquet": str(path), "rows": actual_rows, "iceberg": f"{namespace}.{name}", "snapshot_id": table.current_snapshot().snapshot_id, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        print(f"Verified {name}: {actual_rows:,} rows", flush=True)
    weight_result = weights(con, approved=True)
    write_json(out / "class_weights.json", weight_result)
    report["elapsed_seconds"] = round(time.monotonic()-started, 2)
    write_json(out / "quality_report.json", report)
    write_json(ROOT / "data/features/current.json", {"run_id": run_id, "path": str(out), "namespace": namespace})
    write_json(source_pointer, {'namespace': source_namespace, 'approved_by_day4_run': run_id})
    write_report(report, weight_result, out)
    print(f"Quality gate: {report['status']}; artifacts: {out}", flush=True)
    con.close()
    return 0


def write_report(report, weight_result, out):
    """Render a reproducible report from the verified run's actual statistics."""
    passed = sum(item["passed"] for item in report["checks"])
    lines = [
        "# Báo cáo Ngày 4 — Feature engineering và nhãn", "",
        "## Kết luận", "",
        f"**PASS {passed}/{len(report['checks'])} quality checks** trên nguồn {report['source_namespace']}.",
        f"Run: {report['run_id']}; {report['rows']:,} snapshot; {report['elapsed_seconds']} giây cho pipeline ngày 4.",
        f"Positive rate toàn bộ: {report['positive_rate']:.4%}. Null ở cột bắt buộc: {report['null_required_rows']}.", "",
        "Đầu ra đã được duyệt qua data/features/current.json. Nguồn mặc định cho lần chạy tiếp theo nằm trong data/source_current.json.", "",
        "## Các lỗi nguồn đã sửa", "",
        "- Sinh timestamp bằng datetime/timedelta; lưu UTC microsecond trong Iceberg, tính ngày nghiệp vụ theo Asia/Ho_Chi_Minh.",
        "- Cash-flow dùng schema chuẩn fk_product/fk_cash_flow_type/fk_deliver_type; phân biệt POSTED/CANCELLED, repayment, fee và non-target event.",
        "- Suy ra ACTIVE/DORMANT/CLOSED theo từng ngày. Giữ balance đến raw_end; số dư về 0 từ ngày đóng.",
        "- Hạn mức theo risk_profile; amount giải ngân bị chặn bởi available_limit; OVERDUE chỉ sau ba ngày giao dịch vượt hạn mức.",
        "- Tính NAV và collateral_value; tỷ lệ có mẫu số 0 trả về 0.0.",
        "- Ngày mở tài khoản nằm trong tháng 1; archetype chỉ dùng nội bộ để sinh hành vi.",
        "- RNG tách theo tài khoản/stream, được kiểm thử không thay đổi dữ liệu tài khoản cũ khi thêm tài khoản mới.", "",
        "## Thay đổi đã được người dùng duyệt", "",
        "Xác suất trả nợ tăng từ 5% lên 10%/ngày khi ACTIVE và có dư nợ; đã cập nhật decision §8.5 cùng các cấu hình tương ứng.",
        "Giữ nguyên định nghĩa label và toàn bộ ngưỡng quality gate. Calibration chỉ điều chỉnh xác suất sinh event, không thay nhãn sau khi sinh.",
        "Pilot 500 tài khoản, seed 42; kết quả calibration và lịch sử các vòng ở data/generation_calibration.json. Metadata của nguồn mới nằm tại data/generated/day4_v2/generation_run.json.", "",
        "## Feature và nhãn", "",
        "Mỗi dòng có khóa (master_account, report_date). Bảng fs_* không chứa label; training_dataset gồm feature, segment, loan_label_next và split.",
        "Feature chỉ dùng dữ liệu đến cuối ngày D; cửa sổ 7 ngày là D−6..D, 30 ngày là D−29..D.",
        "debt_change_7d lấy đúng số dư D−7, không dịch bảy dòng trên một tập đã lọc.",
        "Label dùng ít nhất một event POSTED đúng tổ hợp Margin MBS hoặc MBLink trong D+1..D+30. Ngày D, D+31, cancelled, repayment và sai tổ hợp không tạo label dương.",
        "Segment: au khi còn dư nợ hoặc có event hợp lệ trong 30 ngày gần nhất; lu khi từng dùng nhưng hiện không dư nợ và không có event gần đây; còn lại nu.",
        "Không xuất days_since_last_margin_event, biến ẩn hoặc cờ generator vào feature.", "",
        "| Nhóm | Feature |", "|---|---|",
    ]
    for name, fields in GROUPS.items():
        lines.append(f"| {name} | {', '.join(fields)} |")
    lines += [
        "", "## Split và kết quả", "",
        "Train: 2025-02-01..2025-06-30; validation: 2025-07-31..2025-09-30; test: 2025-10-31..2025-12-31.",
        f"Đã loại {report['embargo_rows_excluded']:,} snapshot embargo. Chỉ lấy tài khoản ACTIVE, tuổi ≥30 ngày và đủ 30 ngày dữ liệu tương lai.", "",
        "| Split | Segment | Số dòng | Positive | Positive rate |", "|---|---|---:|---:|---:|",
    ]
    for row in report["by_split_segment"]:
        lines.append(f"| {row['split']} | {row['margin_segment']} | {row['rows']:,} | {row['positives']:,} | {row['positive_rate']:.4%} |")
    lines += ["", "Tỷ trọng tại snapshot cuối (gate: mỗi segment ≥10%):", ""]
    for segment, share in report["last_snapshot_shares"].items():
        lines.append(f"- {segment}: {share:.4%}.")
    lines += [
        "", "## Class imbalance", "",
        "Balanced class weight = N/(2×N_class), tính riêng từng segment trên train. Không resample validation/test; không kết hợp thêm scale_pos_weight.",
        "", "| Segment | Weight 0 | Weight 1 |", "|---|---:|---:|",
    ]
    for segment, values in weight_result["segments"].items():
        w=values["weights"]
        lines.append(f"| {segment} | {w['0']:.6f} | {w['1']:.6f} |")
    lines += [
        "", "## Kiểm chứng", "",
        "- Source gate: schema, timestamp, lịch sử balance đầy đủ.",
        "- Quality gate: khóa, null, foreign key, miền giá trị, vòng đời tài khoản, biên thời gian, cả hai lớp trong từng split/segment.",
        "- Đối soát dư nợ toàn bộ panel bằng giải ngân/trả nợ POSTED và trạng thái đóng tài khoản.",
        "- Đối chiếu độc lập rolling/label cho 150 snapshot bằng truy vấn trực tiếp.",
        "- Đọc lại mọi bảng Iceberg, sắp theo khóa và so sánh toàn bộ nội dung với Parquet; có SHA-256 và snapshot IDs trong quality_report.json.",
        "- Unit tests tại tests/test_day4.py và tests/test_generator.py: boundary, point-in-time, lifecycle, RNG độc lập, công thức số dư, timezone và class weights.", "",
        "## Đầu ra", "", f"Thư mục: {out}", "",
    ]
    for name, detail in report["outputs"].items():
        lines.append(f"- {name}.parquet: {detail['rows']:,} dòng; Iceberg {detail['iceberg']}.")
    lines += [
        "- quality_report.json: checks, provenance, hashes.",
        "- class_weights.json: weights đã duyệt.",
        "- data/features/current.json: trỏ đến phiên bản training đã duyệt.",
        "- data/source_current.json: trỏ đến nguồn Iceberg đã duyệt.", "",
        "## Giới hạn và phạm vi nghiệm thu", "",
        "PASS áp dụng cho quality gate ngày 4. Tỷ trọng segment đã đạt ngưỡng tối thiểu; chưa khớp các mục tiêu tham khảo nu=35–55%, lu=20–40%, au=15–35% trong decision §10.",
        "Chưa nghiệm thu mục tiêu thống kê bổ sung như số giao dịch/tháng. Chưa train model (ngày 6), chưa đánh giá hiệu quả kinh doanh trên dữ liệu thật.",
        "Nguồn không có ingestion timestamp nên kiểm thử point-in-time hiện bao phủ event time, chưa bao phủ late-arriving data trong production.",
        "Nguồn cũ raw và data/generated/full được giữ để đối chiếu; pipeline mặc định đã chuyển sang nguồn mới. Báo cáo day4_quality_history.json là lịch sử của các output lỗi đã xóa.", "",
        "## Chạy lại", "", "```powershell",
        ".\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v",
        ".\\.venv\\Scripts\\python.exe scripts/day4_feature_engineering.py",
        "```", "", "Exit 2 chỉ ghi báo cáo lỗi; không xuất dataset khi gate FAIL.",
        "Muốn cập nhật Markdown từ run đã duyệt mà không tạo thêm dataset: thêm --report-only.", "",
    ]
    (ROOT / "docs/day4_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-end", type=date.fromisoformat, default=date(2026, 1, 30))
    parser.add_argument("--source-namespace", help="Explicit source namespace; otherwise use the last approved source, or raw.")
    parser.add_argument("--report-only", action="store_true", help="Refresh Markdown from the current approved run without rebuilding data.")
    args = parser.parse_args()
    if args.report_only:
        pointer = json.loads((ROOT / "data/features/current.json").read_text())
        output = Path(pointer["path"])
        write_report(json.loads((output / "quality_report.json").read_text()),
                     json.loads((output / "class_weights.json").read_text()), output)
    else:
        sys.exit(run(args))
