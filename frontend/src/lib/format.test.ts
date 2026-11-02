import { describe, expect, it } from "vitest";
import { band, greeting, isStandardOrder, orderProblem, patientLine } from "./format";

describe("band", () => {
  it("uses the 26 cut-off on the full test only", () => {
    expect(band(26, 30)?.cls).toBe("good");
    expect(band(25, 30)?.cls).toBe("warn");
    expect(band(25, 26)).toBeNull();
    expect(band(null, 30)).toBeNull();
  });
});

describe("orderProblem", () => {
  it("needs a task", () => expect(orderProblem([])).toMatch(/at least one/));
  it("needs memory before recall", () => {
    expect(orderProblem([12])).toMatch(/Delayed recall/);
    expect(orderProblem([12, 5])).toMatch(/Delayed recall/);
    expect(orderProblem([5, 1, 12])).toBeNull();
  });
  it("is fine without recall", () => expect(orderProblem([1, 2])).toBeNull());
});

describe("isStandardOrder", () => {
  it("is all 13 tasks in order", () => {
    expect(isStandardOrder([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])).toBe(true);
    expect(isStandardOrder([2, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])).toBe(false);
    expect(isStandardOrder([1, 2])).toBe(false);
  });
});

describe("display helpers", () => {
  it("skips empty details", () => {
    expect(patientLine({ date_of_birth: null, sex: "Female", education_years: 12 })).toBe("Female · 12 yrs education");
  });
  it("greets by the hour", () => {
    expect(greeting(new Date(2026, 0, 1, 9))).toBe("Good morning");
    expect(greeting(new Date(2026, 0, 1, 18))).toBe("Good evening");
  });
});
