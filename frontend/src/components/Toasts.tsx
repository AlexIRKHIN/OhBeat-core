// Notifications (toasts). NFR-19: losing the internet or the server is shown at once.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

type Kind = "success" | "error" | "info";
interface Toast {
  id: number;
  kind: Kind;
  text: string;
}

interface ToastApi {
  show: (text: string, kind?: Kind) => void;
}

const ToastContext = createContext<ToastApi>({ show: () => undefined });

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

const KIND_CLASS: Record<Kind, string> = {
  success: "bg-accent-deep",
  error: "bg-danger",
  info: "border border-line bg-panel-2",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [online, setOnline] = useState(() => navigator.onLine);
  const nextId = useRef(1);

  const show = useCallback((text: string, kind: Kind = "info") => {
    const id = nextId.current++;
    setToasts((list) => [...list.filter((toast) => toast.text !== text), { id, kind, text }]);
    window.setTimeout(() => setToasts((list) => list.filter((toast) => toast.id !== id)), 5000);
  }, []);

  useEffect(() => {
    const goOffline = () => setOnline(false);
    const goOnline = () => {
      setOnline(true);
      show(t("common.backOnline"), "success");
    };
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);
    return () => {
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
    };
  }, [show, t]);

  const api = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4" aria-live="polite">
        {!online && (
          <div role="alert" className="pointer-events-auto rounded-lg bg-danger px-4 py-2 text-sm text-white shadow-lg">
            {t("common.offline")}
          </div>
        )}
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={`pointer-events-auto max-w-md rounded-lg px-4 py-2 text-sm text-white shadow-lg ${KIND_CLASS[toast.kind]}`}
          >
            {toast.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
