import json
import os
import time
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import seaborn as sns
from sklearn.exceptions import UndefinedMetricWarning
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from tqdm import tqdm

API_URL = "http://127.0.0.1:8000/check_news"
INPUT_FILE = "test_data_1000.jsonl"
CACHE_DB_PATH = "data/kb_content.db"
LABELS = ["TIN THẬT", "TIN GIẢ", "GÂY HIỂU LẦM"]

warnings.filterwarnings("ignore", category=UndefinedMetricWarning)


def clear_cache() -> None:
    """Xóa cache DB để đảm bảo mỗi lần chạy là một lần kiểm thử mới."""
    if os.path.exists(CACHE_DB_PATH):
        try:
            os.remove(CACHE_DB_PATH)
            print(f"Đã xóa cache cũ: {CACHE_DB_PATH}")
        except Exception as exc:
            print(f"Không thể xóa cache: {exc}. Vui lòng xóa thủ công rồi tiếp tục.")
            input("Nhấn Enter để tiếp tục khi bạn đã dọn cache...")
    else:
        print("Cache đã sạch.")


def load_test_data() -> list[dict] | None:
    """Tải dữ liệu từ file .jsonl."""
    samples = []
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as file:
            for line in file:
                samples.append(json.loads(line))
        return samples
    except FileNotFoundError:
        print(f"Lỗi: Không tìm thấy file {INPUT_FILE}. Hãy chạy generate_test_data.py trước.")
        return None
    except Exception as exc:
        print(f"Lỗi khi đọc file data: {exc}")
        return None


def calculate_fnr_fpr_per_class(cm: np.ndarray, labels: list[str]) -> dict:
    """Tính FNR và FPR cho từng lớp."""
    metrics: dict[str, dict[str, float]] = {}
    for i, label in enumerate(labels):
        tp = cm[i, i]
        fn = cm[i, :].sum() - tp
        fp = cm[:, i].sum() - tp
        tn = cm.sum() - (cm[i, :].sum() + cm[:, i].sum() - tp)
        fnr = fn / (fn + tp) if (fn + tp) > 0 else 0.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
        metrics[label] = {"FNR": fnr, "FPR": fpr}
    return metrics


def plot_confusion_matrix(cm: np.ndarray, labels: list[str], filename: str = "evaluation_confusion_matrix.png") -> None:
    """Vẽ và lưu ma trận nhầm lẫn."""
    plt.figure(figsize=(10, 7))
    ax = sns.heatmap(
        cm,
        annot=True,
        fmt="d",
        cmap="Blues",
        xticklabels=labels,
        yticklabels=labels,
    )
    ax.set_title("Ma trận nhầm lẫn (Confusion Matrix)", fontsize=16)
    ax.set_xlabel("Dự đoán (Predicted)", fontsize=12)
    ax.set_ylabel("Thực tế (Actual)", fontsize=12)
    plt.savefig(filename)
    print(f"\nĐã lưu biểu đồ ma trận nhầm lẫn vào '{filename}'")


def run_evaluation() -> None:
    samples = load_test_data()
    if not samples:
        return

    print(f"Đã tải {len(samples)} mẫu kiểm thử từ {INPUT_FILE}.")
    clear_cache()
    print("Vui lòng đảm bảo server ZeroFake đang chạy (run_server.bat)...")
    time.sleep(2)

    y_true: list[str] = []
    y_pred: list[str] = []

    pbar = tqdm(samples, desc="Running Batch Evaluation")
    for sample in pbar:
        text = sample.get("text")
        ground_truth = sample.get("ground_truth")
        if not text or ground_truth not in LABELS:
            continue

        payload = {
            "text": text,
            "flash_mode": True,
            "agent1_model": "models/gemini-2.5-flash",
            "agent2_model": "models/gemini-2.5-pro",
        }

        prediction = None
        try:
            response = requests.post(API_URL, json=payload, timeout=120)
            if response.status_code == 200:
                result = response.json()
                prediction = result.get("conclusion")
            else:
                print(f"Lỗi API: {response.status_code} cho text: {text[:50]}...")
        except requests.exceptions.RequestException as exc:
            print(f"Lỗi kết nối: {exc} cho text: {text[:50]}...")

        if prediction in LABELS:
            y_true.append(ground_truth)
            y_pred.append(prediction)
        else:
            print(f"Bỏ qua mẫu do dự đoán không hợp lệ: {prediction}")

    print("\n--- Hoàn tất chạy kiểm thử ---")
    if not y_true:
        print("Không có kết quả hợp lệ nào. Kiểm tra lại kết nối server.")
        return

    print(f"Tổng số mẫu đã đánh giá thành công: {len(y_true)}")

    acc = accuracy_score(y_true, y_pred)
    print("\n--- 1. Chỉ số Tổng quan ---")
    print(f"Accuracy (ACC): {acc:.4f}")

    report_dict = classification_report(
        y_true,
        y_pred,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )

    print("\n--- 2. Báo cáo Chi tiết (F1, Precision, Recall) ---")
    print(f"{'':<15} {'Precision':<10} {'Recall':<10} {'F1-Score':<10} {'Support':<10}")
    print("-" * 55)
    for label in LABELS:
        metrics = report_dict.get(label, {})
        print(
            f"{label:<15} {metrics.get('precision', 0.0):<10.4f} "
            f"{metrics.get('recall', 0.0):<10.4f} {metrics.get('f1-score', 0.0):<10.4f} "
            f"{metrics.get('support', 0):<10}"
        )
    print("-" * 55)
    macro_avg = report_dict.get("macro avg", {})
    print(
        f"{'Macro Avg':<15} {macro_avg.get('precision', 0.0):<10.4f} "
        f"{macro_avg.get('recall', 0.0):<10.4f} {macro_avg.get('f1-score', 0.0):<10.4f} "
        f"{macro_avg.get('support', 0):<10}"
    )

    cm = confusion_matrix(y_true, y_pred, labels=LABELS)
    print("\n--- 3. Chỉ số FNR (Bỏ lỡ) và FPR (Báo động nhầm) ---")
    fnr_fpr_metrics = calculate_fnr_fpr_per_class(cm, LABELS)
    print(f"{'Lớp':<15} {'FNR (Bỏ lỡ)':<15} {'FPR (Báo động nhầm)':<20}")
    print("-" * 55)
    for label, metrics in fnr_fpr_metrics.items():
        print(f"{label:<15} {metrics['FNR']:<15.4f} {metrics['FPR']:<20.4f}")

    plot_confusion_matrix(cm, LABELS)


if __name__ == "__main__":
    run_evaluation()
