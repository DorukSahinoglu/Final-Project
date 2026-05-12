import { useCallback, useState } from "react";
import type { ToastItem } from "@/components/dashboard/toast-stack";

export function useToast() {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const pushToast = useCallback((title: string, body: string) => {
    setToasts((items) => [...items, { id: Date.now() + Math.random(), title, body }]);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts((items) => items.filter((item) => item.id !== id));
  }, []);

  return { toasts, pushToast, removeToast };
}
