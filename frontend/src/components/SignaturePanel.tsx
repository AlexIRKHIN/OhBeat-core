// Signing Exclusive contracts with an SMS code (RFC ПЭП §3, §4; NFR-31).
// ASSUMPTION: GAP-71 — the screen is not in UI_Specifications: the draft is read first, then
// "Sign" sends the code, the field takes 6 digits, the pause before a new code is counted down.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api } from "../api/client";
import type { Order } from "../api/types";
import { errorText } from "../lib/errors";
import { codeDigits, timeLeft, useNow } from "../lib/time";
import { Spinner } from "./ui";

interface Drafts {
  items: { item_id: number; contract_number: string; title: string; text: string; draft_sha256: string }[];
}

interface CodeSent {
  expires_at: string;
  resend_after: string;
  phone: string;
}

export function SignaturePanel({ order }: { order: Order }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const drafts = useQuery({
    queryKey: ["orders", String(order.order_id), "contract-draft"],
    queryFn: () => api<Drafts>(`/orders/${order.order_id}/contract-draft`),
  });
  const [sent, setSent] = useState<CodeSent | null>(null);
  const [resendAt, setResendAt] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const now = useNow(true);

  const send = useMutation({
    mutationFn: () => api<CodeSent>(`/orders/${order.order_id}/signature/otp`, { method: "POST" }),
    onSuccess: (data) => {
      setSent(data);
      setResendAt(Date.parse(data.resend_after));
      setCode("");
      setProblem(null);
    },
    onError: (error) => {
      // 429: the server says how long to wait (GAP-73) — the button counts it down
      if (error instanceof ApiError && error.errorCode === "TOO_MANY_REQUESTS") {
        const wait = error.details[0]?.retry_after ?? 60;
        setResendAt(Date.now() + wait * 1000);
      }
      setProblem(errorText(error));
    },
  });

  const verify = useMutation({
    mutationFn: () => api<{ signed_at: string }>(`/orders/${order.order_id}/signature/verify`, { method: "POST", body: { code } }),
    onSuccess: () => {
      setProblem(null);
      void queryClient.invalidateQueries({ queryKey: ["orders", String(order.order_id)] });
    },
    onError: (error) => {
      setCode("");
      if (error instanceof ApiError && error.errorCode === "INVALID_CODE") {
        setProblem(error.details[0]?.issue ?? error.message); // "Wrong code, attempts left: 2"
        return;
      }
      if (error instanceof ApiError && ["CODE_EXPIRED", "CODE_ATTEMPTS_EXCEEDED"].includes(error.errorCode)) {
        setSent(null); // the code is spent: the next step is a new one
      }
      if (error instanceof ApiError && ["ALREADY_SIGNED", "INVALID_STATUS"].includes(error.errorCode)) {
        void queryClient.invalidateQueries({ queryKey: ["orders", String(order.order_id)] });
      }
      setProblem(errorText(error));
    },
  });

  const codeLeft = sent ? timeLeft(sent.expires_at, now) : null;
  const resendLeft = resendAt ? timeLeft(resendAt, now) : null;

  return (
    <section className="card space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-cyan">{t("signature.title")}</h2>
        <p className="text-sm text-soft">{t("signature.intro")}</p>
      </div>

      {drafts.isPending && <Spinner />}
      {drafts.isError && <p className="alert-error">{errorText(drafts.error)}</p>}
      {drafts.data?.items.map((item) => (
        <div key={item.item_id} className="space-y-1">
          <p className="text-sm text-ink">
            {t("order.contract", { number: item.contract_number })} · {item.title}
          </p>
          {/* RFC §3 p. 2: the Artist reads the text before asking for a code */}
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-panel-2 p-3 font-sans text-xs leading-relaxed text-soft">
            {item.text}
          </pre>
          <p className="break-all font-mono text-[11px] text-muted">SHA-256: {item.draft_sha256}</p>
        </div>
      ))}

      {!sent ? (
        <button type="button" className="btn-primary" disabled={!drafts.data || send.isPending || Boolean(resendLeft)} onClick={() => send.mutate()}>
          {send.isPending && <Spinner />}
          {resendLeft ? t("signature.resendIn", { left: resendLeft }) : t("signature.sign")}
        </button>
      ) : (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (code.length === 6) verify.mutate();
          }}
        >
          <p className="text-sm text-soft">
            {t("signature.sentTo", { phone: sent.phone })}{" "}
            {codeLeft ? t("signature.validFor", { left: codeLeft }) : <span className="text-orange">{t("signature.codeOver")}</span>}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor="otp-code" className="sr-only">
              {t("signature.codeLabel")}
            </label>
            <input
              id="otp-code"
              className="input w-36 text-center font-mono text-lg tracking-[0.3em]"
              value={code}
              onChange={(e) => setCode(codeDigits(e.target.value))}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000"
              maxLength={6}
              autoFocus
            />
            <button type="submit" className="btn-primary" disabled={code.length !== 6 || verify.isPending}>
              {verify.isPending && <Spinner />}
              {t("signature.confirm")}
            </button>
            <button type="button" className="btn-secondary" disabled={Boolean(resendLeft) || send.isPending} onClick={() => send.mutate()}>
              {resendLeft ? t("signature.resendIn", { left: resendLeft }) : t("signature.resend")}
            </button>
          </div>
        </form>
      )}
      {problem && <p className="alert-error">{problem}</p>}
    </section>
  );
}
