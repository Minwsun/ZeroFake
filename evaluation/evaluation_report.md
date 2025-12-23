# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE

**Ngày đánh giá**: 2025-12-23 20:38:51
**Tổng số mẫu**: 100

## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)

### Ma trận nhầm lẫn (Confusion Matrix)

| Thực tế \ Dự đoán | TIN THẬT | TIN GIẢ |
|-------------------|----------|---------|
| **TIN THẬT** | 52 | 2 |
| **TIN GIẢ** | 9 | 37 |

### Các chỉ số hiệu suất

| Chỉ số | Giá trị | Mục tiêu | Đánh giá |
|--------|---------|----------|----------|
| **Accuracy** | 89.00% | > 80% | ✓ Đạt |
| **Macro-F1** | 88.75% | > 80% | ✓ Đạt |
| **FNR (Bỏ lọt tin giả)** | 19.57% | < 10% | ✗ Chưa đạt |
| **FPR (Vu oan tin thật)** | 19.57% | < 15% | ✗ Chưa đạt |

### F1-Score theo từng lớp

| Lớp | Precision | Recall | F1-Score |
|-----|-----------|--------|----------|
| TIN THẬT | 85.25% | 96.30% | 90.43% |
| TIN GIẢ | 94.87% | 80.43% | 87.06% |

## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)

| Chỉ số | Giá trị | Ý nghĩa |
|--------|---------|---------|
| **Evidence Relevance** | 100.00% | Tỷ lệ có bằng chứng liên quan |
| **Dialectic Quality** | 0.00% | Chất lượng tranh biện Red/Blue |
| **Reasoning Consistency** | 55.00% | Lý do khớp với kết luận |

## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)

| Chỉ số | Giá trị | Mục tiêu |
|--------|---------|----------|
| **Latency trung bình** | 130.85s | < 15s |
| **Latency P50** | 132.67s | - |
| **Latency P95** | 199.36s | - |
| **Latency tối đa** | 232.36s | - |
| **Cache Hit Rate** | 0.00% | - |

## KẾT QUẢ THEO LĨNH VỰC

| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |
|----------|----------|--------|----------|
| other | 89.00% | 100 | ✓ |

## TỔNG KẾT

- **Tổng số mẫu đánh giá**: 100
- **Số dự đoán đúng**: 89
- **Accuracy tổng thể**: 89.00%
- **Thời gian đánh giá**: 89 phút