# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE

**Ngày đánh giá**: 2025-12-22 04:15:06
**Tổng số mẫu**: 10

## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)

### Ma trận nhầm lẫn (Confusion Matrix)

| Thực tế \ Dự đoán | TIN THẬT | TIN GIẢ |
|-------------------|----------|---------|
| **TIN THẬT** | 2 | 2 |
| **TIN GIẢ** | 0 | 6 |

### Các chỉ số hiệu suất

| Chỉ số | Giá trị | Mục tiêu | Đánh giá |
|--------|---------|----------|----------|
| **Accuracy** | 80.00% | > 80% | ✗ Chưa đạt |
| **Macro-F1** | 76.19% | > 80% | ✗ Chưa đạt |
| **FNR (Bỏ lọt tin giả)** | 0.00% | < 10% | ✓ Đạt |
| **FPR (Vu oan tin thật)** | 0.00% | < 15% | ✓ Đạt |

### F1-Score theo từng lớp

| Lớp | Precision | Recall | F1-Score |
|-----|-----------|--------|----------|
| TIN THẬT | 100.00% | 50.00% | 66.67% |
| TIN GIẢ | 75.00% | 100.00% | 85.71% |

## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)

| Chỉ số | Giá trị | Ý nghĩa |
|--------|---------|---------|
| **Evidence Relevance** | 0.00% | Tỷ lệ có bằng chứng liên quan |
| **Dialectic Quality** | 0.00% | Chất lượng tranh biện Red/Blue |
| **Reasoning Consistency** | 70.00% | Lý do khớp với kết luận |

## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)

| Chỉ số | Giá trị | Mục tiêu |
|--------|---------|----------|
| **Latency trung bình** | 24.94s | < 15s |
| **Latency P50** | 23.54s | - |
| **Latency P95** | 36.40s | - |
| **Latency tối đa** | 37.15s | - |
| **Cache Hit Rate** | 0.00% | - |

## KẾT QUẢ THEO LĨNH VỰC

| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |
|----------|----------|--------|----------|
| other | 80.00% | 10 | ✓ |

## TỔNG KẾT

- **Tổng số mẫu đánh giá**: 10
- **Số dự đoán đúng**: 8
- **Accuracy tổng thể**: 80.00%
- **Thời gian đánh giá**: 4 phút