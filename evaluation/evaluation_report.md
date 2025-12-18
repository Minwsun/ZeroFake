# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE

**Ngày đánh giá**: 2025-12-19 00:51:45
**Tổng số mẫu**: 10

## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)

### Ma trận nhầm lẫn (Confusion Matrix)

| Thực tế \ Dự đoán | TIN THẬT | TIN GIẢ | GÂY HIỂU LẦM |
|-------------------|----------|---------|--------------|
| **TIN THẬT** | 5 | 2 | 0 |
| **TIN GIẢ** | 0 | 3 | 0 |
| **GÂY HIỂU LẦM** | 0 | 0 | 0 |

### Các chỉ số hiệu suất

| Chỉ số | Giá trị | Mục tiêu | Đánh giá |
|--------|---------|----------|----------|
| **Accuracy** | 80.00% | > 80% | ✗ Chưa đạt |
| **Macro-F1** | 52.78% | > 80% | ✗ Chưa đạt |
| **FNR (Bỏ lọt tin giả)** | 0.00% | < 10% | ✓ Đạt |
| **FPR (Vu oan tin thật)** | 0.00% | < 15% | ✓ Đạt |

### F1-Score theo từng lớp

| Lớp | Precision | Recall | F1-Score |
|-----|-----------|--------|----------|
| TIN THẬT | 100.00% | 71.43% | 83.33% |
| TIN GIẢ | 60.00% | 100.00% | 75.00% |
| GÂY HIỂU LẦM | 0.00% | 0.00% | 0.00% |

## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)

| Chỉ số | Giá trị | Ý nghĩa |
|--------|---------|---------|
| **Evidence Relevance** | 10.00% | Tỷ lệ có bằng chứng liên quan |
| **Dialectic Quality** | 0.00% | Chất lượng tranh biện Red/Blue |
| **Reasoning Consistency** | 20.00% | Lý do khớp với kết luận |

## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)

| Chỉ số | Giá trị | Mục tiêu |
|--------|---------|----------|
| **Latency trung bình** | 105.41s | < 15s |
| **Latency P50** | 103.50s | - |
| **Latency P95** | 130.93s | - |
| **Latency tối đa** | 131.38s | - |
| **Cache Hit Rate** | 0.00% | - |

## KẾT QUẢ THEO LĨNH VỰC

| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |
|----------|----------|--------|----------|
| Zombie News | 100.00% | 2 | ✓ |
| Xã hội | 100.00% | 2 | ✓ |
| Chính trị | 100.00% | 1 | ✓ |
| Bịa đặt | 100.00% | 1 | ✓ |
| Văn hóa | 100.00% | 1 | ✓ |
| Thể thao | 50.00% | 2 | ✗ |
| Quốc tế | 0.00% | 1 | ✗ |

## TỔNG KẾT

- **Tổng số mẫu đánh giá**: 10
- **Số dự đoán đúng**: 8
- **Accuracy tổng thể**: 80.00%
- **Thời gian đánh giá**: 17 phút