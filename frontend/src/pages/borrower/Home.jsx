import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { rupiah, formatDate } from "@/lib/format";
import { StatusBadge, EmptyState, LoadingRows } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { AlertTriangle, PlusCircle, Clock } from "lucide-react";

export const LoanCard = ({ loan, cta }) => (
  <Link
    to={`/loans/${loan.id}`}
    data-testid={`loan-card-${loan.loan_number}`}
    className="block rounded-2xl border bg-card p-5 card-soft transition-transform hover:-translate-y-0.5"
  >
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="font-heading text-sm font-semibold num">{loan.loan_number}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{loan.borrower_name}</p>
      </div>
      <StatusBadge value={loan.effective_status} />
    </div>
    <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
      <div>
        <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Pokok</p>
        <p className="text-sm font-semibold num">{rupiah(loan.principal_amount)}</p>
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Total Tagihan</p>
        <p className="text-sm font-semibold num">{rupiah(loan.total_due)}</p>
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Jatuh Tempo</p>
        <p className="text-sm font-medium">{loan.due_date ? formatDate(loan.due_date) : "-"}</p>
      </div>
      <div>
        <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
          {loan.late_days > 0 ? "Terlambat" : "Durasi"}
        </p>
        <p className="text-sm font-medium">
          {loan.late_days > 0 ? `${loan.late_days} hari` : `${loan.duration_days} hari`}
        </p>
      </div>
    </div>
    {cta}
  </Link>
);

export default function BorrowerHome() {
  const { user } = useAuth();
  const { data: credit, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: async () => (await api.get("/dashboard")).data });
  const { data: loans } = useQuery({
    queryKey: ["loans", "borrower-active"],
    queryFn: async () =>
      (
        await api.get("/loans", {
          params: { status: "WAITING_ADMIN_APPROVAL,WAITING_FUNDING,FUNDING_CLAIMED,WAITING_DISBURSEMENT_CONFIRMATION,ACTIVE,OVERDUE,WAITING_PAYMENT_VERIFICATION", page_size: 20 },
        })
      ).data,
  });

  const status = user?.account_status;
  const usedPct = credit?.borrower_limit ? Math.min(100, (credit.outstanding_principal / credit.borrower_limit) * 100) : 0;

  return (
    <div className="space-y-7">
      <div className="animate-rise">
        <p className="text-sm text-muted-foreground">Selamat datang,</p>
        <h1 className="font-heading text-2xl font-semibold sm:text-3xl">{user?.full_name}</h1>
      </div>

      {status !== "ACTIVE" && (
        <div data-testid="account-status-notice" className="flex gap-3 rounded-2xl border border-amber-300/60 bg-amber-50 p-5 dark:bg-amber-500/10">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
          <div>
            <p className="font-heading text-sm font-semibold">
              {status === "WAITING_VERIFICATION" && "Akun Anda sedang menunggu verifikasi Admin."}
              {status === "REJECTED" && "Registrasi Anda ditolak."}
              {status === "SUSPENDED" && "Akun Anda sedang ditangguhkan."}
              {status === "BLOCKED" && "Akun Anda diblokir."}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {status === "WAITING_VERIFICATION"
                ? "Anda belum dapat mengajukan pinjaman sebelum Admin menyetujui akun dan menetapkan limit Anda."
                : user?.rejection_reason || "Silakan hubungi Admin untuk informasi lebih lanjut."}
            </p>
          </div>
        </div>
      )}

      {status === "ACTIVE" && (
        <>
          <div className="rounded-2xl border bg-primary p-6 text-primary-foreground card-soft" data-testid="limit-card">
            <p className="text-[10px] uppercase tracking-widest text-primary-foreground/70">Total Limit</p>
            <p className="mt-1 font-heading text-3xl font-semibold num">{rupiah(credit?.borrower_limit)}</p>
            <Progress value={usedPct} className="mt-5 h-2 bg-primary-foreground/20" />
            <div className="mt-4 grid grid-cols-2 gap-4">
              <div>
                <p className="text-[10px] uppercase tracking-widest text-primary-foreground/70">Terpakai</p>
                <p data-testid="limit-used" className="text-base font-semibold num">{rupiah(credit?.outstanding_principal)}</p>
              </div>
              <div>
                <p className="text-[10px] uppercase tracking-widest text-primary-foreground/70">Tersedia</p>
                <p data-testid="limit-available" className="text-base font-semibold num">{rupiah(credit?.available_limit)}</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-2xl border bg-card p-5 card-soft">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Pinjaman Aktif</p>
              <p data-testid="active-loan-count" className="mt-1 font-heading text-2xl font-semibold num">
                {credit?.active_loans ?? 0} / {credit?.max_active_loans ?? 0}
              </p>
            </div>
            <div className="rounded-2xl border bg-card p-5 card-soft">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Durasi Maks.</p>
              <p className="mt-1 font-heading text-2xl font-semibold num">{credit?.max_duration_days ?? 0} hari</p>
            </div>
          </div>

          <Button asChild data-testid="cta-apply-loan-btn" className="h-12 w-full rounded-full text-sm font-semibold">
            <Link to="/apply">
              <PlusCircle className="mr-2 h-4 w-4" /> Ajukan Pinjaman
            </Link>
          </Button>
        </>
      )}

      <section className="space-y-4">
        <h2 className="font-heading text-lg font-semibold">Pinjaman Berjalan</h2>
        {isLoading && <LoadingRows rows={2} />}
        {loans?.items?.length ? (
          <div className="space-y-4">
            {loans.items.map((l) => (
              <LoanCard key={l.id} loan={l} />
            ))}
          </div>
        ) : (
          !isLoading && (
            <EmptyState
              testId="empty-active-loans"
              title="Belum ada pinjaman berjalan"
              description="Pinjaman yang Anda ajukan akan muncul di sini beserta status prosesnya."
            />
          )
        )}
      </section>

      {credit?.completed_loans > 0 && (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Clock className="h-3.5 w-3.5" /> {credit.completed_loans} pinjaman telah lunas · {credit.paid_late} pernah terlambat
        </p>
      )}
    </div>
  );
}
