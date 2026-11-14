# 32 — Analyst Tin tức (GĐ3 bước 6 — NEWS-01..04; 3-C10; DEC-08)

> Tạo 2026-11-14. Code: `backend/src/gold_trading/analysts/news.py` (luồng đọc tin + analyst), `analysts/news_llm.py` (gọi Claude, ngân sách, prompt), `storage/news_llm.py` + migration `0017_news_llm_calls`. Test: `tests/test_news_analyst.py`. Dữ liệu GĐ1: `21-khung-tin.md` (RSS Fed + Bộ Tài chính, gộp trùng, nhận diện thực thể).

## 1. Quyết định

- **DEC-08 (người dùng 2026-11-14):** nhà cung cấp LLM = **Claude của Anthropic**, ngân sách **20 USD / tháng**.
- **Cùng ngày, người dùng: "dùng miễn phí mọi thứ trước, sau đó mới dùng tiền thật"** → **mặc định TẮT** gọi Claude (`GT_NEWS_LLM=0`) **và** ngân sách mặc định **0 USD** (`GT_NEWS_BUDGET_USD=0`) — hai lớp chặn độc lập; có khóa mà quên bật / bật mà quên đặt ngân sách vẫn không tốn tiền. Bật khi sẵn sàng: `GT_NEWS_LLM=1`, `GT_NEWS_BUDGET_USD=20`, `ANTHROPIC_API_KEY` trong `.env`.
- Mô hình mặc định `claude-opus-5-5` (đổi bằng `GT_NEWS_MODEL`; rẻ hơn ~40 lần: `claude-haiku-5-5` — người dùng quyết), effort `low` (việc phân loại), fallback phía máy chủ khi mô hình từ chối (`fallbacks: "default"`).
- Điều khoản: chỉ gửi thông cáo / bài phát biểu chính thức của Fed + Bộ Tài chính (tác phẩm chính phủ Mỹ, nhà cung cấp `VERIFIED`); không gửi dữ liệu cá nhân / tài khoản.

## 2. Hai chế độ

| | Miễn phí (mặc định, `RULES_ONLY`) | Claude (`LLM`) |
| --- | --- | --- |
| Tin | Tin 24 giờ, đã gộp trùng (NEWS-01, GĐ1), lọc luật: tiếng Anh + có thực thể FED / RATES / INFLATION / LABOR / GOLD / USD / FISCAL / GEOPOLITICS | như bên trái |
| Đánh giá | **Không** — chỉ tiêu đề, liên kết, chủ đề, cờ "giống lệnh cho AI" | chiều tác động lên vàng / USD, lập trường Fed, mức tác động, độ mới, tầm thời gian, trích dẫn nguyên văn, tóm tắt tiếng Việt |
| Trạng thái | `HEALTHY` + cờ `RULES_ONLY`, `OPTIONAL_MISSING:claude`, confidence 0,5 | `HEALTHY`, confidence 1 (0,5 nếu còn tin chưa đọc được) |

## 3. Gọi Claude (NEWS-02, NEWS-03)

- **Luồng riêng** (`NewsLlmWorker`, mỗi 60 giây) — **không bao giờ** trong nhịp 2 giây của orchestrator (làn nhanh chậm > 10 giây → Safety chặn mở lệnh).
- Chỉ tin thấy lần đầu trong **48 giờ** (khởi động không đọc lại 90 ngày lịch sử); tối đa 5 tin / vòng, mới nhất trước; tin > 12.000 ký tự → **không gửi** (không cắt âm thầm).
- Prompt có phiên bản (`news-prompt-1`): bài nằm trong `<article>` là **dữ liệu không tin cậy**, cấm làm theo; kết quả ép theo **schema JSON** (structured outputs) gồm `gold_impact`, `usd_impact`, `fed_stance`, `impact`, `novelty`, `horizon`, `evidence_quote`, `summary_vi`, `injection_suspected`. Không gửi `temperature` / `thinking` (bị cấm trên mô hình hiện hành).
- `max_tokens` 4.000, timeout 60 giây, SDK tự thử lại 2 lần; lỗi → tối đa 3 lần thử / tin, chờ 5 → 10 phút. Lỗi khóa / quyền / hạn mức chi tiêu → **dừng luồng** (không thử mãi). Từ chối (`refusal`) / cắt cụt (`max_tokens`) / không phải JSON → ghi trạng thái, **không đoán**.
- **Sổ chỉ-thêm `news_llm_calls`** (trigger chặn sửa / xóa; khóa duy nhất tin + prompt + mô hình + lần thử): mô hình yêu cầu + mô hình thật phục vụ, token, **chi phí `Decimal`**, `request_id`, kết quả.

