import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useTheme } from "./useTheme";

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("useTheme", () => {
  it("mặc định tối khi chưa lưu gì", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("đọc khóa mới cutlotdesk.theme", () => {
    localStorage.setItem("cutlotdesk.theme", "light");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("light");
  });

  it("giữ lựa chọn đã lưu ở khóa cũ aurumdesk.theme và ghi sang khóa mới", () => {
    localStorage.setItem("aurumdesk.theme", "light");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("light");
    expect(localStorage.getItem("cutlotdesk.theme")).toBe("light");
  });

  it("khóa mới được ưu tiên hơn khóa cũ", () => {
    localStorage.setItem("aurumdesk.theme", "light");
    localStorage.setItem("cutlotdesk.theme", "dark");
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");
  });

  it("đổi theme thì lưu vào khóa mới", () => {
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(localStorage.getItem("cutlotdesk.theme")).toBe("light");
  });
});
