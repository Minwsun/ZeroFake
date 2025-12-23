# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE

**Ngày đánh giá**: 2025-12-23 15:59:09
**Tổng số mẫu**: 100

## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)

### Ma trận nhầm lẫn (Confusion Matrix)

| Thực tế \ Dự đoán | TIN THẬT | TIN GIẢ |
|-------------------|----------|---------|
| **TIN THẬT** | 47 | 2 |
| **TIN GIẢ** | 5 | 46 |

### Các chỉ số hiệu suất

| Chỉ số | Giá trị | Mục tiêu | Đánh giá |
|--------|---------|----------|----------|
| **Accuracy** | 93.00% | > 80% | ✓ Đạt |
| **Macro-F1** | 93.00% | > 80% | ✓ Đạt |
| **FNR (Bỏ lọt tin giả)** | 9.80% | < 10% | ✓ Đạt |
| **FPR (Vu oan tin thật)** | 9.80% | < 15% | ✓ Đạt |

### F1-Score theo từng lớp

| Lớp | Precision | Recall | F1-Score |
|-----|-----------|--------|----------|
| TIN THẬT | 90.38% | 95.92% | 93.07% |
| TIN GIẢ | 95.83% | 90.20% | 92.93% |

## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)

| Chỉ số | Giá trị | Ý nghĩa |
|--------|---------|---------|
| **Evidence Relevance** | 100.00% | Tỷ lệ có bằng chứng liên quan |
| **Dialectic Quality** | 0.00% | Chất lượng tranh biện Red/Blue |
| **Reasoning Consistency** | 47.00% | Lý do khớp với kết luận |

## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)

| Chỉ số | Giá trị | Mục tiêu |
|--------|---------|----------|
| **Latency trung bình** | 84.15s | < 15s |
| **Latency P50** | 81.84s | - |
| **Latency P95** | 111.38s | - |
| **Latency tối đa** | 128.56s | - |
| **Cache Hit Rate** | 0.00% | - |

## KẾT QUẢ THEO LĨNH VỰC

| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |
|----------|----------|--------|----------|
| other | 93.00% | 100 | ✓ |

## TỔNG KẾT

- **Tổng số mẫu đánh giá**: 100
- **Số dự đoán đúng**: 93
- **Accuracy tổng thể**: 93.00%
- **Thời gian đánh giá**: 57 phút