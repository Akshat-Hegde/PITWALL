import { describe, expect, test } from "vitest";
import { initials } from "./components/Motifs";

describe("avatar initials", () => {
  test("first and last word, or the capitals of one word", () => {
    expect(initials("Maya Rao")).toBe("MR");
    expect(initials("J. Lindqvist")).toBe("JL");
    expect(initials("NightShift_Nico")).toBe("NN");
    expect(initials("Apex_Hunter")).toBe("AH");
    expect(initials("leni")).toBe("LE");
    expect(initials("  ")).toBe("?");
  });
});
