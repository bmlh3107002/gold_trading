# 38 — Giao thức đánh giá đăng ký trước cho GĐ6 (KN-07, BT-04) — BẢN NHÁP CHỜ DUYỆT

> 2026-11-17 · GĐ5 bước 9. Viết **trước** khi có bất kỳ kết quả backtest nào. Sau khi người dùng duyệt, giao thức này **khóa lại**: không đổi tiêu chí sau khi đã nhìn kết quả. Muốn đổi → ghi lý do, tăng phiên bản giao thức, và phần dữ liệu "để dành" đã dùng thì **không dùng lại** được.
>
> Đối tượng: chiến lược `xu-huong-m15@1.0.0` (thiết kế 36) với hồ sơ rủi ro của người dùng (H1–H11). Tham số: [`so-tham-so.md`](so-tham-so.md).

## 1. Câu hỏi cần trả lời (một câu)

**Sau khi trừ đủ chi phí, chiến lược có lợi thế thật hay không?** "Không có lợi thế" là kết quả **trung thực và hợp lệ** — khi đó không lên SHADOW / LIVE, không có gì là thất bại của việc kiểm tra.

Lưu ý đã biết từ trước (đánh giá độc lập): trên dữ liệu ngẫu nhiên, luật hiện tại vẫn báo "có xu hướng" ở khoảng 36 % số nến. Vì vậy **so với mốc ngẫu nhiên là bắt buộc**, không chỉ nhìn lãi / lỗ.

## 2. Dữ liệu

- Chỉ nến M15 **thật** XAUUSD của **chính sàn** người dùng (xuất từ MT5, nạp bằng `import-csv`), càng dài càng tốt — mục tiêu **≥ 2 năm** để có nhiều kiểu thị trường. Dữ liệu mẫu (SAMPLE): **không có giá trị đánh giá**, báo cáo ghi rõ.
- Chạy lại theo đúng thời điểm biết dữ liệu (point-in-time, BT-01), cùng phiên bản analyst / Fusion / Risk đang dùng.
- Chi phí (BT-02): spread thật theo từng nến; đệm trượt giá như Risk (p95 30 ngày trước đó); phí / lot người dùng nhập; swap theo thông số sàn; lệnh khớp ở nến **sau** nến ra tín hiệu (không khớp ở giá đóng nến đã dùng để quyết định).
- **Điểm còn mở (quyết ở kế hoạch GĐ6):** lịch kinh tế / tin lịch sử cho 2 năm có thể không đủ. Nếu thiếu, chạy thêm một biến thể "chặn cố định quanh giờ công bố đã biết" và ghi rõ đây là giới hạn.

## 3. Chia dữ liệu — để dành một đoạn không đụng tới

```
|———————— phần phát triển (≈ 75 %) ————————|—— để dành (≈ 25 %, tối thiểu 6 tháng) ——|
  walk-forward: học 12 tháng → kiểm 3 tháng,        chỉ chạy MỘT lần, cuối cùng,
  cuốn chiếu tới hết phần phát triển                 với đúng một tổ hợp đã chọn
```

- **Đoạn để dành** là đoạn **mới nhất**. Không ai (kể cả người phát triển) xem kết quả trên đoạn này cho tới lần chạy cuối. Chạy đúng **một lần**.
- **Walk-forward** trên phần phát triển: mỗi vòng chọn tổ hợp tham số tốt nhất trên 12 tháng "học" (theo kỳ vọng / lệnh sau chi phí), rồi đo trên 3 tháng "kiểm" kế tiếp. Ghép mọi đoạn "kiểm" = kết quả ngoài mẫu.

## 4. Những gì được thử (khóa trước)

Chỉ 3 nút loại A, lưới cố định — **27 tổ hợp**:

| Nút | Các giá trị thử |
| --- | --- |
| P1 điểm chất lượng tối thiểu | 0,5 · 0,6 · 0,7 |
| P7 cắt lỗ | 1,0 · 1,5 · 2,0 ATR |
| P8 chốt lời | 1,5 · 2 · 3 × SL |

Mọi tổ hợp đều được báo cáo (kể cả tổ hợp xấu). Tổ hợp hiện tại (0,6 / 1,5 / 2) luôn được báo cáo riêng. Thử thêm bất cứ thứ gì ngoài lưới → ghi lại và **cộng vào số lần thử** (mục 6).

