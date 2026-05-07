import { describe, expect, it } from "vitest";

import {
  CHAT_STATUS_PHRASE_MAX_MS,
  CHAT_STATUS_PHRASE_MIN_MS,
  pickNextPhraseIndex,
  randomPhraseRotationDelayMs,
  RECALL_UI_PHRASE_WHITELIST,
  THINKING_UI_PHRASE_WHITELIST
} from "./chatStatusPhraseLists";

describe("chatStatusPhraseLists", () => {
  it("has 40 phrases per mode", () => {
    expect(THINKING_UI_PHRASE_WHITELIST.length).toBe(40);
    expect(RECALL_UI_PHRASE_WHITELIST.length).toBe(40);
  });

  it("pickNextPhraseIndex never returns prev for length > 1", () => {
    const len: number = 40;
    for (let p: number = 0; p < len; p += 1) {
      for (let k: number = 0; k < 50; k += 1) {
        const nxt: number = pickNextPhraseIndex(p, len);
        expect(nxt).toBeGreaterThanOrEqual(0);
        expect(nxt).toBeLessThan(len);
        expect(nxt).not.toBe(p);
      }
    }
  });

  it("randomPhraseRotationDelayMs is in [min, max]", () => {
    for (let i: number = 0; i < 30; i += 1) {
      const ms: number = randomPhraseRotationDelayMs();
      expect(ms).toBeGreaterThanOrEqual(CHAT_STATUS_PHRASE_MIN_MS);
      expect(ms).toBeLessThanOrEqual(CHAT_STATUS_PHRASE_MAX_MS);
    }
  });
});
