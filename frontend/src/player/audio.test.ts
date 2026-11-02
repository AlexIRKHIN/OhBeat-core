import { describe, expect, it, vi } from "vitest";

import { formatTime, prepare, switchTo, type MediaElement } from "./audio";

/** A stand-in for <audio> that records the order of calls. */
class FakeElement implements MediaElement {
  calls: string[] = [];
  preload = "auto";
  currentTime = 0;
  private source = "";

  get src(): string {
    return this.source;
  }
  set src(value: string) {
    this.calls.push(`src=${value}`);
    this.source = value;
  }
  pause = vi.fn(() => void this.calls.push("pause"));
  load = vi.fn(() => void this.calls.push("load"));
  play = vi.fn(() => {
    this.calls.push("play");
    return Promise.resolve();
  });
  removeAttribute = vi.fn((name: string) => void this.calls.push(`remove ${name}`));
}

const fakeElement = () => new FakeElement();

describe("RFC_Audio_Streaming §4", () => {
  it("lazy loading: preload none until Play", () => {
    const el = fakeElement();
    prepare(el);
    expect(el.preload).toBe("none");
    expect(el.calls).toEqual([]); // no src, nothing downloaded
  });

  it("switching tracks aborts the previous download before setting the new source", async () => {
    const el = fakeElement();
    await switchTo(el, "http://localhost:9000/public-media/previews/2_v1.mp3");
    expect(el.calls).toEqual([
      "pause",
      "remove src",
      "load",
      "src=http://localhost:9000/public-media/previews/2_v1.mp3",
      "play",
    ]);
  });
});

describe("time format", () => {
  it("M:SS", () => {
    expect(formatTime(184.6)).toBe("3:04");
    expect(formatTime(Number.NaN)).toBe("0:00");
  });
});
