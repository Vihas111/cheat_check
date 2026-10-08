import { useCallback } from "react";

import { api } from "../api/client";
import { useFeedback } from "./chrome";

/** "Not a match": drop this pair of items from every comparison, with an Undo in the toast. */
export function useDismiss() {
  const { toast } = useFeedback();
  return useCallback(async (matchId: number, after?: () => void) => {
    try {
      const r = await api.post<{ scope: string; reason: string }>(`/m/${matchId}/dismiss`);
      toast("Marked as not a match. Re-scanning.", {
        action: {
          label: "Undo",
          onPress: async () => {
            await api.post("/settings/whitelist/delete", { kind: "pair", scope: r.scope, reason: r.reason });
            toast("Restored. Re-scanning.");
            after?.();
          },
        },
      });
      after?.();
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
    }
  }, [toast]);
}
