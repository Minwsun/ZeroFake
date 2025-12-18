"""
ZeroFake Comprehensive Evaluation Framework
3-Tier Metrics: Quantitative, Reasoning Quality, Operational
"""
import json
import time
import requests
from datetime import datetime
from collections import Counter, defaultdict
import numpy as np

API_URL = "http://127.0.0.1:8000/check_news"
DELAY_SECONDS = 0  # No rate limiting needed

class EvaluationFramework:
    def __init__(self, dataset_path="evaluation/test_dataset_1000.json"):
        with open(dataset_path, "r", encoding="utf-8") as f:
            self.dataset = json.load(f)
        self.results = []
        self.start_time = None
        
    def run_evaluation(self, limit=None):
        """Run evaluation on dataset"""
        self.start_time = datetime.now()
        samples = self.dataset[:limit] if limit else self.dataset
        
        print("=" * 70)
        print(f"ZEROFAKE COMPREHENSIVE EVALUATION")
        print(f"Samples: {len(samples)} | Rate limit: {DELAY_SECONDS}s")
        print(f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        for i, sample in enumerate(samples, 1):
            try:
                start = time.time()
                r = requests.post(API_URL, json={"text": sample["text"]}, timeout=300)
                elapsed = time.time() - start
                result = r.json()
                
                self.results.append({
                    "text": sample["text"],
                    "expected": sample["expected"],
                    "predicted": result.get("conclusion", "ERROR"),
                    "category": sample["category"],
                    "reason": result.get("reason", "")[:200],
                    "debate_log": result.get("debate_log", {}),
                    "evidence_link": result.get("evidence_link", ""),
                    "latency": round(elapsed, 2),
                    "cached": result.get("cached", False)
                })
                
                status = "✓" if sample["expected"] == result.get("conclusion") else "✗"
                print(f"[{i}/{len(samples)}] {status} {sample['text'][:40]}... => {result.get('conclusion')} ({elapsed:.1f}s)")
                
            except Exception as e:
                self.results.append({
                    "text": sample["text"],
                    "expected": sample["expected"],
                    "predicted": "ERROR",
                    "category": sample["category"],
                    "reason": str(e)[:200],
                    "debate_log": {},
                    "evidence_link": "",
                    "latency": 0,
                    "cached": False
                })
                print(f"[{i}/{len(samples)}] ✗ ERROR: {e}")
            
            if i < len(samples):
                time.sleep(DELAY_SECONDS)
        
        self._save_results()
        return self.generate_report()
    
    def _save_results(self):
        with open("evaluation/evaluation_results.json", "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=2)
    
    def generate_report(self):
        """Generate comprehensive evaluation report"""
        report = []
        report.append("# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE")
        report.append(f"\n**Ngày đánh giá**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"**Tổng số mẫu**: {len(self.results)}")
        
        # ══════════════════════════════════════════════════════════════════
        # TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)
        # ══════════════════════════════════════════════════════════════════
        report.append("\n## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)\n")
        
        # Confusion Matrix (Binary Classification)
        labels = ["TIN THẬT", "TIN GIẢ"]
        cm = self._confusion_matrix(labels)
        
        report.append("### Ma trận nhầm lẫn (Confusion Matrix)\n")
        report.append("| Thực tế \\ Dự đoán | TIN THẬT | TIN GIẢ |")
        report.append("|-------------------|----------|---------|")
        for i, actual in enumerate(labels):
            row = f"| **{actual}** |"
            for j in range(len(labels)):
                row += f" {cm[i][j]} |"
            report.append(row)
        
        # Calculate metrics
        metrics = self._calculate_metrics(cm, labels)
        
        report.append("\n### Các chỉ số hiệu suất\n")
        report.append("| Chỉ số | Giá trị | Mục tiêu | Đánh giá |")
        report.append("|--------|---------|----------|----------|")
        report.append(f"| **Accuracy** | {metrics['accuracy']:.2%} | > 80% | {'✓ Đạt' if metrics['accuracy'] > 0.8 else '✗ Chưa đạt'} |")
        report.append(f"| **Macro-F1** | {metrics['macro_f1']:.2%} | > 80% | {'✓ Đạt' if metrics['macro_f1'] > 0.8 else '✗ Chưa đạt'} |")
        report.append(f"| **FNR (Bỏ lọt tin giả)** | {metrics['fnr']:.2%} | < 10% | {'✓ Đạt' if metrics['fnr'] < 0.1 else '✗ Chưa đạt'} |")
        report.append(f"| **FPR (Vu oan tin thật)** | {metrics['fpr']:.2%} | < 15% | {'✓ Đạt' if metrics['fpr'] < 0.15 else '✗ Chưa đạt'} |")
        
        report.append("\n### F1-Score theo từng lớp\n")
        report.append("| Lớp | Precision | Recall | F1-Score |")
        report.append("|-----|-----------|--------|----------|")
        for label in labels:
            p = metrics['precision'].get(label, 0)
            r = metrics['recall'].get(label, 0)
            f = metrics['f1'].get(label, 0)
            report.append(f"| {label} | {p:.2%} | {r:.2%} | {f:.2%} |")
        
        # ══════════════════════════════════════════════════════════════════
        # TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)
        # ══════════════════════════════════════════════════════════════════
        report.append("\n## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)\n")
        
        qualitative = self._calculate_qualitative_metrics()
        
        report.append("| Chỉ số | Giá trị | Ý nghĩa |")
        report.append("|--------|---------|---------|")
        report.append(f"| **Evidence Relevance** | {qualitative['evidence_relevance']:.2%} | Tỷ lệ có bằng chứng liên quan |")
        report.append(f"| **Dialectic Quality** | {qualitative['dialectic_quality']:.2%} | Chất lượng tranh biện Red/Blue |")
        report.append(f"| **Reasoning Consistency** | {qualitative['reasoning_consistency']:.2%} | Lý do khớp với kết luận |")
        
        # ══════════════════════════════════════════════════════════════════
        # TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)
        # ══════════════════════════════════════════════════════════════════
        report.append("\n## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)\n")
        
        latencies = [r["latency"] for r in self.results if r["latency"] > 0]
        
        report.append("| Chỉ số | Giá trị | Mục tiêu |")
        report.append("|--------|---------|----------|")
        if latencies:
            report.append(f"| **Latency trung bình** | {np.mean(latencies):.2f}s | < 15s |")
            report.append(f"| **Latency P50** | {np.percentile(latencies, 50):.2f}s | - |")
            report.append(f"| **Latency P95** | {np.percentile(latencies, 95):.2f}s | - |")
            report.append(f"| **Latency tối đa** | {max(latencies):.2f}s | - |")
        
        cache_rate = sum(1 for r in self.results if r.get("cached")) / len(self.results)
        report.append(f"| **Cache Hit Rate** | {cache_rate:.2%} | - |")
        
        # ══════════════════════════════════════════════════════════════════
        # KẾT QUẢ THEO CATEGORY
        # ══════════════════════════════════════════════════════════════════
        report.append("\n## KẾT QUẢ THEO LĨNH VỰC\n")
        
        cat_accuracy = self._accuracy_by_category()
        report.append("| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |")
        report.append("|----------|----------|--------|----------|")
        for cat, acc in sorted(cat_accuracy.items(), key=lambda x: -x[1]):
            count = sum(1 for r in self.results if r["category"] == cat)
            status = "✓" if acc > 0.7 else "⚠" if acc > 0.5 else "✗"
            report.append(f"| {cat} | {acc:.2%} | {count} | {status} |")
        
        # ══════════════════════════════════════════════════════════════════
        # TỔNG KẾT
        # ══════════════════════════════════════════════════════════════════
        report.append("\n## TỔNG KẾT\n")
        
        total_correct = sum(1 for r in self.results if r["expected"] == r["predicted"])
        total_samples = len(self.results)
        
        report.append(f"- **Tổng số mẫu đánh giá**: {total_samples}")
        report.append(f"- **Số dự đoán đúng**: {total_correct}")
        report.append(f"- **Accuracy tổng thể**: {total_correct/total_samples:.2%}")
        report.append(f"- **Thời gian đánh giá**: {(datetime.now() - self.start_time).seconds // 60} phút")
        
        # Save report
        report_text = "\n".join(report)
        with open("evaluation/evaluation_report.md", "w", encoding="utf-8") as f:
            f.write(report_text)
        
        print("\n" + "=" * 70)
        print("EVALUATION COMPLETE!")
        print(f"Report saved to: evaluation/evaluation_report.md")
        print("=" * 70)
        
        return report_text
    
    def _confusion_matrix(self, labels):
        cm = [[0] * len(labels) for _ in range(len(labels))]
        label_to_idx = {l: i for i, l in enumerate(labels)}
        
        for r in self.results:
            actual = r["expected"]
            predicted = r["predicted"]
            if actual in label_to_idx and predicted in label_to_idx:
                cm[label_to_idx[actual]][label_to_idx[predicted]] += 1
        return cm
    
    def _calculate_metrics(self, cm, labels):
        total = sum(sum(row) for row in cm)
        correct = sum(cm[i][i] for i in range(len(labels)))
        accuracy = correct / total if total > 0 else 0
        
        precision = {}
        recall = {}
        f1 = {}
        
        for i, label in enumerate(labels):
            tp = cm[i][i]
            fp = sum(cm[j][i] for j in range(len(labels))) - tp
            fn = sum(cm[i]) - tp
            
            p = tp / (tp + fp) if (tp + fp) > 0 else 0
            r = tp / (tp + fn) if (tp + fn) > 0 else 0
            f = 2 * p * r / (p + r) if (p + r) > 0 else 0
            
            precision[label] = p
            recall[label] = r
            f1[label] = f
        
        macro_f1 = np.mean(list(f1.values()))
        
        # FNR for TIN GIẢ: False Negatives / (True Positives + False Negatives)
        fake_idx = labels.index("TIN GIẢ")
        fake_tp = cm[fake_idx][fake_idx]
        fake_fn = sum(cm[fake_idx]) - fake_tp
        fnr = fake_fn / (fake_tp + fake_fn) if (fake_tp + fake_fn) > 0 else 0
        
        # FPR for TIN THẬT: False Positives / (True Negatives + False Positives)
        real_idx = labels.index("TIN THẬT")
        real_fp = sum(cm[j][real_idx] for j in range(len(labels))) - cm[real_idx][real_idx]
        real_tn = total - sum(cm[real_idx]) - real_fp
        fpr = real_fp / (real_tn + real_fp) if (real_tn + real_fp) > 0 else 0
        
        return {
            "accuracy": accuracy,
            "macro_f1": macro_f1,
            "fnr": fnr,
            "fpr": fpr,
            "precision": precision,
            "recall": recall,
            "f1": f1
        }
    
    def _calculate_qualitative_metrics(self):
        evidence_count = sum(1 for r in self.results if r.get("evidence_link"))
        dialectic_count = 0
        consistency_count = 0
        
        for r in self.results:
            debate = r.get("debate_log", {})
            if debate:
                red = debate.get("red_team_argument", "")
                blue = debate.get("blue_team_argument", "")
                if red and blue and red != blue:
                    dialectic_count += 1
            
            # Check reasoning consistency
            reason = r.get("reason", "").lower()
            pred = r.get("predicted", "")
            if pred == "TIN THẬT" and ("đúng" in reason or "xác nhận" in reason or "thật" in reason):
                consistency_count += 1
            elif pred == "TIN GIẢ" and ("sai" in reason or "giả" in reason or "không có" in reason or "lỗi thời" in reason or "cũ" in reason):
                consistency_count += 1
        
        total = len(self.results)
        return {
            "evidence_relevance": evidence_count / total if total > 0 else 0,
            "dialectic_quality": dialectic_count / total if total > 0 else 0,
            "reasoning_consistency": consistency_count / total if total > 0 else 0
        }
    
    def _accuracy_by_category(self):
        cat_correct = defaultdict(int)
        cat_total = defaultdict(int)
        
        for r in self.results:
            cat = r["category"]
            cat_total[cat] += 1
            if r["expected"] == r["predicted"]:
                cat_correct[cat] += 1
        
        return {cat: cat_correct[cat] / cat_total[cat] for cat in cat_total}


if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    
    evaluator = EvaluationFramework()
    report = evaluator.run_evaluation(limit=limit)
    print("\n" + report)
