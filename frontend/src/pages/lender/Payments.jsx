import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { rupiah, formatDateTime } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, StatusBadge, ProofImage, Field, ConfirmDialog } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

export default function LenderPayments() {
  const [tab, setTab] = useState("PENDING");
  const [verifyTarget, setVerifyTarget] = useState(null);
  const [rejectTarget, setRejectTarget] = useState(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["payments", tab],
    queryFn: async () => (await api.get("/payments", { params: { status: tab, page_size: 50 } })).data,
  });

  const act = async (fn, msg) => {
    setBusy(true);
    try {
      await fn();
      toast.success(msg);
      setVerifyTarget(null);
      setRejectTarget(null);
      setReason("");
      await refetch();
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["loans"] });
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title="Pembayaran" description="Verifikasi laporan pembayaran dari Peminjam yang Anda danai." />
      <Tabs value={tab} onValueChange={setTab} className="mb-6">
        <TabsList>
          <TabsTrigger value="PENDING" data-testid="payments-tab-pending">Menunggu Verifikasi</TabsTrigger>
          <TabsTrigger value="VERIFIED,REJECTED" data-testid="payments-tab-history">Riwayat</TabsTrigger>
        </TabsList>
      </Tabs>

      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <div className="space-y-5" data-testid="lender-payments-list">
          {data.items.map((p) => (
            <div key={p.id} className="rounded-2xl border bg-card p-6 card-soft" data-testid={`payment-card-${p.id}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-heading text-sm font-semibold num">{p.loan_number}</p>
                  <p className="text-xs text-muted-foreground">{p.borrower_name} · Attempt #{p.attempt_no}</p>
                </div>
                <StatusBadge value={p.status} map="payment" />
              </div>
              <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
                <Field label="Total Tagihan" value={rupiah(p.amount_due_at_submission)} mono />
                <Field label="Dilaporkan Dibayar" value={rupiah(p.amount_paid)} mono />
                <Field label="Denda Termasuk" value={rupiah(p.late_fee_at_submission)} mono />
                <Field label="Waktu Lapor" value={formatDateTime(p.payment_submitted_at)} />
              </div>
              {p.lender_bank && (
                <p className="mt-4 text-xs text-muted-foreground">
                  Rekening tujuan: {p.lender_bank.bank_name} · {p.lender_bank.account_number} · {p.lender_bank.account_holder}
                </p>
              )}
              {p.rejection_reason && <p className="mt-3 text-sm text-destructive">Ditolak: {p.rejection_reason}</p>}
              <div className="mt-5">
                <ProofImage fileId={p.proof_file_id} label="Lihat Bukti Pembayaran" testId={`proof-btn-${p.id}`} />
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                {p.status === "PENDING" && (
                  <>
                    <Button data-testid={`verify-btn-${p.id}`} className="rounded-full" onClick={() => setVerifyTarget(p)}>
                      Pembayaran Diterima
                    </Button>
                    <Button data-testid={`reject-btn-${p.id}`} variant="outline" className="rounded-full" onClick={() => setRejectTarget(p)}>
                      Tolak Pembayaran
                    </Button>
                  </>
                )}
                <Button variant="ghost" className="rounded-full" onClick={() => navigate(`/loans/${p.loan_id}`)}>
                  Detail Pinjaman
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState testId="empty-lender-payments" title="Tidak ada pembayaran" description="Belum ada laporan pembayaran pada kategori ini." />
      )}

      <ConfirmDialog
        open={!!verifyTarget}
        onOpenChange={() => setVerifyTarget(null)}
        testId="verify-dialog"
        title="Pembayaran diterima?"
        description={verifyTarget ? `Pastikan dana ${rupiah(verifyTarget.amount_due_at_submission)} benar-benar sudah masuk ke rekening Anda. Pinjaman akan ditandai LUNAS.` : ""}
        confirmLabel="Ya, Sudah Masuk"
        loading={busy}
        onConfirm={() => act(() => api.post(`/payments/${verifyTarget.id}/verify`), "Pembayaran diverifikasi, pinjaman LUNAS")}
      />

      <Dialog open={!!rejectTarget} onOpenChange={() => setRejectTarget(null)}>
        <DialogContent data-testid="reject-payment-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Tolak laporan pembayaran</DialogTitle>
            <DialogDescription>Alasan wajib diisi. Denda akan kembali dihitung berdasarkan tanggal aktual.</DialogDescription>
          </DialogHeader>
          <Textarea data-testid="reject-reason-input" value={reason} onChange={(e) => setReason(e.target.value)} rows={4} placeholder="Contoh: Dana belum masuk ke rekening." />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejectTarget(null)} disabled={busy}>Batal</Button>
            <Button
              data-testid="reject-payment-submit-btn"
              variant="destructive"
              disabled={busy || reason.trim().length < 3}
              onClick={() => act(() => api.post(`/payments/${rejectTarget.id}/reject`, { reason }), "Laporan pembayaran ditolak")}
            >
              {busy ? "Memproses..." : "Tolak Pembayaran"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
