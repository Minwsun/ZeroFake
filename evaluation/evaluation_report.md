# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE

**Ngày đánh giá**: 2025-12-23 18:04:51
**Tổng số mẫu**: 100

## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)

### Ma trận nhầm lẫn (Confusion Matrix)

| Thực tế \ Dự đoán | TIN THẬT | TIN GIẢ |
|-------------------|----------|---------|
| **TIN THẬT** | 43 | 2 |
| **TIN GIẢ** | 3 | 51 |

### Các chỉ số hiệu suất

| Chỉ số | Giá trị | Mục tiêu | Đánh giá |
|--------|---------|----------|----------|
| **Accuracy** | 94.95% | > 80% | ✓ Đạt |
| **Macro-F1** | 94.92% | > 80% | ✓ Đạt |
| **FNR (Bỏ lọt tin giả)** | 5.56% | < 10% | ✓ Đạt |
| **FPR (Vu oan tin thật)** | 5.56% | < 15% | ✓ Đạt |

### F1-Score theo từng lớp

| Lớp | Precision | Recall | F1-Score |
|-----|-----------|--------|----------|
| TIN THẬT | 93.48% | 95.56% | 94.51% |
| TIN GIẢ | 96.23% | 94.44% | 95.33% |

## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)

| Chỉ số | Giá trị | Ý nghĩa |
|--------|---------|---------|
| **Evidence Relevance** | 99.00% | Tỷ lệ có bằng chứng liên quan |
| **Dialectic Quality** | 0.00% | Chất lượng tranh biện Red/Blue |
| **Reasoning Consistency** | 45.00% | Lý do khớp với kết luận |

## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)

| Chỉ số | Giá trị | Mục tiêu |
|--------|---------|----------|
| **Latency trung bình** | 107.72s | < 15s |
| **Latency P50** | 99.92s | - |
| **Latency P95** | 171.90s | - |
| **Latency tối đa** | 213.17s | - |
| **Cache Hit Rate** | 0.00% | - |

## KẾT QUẢ THEO LĨNH VỰC

| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |
|----------|----------|--------|----------|
| other | 94.00% | 100 | ✓ |

## TỔNG KẾT

- **Tổng số mẫu đánh giá**: 100
- **Số dự đoán đúng**: 94
- **Accuracy tổng thể**: 94.00%
- **Thời gian đánh giá**: 74 phút