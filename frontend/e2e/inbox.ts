// The "phone" of the test: the SMS mock of Core API also writes every message into a file of a
// shared volume (MOCK_INBOX_PATH). The test waits there for the code, as a person waits for the SMS.
import { readFile } from "node:fs/promises";

const INBOX = process.env.E2E_INBOX ?? "/var/mock-inbox/messages.jsonl";

interface Message {
  at: string;
  kind: "sms" | "email";
  to: string;
  subject?: string;
  text: string;
}

async function messages(): Promise<Message[]> {
  try {
    return (await readFile(INBOX, "utf8")).split("\n").filter(Boolean).map((line) => JSON.parse(line) as Message);
  } catch {
    return [];
  }
}

/** The 6-digit code of the latest SMS to `phone` sent after `since`. */
export async function smsCode(phone: string, since: Date, seconds = 30): Promise<string> {
  for (let i = 0; i < seconds * 2; i++) {
    const sms = (await messages()).filter((m) => m.kind === "sms" && m.to === phone && new Date(m.at) >= since).pop();
    const code = sms?.text.match(/код (\d{6})/)?.[1];
    if (code) return code;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`no SMS to ${phone} in ${seconds} s (inbox ${INBOX})`);
}

/** Emails to `to` with the subject containing `subject`, sent after `since`. */
export async function emails(to: string, subject: string, since: Date): Promise<Message[]> {
  return (await messages()).filter((m) => m.kind === "email" && m.to === to && m.subject?.includes(subject) && new Date(m.at) >= since);
}
