# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE

**Ngày đánh giá**: 2025-12-22 04:29:00
**Tổng số mẫu**: 10

## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)

### Ma trận nhầm lẫn (Confusion Matrix)

| Thực tế \ Dự đoán | TIN THẬT | TIN GIẢ |
|-------------------|----------|---------|
| **TIN THẬT** | 3 | 1 |
| **TIN GIẢ** | 0 | 6 |

### Các chỉ số hiệu suất

| Chỉ số | Giá trị | Mục tiêu | Đánh giá |
|--------|---------|----------|----------|
| **Accuracy** | 90.00% | > 80% | ✓ Đạt |
| **Macro-F1** | 89.01% | > 80% | ✓ Đạt |
| **FNR (Bỏ lọt tin giả)** | 0.00% | < 10% | ✓ Đạt |
| **FPR (Vu oan tin thật)** | 0.00% | < 15% | ✓ Đạt |

### F1-Score theo từng lớp

| Lớp | Precision | Recall | F1-Score |
|-----|-----------|--------|----------|
| TIN THẬT | 100.00% | 75.00% | 85.71% |
| TIN GIẢ | 85.71% | 100.00% | 92.31% |

## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)

| Chỉ số | Giá trị | Ý nghĩa |
|--------|---------|---------|
| **Evidence Relevance** | 0.00% | Tỷ lệ có bằng chứng liên quan |
| **Dialectic Quality** | 0.00% | Chất lượng tranh biện Red/Blue |
| **Reasoning Consistency** | 70.00% | Lý do khớp với kết luận |

## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)

| Chỉ số | Giá trị | Mục tiêu |
|--------|---------|----------|
| **Latency trung bình** | 58.74s | < 15s |
| **Latency P50** | 53.91s | - |
| **Latency P95** | 84.03s | - |
| **Latency tối đa** | 88.40s | - |
| **Cache Hit Rate** | 0.00% | - |

## KẾT QUẢ THEO LĨNH VỰC

| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |
|----------|----------|--------|----------|
| other | 90.00% | 10 | ✓ |

## TỔNG KẾT

- **Tổng số mẫu đánh giá**: 10
- **Số dự đoán đúng**: 9
- **Accuracy tổng thể**: 90.00%
- **Thời gian đánh giá**: 9 phút