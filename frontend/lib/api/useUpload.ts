"use client";

import { useCallback, useRef, useState } from "react";
import type { ErrorEnvelope } from "@/lib/report/types";
import { uploadFile, type UploadProgress, type UploadResponse, type UploadResult } from "./upload";

/**
 * The upload hook (MASTER_SPEC Part 7 §5, the M28-S1 "upload path to a file resource").
 *
 * A thin stateful wrapper over {@link uploadFile}: it holds the current phase, real progress, and
 * the terminal result — either the stored `UploadResponse` or the Part 6 §6 error envelope — so a
 * page renders the drop zone from one hook and routes on success. There is deliberately no global
 * store (Part 7 §5.1); this state is local to the upload screen and gone once the file resource has
 * its own URL. Only one upload runs at a time — starting a new one aborts the previous transfer.
 */

export type UploadStatus = "idle" | "uploading" | "success" | "error";

export interface UploadState {
  status: UploadStatus;
  progress: UploadProgress | null;
  result: UploadResponse | null;
  error: ErrorEnvelope | null;
}

const IDLE: UploadState = { status: "idle", progress: null, result: null, error: null };

export function useUpload() {
  const [state, setState] = useState<UploadState>(IDLE);
  const abortRef = useRef<AbortController | null>(null);

  const upload = useCallback(async (file: File): Promise<UploadResult> => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({
      status: "uploading",
      progress: { loaded: 0, total: file.size, fraction: file.size > 0 ? 0 : null },
      result: null,
      error: null,
    });

    const outcome = await uploadFile(file, {
      signal: controller.signal,
      // Ignore late progress from a superseded transfer — only advance the upload still in flight.
      onProgress: (progress) =>
        setState((prev) => (prev.status === "uploading" ? { ...prev, progress } : prev)),
    });

    if (outcome.ok) {
      setState({
        status: "success",
        progress: { loaded: file.size, total: file.size, fraction: 1 },
        result: outcome.data,
        error: null,
      });
    } else {
      setState({ status: "error", progress: null, result: null, error: outcome.error });
    }
    return outcome;
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(IDLE);
  }, []);

  return { ...state, upload, reset };
}
