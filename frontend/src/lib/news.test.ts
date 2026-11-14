import { describe, expect, it } from "vitest";
import { readNews } from "./news";

describe("readNews", () => {
  it("chỉ nhận liên kết https, bỏ mục sai kiểu", () => {
    const f = readNews({
      mode: "RULES_ONLY",
      unassessed: [{ title: "A", url: "javascript:alert(1)" }, { title: 5 }, { title: "B", url: "https://www.federalreserve.gov/x" }],
    });
    expect(f.unassessed.map((i) => [i.title, i.url])).toEqual([
      ["A", null],
      ["B", "https://www.federalreserve.gov/x"],
    ]);
  });
  it("chế độ không rõ → null, không đoán", () => {
    expect(readNews({ mode: "MAGIC" }).mode).toBeNull();
  });
});
