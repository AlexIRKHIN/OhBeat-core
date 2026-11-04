// Files of a paid order (FR-28). Every click asks the server for fresh links: they live one hour
// and are kept nowhere (NFR-8), so an old page never shows a dead link as if it worked.
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { Downloads } from "../api/types";
import { errorText } from "../lib/errors";
import { formatMoscowDateTime } from "../lib/validation";
import { Spinner } from "./ui";

export function DownloadLinks({ orderId, beatId }: { orderId: number; beatId?: number }) {
  const { t } = useTranslation();
  const links = useMutation({ mutationFn: () => api<Downloads>(`/orders/${orderId}/downloads`) });
  const items = links.data?.items.filter((i) => beatId === undefined || i.beat_id === beatId) ?? [];

  return (
    <div className="space-y-2">
      <button type="button" className="btn-secondary" onClick={() => links.mutate()} disabled={links.isPending}>
        {links.isPending && <Spinner />}
        {links.data ? t("downloads.refresh") : t("downloads.get")}
      </button>
      {links.isError && <p className="alert-error">{errorText(links.error)}</p>}
      {links.data && (
        <div className="space-y-2 text-left">
          {items.map((item) => (
            <ul key={item.contract_number} className="flex flex-wrap gap-2">
              {item.files.map((file) => (
                <li key={file.kind}>
                  <a href={file.url} className="btn-primary px-3 py-1.5 text-xs" download>
                    {t(`downloads.kind.${file.kind}`, { number: item.contract_number })}
                  </a>
                </li>
              ))}
            </ul>
          ))}
          <p className="text-xs text-muted">{t("downloads.expires", { time: formatMoscowDateTime(links.data.expires_at) })}</p>
        </div>
      )}
    </div>
  );
}
