import { rupiah } from "@/lib/format";
import { cn } from "@/lib/utils";

export const SETTLEMENT_STATUS = {
  PENDING: { label: "Belum Disetor", tone: "pending" },
  WAITING_VERIFICATION: { label: "Menunggu Verifikasi", tone: "active" },
  SETTLED: { label: "Selesai", tone: "success" },
};

export const PAYOUT_STATUS = {
  NOT_READY: { label: "Belum Siap", tone: "neutral" },
  PENDING: { label: "Belum Dibayar", tone: "pending" },
  PAID: { label: "Sudah Dibayar", tone: "success" },
};

const TONE = {
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  active: "bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-300",
  success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300",
};

export const ShareBadge = ({ value, map = "settlement" }) => {
  const dict = map === "payout" ? PAYOUT_STATUS : SETTLEMENT_STATUS;
  const meta = dict[value] || { label: value || "-", tone: "neutral" };
  return (
    <span
      data-testid={`share-badge-${value}`}
      className={cn("inline-flex items-center rounded-md px-2 py-1 text-[10px] font-semibold uppercase tracking-widest", TONE[meta.tone])}
    >
      {meta.label}
    </span>
  );
};

const Row = ({ label, value, strong, accent }) => (
  <div className={cn("flex items-baseline justify-between gap-4 py-1.5", strong && "border-t pt-3 mt-1")}>
    <span className={cn("text-xs text-muted-foreground", strong && "font-semibold text-foreground")}>{label}</span>
    <span className={cn("num text-sm font-medium", strong && "font-heading text-base font-semibold", accent && "text-primary")}>
      {value}
    </span>
  </div>
);

/** Breakdown lengkap agar Pendana memahami sumber setiap angka. */
export function ShareBreakdown({ d, testId = "share-breakdown" }) {
  if (!d) return null;
  return (
    <div data-testid={testId} className="rounded-xl bg-muted/60 p-5">
      <Row label="Pokok Pinjaman" value={rupiah(d.principal)} />
      <Row label="Bunga Terealisasi" value={rupiah(d.interest_realized)} />
      <Row label="Denda Terealisasi" value={rupiah(d.late_fee_realized)} />
      <Row label="Total Diterima Pendana" value={rupiah(d.total_received)} strong />
      <div className="mt-4 space-y-0">
        <Row label="Profit Pool (bunga + denda)" value={rupiah(d.profit_pool)} />
        <Row label={`Pendana ${d.lender_pct_snapshot}%`} value={rupiah(d.lender_profit)} />
        <Row label={`Admin ${d.admin_pct_snapshot}%`} value={rupiah(d.admin_profit)} />
        <Row label={`Aplikator ${d.platform_pct_snapshot}%`} value={rupiah(d.platform_profit)} />
      </div>
      <div className="mt-4">
        <Row label="Hak Pokok Pendana" value={rupiah(d.principal_return)} />
        <Row label="Total Hak Pendana" value={rupiah(d.lender_total_entitlement)} strong />
        <Row label="Wajib Disetor ke Rekening Pusat" value={rupiah(d.lender_settlement_due)} strong accent />
      </div>
    </div>
  );
}

export function SettlementAccountCard({ account }) {
  if (!account?.settlement_account_number) {
    return (
      <p data-testid="settlement-account-empty" className="rounded-xl border border-dashed px-4 py-3 text-xs text-muted-foreground">
        Rekening settlement belum diatur oleh Superadmin. Hubungi Superadmin sebelum melakukan setoran.
      </p>
    );
  }
  return (
    <div data-testid="settlement-account-card" className="rounded-xl bg-primary p-5 text-primary-foreground">
      <p className="text-[10px] uppercase tracking-widest text-primary-foreground/70">Rekening Settlement Pusat</p>
      <p className="mt-2 font-heading text-lg font-semibold">
        {account.settlement_account_type}
        {account.settlement_account_bank_name ? ` · ${account.settlement_account_bank_name}` : ""}
      </p>
      <p className="num text-sm">{account.settlement_account_number}</p>
      <p className="text-sm uppercase">{account.settlement_account_holder}</p>
      {account.settlement_instructions && (
        <p className="mt-3 border-t border-primary-foreground/20 pt-3 text-xs text-primary-foreground/80">
          {account.settlement_instructions}
        </p>
      )}
    </div>
  );
}
