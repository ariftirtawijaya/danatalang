import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import { TONE_CLASS, LOAN_STATUS, ACCOUNT_STATUS, PAYMENT_STATUS } from "@/lib/status";
import { Skeleton } from "@/components/ui/skeleton";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Inbox } from "lucide-react";

export const StatusBadge = ({ value, map = "loan", className }) => {
  const dict = map === "account" ? ACCOUNT_STATUS : map === "payment" ? PAYMENT_STATUS : LOAN_STATUS;
  const meta = dict[value] || { label: value || "-", tone: "neutral" };
  return (
    <span
      data-testid={`status-badge-${value}`}
      className={cn(
        "inline-flex items-center rounded-md px-2 py-1 text-[10px] font-semibold uppercase tracking-widest",
        TONE_CLASS[meta.tone],
        className
      )}
    >
      {meta.label}
    </span>
  );
};

export const StatCard = ({ label, value, sub, icon: Icon, tone = "neutral", testId, onClick }) => (
  <div
    data-testid={testId}
    onClick={onClick}
    className={cn(
      "rounded-2xl border bg-card p-5 card-soft h-full flex flex-col gap-3",
      onClick && "cursor-pointer transition-transform hover:-translate-y-0.5"
    )}
  >
    <div className="flex items-start justify-between gap-3">
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      {Icon && (
        <span className={cn("rounded-lg p-1.5", TONE_CLASS[tone])}>
          <Icon className="h-4 w-4" />
        </span>
      )}
    </div>
    <div>
      <p className="font-heading text-2xl font-semibold num">{value}</p>
      {sub && <p className="mt-1 text-xs text-muted-foreground">{sub}</p>}
    </div>
  </div>
);

export const EmptyState = ({ title, description, action, testId }) => (
  <div data-testid={testId} className="flex flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-14 text-center">
    <Inbox className="mb-3 h-8 w-8 text-muted-foreground/60" />
    <p className="font-heading text-base font-medium">{title}</p>
    {description && <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>}
    {action && <div className="mt-5">{action}</div>}
  </div>
);

export const LoadingRows = ({ rows = 4 }) => (
  <div className="space-y-3">
    {Array.from({ length: rows }).map((_, i) => (
      <Skeleton key={i} className="h-16 w-full rounded-xl" />
    ))}
  </div>
);

export const PageHeader = ({ title, description, children }) => (
  <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
    <div>
      <h1 className="font-heading text-2xl font-semibold sm:text-3xl">{title}</h1>
      {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
    </div>
    {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
  </div>
);

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = "Lanjutkan", onConfirm, loading, testId, destructive }) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent data-testid={testId}>
        <AlertDialogHeader>
          <AlertDialogTitle className="font-heading">{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel data-testid="confirm-cancel-btn" disabled={loading}>Batal</AlertDialogCancel>
          <AlertDialogAction
            data-testid="confirm-accept-btn"
            disabled={loading}
            onClick={(e) => {
              e.preventDefault();
              onConfirm();
            }}
            className={destructive ? "bg-destructive text-destructive-foreground hover:bg-destructive/90" : ""}
          >
            {loading ? "Memproses..." : confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function ProofImage({ fileId, label = "Lihat Bukti", testId }) {
  const [url, setUrl] = useState(null);
  const [open, setOpen] = useState(false);
  const [isPdf, setIsPdf] = useState(false);

  // Blob URL hanya direvoke saat unmount / fileId berubah / tampilan ditutup —
  // JANGAN memasukkan `url` ke dependency, karena setUrl akan memicu cleanup dan
  // merevoke blob yang baru saja dibuat (ERR_FILE_NOT_FOUND pada <img>/link PDF).
  useEffect(() => {
    if (!open || !fileId) return undefined;
    let objectUrl;
    let cancelled = false;
    setUrl(null);
    api
      .get(`/files/${fileId}`, { responseType: "blob" })
      .then(({ data }) => {
        if (cancelled) return;
        setIsPdf(data.type === "application/pdf");
        objectUrl = URL.createObjectURL(data);
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setUrl("error");
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [open, fileId]);

  if (!fileId) return <span className="text-sm text-muted-foreground">Tidak ada bukti</span>;

  return (
    <div className="space-y-2">
      {!open && (
        <Button data-testid={testId || "view-proof-btn"} variant="outline" size="sm" className="rounded-full" onClick={() => setOpen(true)}>
          {label}
        </Button>
      )}
      {open && url === "error" && <p className="text-sm text-destructive">Gagal memuat bukti</p>}
      {open && url && url !== "error" && (
        isPdf ? (
          <a href={url} target="_blank" rel="noreferrer" className="text-sm font-medium text-primary underline">
            Buka dokumen bukti (PDF)
          </a>
        ) : (
          <img
            data-testid="proof-image"
            src={url}
            alt="Bukti transfer"
            className="max-h-80 w-full max-w-sm rounded-xl border object-contain bg-muted"
          />
        )
      )}
      {open && !url && <Skeleton className="h-40 w-full max-w-sm rounded-xl" />}
    </div>
  );
}

export const Field = ({ label, value, mono }) => (
  <div className="space-y-1">
    <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
    <p className={cn("text-sm font-medium", mono && "num")}>{value ?? "-"}</p>
  </div>
);
