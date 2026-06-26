import { describe, it, expect } from "vitest";
import { isOverRect } from "../renderer/hit-test.js";

const rect = { x: 10, y: 20, w: 100, h: 200 };

describe("isOverRect", () => {
  it("is true inside", () => {
    expect(isOverRect(50, 100, rect)).toBe(true);
  });
  it("is true on the edges", () => {
    expect(isOverRect(10, 20, rect)).toBe(true);
    expect(isOverRect(110, 220, rect)).toBe(true);
  });
  it("is false outside", () => {
    expect(isOverRect(5, 100, rect)).toBe(false);
    expect(isOverRect(50, 500, rect)).toBe(false);
  });
  it("is false past the right edge", () => {
    expect(isOverRect(111, 100, rect)).toBe(false);
  });
  it("is false above the top edge", () => {
    expect(isOverRect(50, 19, rect)).toBe(false);
  });
});
