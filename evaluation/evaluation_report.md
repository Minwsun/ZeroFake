# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE

**Ngày đánh giá**: 2025-12-20 00:21:33
**Tổng số mẫu**: 1000

## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)

### Ma trận nhầm lẫn (Confusion Matrix)

| Thực tế \ Dự đoán | TIN THẬT | TIN GIẢ |
|-------------------|----------|---------|
| **TIN THẬT** | 381 | 119 |
| **TIN GIẢ** | 255 | 245 |

### Các chỉ số hiệu suất

| Chỉ số | Giá trị | Mục tiêu | Đánh giá |
|--------|---------|----------|----------|
| **Accuracy** | 62.60% | > 80% | ✗ Chưa đạt |
| **Macro-F1** | 61.90% | > 80% | ✗ Chưa đạt |
| **FNR (Bỏ lọt tin giả)** | 51.00% | < 10% | ✗ Chưa đạt |
| **FPR (Vu oan tin thật)** | 51.00% | < 15% | ✗ Chưa đạt |

### F1-Score theo từng lớp

| Lớp | Precision | Recall | F1-Score |
|-----|-----------|--------|----------|
| TIN THẬT | 59.91% | 76.20% | 67.08% |
| TIN GIẢ | 67.31% | 49.00% | 56.71% |

## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)

| Chỉ số | Giá trị | Ý nghĩa |
|--------|---------|---------|
| **Evidence Relevance** | 11.60% | Tỷ lệ có bằng chứng liên quan |
| **Dialectic Quality** | 0.00% | Chất lượng tranh biện Red/Blue |
| **Reasoning Consistency** | 30.00% | Lý do khớp với kết luận |

## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)

| Chỉ số | Giá trị | Mục tiêu |
|--------|---------|----------|
| **Latency trung bình** | 73.97s | < 15s |
| **Latency P50** | 69.61s | - |
| **Latency P95** | 122.74s | - |
| **Latency tối đa** | 229.82s | - |
| **Cache Hit Rate** | 0.00% | - |

## KẾT QUẢ THEO LĨNH VỰC

| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |
|----------|----------|--------|----------|
| Địa lý | 100.00% | 1 | ✓ |
| Thời tiết | 86.05% | 43 | ✓ |
| Kinh tế | 78.87% | 71 | ✓ |
| Thể thao | 78.08% | 73 | ✓ |
| Quốc tế | 76.36% | 55 | ✓ |
| Xã hội | 75.38% | 65 | ✓ |
| Chính trị | 73.44% | 64 | ✓ |
| Khoa học | 72.55% | 51 | ✓ |
| Văn hóa | 71.43% | 42 | ✓ |
| Công nghệ | 71.43% | 35 | ✓ |
| Zombie News | 68.60% | 86 | ⚠ |
| Xuyên tạc | 53.66% | 82 | ⚠ |
| Lừa đảo | 48.11% | 106 | ✗ |
| Y tế sai | 42.45% | 139 | ✗ |
| Bịa đặt | 36.78% | 87 | ✗ |

## TỔNG KẾT

- **Tổng số mẫu đánh giá**: 1000
- **Số dự đoán đúng**: 626
- **Accuracy tổng thể**: 62.60%
- **Thời gian đánh giá**: 1233 phút