# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE

**Ngày đánh giá**: 2025-12-22 03:52:54
**Tổng số mẫu**: 10

## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)

### Ma trận nhầm lẫn (Confusion Matrix)

| Thực tế \ Dự đoán | TIN THẬT | TIN GIẢ |
|-------------------|----------|---------|
| **TIN THẬT** | 2 | 2 |
| **TIN GIẢ** | 1 | 5 |

### Các chỉ số hiệu suất

| Chỉ số | Giá trị | Mục tiêu | Đánh giá |
|--------|---------|----------|----------|
| **Accuracy** | 70.00% | > 80% | ✗ Chưa đạt |
| **Macro-F1** | 67.03% | > 80% | ✗ Chưa đạt |
| **FNR (Bỏ lọt tin giả)** | 16.67% | < 10% | ✗ Chưa đạt |
| **FPR (Vu oan tin thật)** | 16.67% | < 15% | ✗ Chưa đạt |

### F1-Score theo từng lớp

| Lớp | Precision | Recall | F1-Score |
|-----|-----------|--------|----------|
| TIN THẬT | 66.67% | 50.00% | 57.14% |
| TIN GIẢ | 71.43% | 83.33% | 76.92% |

## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)

| Chỉ số | Giá trị | Ý nghĩa |
|--------|---------|---------|
| **Evidence Relevance** | 10.00% | Tỷ lệ có bằng chứng liên quan |
| **Dialectic Quality** | 0.00% | Chất lượng tranh biện Red/Blue |
| **Reasoning Consistency** | 70.00% | Lý do khớp với kết luận |

## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)

| Chỉ số | Giá trị | Mục tiêu |
|--------|---------|----------|
| **Latency trung bình** | 44.67s | < 15s |
| **Latency P50** | 43.97s | - |
| **Latency P95** | 53.96s | - |
| **Latency tối đa** | 56.94s | - |
| **Cache Hit Rate** | 0.00% | - |

## KẾT QUẢ THEO LĨNH VỰC

| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |
|----------|----------|--------|----------|
| other | 70.00% | 10 | ⚠ |

## TỔNG KẾT

- **Tổng số mẫu đánh giá**: 10
- **Số dự đoán đúng**: 7
- **Accuracy tổng thể**: 70.00%
- **Thời gian đánh giá**: 7 phút