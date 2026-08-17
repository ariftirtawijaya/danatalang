import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg, API } from "@/lib/api";
import { rupiah, formatDateTime } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, StatCard, ProofImage, Field } from "@/components/common";
import { ShareBadge, ShareBreakdown } from "@/components/profit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { TrendingUp, Coins, AlertCircle, Wallet, Users, Building2 } from "lucide-react";

const useDistributions = (params, key) =>
  useQuery({
    queryKey: ["distributions", key, params],
    queryFn: async () => (await api.get("/profit-distributions", { params: { page_size: 50, ...params } })).data,
  });

function DistCard({ d, children, testId }) {
  const navigate = useNavigate();
  return (
    <div className="rounded-2xl border bg-card p-6 card-soft" data-testid={testId}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-heading text-sm font-semibold num">{d.loan_number}</p>
          <p className="text-xs text-muted-foreground">
            {d.borrower_name} · Pendana {d.lender_name} · Admin {d.admin_name || "-"} · Lunas {formatDateTime(d.paid_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ShareBadge value={d.lender_settlement_status} />
          <ShareBadge value={d.admin_payout_status} map="payout" />
          {d.is_reversed && <span className="rounded-md bg-red-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-red-800">Dibatalkan</span>}
        </div>
      </div>
      <div className="mt-5">
        <ShareBreakdown d={d} testId={`breakdown-${d.id}`} />
      </div>
      {d.settlement_rejection_reason && (
        <p className="mt-4 text-sm text-destructive">Penolakan terakhir: {d.settlement_rejection_reason}</p>
      )}
      {d.reversal_reason && <p className="mt-3 text-sm text-destructive">Reversal: {d.reversal_reason}</p>}
      <div className="mt-5 flex flex-wrap items-center gap-2">
        {children}
        <Button variant="ghost" className="rounded-full" onClick={() => navigate(`/loans/${d.loan_id}`)}>
          Detail Pinjaman
        </Button>
      </div>
    </div>
  );
}

export default function ProfitSharing() {
  const [reason, setReason] = useState("");
  const [rejectTarget, setRejectTarget] = useState(null);
  const [payoutTarget, setPayoutTarget] = useState(null);
  const [reverseTarget, setReverseTarget] = useState(null);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [filters, setFilters] = useState({ paid_from: "", paid_to: "", q: "" });

  const { data: summary, isLoading: loadingSummary, refetch: refetchSummary } = useQuery({
    queryKey: ["share-summary"],
    queryFn: async () => (await api.get("/profit-distributions/summary")).data,
  });
  const pending = useDistributions({ settlement_status: "PENDING" }, "pending");
  const waiting = useDistributions({ settlement_status: "WAITING_VERIFICATION" }, "waiting");
  const settled = useDistributions({ settlement_status: "SETTLED" }, "settled");
  const payoutPending = useDistributions({ payout_status: "PENDING" }, "payout-pending");
  const payoutPaid = useDistributions({ payout_status: "PAID" }, "payout-paid");
  const history = useDistributions({ include_reversed: true, ...filters }, "history");

  const refreshAll = async () => {
    await Promise.all([
      refetchSummary(), pending.refetch(), waiting.refetch(), settled.refetch(),
      payoutPending.refetch(), payoutPaid.refetch(), history.refetch(),
    ]);
  };

  const run = async (fn, msg) => {
    setBusy(true);
    try {
      await fn();
      toast.success(msg);
      setRejectTarget(null);
      setPayoutTarget(null);
      setReverseTarget(null);
      setReason("");
      setFile(null);
      await refreshAll();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  const exportCsv = () => {
    const token = localStorage.getItem("pk_token");
    const qs = new URLSearchParams({ ...filters, auth: token || "" }).toString();
    window.open(`${API}/profit-distributions/export.csv?${qs}`, "_blank");
  };

  return (
    <div>
      <PageHeader title="Bagi Hasil" description="Pembagian keuntungan terealisasi, setoran Pendana, dan payout Admin.">
        <Button data-testid="export-share-csv-btn" variant="outline" className="rounded-full" onClick={exportCsv}>
          Export CSV
        </Button>
      </PageHeader>

      <Tabs defaultValue="dashboard">
        <TabsList className="mb-6 flex-wrap">
          <TabsTrigger value="dashboard" data-testid="share-tab-dashboard">Dashboard</TabsTrigger>
          <TabsTrigger value="settlement" data-testid="share-tab-settlement">Settlement Pendana</TabsTrigger>
          <TabsTrigger value="payout" data-testid="share-tab-payout">Payout Admin</TabsTrigger>
          <TabsTrigger value="riwayat" data-testid="share-tab-history">Riwayat</TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard">
          {loadingSummary ? (
            <LoadingRows rows={3} />
          ) : (
            <div className="space-y-8" data-testid="share-dashboard">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard testId="stat-profit-pool" label="Profit Terealisasi" value={rupiah(summary?.profit_pool)} icon={TrendingUp} tone="success" sub={`${summary?.count || 0} pinjaman lunas`} />
                <StatCard testId="stat-interest" label="Bunga Terealisasi" value={rupiah(summary?.interest_realized)} icon={Coins} tone="active" />
                <StatCard testId="stat-latefee" label="Denda Terealisasi" value={rupiah(summary?.late_fee_realized)} icon={AlertCircle} tone="warning" />
                <StatCard testId="stat-principal" label="Pokok Kembali" value={rupiah(summary?.principal_returned)} icon={Wallet} tone="neutral" />
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <StatCard testId="stat-lender-share" label="Hak Pendana" value={rupiah(summary?.lender_profit)} icon={Users} tone="active" />
                <StatCard testId="stat-admin-share" label="Hak Admin" value={rupiah(summary?.admin_profit)} icon={Users} tone="pending" />
                <StatCard testId="stat-platform-share" label="Hak Aplikator" value={rupiah(summary?.platform_profit)} icon={Building2} tone="success" />
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <StatCard testId="stat-settlement-pending" label="Settlement Belum Disetor" value={rupiah(summary?.settlement_pending)} sub={`${summary?.count_settlement_pending || 0} pinjaman`} tone="pending" />
                <StatCard testId="stat-settlement-waiting" label="Menunggu Verifikasi" value={rupiah(summary?.settlement_waiting)} sub={`${summary?.count_settlement_waiting || 0} pinjaman`} tone="active" />
                <StatCard testId="stat-settlement-settled" label="Sudah Diterima" value={rupiah(summary?.settlement_settled)} sub={`${summary?.count_settlement_settled || 0} pinjaman`} tone="success" />
              </div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <StatCard testId="stat-admin-earned" label="Admin Earned" value={rupiah(summary?.admin_earned)} tone="neutral" />
                <StatCard testId="stat-admin-payable" label="Admin Payable" value={rupiah(summary?.admin_payable)} tone="pending" />
                <StatCard testId="stat-admin-paid" label="Admin Paid" value={rupiah(summary?.admin_paid)} tone="success" />
                <StatCard testId="stat-platform-collected" label="Aplikator Collected" value={rupiah(summary?.platform_collected)} sub={`Earned ${rupiah(summary?.platform_earned)}`} tone="success" />
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value="settlement">
          <div className="space-y-10">
            <section>
              <h2 className="mb-4 text-base font-semibold md:text-lg">Menunggu Verifikasi</h2>
              {waiting.isLoading ? <LoadingRows rows={2} /> : waiting.data?.items?.length ? (
                <div className="space-y-5" data-testid="settlement-waiting-list">
                  {waiting.data.items.map((d) => (
                    <DistCard key={d.id} d={d} testId={`waiting-card-${d.id}`}>
                      <ProofImage fileId={d.settlement_proof_file_id} label="Lihat Bukti Setoran" testId={`settlement-proof-${d.id}`} />
                      <Button data-testid={`verify-settlement-btn-${d.id}`} className="rounded-full"
                        onClick={() => run(() => api.post(`/profit-distributions/${d.id}/settlement/verify`), "Setoran diverifikasi")}>
                        Verifikasi Setoran
                      </Button>
                      <Button data-testid={`reject-settlement-btn-${d.id}`} variant="outline" className="rounded-full" onClick={() => setRejectTarget(d)}>
                        Tolak
                      </Button>
                    </DistCard>
                  ))}
                </div>
              ) : <EmptyState testId="empty-waiting" title="Tidak ada setoran menunggu verifikasi" />}
            </section>

            <section>
              <h2 className="mb-4 text-base font-semibold md:text-lg">Belum Disetor</h2>
              {pending.isLoading ? <LoadingRows rows={2} /> : pending.data?.items?.length ? (
                <div className="space-y-5" data-testid="settlement-pending-list">
                  {pending.data.items.map((d) => (
                    <DistCard key={d.id} d={d} testId={`pending-card-${d.id}`}>
                      <Button data-testid={`reverse-btn-${d.id}`} variant="outline" className="rounded-full" onClick={() => setReverseTarget(d)}>
                        Batalkan (Reversal)
                      </Button>
                    </DistCard>
                  ))}
                </div>
              ) : <EmptyState testId="empty-pending" title="Semua setoran sudah dilaporkan" />}
            </section>

            <section>
              <h2 className="mb-4 text-base font-semibold md:text-lg">Sudah Diterima</h2>
              {settled.isLoading ? <LoadingRows rows={2} /> : settled.data?.items?.length ? (
                <div className="space-y-5" data-testid="settlement-settled-list">
                  {settled.data.items.map((d) => (
                    <DistCard key={d.id} d={d} testId={`settled-card-${d.id}`}>
                      <ProofImage fileId={d.settlement_proof_file_id} label="Lihat Bukti Setoran" testId={`settled-proof-${d.id}`} />
                    </DistCard>
                  ))}
                </div>
              ) : <EmptyState testId="empty-settled" title="Belum ada setoran diterima" />}
            </section>
          </div>
        </TabsContent>

        <TabsContent value="payout">
          <div className="space-y-10">
            <section>
              <h2 className="mb-4 text-base font-semibold md:text-lg">Belum Dibayar</h2>
              {payoutPending.isLoading ? <LoadingRows rows={2} /> : payoutPending.data?.items?.length ? (
                <div className="space-y-5" data-testid="payout-pending-list">
                  {payoutPending.data.items.map((d) => (
                    <DistCard key={d.id} d={d} testId={`payout-card-${d.id}`}>
                      {d.admin_bank && (
                        <span className="rounded-xl bg-muted px-4 py-2 text-xs text-muted-foreground">
                          Rekening Admin: {d.admin_bank.bank_name || "-"} · {d.admin_bank.account_number || "belum diisi"} · {d.admin_bank.account_holder || "-"}
                        </span>
                      )}
                      <Button data-testid={`mark-payout-btn-${d.id}`} className="rounded-full" onClick={() => setPayoutTarget(d)}>
                        Tandai Payout Dibayar
                      </Button>
                    </DistCard>
                  ))}
                </div>
              ) : <EmptyState testId="empty-payout-pending" title="Tidak ada payout menunggu pembayaran" />}
            </section>

            <section>
              <h2 className="mb-4 text-base font-semibold md:text-lg">Sudah Dibayar</h2>
              {payoutPaid.isLoading ? <LoadingRows rows={2} /> : payoutPaid.data?.items?.length ? (
                <div className="space-y-5" data-testid="payout-paid-list">
                  {payoutPaid.data.items.map((d) => (
                    <DistCard key={d.id} d={d} testId={`payout-paid-card-${d.id}`}>
                      <Field label="Dibayar" value={formatDateTime(d.admin_payout_paid_at)} />
                      <ProofImage fileId={d.admin_payout_proof_file_id} label="Lihat Bukti Payout" testId={`payout-proof-${d.id}`} />
                    </DistCard>
                  ))}
                </div>
              ) : <EmptyState testId="empty-payout-paid" title="Belum ada payout dibayarkan" />}
            </section>
          </div>
        </TabsContent>

        <TabsContent value="riwayat">
          <div className="mb-6 grid gap-4 sm:grid-cols-3">
            <div className="space-y-2">
              <Label>Lunas Dari</Label>
              <Input data-testid="filter-paid-from" type="date" value={filters.paid_from} onChange={(e) => setFilters({ ...filters, paid_from: e.target.value })} className="h-11 rounded-xl" />
            </div>
            <div className="space-y-2">
              <Label>Lunas Sampai</Label>
              <Input data-testid="filter-paid-to" type="date" value={filters.paid_to} onChange={(e) => setFilters({ ...filters, paid_to: e.target.value })} className="h-11 rounded-xl" />
            </div>
            <div className="space-y-2">
              <Label>Cari</Label>
              <Input data-testid="filter-q" placeholder="Nomor pinjaman / nama" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} className="h-11 rounded-xl" />
            </div>
          </div>
          {history.isLoading ? <LoadingRows /> : history.data?.items?.length ? (
            <div className="space-y-5" data-testid="share-history-list">
              {history.data.items.map((d) => (
                <DistCard key={d.id} d={d} testId={`history-card-${d.id}`} />
              ))}
            </div>
          ) : <EmptyState testId="empty-history" title="Belum ada riwayat pembagian hasil" />}
        </TabsContent>
      </Tabs>

      <Dialog open={!!rejectTarget} onOpenChange={() => { setRejectTarget(null); setReason(""); }}>
        <DialogContent data-testid="reject-settlement-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Tolak setoran bagi hasil</DialogTitle>
            <DialogDescription>Alasan minimal 10 karakter. Status kembali ke BELUM DISETOR dan Pendana dapat mengunggah ulang.</DialogDescription>
          </DialogHeader>
          <Textarea data-testid="reject-settlement-reason" rows={4} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Contoh: Nominal setoran tidak sesuai." />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRejectTarget(null)} disabled={busy}>Batal</Button>
            <Button data-testid="reject-settlement-submit" variant="destructive" disabled={busy || reason.trim().length < 10}
              onClick={() => run(() => api.post(`/profit-distributions/${rejectTarget.id}/settlement/reject`, { reason }), "Setoran ditolak")}>
              {busy ? "Memproses..." : "Tolak Setoran"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!payoutTarget} onOpenChange={() => { setPayoutTarget(null); setFile(null); }}>
        <DialogContent data-testid="payout-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Tandai Payout Admin Dibayar</DialogTitle>
            <DialogDescription>Nominal ditentukan sistem dan tidak dapat diubah. Unggah bukti transfer ke Admin.</DialogDescription>
          </DialogHeader>
          {payoutTarget && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Nominal Payout</Label>
                <Input data-testid="payout-amount-readonly" readOnly value={rupiah(payoutTarget.admin_profit)} className="h-11 rounded-xl num" />
              </div>
              <Field label="Admin Penerima" value={payoutTarget.admin_name} />
              <div className="space-y-2">
                <Label>Bukti Transfer (JPG/PNG/WEBP/PDF, maks 5MB)</Label>
                <Input data-testid="payout-file-input" type="file" accept="image/jpeg,image/png,image/webp,application/pdf"
                  onChange={(e) => setFile(e.target.files?.[0] || null)} className="h-11 rounded-xl" />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPayoutTarget(null)} disabled={busy}>Batal</Button>
            <Button data-testid="payout-submit-btn" disabled={busy || !file}
              onClick={() => {
                const fd = new FormData();
                fd.append("proof", file);
                return run(() => api.post(`/profit-distributions/${payoutTarget.id}/admin-payout/mark-paid`, fd), "Payout Admin ditandai dibayar");
              }}>
              {busy ? "Memproses..." : "Tandai Dibayar"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!reverseTarget} onOpenChange={() => { setReverseTarget(null); setReason(""); }}>
        <DialogContent data-testid="reverse-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Batalkan pembagian hasil (Reversal)</DialogTitle>
            <DialogDescription>
              Record finansial tidak dihapus, hanya ditandai dibatalkan dan dikeluarkan dari laporan aktif. Alasan minimal 10 karakter.
            </DialogDescription>
          </DialogHeader>
          <Textarea data-testid="reverse-reason" rows={4} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Contoh: Kesalahan sistem pada pencatatan pembayaran." />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setReverseTarget(null)} disabled={busy}>Batal</Button>
            <Button data-testid="reverse-submit-btn" variant="destructive" disabled={busy || reason.trim().length < 10}
              onClick={() => run(() => api.post(`/profit-distributions/${reverseTarget.id}/reverse`, { reason }), "Pembagian hasil dibatalkan")}>
              {busy ? "Memproses..." : "Batalkan"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
