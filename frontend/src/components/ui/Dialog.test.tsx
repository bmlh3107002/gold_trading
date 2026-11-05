import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Dialog } from "./Dialog";

describe("Dialog", () => {
  it("có role dialog, focus nút an toàn và đóng bằng Escape", async () => {
    const onClose = vi.fn();
    render(
      <Dialog
        open
        title="Tiêu đề"
        description="Mô tả"
        closeLabel="Đóng"
        onClose={onClose}
        actions={
          <>
            <button data-autofocus>Hủy</button>
            <button>OK</button>
          </>
        }
      />,
    );
    const dialog = screen.getByRole("dialog", { name: "Tiêu đề" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAccessibleDescription("Mô tả");
    expect(screen.getByRole("button", { name: "Hủy" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("giữ focus trong dialog khi Tab", async () => {
    render(
      <Dialog open title="T" closeLabel="Đóng" onClose={() => {}} actions={<button data-autofocus>Hủy</button>} />,
    );
    await userEvent.tab();
    await userEvent.tab();
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
  });
});
