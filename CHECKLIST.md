# CHECKLIST — đã tách theo giai đoạn

Từ 2026-11-06, bản đồ việc được tách thành **một file cho mỗi giai đoạn** để mỗi phiên chỉ đọc phần đang làm (tiết kiệm token):

- Chỉ mục, nguyên tắc "đi sạch từng giai đoạn", cách đánh mã, bất biến, lộ trình: [`docs/giai-doan/README.md`](docs/giai-doan/README.md)
- Giai đoạn hiện tại: xem `PROGRESS.md` → mục "Trạng thái hiện tại".

Mã việc/case/quyết định (`ING-09`, `1A-C07`, `DEC-12`…) giữ nguyên, không đổi. Tìm một mã: `grep -rn "ING-09" docs/giai-doan/`.