## 5. Chỉ số (tất cả **sau** chi phí, ở mức rủi ro 0,25 %/lệnh của người dùng)

Số lệnh; tỷ lệ thắng; kỳ vọng / lệnh (theo R và theo USD); hệ số lợi nhuận; sụt giảm lớn nhất; chuỗi thua dài nhất; số lần chạm dừng hẳn (H6) và tạm dừng (H4); Sharpe theo ngày; thời gian giữ lệnh. Chia nhỏ theo **regime**, theo **phiên** (Á / London / Mỹ), theo **năm**, theo **chiều** (mua / bán).

## 6. So mốc + chống "may mắn"

1. **Mốc ngẫu nhiên (bắt buộc):** vào lệnh **ngẫu nhiên** trong cùng giờ phiên, cùng số lệnh, cùng chiều tỷ lệ, cùng SL / TP / đóng 16:45 — lặp **1.000 lần**. Chiến lược phải **vượt phân vị 95 %** của mốc này về kỳ vọng / lệnh.
2. **Mốc không lọc:** vào mỗi khi có hướng, bỏ các điều kiện V3–V6 — để biết các bộ lọc có giúp không.
3. **Tham chiếu:** không giao dịch (0) và mua – giữ (chỉ để đọc, không dùng làm tiêu chí).
4. **Hiệu chỉnh vì đã thử nhiều lần:** Deflated Sharpe Ratio (Bailey & López de Prado 2014) với số lần thử = 27 + mọi lần thử thêm; **PBO** (xác suất khớp quá mức) bằng CSCV, chia 16 khối (Bailey và cộng sự 2017).
5. Khoảng tin cậy 95 % của kỳ vọng / lệnh bằng bootstrap theo khối ngày.

## 7. Tiêu chí ĐẠT (BT-04) — phải đạt **tất cả**

| # | Tiêu chí |
| --- | --- |
| T1 | Ngoài mẫu (ghép walk-forward) có **≥ 200 lệnh**; đoạn để dành có **≥ 30 lệnh** |
| T2 | Kỳ vọng / lệnh sau chi phí **> 0**, và cận dưới khoảng tin cậy 95 % **> 0** (ngoài mẫu) |
| T3 | Hệ số lợi nhuận ngoài mẫu **≥ 1,2** |
| T4 | Vượt **phân vị 95 %** của mốc ngẫu nhiên |
| T5 | Deflated Sharpe: xác suất **≥ 0,95**; PBO **≤ 0,2** |
| T6 | Sụt giảm lớn nhất ngoài mẫu **< 5 %** (ngưỡng dừng hẳn H6 bạn chọn) |
| T7 | Đoạn để dành: kỳ vọng / lệnh **> 0** và không thấp hơn **một nửa** kỳ vọng ngoài mẫu |
| T8 | Không có một năm / một regime nào chiếm **> 70 %** tổng lãi (lợi thế không chỉ đến từ một giai đoạn) |

Không đạt → **không** lên SHADOW / LIVE. Có thể viết phiên bản chiến lược mới (bản mới = chưa kiểm chứng, phải qua lại toàn bộ giao thức, và **cần dữ liệu để dành mới** vì đoạn cũ đã dùng).

## 8. Không được làm

- Xem kết quả đoạn để dành trước lần chạy cuối; chạy đoạn để dành hai lần.
- Bỏ bớt lệnh / giai đoạn xấu ("lúc đó thị trường bất thường").
- Đổi tiêu chí mục 7 hoặc lưới mục 4 sau khi đã thấy kết quả.
- Gọi kết quả là "xác suất thắng" hay "độ tin cậy dự báo".

## 9. Báo cáo GĐ6 phải ghi

Giả định chi phí; khoảng dữ liệu + chỗ thiếu; phiên bản mọi thành phần; số lần thử thật (cho Deflated Sharpe); các bias còn lại (lịch kinh tế lịch sử, spread lịch sử, khớp ở nến kế tiếp); kết quả mọi tổ hợp; kết luận **ĐẠT / KHÔNG ĐẠT** theo từng tiêu chí T1–T8.

## Nhật ký

- **2026-11-17** — Bản nháp đầu. Mọi con số tiêu chí là **đề xuất** của người phát triển, chờ người dùng duyệt (BT-04).
