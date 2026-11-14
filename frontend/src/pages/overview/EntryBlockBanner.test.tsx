import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { makeStatus } from "../../test/fixtures";
import { EntryBlockBanner } from "./EntryBlockBanner";

describe("EntryBlockBanner (GĐ2 4d)", () => {
  it("không hiện khi không có cửa sổ chặn", () => {
    const { container } = render(<EntryBlockBanner status={makeStatus()} />);
    expect(container.firstChild).toBeNull();
  });

  it("hiện lý do tiếng Việt, giờ hết hạn, và cửa sổ mở (spread)", () => {
    render(
      <EntryBlockBanner
        status={makeStatus({
          entry_block_windows: [
            {
              start_at: "2026-12-10T13:15:00Z",
              end_at: "2026-12-10T13:46:20Z",
              reason_codes: ["CALENDAR_HIGH", "RELEASE_HIGH_RECEIVED"],
            },
            { start_at: "2026-12-10T14:00:00Z", end_at: null, reason_codes: ["SPREAD_WIDE", "XYZ_NEW"] },
          ],
        })}
      />,
    );
    const b = screen.getByTestId("entry-block-banner");
    expect(b).toHaveTextContent("Đang chặn mở lệnh mới");
    expect(b).toHaveTextContent("Cửa sổ công bố số liệu quan trọng · Vừa có số liệu quan trọng (15 phút)");
    expect(b).toHaveTextContent("Spread giãn mạnh · Lý do khác (XYZ_NEW) — tới khi hết nguyên nhân");
    expect(b).toHaveTextContent(/tới \d/);
  });
});