## 4. Ngân sách (trần cứng)

- Trước mỗi lần gọi: **chi phí xấu nhất** = token đầu vào ước lượng thừa (1 token / 2 ký tự) × 10 USD/MTok + 4.000 token đầu ra × 50 USD/MTok (giá cao nhất — fallback có thể đổi mô hình) ≈ 0,21 USD. Gọi khi `đã tiêu tháng + xấu nhất ≤ ngân sách tháng` **và** `đã tiêu hôm nay + xấu nhất ≤ 2 × ngân sách / số ngày của tháng` (20 USD → ~1,33 USD / ngày). Tháng / ngày theo UTC.
- Chi phí thật từ `usage`: theo giá của mô hình yêu cầu / phục vụ (lấy giá cao hơn); mô hình lạ → giá cao nhất; token cache: ghi × 1,25, đọc × 1 (không bao giờ tính thấp hơn thật).
- Ước tính dùng thật (Opus 5.5, ~1.500 token vào + ~300 ra): ~0,012 USD / tin; vài chục tin / ngày → vài USD / tháng.

## 5. Analyst (NEWS-04, 3-C10)

- Toàn cục; chỉ dùng kết quả **ghi trước `as_of`** (point-in-time). Kết quả **không dùng** nếu: mô hình báo `injection_suspected`, **hoặc** luật GĐ1 gắn `SUSPECT_INSTRUCTIONS` (3-C10 — kể cả khi mô hình nói "sạch"), **hoặc** trích dẫn không có nguyên văn trong bài (`CITATION_NOT_FOUND`), hoặc giá trị ngoài danh mục.
- Đặc trưng: tin đã đánh giá (≤ 10) + tin chưa đánh giá (≤ 10), đếm theo chiều tác động, `tone_score` = Σ (+1 hỗ trợ / −1 cản) × mức 1–3 (**không phải xác suất**), `NEWS_SHOCK` khi có tin `HIGH` + `SURPRISE` trong 2 giờ, số tin đang chờ / chưa đọc được / bị loại, ngân sách đã dùng.
- Job `NEWS` (tin mới — định tuyến GĐ2; kết quả hết hạn → `router-2026.11.14g`) **chỉ tổng hợp lại**, không gọi Claude. Hết hạn 15 phút; dự phòng mỗi nhịp. Luồng đọc tin xong → tính lại ngay.

## 6. Giới hạn

- **Chưa gọi Claude thật lần nào** (tốn tiền; người dùng chọn miễn phí trước): đường gọi đã kiểm bằng client giả đúng hình dạng phản hồi SDK (`anthropic` 2.8.0, kiểm chữ ký `beta.messages.create` có `fallbacks`, `output_config`). Lần bật đầu tiên nên chạy thử vài tin rồi xem sổ chi phí.
- Chiều tác động theo quan hệ lý thuyết, chưa hiệu chỉnh; nguồn chỉ có Fed + Bộ Tài chính.

## 7. Kiểm chứng

42 test (bộ nhớ + SQLite): chế độ miễn phí, mặc định không tốn tiền (ngân sách 0 → không gọi dù có khóa), không khóa → tắt, hình dạng yêu cầu (bài trong thẻ, schema, fallback, effort, không tham số cấm), chỉ gọi tin liên quan + chi phí tính tay (1.500 × 4 + 300 × 20 → 0,012 USD), tổng hợp + NEWS_SHOCK, 3-C10 (tin "ignore all previous instructions" bị loại dù mô hình nói sạch), trích dẫn phải nguyên văn, từ chối / cắt cụt / không JSON / lỗi mạng, thử lại có giãn cách rồi bỏ, lỗi khóa dừng luồng, trần ngày / tháng, giá mô hình lạ, tin quá dài không gửi, point-in-time, tin > 48 giờ không đọc, sổ chỉ-thêm, router, bộ xử lý không gọi Claude, API. **Lỗi tìm được khi viết test:** phản hồi không ghi mô hình phục vụ → bị tính theo giá cao nhất (10 thay vì 4 USD/MTok) — đã sửa. **Soát Postgres:** migration lên / xuống / lên, 8 luồng ghi trùng → 1, trigger chặn sửa / xóa, ràng buộc chặn trạng thái lạ, 1.000 chi phí nhỏ cộng đúng tuyệt đối (Decimal), luồng đọc tin: không khóa / ngân sách 0 → 0 lần gọi.
