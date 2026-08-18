import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { rupiah, formatDateTime } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, ProofImage } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";

export default function AdminRemittance() {
  const [busy, setBusy] = useState(false);
  const [rejectTarget, setRejectTarget] = useState(null);
  const [reason, setReason] = useState("");

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["lender-remittances"],
    queryFn: async () => (await api.get("/admin-remittances")).data,
  });

  const run = async (fn, msg) => {
    setBusy(true);
    try { await fn(); toast.success(msg); setRejectTarget(null); setReason(""); await refetch(); }
    catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  const byStatus = (statuses) => (data?.items || []).filter((r) => statuses.includes(r.status));

  const Card = ({ r, children }) => (
    <div className="rounded-2xl border bg-card p-6 card-soft" data-testid={`lender-rem-${r.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-heading text-sm font-semibold num">{r.remittance_number}</p>
          <p className="text-xs text-muted-foreground">Admin {r.admin_name} · {r.item_count} pinjaman · dikirim {formatDateTime(r.submitted_at)}</p>
        </div>
        <span className="num font-heading text-base font-semibold">{rupiah(r.total_amount)}</span>
      </div>
      <div className="mt-4">
        {(r.items || []).map((i) => (
          <div key={i.id} className="flex flex-wrap items-baseline justify-between gap-3 border-b py-2 text-xs last:border-0" data-testid={`lender-rem-item-${i.id}`}>
            <span className="num font-semibold">{i.loan_number}</span>
            <span className="text-muted-foreground">{i.borrower_name}</span>
            <span className="text-muted-foreground">Pokok {rupiah(i.principal_snapshot)} · Bunga {rupiah(i.interest_snapshot)} · Denda {rupiah(i.late_fee_snapshot)}</span>
            <span className="num font-semibold">{rupiah(i.total_collected)}</span>
          </div>
        ))}
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        {r.proof_file_id && <ProofImage fileId={r.proof_file_id} label="Lihat Bukti Transfer" testId={`lender-rem-proof-${r.id}`} />}
        {children}
      </div>
      {r.rejection_reason && <p className="mt-3 text-sm text-destructive">Penolakan terakhir: {r.rejection_reason}</p>}
    </div>
  );

  return (
    <div>
      <PageHeader title="Setoran Admin" description="Setoran uang tagihan yang dikumpulkan Admin lapangan dari Peminjam Anda." />
      <Tabs defaultValue="waiting">
        <TabsList className="mb-6 flex-wrap">
          <TabsTrigger value="waiting" data-testid="rem-tab-waiting">Menunggu Verifikasi</TabsTrigger>
          <TabsTrigger value="done" data-testid="rem-tab-done">Selesai</TabsTrigger>
          <TabsTrigger value="rejected" data-testid="rem-tab-rejected">Ditolak / Riwayat</TabsTrigger>
        </TabsList>

        <TabsContent value="waiting">
          {isLoading ? <LoadingRows /> : byStatus(["WAITING_VERIFICATION", "VERIFYING"]).length ? (
            <div className="space-y-5" data-testid="lender-rem-waiting">
              {byStatus(["WAITING_VERIFICATION", "VERIFYING"]).map((r) => (
                <Card key={r.id} r={r}>
                  <Button data-testid={`verify-rem-btn-${r.id}`} className="rounded-full" disabled={busy}
                    onClick={() => run(() => api.post(`/admin-remittances/${r.id}/verify`), "Setoran diterima, pinjaman menjadi LUNAS")}>
                    Setoran Diterima
                  </Button>
                  <Button data-testid={`reject-rem-btn-${r.id}`} variant="outline" className="rounded-full" onClick={() => setRejectTarget(r)}>
                    Tolak Setoran
                  </Button>
                </Card>
              ))}
            </div>
          ) : <EmptyState testId="empty-rem-waiting" title="Tidak ada setoran menunggu verifikasi" />}
        </TabsContent>

        <TabsContent value="done">
          {byStatus(["VERIFIED"]).length ? (
            <div className="space-y-5" data-testid="lender-rem-done">
              {byStatus(["VERIFIED"]).map((r) => <Card key={r.id} r={r}><span className="text-xs text-muted-foreground">Diverifikasi {formatDateTime(r.verified_at)}</span></Card>)}
            </div>
          ) : <EmptyState testId="empty-rem-done" title="Belum ada setoran selesai" />}
        </TabsContent>

        <TabsContent value="rejected">
          {byStatus(["REJECTED", "PREPARED"]).length ? (
            <div className="space-y-5" data-testid="lender-rem-rejected">
              {byStatus(["REJECTED", "PREPARED"]).map((r) => <Card key={r.id} r={r} />)}
            </div>
          ) : <EmptyState testId="empty-rem-rejected" title="Belum ada riwayat penolakan" />}
        </TabsContent>
      </Tabs>

      <Dialog open={!!rejectTarget} onOpenChange={() => { setRejectTarget(null); setReason(""); }}>
        <DialogContent data-testid="reject-rem-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Tolak setoran Admin</DialogTitle>
            <DialogDescription>
              Alasan minimal 10 karakter. Pinjaman tetap berstatus Pembayaran Diterima Admin dan tidak ada denda tambahan bagi Peminjam.
            </DialogDescription>
          </DialogHeader>
          <Textarea data-testid="reject-rem-reason" rows={4} value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder="Contoh: Nominal transfer tidak sesuai total setoran." />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejectTarget(null)} disabled={busy}>Batal</Button>
            <Button data-testid="reject-rem-submit" variant="destructive" disabled={busy || reason.trim().length < 10}
              onClick={() => run(() => api.post(`/admin-remittances/${rejectTarget.id}/reject`, { reason }), "Setoran ditolak")}>
              {busy ? "Memproses..." : "Tolak Setoran"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
