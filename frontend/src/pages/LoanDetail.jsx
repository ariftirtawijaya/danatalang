import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { rupiah, formatDate, formatDateTime, formatThousand, onlyDigits, maskNik } from "@/lib/format";
import { StatusBadge, Field, ConfirmDialog, ProofImage, LoadingRows, PageHeader } from "@/components/common";
import { statusLabel } from "@/lib/status";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { ArrowLeft, CircleDot } from "lucide-react";

const RejectDialog = ({ open, onOpenChange, title, onSubmit, loading, testId }) => {
  const [reason, setReason] = useState("");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid={testId}>
        <DialogHeader>
          <DialogTitle className="font-heading">{title}</DialogTitle>
          <DialogDescription>Alasan wajib diisi dan akan tercatat pada audit log.</DialogDescription>
        </DialogHeader>
        <Textarea data-testid="reject-reason-input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Tulis alasan..." rows={4} />
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={loading}>Batal</Button>
          <Button
            data-testid="reject-submit-btn"
            variant="destructive"
            disabled={loading || reason.trim().length < 3}
            onClick={() => onSubmit(reason)}
          >
            {loading ? "Memproses..." : "Kirim Penolakan"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

function ProofForm({ open, onOpenChange, title, description, amountLabel, fixedAmount, onSubmit, loading, testId, confirmText }) {
  const [amount, setAmount] = useState(fixedAmount ? String(fixedAmount) : "");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [time, setTime] = useState(new Date().toTimeString().slice(0, 5));
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState(null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid={testId} className="max-h-[92vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-heading">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>{amountLabel}</Label>
            <Input
              data-testid="proof-amount-input"
              inputMode="numeric"
              value={formatThousand(amount)}
              onChange={(e) => setAmount(onlyDigits(e.target.value))}
              className="h-11 rounded-xl num"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Tanggal Transfer</Label>
              <Input data-testid="proof-date-input" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-11 rounded-xl" />
            </div>
            <div className="space-y-2">
              <Label>Jam Transfer</Label>
              <Input data-testid="proof-time-input" type="time" value={time} onChange={(e) => setTime(e.target.value)} className="h-11 rounded-xl" />
            </div>
          </div>
          <div className="space-y-2">
            <Label>Bukti Transfer (JPG/PNG/PDF, maks 5MB)</Label>
            <Input
              data-testid="proof-file-input"
              type="file"
              accept="image/jpeg,image/png,image/webp,application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="h-11 rounded-xl"
            />
          </div>
          <div className="space-y-2">
            <Label>Catatan (opsional)</Label>
            <Textarea data-testid="proof-notes-input" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} />
          </div>
          <p className="rounded-xl bg-muted px-4 py-3 text-xs text-muted-foreground">{confirmText}</p>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={loading}>Batal</Button>
          <Button
            data-testid="proof-submit-btn"
            disabled={loading || !file || !amount}
            onClick={() => onSubmit({ amount: Number(amount), date, time, notes, file })}
          >
            {loading ? "Mengirim..." : "Kirim"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function LoanDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState(null);

  const { data: loan, isLoading, refetch } = useQuery({
    queryKey: ["loan", id],
    queryFn: async () => (await api.get(`/loans/${id}`)).data,
  });

  const role = user?.role;
  const isStaff = role === "admin" || role === "superadmin";
  const pendingPayment = loan?.payments?.find((p) => p.status === "PENDING");

  const after = async (msg) => {
    toast.success(msg);
    setDialog(null);
    await refetch();
    qc.invalidateQueries({ queryKey: ["dashboard"] });
    qc.invalidateQueries({ queryKey: ["loans"] });
    qc.invalidateQueries({ queryKey: ["payments"] });
  };

  const run = async (fn, msg) => {
    setBusy(true);
    try {
      await fn();
      await after(msg);
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  if (isLoading) return <LoadingRows rows={5} />;
  if (!loan) return <p className="text-sm text-muted-foreground">Pinjaman tidak ditemukan.</p>;

  const uploadDisbursement = ({ amount, date, time, notes, file }) => {
    const fd = new FormData();
    fd.append("amount", amount);
    fd.append("transfer_at", `${date}T${time}`);
    fd.append("notes", notes || "");
    fd.append("proof", file);
    return run(() => api.post(`/loans/${loan.id}/disburse`, fd), "Pencairan berhasil dilaporkan");
  };

  const uploadPayment = ({ amount, date, time, notes, file }) => {
    const fd = new FormData();
    fd.append("amount", amount);
    fd.append("paid_at", `${date}T${time}`);
    fd.append("notes", notes || "");
    fd.append("proof", file);
    return run(() => api.post(`/loans/${loan.id}/pay`, fd), "Laporan pembayaran terkirim, menunggu verifikasi Pendana");
  };

  return (
    <div>
      <button data-testid="back-btn" onClick={() => navigate(-1)} className="mb-5 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Kembali
      </button>

      <PageHeader title={loan.loan_number} description={`Diajukan ${formatDateTime(loan.submitted_at)}`}>
        <StatusBadge value={loan.effective_status} />
      </PageHeader>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section className="rounded-2xl border bg-card p-6 card-soft" data-testid="loan-summary">
            <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Ringkasan Pinjaman</p>
            <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-3">
              <Field label="Pokok" value={rupiah(loan.principal_amount)} mono />
              <Field label={`Bunga (${loan.interest_rate}%)`} value={rupiah(loan.interest_amount)} mono />
              <Field label="Total Tagihan Dasar" value={rupiah(loan.base_repayment_amount)} mono />
              <Field label="Durasi" value={`${loan.duration_days} hari`} />
              <Field label="Denda / Hari" value={`${loan.late_fee_rate}%`} />
              <Field label="Tanggal Pencairan" value={loan.disbursed_at ? formatDate(loan.disbursed_at) : "-"} />
              <Field label="Jatuh Tempo" value={loan.due_date ? formatDate(loan.due_date) : "-"} />
              <Field label="Keterlambatan" value={loan.late_days > 0 ? `${loan.late_days} hari` : "-"} />
              <Field label="Denda" value={rupiah(loan.late_fee_amount)} mono />
            </div>
            <div className="mt-6 flex items-end justify-between border-t pt-5">
              <p className="font-heading text-sm font-semibold">TOTAL YANG HARUS DIBAYAR</p>
              <p data-testid="loan-total-due" className="font-heading text-2xl font-semibold num">{rupiah(loan.total_due)}</p>
            </div>
            {loan.payment_frozen && (
              <p className="mt-3 text-xs text-muted-foreground">
                Denda dibekukan sejak laporan pembayaran dikirim. Nilai tagihan tidak bertambah selama menunggu verifikasi Pendana.
              </p>
            )}
          </section>

          {loan.rejection_reason && (
            <section className="rounded-2xl border border-destructive/30 bg-destructive/5 p-6" data-testid="rejection-box">
              <p className="font-heading text-sm font-semibold text-destructive">Pengajuan Ditolak</p>
              <p className="mt-1 text-sm text-muted-foreground">{loan.rejection_reason}</p>
            </section>
          )}

          {(isStaff || role === "lender") && (
            <section className="rounded-2xl border bg-card p-6 card-soft">
              <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Data Peminjam</p>
              <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-3">
                <Field label="Nama" value={loan.borrower_name} />
                <Field label="No HP" value={loan.borrower_phone} mono />
                {loan.borrower_nik && <Field label="NIK" value={isStaff ? loan.borrower_nik : maskNik(loan.borrower_nik)} mono />}
                {loan.borrower_account_status && <Field label="Status Akun" value={statusLabel(loan.borrower_account_status)} />}
              </div>
              {loan.borrower_bank && (
                <div className="mt-5 rounded-xl bg-muted p-5">
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Rekening Tujuan Pencairan</p>
                  <p className="mt-1 font-heading text-lg font-semibold">{loan.borrower_bank.bank_name}</p>
                  <p className="num text-sm">{loan.borrower_bank.account_number}</p>
                  <p className="text-sm uppercase">{loan.borrower_bank.account_holder}</p>
                </div>
              )}
            </section>
          )}

          {isStaff && loan.borrower_credit && (
            <section className="rounded-2xl border bg-card p-6 card-soft" data-testid="credit-info">
              <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Informasi Kredit & Histori</p>
              <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
                <Field label="Limit" value={rupiah(loan.borrower_credit.borrower_limit)} mono />
                <Field label="Terpakai" value={rupiah(loan.borrower_credit.outstanding_principal)} mono />
                <Field label="Tersedia" value={rupiah(loan.borrower_credit.available_limit)} mono />
                <Field label="Pinjaman Aktif" value={`${loan.borrower_credit.active_loans} / ${loan.borrower_credit.max_active_loans}`} />
                <Field label="Total Pengajuan" value={loan.borrower_credit.total_applications} />
                <Field label="Lunas" value={loan.borrower_credit.completed_loans} />
                <Field label="Lunas Tepat Waktu" value={loan.borrower_credit.paid_on_time} />
                <Field label="Pernah Terlambat" value={loan.borrower_credit.paid_late} />
                <Field label="Total Hari Terlambat" value={loan.borrower_credit.total_late_days} />
                <Field label="Terlambat Terlama" value={`${loan.borrower_credit.longest_late_days} hari`} />
                <Field label="Total Pernah Dipinjam" value={rupiah(loan.borrower_credit.total_borrowed_amount)} mono />
                <Field label="Ditolak" value={loan.borrower_credit.total_rejected} />
              </div>
            </section>
          )}

          {loan.disbursement && (
            <section className="rounded-2xl border bg-card p-6 card-soft" data-testid="disbursement-box">
              <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Pencairan</p>
              <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-3">
                <Field label="Nominal" value={rupiah(loan.disbursement.amount)} mono />
                <Field label="Waktu Transfer" value={formatDateTime(loan.disbursement.transfer_at)} />
                <Field label="Dikonfirmasi" value={loan.disbursement.confirmed_at ? formatDateTime(loan.disbursement.confirmed_at) : "Belum"} />
                <Field label="Pendana" value={loan.lender_name} />
                <Field label="Catatan" value={loan.disbursement.notes || "-"} />
              </div>
              <div className="mt-5">
                <ProofImage fileId={loan.disbursement.proof_file_id} label="Lihat Bukti Transfer" testId="view-disbursement-proof-btn" />
              </div>
            </section>
          )}

          {loan.payments?.length > 0 && (
            <section className="rounded-2xl border bg-card p-6 card-soft" data-testid="payments-box">
              <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Riwayat Pembayaran</p>
              <div className="mt-5 space-y-5">
                {loan.payments.map((p) => (
                  <div key={p.id} className="rounded-xl border p-5" data-testid={`payment-attempt-${p.attempt_no}`}>
                    <div className="flex items-center justify-between">
                      <p className="font-heading text-sm font-semibold">Payment Attempt #{p.attempt_no}</p>
                      <StatusBadge value={p.status} map="payment" />
                    </div>
                    <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
                      <Field label="Dibayar" value={rupiah(p.amount_paid)} mono />
                      <Field label="Tagihan Saat Lapor" value={rupiah(p.amount_due_at_submission)} mono />
                      <Field label="Denda Saat Lapor" value={rupiah(p.late_fee_at_submission)} mono />
                      <Field label="Dilaporkan" value={formatDateTime(p.payment_submitted_at)} />
                    </div>
                    {p.rejection_reason && <p className="mt-3 text-sm text-destructive">Ditolak: {p.rejection_reason}</p>}
                    {p.notes && <p className="mt-2 text-xs text-muted-foreground">Catatan: {p.notes}</p>}
                    <div className="mt-4">
                      <ProofImage fileId={p.proof_file_id} label="Lihat Bukti Pembayaran" testId={`view-payment-proof-${p.attempt_no}`} />
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {loan.timeline?.length > 0 && (
            <section className="rounded-2xl border bg-card p-6 card-soft" data-testid="loan-timeline">
              <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Timeline Aktivitas</p>
              <ol className="mt-5 space-y-4">
                {loan.timeline.map((t, i) => (
                  <li key={i} className="flex gap-3">
                    <CircleDot className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                    <div>
                      <p className="text-sm font-medium">
                        {t.from_status ? `${statusLabel(t.from_status)} → ${statusLabel(t.to_status)}` : statusLabel(t.to_status)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {formatDateTime(t.changed_at)} · {t.changed_by_name}
                        {t.reason ? ` · ${t.reason}` : ""}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>

        <aside className="space-y-4">
          <section className="rounded-2xl border bg-card p-6 card-soft">
            <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Tindakan</p>
            <div className="mt-5 space-y-3">
              {isStaff && loan.status === "WAITING_ADMIN_APPROVAL" && (
                <>
                  <Button data-testid="approve-loan-btn" className="w-full rounded-full" onClick={() => setDialog("approve")}>
                    Setujui Pengajuan
                  </Button>
                  <Button data-testid="reject-loan-btn" variant="outline" className="w-full rounded-full" onClick={() => setDialog("reject-loan")}>
                    Tolak Pengajuan
                  </Button>
                </>
              )}
              {isStaff && loan.status === "WAITING_DISBURSEMENT_CONFIRMATION" && (
                <Button data-testid="confirm-disbursement-btn" className="w-full rounded-full" onClick={() => setDialog("confirm-disb")}>
                  Konfirmasi Pencairan
                </Button>
              )}
              {role === "lender" && loan.status === "WAITING_FUNDING" && (
                <Button data-testid="claim-funding-btn" className="w-full rounded-full" onClick={() => setDialog("claim")}>
                  Ambil Pendanaan
                </Button>
              )}
              {role === "lender" && loan.status === "FUNDING_CLAIMED" && loan.lender_id === user.id && (
                <Button data-testid="report-disbursement-btn" className="w-full rounded-full" onClick={() => setDialog("disburse")}>
                  Sudah Dicairkan
                </Button>
              )}
              {role === "lender" && loan.status === "WAITING_PAYMENT_VERIFICATION" && pendingPayment && loan.lender_id === user.id && (
                <>
                  <Button data-testid="verify-payment-btn" className="w-full rounded-full" onClick={() => setDialog("verify")}>
                    Pembayaran Diterima
                  </Button>
                  <Button data-testid="reject-payment-btn" variant="outline" className="w-full rounded-full" onClick={() => setDialog("reject-payment")}>
                    Tolak Pembayaran
                  </Button>
                </>
              )}
              {role === "borrower" && ["ACTIVE", "OVERDUE"].includes(loan.status) && (
                <Button data-testid="pay-loan-btn" className="w-full rounded-full" onClick={() => setDialog("pay")}>
                  Saya Sudah Membayar
                </Button>
              )}
              {role === "borrower" && loan.status === "WAITING_PAYMENT_VERIFICATION" && (
                <p className="text-sm text-muted-foreground">Menunggu verifikasi pembayaran oleh Pendana.</p>
              )}
              {loan.status === "PAID" && <p className="text-sm font-medium text-emerald-600">Pinjaman ini telah LUNAS.</p>}
              {isStaff && loan.status === "WAITING_PAYMENT_VERIFICATION" && (
                <p className="text-sm text-muted-foreground">
                  Verifikasi pembayaran hanya dapat dilakukan oleh Pendana yang mendanai pinjaman ini.
                </p>
              )}
            </div>
          </section>

          {role === "superadmin" && loan.status === "WAITING_PAYMENT_VERIFICATION" && pendingPayment && (
            <section className="rounded-2xl border border-destructive/40 bg-destructive/5 p-6" data-testid="superadmin-override-box">
              <p className="font-heading text-sm font-semibold uppercase tracking-widest text-destructive">Emergency Override</p>
              <p className="mt-2 text-xs text-muted-foreground">
                Gunakan hanya pada kondisi luar biasa (misal Pendana tidak dapat dihubungi). Di luar alur pembayaran normal,
                wajib beralasan, dan seluruh tindakan tercatat pada Audit Log.
              </p>
              <div className="mt-5 space-y-3">
                <Button data-testid="override-verify-btn" variant="destructive" className="w-full rounded-full" onClick={() => setDialog("override-verify")}>
                  Override: Tandai Lunas
                </Button>
                <Button data-testid="override-reject-btn" variant="outline" className="w-full rounded-full" onClick={() => setDialog("override-reject")}>
                  Override: Tolak Pembayaran
                </Button>
              </div>
            </section>
          )}

          {loan.lender_bank && (role === "borrower" || isStaff) && ["ACTIVE", "OVERDUE", "WAITING_PAYMENT_VERIFICATION"].includes(loan.status) && (
            <section className="rounded-2xl border bg-primary p-6 text-primary-foreground card-soft" data-testid="payment-destination">
              <p className="text-[10px] uppercase tracking-widest text-primary-foreground/70">Transfer Pembayaran Ke</p>
              <p className="mt-2 font-heading text-xl font-semibold">{loan.lender_bank.bank_name}</p>
              <p className="num text-sm">{loan.lender_bank.account_number}</p>
              <p className="text-sm uppercase">{loan.lender_bank.account_holder}</p>
              <div className="mt-5 border-t border-primary-foreground/20 pt-4">
                <p className="text-[10px] uppercase tracking-widest text-primary-foreground/70">Total Yang Harus Dibayar</p>
                <p className="font-heading text-2xl font-semibold num">{rupiah(loan.total_due)}</p>
              </div>
            </section>
          )}
        </aside>
      </div>

      <ConfirmDialog
        open={dialog === "approve"}
        onOpenChange={() => setDialog(null)}
        testId="approve-confirm-dialog"
        title="Setujui pengajuan?"
        description={`Yakin ingin menyetujui pinjaman ${loan.loan_number} sebesar ${rupiah(loan.principal_amount)}? Pinjaman akan ditawarkan kepada Pendana.`}
        confirmLabel="Ya, Setujui"
        loading={busy}
        onConfirm={() => run(() => api.post(`/loans/${loan.id}/approve`), "Pengajuan disetujui")}
      />
      <ConfirmDialog
        open={dialog === "claim"}
        onOpenChange={() => setDialog(null)}
        testId="claim-confirm-dialog"
        title="Ambil pendanaan?"
        description={`Yakin ingin mengambil pendanaan ${rupiah(loan.principal_amount)}? Hanya satu Pendana dapat mendanai pinjaman ini.`}
        confirmLabel="Ya, Ambil"
        loading={busy}
        onConfirm={() => run(() => api.post(`/loans/${loan.id}/claim`), "Pendanaan berhasil diambil")}
      />
      <ConfirmDialog
        open={dialog === "confirm-disb"}
        onOpenChange={() => setDialog(null)}
        testId="confirm-disb-dialog"
        title="Konfirmasi pencairan?"
        description={`Pastikan dana ${rupiah(loan.principal_amount)} benar-benar telah diterima Peminjam. Jatuh tempo dihitung dari waktu konfirmasi ini.`}
        confirmLabel="Ya, Konfirmasi"
        loading={busy}
        onConfirm={() => run(() => api.post(`/loans/${loan.id}/confirm-disbursement`), "Pencairan dikonfirmasi, pinjaman aktif")}
      />
      <ConfirmDialog
        open={dialog === "verify"}
        onOpenChange={() => setDialog(null)}
        testId="verify-payment-dialog"
        title="Pembayaran diterima?"
        description={`Pastikan dana ${rupiah(pendingPayment?.amount_due_at_submission)} benar-benar sudah masuk ke rekening Anda. Pinjaman akan ditandai LUNAS.`}
        confirmLabel="Ya, Sudah Masuk"
        loading={busy}
        onConfirm={() => run(() => api.post(`/payments/${pendingPayment.id}/verify`), "Pembayaran diverifikasi, pinjaman LUNAS")}
      />
      <RejectDialog
        open={dialog === "reject-loan"}
        onOpenChange={() => setDialog(null)}
        testId="reject-loan-dialog"
        title="Tolak pengajuan pinjaman"
        loading={busy}
        onSubmit={(reason) => run(() => api.post(`/loans/${loan.id}/reject`, { reason }), "Pengajuan ditolak")}
      />
      <RejectDialog
        open={dialog === "override-verify"}
        onOpenChange={() => setDialog(null)}
        testId="override-verify-dialog"
        title="Override Superadmin — tandai LUNAS"
        loading={busy}
        onSubmit={(reason) =>
          reason.trim().length < 10
            ? toast.error("Alasan override minimal 10 karakter")
            : run(() => api.post(`/payments/${pendingPayment.id}/override`, { action: "verify", reason }), "Override Superadmin: pinjaman ditandai LUNAS")
        }
      />
      <RejectDialog
        open={dialog === "override-reject"}
        onOpenChange={() => setDialog(null)}
        testId="override-reject-dialog"
        title="Override Superadmin — tolak pembayaran"
        loading={busy}
        onSubmit={(reason) =>
          reason.trim().length < 10
            ? toast.error("Alasan override minimal 10 karakter")
            : run(() => api.post(`/payments/${pendingPayment.id}/override`, { action: "reject", reason }), "Override Superadmin: laporan pembayaran ditolak")
        }
      />
      <RejectDialog
        open={dialog === "reject-payment"}
        onOpenChange={() => setDialog(null)}
        testId="reject-payment-dialog"
        title="Tolak laporan pembayaran"
        loading={busy}
        onSubmit={(reason) => run(() => api.post(`/payments/${pendingPayment.id}/reject`, { reason }), "Laporan pembayaran ditolak")}
      />
      {dialog === "disburse" && (
        <ProofForm
          open
          onOpenChange={() => setDialog(null)}
          testId="disburse-dialog"
          title="Konfirmasi Pencairan Dana"
          description={`Transfer ${rupiah(loan.principal_amount)} ke rekening Peminjam, lalu unggah bukti transfer.`}
          amountLabel="Nominal Transfer"
          fixedAmount={loan.principal_amount}
          confirmText={`Pastikan Anda telah mentransfer ${rupiah(loan.principal_amount)} sebelum melanjutkan.`}
          loading={busy}
          onSubmit={uploadDisbursement}
        />
      )}
      {dialog === "pay" && (
        <ProofForm
          open
          onOpenChange={() => setDialog(null)}
          testId="pay-dialog"
          title="Laporkan Pembayaran"
          description={`Total tagihan Anda saat ini ${rupiah(loan.total_due)}. Pembayaran harus dilakukan sekaligus penuh.`}
          amountLabel="Nominal Yang Dibayar"
          fixedAmount={loan.total_due}
          confirmText={`Pastikan Anda telah mentransfer ${rupiah(loan.total_due)} ke rekening Pendana sebelum melanjutkan.`}
          loading={busy}
          onSubmit={uploadPayment}
        />
      )}
    </div>
  );
}
