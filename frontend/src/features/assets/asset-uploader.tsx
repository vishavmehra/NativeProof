"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageUp, RotateCw, Upload, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type DragEvent } from "react";

import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { getAccessToken } from "@/lib/auth/token";
import { env } from "@/lib/env";
import { cn } from "@/lib/utils";

export type Asset = components["schemas"]["Asset"];
/** Images only: the API accepts no other upload kind. */
export type AssetKind = Extract<Asset["kind"], "image">;

/** Mirrors contracts/README §13 "Uploads". The server re-checks magic bytes and is the authority. */
export const UPLOAD_RULES: Record<AssetKind, { formats: string[]; label: string; maxBytes: number; accept: string }> = {
  image: {
    formats: ["png", "jpeg", "webp"],
    label: "PNG, JPEG, or WebP",
    maxBytes: 5 * 1024 * 1024,
    accept: "image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp",
  },
};

/** Detect the format from the file's first bytes, like the server does. */
export async function sniffFormat(file: Blob): Promise<string | null> {
  const b = new Uint8Array(await file.slice(0, 16).arrayBuffer());
  const ascii = (from: number, to: number) => String.fromCharCode(...b.slice(from, to));
  if (b[0] === 0x89 && ascii(1, 4) === "PNG") return "png";
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "jpeg";
  if (ascii(0, 4) === "RIFF" && ascii(8, 12) === "WEBP") return "webp";
  return null;
}

/** Null when the file passes the client-side checks, otherwise a user-facing reason. */
export async function checkUpload(file: File, kind: AssetKind): Promise<string | null> {
  const rule = UPLOAD_RULES[kind];
  if (file.size === 0) return "The file is empty.";
  if (file.size > rule.maxBytes) return `The file is ${formatBytes(file.size)}; the limit is ${formatBytes(rule.maxBytes)}.`;
  const format = await sniffFormat(file);
  if (!format || !rule.formats.includes(format)) return `The file's content is not ${rule.label}. Renaming a file does not change its format.`;
  return null;
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export const assetKeys = { list: (projectId: string) => ["assets", projectId] as const };

/**
 * Object URL for an uploaded asset's bytes. `content_url` requires the API token, so it cannot be an <img src>.
 * Returns null while loading or when the content is unavailable.
 */
export function useAssetObjectUrl(asset: Pick<Asset, "id" | "content_url"> | null | undefined) {
  const query = useQuery({
    queryKey: ["asset-content", asset?.id],
    enabled: Boolean(asset),
    staleTime: Infinity,
    queryFn: async () => {
      const token = await getAccessToken();
      const res = await fetch(`${env.apiBaseUrl}${asset!.content_url}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(`Could not load the file (${res.status}).`);
      return URL.createObjectURL(await res.blob());
    },
  });
  return query.data ?? null;
}

/**
 * Upload one image to the project (multipart POST /projects/{id}/assets) with a local preview.
 * Client checks mirror the server's rules; the server's verdict wins.
 */
export function AssetUploader({
  projectId,
  kind,
  onUploaded,
  label,
  disabledReason,
}: {
  projectId: string;
  kind: AssetKind;
  onUploaded?(asset: Asset): void;
  label?: string;
  /** When set, the uploader is disabled and this explains why. */
  disabledReason?: string;
}) {
  const rule = UPLOAD_RULES[kind];
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => () => void (preview && URL.revokeObjectURL(preview)), [preview]);

  const upload = useMutation({
    mutationFn: async (selected: File) => {
      const form = new FormData();
      form.append("file", selected);
      form.append("kind", kind);
      // openapi-fetch sends FormData as-is so the browser sets the multipart boundary.
      return unwrap(
        api.POST("/api/v1/projects/{project_id}/assets", {
          params: { path: { project_id: projectId } },
          body: form as unknown as components["schemas"]["Body_upload_asset"],
        }),
      );
    },
    onSuccess: (asset) => {
      void queryClient.invalidateQueries({ queryKey: assetKeys.list(projectId) });
      onUploaded?.(asset);
    },
  });

  async function choose(next: File | undefined) {
    upload.reset();
    setProblem(null);
    if (!next) return;
    const reason = await checkUpload(next, kind);
    if (reason) {
      setFile(null);
      setPreview(null);
      setProblem(reason);
      return;
    }
    setFile(next);
    setPreview(URL.createObjectURL(next));
  }

  function clear() {
    setFile(null);
    setPreview(null);
    setProblem(null);
    upload.reset();
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (!disabledReason) void choose(e.dataTransfer.files[0]);
  }

  const uploaded = upload.data;

  return (
    <div className="space-y-3">
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={rule.accept}
        className="sr-only"
        tabIndex={-1}
        disabled={Boolean(disabledReason)}
        onChange={(e) => void choose(e.target.files?.[0])}
      />
      {!file && (
        <button
          type="button"
          disabled={Boolean(disabledReason)}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          aria-describedby={`${inputId}-rules`}
          className={cn(
            "flex w-full flex-col items-center gap-2 rounded-xl border border-dashed border-border bg-surface px-4 py-6 text-center outline-none transition-colors hover:border-primary/40 hover:bg-accent/40 disabled:cursor-not-allowed disabled:opacity-60",
            dragging && "border-primary/60 bg-accent/60",
          )}
        >
          <ImageUp aria-hidden className="size-6 text-ink-secondary" />
          <span className="text-sm font-medium text-ink">{label ?? "Choose an image or drop it here"}</span>
          <span id={`${inputId}-rules`} className="text-xs text-ink-secondary">
            {rule.label}, up to {formatBytes(rule.maxBytes)}
          </span>
        </button>
      )}
      {disabledReason && <p className="text-xs text-ink-secondary">{disabledReason}</p>}
      {problem && (
        <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">
          {problem}
        </p>
      )}

      {file && preview && (
        <div className="flex flex-wrap items-start gap-4 rounded-xl border border-border bg-surface p-3 shadow-card">
          {/* eslint-disable-next-line @next/next/no-img-element -- local object URL preview */}
          <img src={preview} alt={`Preview of ${file.name}`} className="h-28 w-40 rounded-lg border border-border object-cover" />
          <div className="min-w-0 flex-1 space-y-1.5 text-[13px]">
            <p className="truncate font-medium text-ink">{file.name}</p>
            <p className="text-ink-secondary tabular-nums">{formatBytes(file.size)}</p>
            {uploaded ? (
              <p className="text-success">
                Uploaded · <span className="font-mono text-xs">sha256 {uploaded.sha256.slice(0, 12)}…</span>
              </p>
            ) : (
              <p className="text-ink-secondary">Not uploaded yet. Check the preview first.</p>
            )}
            <div className="flex flex-wrap gap-2 pt-1">
              {!uploaded && (
                <Button size="sm" onClick={() => upload.mutate(file)} disabled={upload.isPending}>
                  <Upload aria-hidden />
                  {upload.isPending ? "Uploading…" : "Upload"}
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={clear} disabled={upload.isPending}>
                {uploaded ? <RotateCw aria-hidden /> : <X aria-hidden />}
                {uploaded ? "Upload another" : "Remove"}
              </Button>
            </div>
          </div>
        </div>
      )}
      {upload.error && <ErrorState error={upload.error} onRetry={() => file && upload.mutate(file)} />}
    </div>
  );
}
