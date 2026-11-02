import { describe, expect, it } from "vitest";

import { checkBeatFile, contentTypeFor, formatDuration } from "./beatFiles";

const fakeFile = (name: string, size: number, type = "") => {
  const file = new File(["x"], name, { type });
  Object.defineProperty(file, "size", { value: size });
  return file;
};
const MB = 1024 * 1024;

describe("AC-2: file checks before the upload starts", () => {
  it("rejects MP3 in the WAV zone", async () => {
    expect(await checkBeatFile("wav", fakeFile("track.mp3", 10 * MB, "audio/mpeg"))).toBe("format");
  });

  it("rejects WAV larger than 200 MB", async () => {
    expect(await checkBeatFile("wav", fakeFile("master.wav", 200 * MB + 1))).toBe("size");
  });

  it("accepts WAV up to 200 MB", async () => {
    expect(await checkBeatFile("wav", fakeFile("master.WAV", 200 * MB))).toBeNull();
  });

  it("rejects a non-zip stems archive and one larger than 1 GB", async () => {
    expect(await checkBeatFile("stems", fakeFile("stems.rar", MB))).toBe("format");
    expect(await checkBeatFile("stems", fakeFile("stems.zip", 1024 * MB + 1))).toBe("size");
  });

  it("rejects a cover larger than 5 MB before reading the image", async () => {
    expect(await checkBeatFile("cover", fakeFile("cover.jpg", 5 * MB + 1))).toBe("size");
  });
});

describe("content type sent to the API", () => {
  it("falls back to audio/wav when the browser gives none", () => {
    expect(contentTypeFor("wav", fakeFile("m.wav", 1))).toBe("audio/wav");
    expect(contentTypeFor("stems", fakeFile("s.zip", 1, "application/x-zip-compressed"))).toBe("application/x-zip-compressed");
    expect(contentTypeFor("cover", fakeFile("c.webp", 1))).toBe("image/webp");
  });
});

describe("duration", () => {
  it("formats seconds as M:SS", () => {
    expect(formatDuration(184)).toBe("3:04");
    expect(formatDuration(null)).toBe("—");
  });
});
