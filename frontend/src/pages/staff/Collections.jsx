import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { rupiah, formatDateTime } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, StatCard, ProofImage, Field } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Wallet, Clock, CheckCircle2, AlertTriangle } from "lucide-react";

const REM_LABEL = {
  PREPARED: "Siap Disetor",
  WAITING_VERIFICATION: "Menunggu Verifikasi",
  VERIFYING: "Sedang Diproses",
  VERIFIED: "Selesai",
  REJECTED: "Ditolak",
  CANCELLED: "Dibatalkan",
};

function ItemRow({ i }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-3 border-b py-2 text-xs last:border-0" data-testid={`rem-item-${i.id}`}>
      <span className="num font-semibold">{i.loan_number}</span>
      <span className="text-muted-foreground">{i.borrower_name}</span>
      <span className="text-muted-foreground">Pokok {rupiah(i.principal_snapshot)} · Bunga {rupiah(i.interest_snapshot)} · Denda {rupiah(i.late_fee_snapshot)}</span>
      <span className="num font-semibold">{rupiah(i.total_collected)}</span>
    </div>
  );
}

export default function Collections() {
  const { user } = useAuth();
  const isSuper = user?.role === "superadmin";
  const navigate = useNavigate();
  const [selected, setSelected] = useState({});
  const [busy, setBusy] = useState(false);
  const [submitTarget, setSubmitTarget] = useState(null);
  const [file, setFile] = useState(null);
  const [cancelTarget, setCancelTarget] = useState(null);
  const [cancelReason, setCancelReason] = useState("");

  const summary = useQuery({ queryKey: ["col-summary"], queryFn: async () => (await api.get("/admin-collections/summary")).data });
  const pending = useQuery({
    queryKey: ["col-unremitted"],
    queryFn: async () => (await api.get("/admin-collections", { params: { unremitted_only: true } })).data,
  });
  const rems = useQuery({ queryKey: ["remittances"], queryFn: async () => (await api.get("/admin-remittances")).data });

  const refresh = async () => { await Promise.all([summary.refetch(), pending.refetch(), rems.refetch()]); };

  const groups = (pending.data?.items || []).reduce((acc, c) => {
    const key = c.lender_id || "-";
    acc[key] = acc[key] || { lender_name: c.lender_name, items: [] };
    acc[key].items.push(c);
    return acc;
  }, {});

  const chosen = Object.keys(selected).filter((k) => selected[k]);
  const chosenTotal = (pending.data?.items || []).filter((c) => selected[c.id]).reduce((s, c) => s + c.total_collected, 0);

  const prepare = async (lenderId) => {
    const ids = (groups[lenderId]?.items || []).filter((c) => selected[c.id]).map((c) => c.id);
    if (!ids.length) return;
    setBusy(true);
    try {
      const res = await api.post("/admin-remittances", { collection_ids: ids });
      toast.success(`Setoran ${res.data.remittance_number} disiapkan`);
      setSelected({});
      await refresh();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  const submit = async () => {
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("proof", file);
      await api.post(`/admin-remittances/${submitTarget.id}/submit`, fd);
      toast.success("Bukti setoran terkirim, menunggu verifikasi Pendana");
      setSubmitTarget(null); setFile(null);
      await refresh();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  const cancelRem = async () => {
    setBusy(true);
    try {
      await api.post(`/admin-remittances/${cancelTarget.id}/cancel`, { reason: cancelReason.trim() });
      toast.success("Setoran dibatalkan, penerimaan kembali menjadi dana titipan");
      setCancelTarget(null); setCancelReason("");
      await refresh();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  const recoverStale = async () => {
    setBusy(true);
    try {
      const res = await api.post("/admin-remittances/recover-stale");
      toast.success(`Recovery selesai: ${res.data.reservations_released + res.data.orphans_released} reservasi dilepas, ${res.data.prepare_finished} dilanjutkan`);
      await refresh();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  const byStatus = (s) => (rems.data?.items || []).filter((r) => s.includes(r.status));

  return (
    <div>
      <PageHeader title={isSuper ? "Koleksi Lapangan" : "Penagihan / Koleksi"}
        description="Pembayaran Peminjam yang diterima Admin di lapangan dan setoran bulk ke Pendana.">
        {isSuper && (
          <Button data-testid="recover-stale-btn" variant="outline" className="rounded-full" disabled={busy} onClick={recoverStale}>
            Bersihkan Reservasi Terlantar
          </Button>
        )}
      </PageHeader>

      <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="collection-summary">
        <StatCard testId="stat-cash-in-hand" label="Dana Titipan" value={rupiah(summary.data?.cash_in_hand)} icon={Wallet} tone="active" sub={`${summary.data?.collections || 0} penerimaan`} />
        <StatCard testId="stat-unremitted" label="Belum Disetor" value={rupiah(summary.data?.unremitted_amount)} icon={Clock} tone="pending" sub={`${summary.data?.unremitted_count || 0} transaksi`} />
        <StatCard testId="stat-waiting-verif" label="Menunggu Verifikasi" value={rupiah(summary.data?.waiting_verification_amount)} icon={Clock} tone="active" />
        <StatCard testId="stat-verified" label="Setoran Selesai" value={rupiah(summary.data?.verified_amount)} icon={CheckCircle2} tone="success" />
      </div>

      {summary.data?.oldest_unremitted_hours > 0 && (
        <p data-testid="aging-info" className={`mb-6 flex items-center gap-2 rounded-xl px-4 py-3 text-xs ${summary.data.aging_warning ? "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300" : "bg-muted text-muted-foreground"}`}>
          <AlertTriangle className="h-4 w-4" /> Penerimaan tertua belum disetor: {summary.data.oldest_unremitted_hours} jam
          {summary.data.aging_warning && " — segera setorkan ke Pendana"}
        </p>
      )}

      {isSuper && summary.data?.per_admin?.length > 0 && (
        <div className="mb-8 space-y-3" data-testid="per-admin-summary">
          <h2 className="text-base font-semibold md:text-lg">Ringkasan per Admin</h2>
          {summary.data.per_admin.map((a) => (
            <div key={a.admin_id} className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border bg-card p-5 card-soft" data-testid={`admin-row-${a.admin_id}`}>
              <span className="font-heading text-sm font-semibold">{a.admin_name}</span>
              <span className="num text-sm">Dana di tangan {rupiah(a.cash_in_hand)}</span>
              <span className="text-xs text-muted-foreground">Belum disetor {a.unremitted_count} transaksi · Tertua {a.oldest_unremitted_hours} jam</span>
              {a.aging_warning && <span className="rounded-md bg-red-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-red-800">Perlu perhatian</span>}
            </div>
          ))}
        </div>
      )}

      <Tabs defaultValue="unremitted">
        <TabsList className="mb-6 flex-wrap">
          <TabsTrigger value="unremitted" data-testid="col-tab-unremitted">Belum Disetor</TabsTrigger>
          <TabsTrigger value="prepared" data-testid="col-tab-prepared">Siap Disetor</TabsTrigger>
          <TabsTrigger value="waiting" data-testid="col-tab-waiting">Menunggu Verifikasi</TabsTrigger>
          <TabsTrigger value="done" data-testid="col-tab-done">Selesai</TabsTrigger>
          <TabsTrigger value="history" data-testid="col-tab-history">Riwayat</TabsTrigger>
        </TabsList>

        <TabsContent value="unremitted">
          {pending.isLoading ? <LoadingRows /> : Object.keys(groups).length ? (
            <div className="space-y-6" data-testid="unremitted-groups">
              {Object.entries(groups).map(([lenderId, g]) => (
                <div key={lenderId} className="rounded-2xl border bg-card p-6 card-soft" data-testid={`lender-group-${lenderId}`}>
                  <p className="font-heading text-sm font-semibold">Pendana {g.lender_name}</p>
                  <div className="mt-4 space-y-2">
                    {g.items.map((c) => (
                      <label key={c.id} className="flex flex-wrap items-center gap-3 border-b py-2 text-xs last:border-0" data-testid={`collection-${c.id}`}>
                        {!isSuper && (
                          <input type="checkbox" data-testid={`select-${c.id}`} checked={!!selected[c.id]}
                            onChange={(e) => setSelected((s) => ({ ...s, [c.id]: e.target.checked }))} />
                        )}
                        <span className="num font-semibold">{c.loan_number}</span>
                        <span className="text-muted-foreground">{c.collection_number} · {c.collection_method === "CASH" ? "Tunai" : "Transfer ke Admin"}</span>
                        <span className="text-muted-foreground">Pokok {rupiah(c.principal_snapshot)} · Bunga {rupiah(c.interest_snapshot)} · Denda {rupiah(c.late_fee_snapshot)}</span>
                        <span className="num font-semibold">{rupiah(c.total_collected)}</span>
                        <span className="text-muted-foreground">{formatDateTime(c.collected_at)}</span>
                      </label>
                    ))}
                  </div>
                  {!isSuper && (
                    <div className="mt-5 flex flex-wrap items-center gap-4">
                      <span className="num text-sm font-semibold">Total dipilih: {rupiah(g.items.filter((c) => selected[c.id]).reduce((s, c) => s + c.total_collected, 0))}</span>
                      <Button data-testid={`prepare-btn-${lenderId}`} className="rounded-full" disabled={busy || !g.items.some((c) => selected[c.id])}
                        onClick={() => prepare(lenderId)}>Buat Setoran Bulk</Button>
                    </div>
                  )}
                </div>
              ))}
              {chosen.length > 1 && <p className="text-xs text-muted-foreground">Total seluruh pilihan: {rupiah(chosenTotal)}</p>}
            </div>
          ) : <EmptyState testId="empty-unremitted" title="Tidak ada dana titipan" description="Penerimaan pembayaran di lapangan akan muncul di sini." />}
        </TabsContent>

        {[["prepared", ["PREPARED", "REJECTED"]], ["waiting", ["WAITING_VERIFICATION", "VERIFYING"]], ["done", ["VERIFIED"]],
          ["history", ["PREPARED", "REJECTED", "WAITING_VERIFICATION", "VERIFYING", "VERIFIED", "CANCELLED"]]].map(([tab, statuses]) => (
          <TabsContent key={tab} value={tab}>
            {rems.isLoading ? <LoadingRows /> : byStatus(statuses).length ? (
              <div className="space-y-5" data-testid={`rem-list-${tab}`}>
                {byStatus(statuses).map((r) => (
                  <div key={r.id} className="rounded-2xl border bg-card p-6 card-soft" data-testid={`remittance-${r.id}`}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="font-heading text-sm font-semibold num">{r.remittance_number}</p>
                        <p className="text-xs text-muted-foreground">Pendana {r.lender_name} · {r.item_count} pinjaman · {formatDateTime(r.created_at)}</p>
                      </div>
                      <span className="rounded-md bg-muted px-2 py-1 text-[10px] font-semibold uppercase tracking-widest" data-testid={`rem-status-${r.id}`}>
                        {REM_LABEL[r.status] || r.status}
                      </span>
                    </div>
                    {r.lender_bank && (
                      <div className="mt-4 rounded-xl bg-muted/60 p-4 text-xs" data-testid={`lender-bank-${r.id}`}>
                        Rekening Pendana: {r.lender_bank.bank_name || "-"} · {r.lender_bank.account_number || "belum diisi"} · {r.lender_bank.account_holder || "-"}
                      </div>
                    )}
                    <div className="mt-4">{(r.items || []).map((i) => <ItemRow key={i.id} i={i} />)}</div>
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                      <span className="num font-heading text-base font-semibold">Total setoran: {rupiah(r.total_amount)}</span>
                      <div className="flex flex-wrap gap-2">
                        {r.proof_file_id && <ProofImage fileId={r.proof_file_id} label="Bukti Transfer" testId={`rem-proof-${r.id}`} />}
                        {!isSuper && ["PREPARED", "REJECTED"].includes(r.status) && (
                          <Button data-testid={`submit-rem-btn-${r.id}`} className="rounded-full" onClick={() => setSubmitTarget(r)}>Kirim Bukti Setoran</Button>
                        )}
                        {r.status === "PREPARED" && !r.remittance_attempt_count && (
                          <Button data-testid={`cancel-rem-btn-${r.id}`} variant="outline" className="rounded-full"
                            onClick={() => { setCancelTarget(r); setCancelReason(""); }}>Batalkan Setoran</Button>
                        )}
                      </div>
                    </div>
                    {r.status === "CANCELLED" && (
                      <p className="mt-3 text-sm text-muted-foreground" data-testid={`rem-cancelled-${r.id}`}>Dibatalkan: {r.cancel_reason}</p>
                    )}
                    {r.rejection_reason && r.status === "REJECTED" && (
                      <p className="mt-3 text-sm text-destructive" data-testid={`rem-rejected-${r.id}`}>Ditolak Pendana: {r.rejection_reason}</p>
                    )}
                    {r.remittance_attempts?.length > 1 && (
                      <div className="mt-4 rounded-xl border p-4" data-testid={`rem-attempts-${r.id}`}>
                        <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Riwayat Setoran</p>
                        {r.remittance_attempts.map((a) => (
                          <p key={a.attempt_no} className="mt-2 text-xs text-muted-foreground">
                            #{a.attempt_no} · {formatDateTime(a.submitted_at)} · {rupiah(a.amount)} · {a.status}
                            {a.rejection_reason ? ` · ${a.rejection_reason}` : ""}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : <EmptyState testId={`empty-${tab}`} title="Belum ada data" />}
          </TabsContent>
        ))}
      </Tabs>

      <Dialog open={!!cancelTarget} onOpenChange={() => { setCancelTarget(null); setCancelReason(""); }}>
        <DialogContent data-testid="cancel-rem-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Batalkan Setoran</DialogTitle>
            <DialogDescription>
              Seluruh penerimaan pada batch ini kembali menjadi dana titipan Admin. Data setoran tetap tersimpan
              sebagai riwayat audit.
            </DialogDescription>
          </DialogHeader>
          {cancelTarget && (
            <div className="space-y-4">
              <Field label="Nomor Setoran" value={cancelTarget.remittance_number} />
              <Field label="Total" value={rupiah(cancelTarget.total_amount)} mono />
              <div className="space-y-2">
                <Label>Alasan pembatalan (minimal 5 karakter)</Label>
                <Input data-testid="cancel-rem-reason" value={cancelReason} onChange={(e) => setCancelReason(e.target.value)}
                  placeholder="Contoh: salah pilih penerimaan" className="h-11 rounded-xl" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCancelTarget(null)} disabled={busy}>Tutup</Button>
            <Button data-testid="cancel-rem-confirm" variant="destructive" disabled={busy || cancelReason.trim().length < 5}
              onClick={cancelRem}>{busy ? "Memproses..." : "Batalkan Setoran"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!submitTarget} onOpenChange={() => { setSubmitTarget(null); setFile(null); }}>
        <DialogContent data-testid="submit-rem-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Kirim Bukti Setoran</DialogTitle>
            <DialogDescription>Transfer total penuh ke rekening Pendana, lalu unggah satu bukti transfer untuk seluruh batch.</DialogDescription>
          </DialogHeader>
          {submitTarget && (
            <div className="space-y-4">
              <Field label="Nomor Setoran" value={submitTarget.remittance_number} />
              <Field label="Total Transfer" value={rupiah(submitTarget.total_amount)} mono />
              {submitTarget.lender_bank && (
                <Field label="Rekening Pendana" value={`${submitTarget.lender_bank.bank_name || "-"} · ${submitTarget.lender_bank.account_number || "-"} · ${submitTarget.lender_bank.account_holder || "-"}`} />
              )}
              <div className="space-y-2">
                <Label>Bukti Transfer (JPG/PNG/WEBP/PDF, maks 5MB)</Label>
                <Input data-testid="rem-file-input" type="file" accept="image/jpeg,image/png,image/webp,application/pdf"
                  onChange={(e) => setFile(e.target.files?.[0] || null)} className="h-11 rounded-xl" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setSubmitTarget(null)} disabled={busy}>Batal</Button>
            <Button data-testid="rem-submit-btn" disabled={busy || !file} onClick={submit}>{busy ? "Mengirim..." : "Kirim"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
