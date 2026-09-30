import { useCallback, useState } from "react";

import { upload } from "./api/client";

/** Sends PDFs in batches of 10, so a large drop shows progress and each request stays small. */
export function useUploader(aid: number, mode: string, onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<string[]>([]);

  const send = useCallback(async (files: File[]) => {
    const pdfs = files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!pdfs.length) {
      setLines(["Only PDF files can be added. Choose files ending in .pdf."]);
      return;
    }
    setBusy(true);
    let added = 0, skipped = 0;
    const errors: string[] = [];
    for (let i = 0; i < pdfs.length; i += 10) {
      setLines([`Uploading ${Math.min(i + 10, pdfs.length)} of ${pdfs.length}…`]);
      try {
        const r = await upload(aid, pdfs.slice(i, i + 10), mode);
        added += r.added.length;
        skipped += r.skipped.length;
        errors.push(...r.errors);
      } catch (e) {
        errors.push(`upload failed: ${(e as Error).message}`);
      }
    }
    setLines([`${added} ${added === 1 ? "file" : "files"} added` + (skipped ? `, ${skipped} already here` : "") + ".", ...errors]);
    setBusy(false);
    onDone();
  }, [aid, mode, onDone]);

  return { send, busy, lines };
}
