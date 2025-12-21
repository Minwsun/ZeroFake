# BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN ZEROFAKE

**Ngày đánh giá**: 2025-12-22 04:41:52
**Tổng số mẫu**: 10

## TẦNG 1: HIỆU SUẤT PHÂN LOẠI (Quantitative Metrics)

### Ma trận nhầm lẫn (Confusion Matrix)

| Thực tế \ Dự đoán | TIN THẬT | TIN GIẢ |
|-------------------|----------|---------|
| **TIN THẬT** | 0 | 0 |
| **TIN GIẢ** | 0 | 0 |

### Các chỉ số hiệu suất

| Chỉ số | Giá trị | Mục tiêu | Đánh giá |
|--------|---------|----------|----------|
| **Accuracy** | 0.00% | > 80% | ✗ Chưa đạt |
| **Macro-F1** | 0.00% | > 80% | ✗ Chưa đạt |
| **FNR (Bỏ lọt tin giả)** | 0.00% | < 10% | ✓ Đạt |
| **FPR (Vu oan tin thật)** | 0.00% | < 15% | ✓ Đạt |

### F1-Score theo từng lớp

| Lớp | Precision | Recall | F1-Score |
|-----|-----------|--------|----------|
| TIN THẬT | 0.00% | 0.00% | 0.00% |
| TIN GIẢ | 0.00% | 0.00% | 0.00% |

## TẦNG 2: CHẤT LƯỢNG SUY LUẬN (Qualitative Metrics)

| Chỉ số | Giá trị | Ý nghĩa |
|--------|---------|---------|
| **Evidence Relevance** | 0.00% | Tỷ lệ có bằng chứng liên quan |
| **Dialectic Quality** | 0.00% | Chất lượng tranh biện Red/Blue |
| **Reasoning Consistency** | 0.00% | Lý do khớp với kết luận |

## TẦNG 3: HIỆU NĂNG HỆ THỐNG (Operational Metrics)

| Chỉ số | Giá trị | Mục tiêu |
|--------|---------|----------|
| **Cache Hit Rate** | 0.00% | - |

## KẾT QUẢ THEO LĨNH VỰC

| Lĩnh vực | Accuracy | Số mẫu | Đánh giá |
|----------|----------|--------|----------|
| other | 0.00% | 10 | ✗ |

## TỔNG KẾT

- **Tổng số mẫu đánh giá**: 10
- **Số dự đoán đúng**: 0
- **Accuracy tổng thể**: 0.00%
- **Thời gian đánh giá**: 0 phút