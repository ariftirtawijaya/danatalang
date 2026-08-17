import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { rupiah, formatDateTime } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, Field } from "@/components/common";
import { ShareBadge, ShareBreakdown, SettlementAccountCard } from "@/components/profit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function LenderSettlement() {
  const [tab, setTab] = useState("PENDING,WAITING_VERIFICATION");
  const [target, setTarget] = useState(null);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["my-distributions", tab],
    queryFn: async () =>
      (await api.get("/profit-distributions", { params: { settlement_status: tab, page_size: 50 } })).data,
  });
  const { data: account } = useQuery({
    queryKey: ["settlement-account"],
    queryFn: async () => (await api.get("/settings/settlement-account")).data,
  });
  const { data: summary } = useQuery({
    queryKey: ["my-share-summary"],
    queryFn: async () => (await api.get("/profit-distributions/summary")).data,
  });

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("proof", file);
      await api.post(`/profit-distributions/${target.id}/settlement`, fd);
      toast.success("Bukti setoran terkirim, menunggu verifikasi Superadmin");
      setTarget(null);
      setFile(null);
      await refetch();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Bagi Hasil"
        description="Pokok pinjaman 100% hak Anda. Bagian Admin & Aplikator dari profit disetor ke rekening pusat."
      />

      {summary && (
        <div className="mb-7 grid gap-4 sm:grid-cols-3" data-testid="lender-share-summary">
          <div className="rounded-2xl border bg-card p-5 card-soft">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Profit Pendana</p>
            <p className="mt-2 font-heading text-xl font-semibold num">{rupiah(summary.lender_profit)}</p>
          </div>
          <div className="rounded-2xl border bg-card p-5 card-soft">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Belum Disetor</p>
            <p className="mt-2 font-heading text-xl font-semibold num">{rupiah(summary.settlement_pending)}</p>
          </div>
          <div className="rounded-2xl border bg-card p-5 card-soft">
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Sudah Disetor</p>
            <p className="mt-2 font-heading text-xl font-semibold num">{rupiah(summary.settlement_settled)}</p>
          </div>
        </div>
      )}

      <div className="mb-6 max-w-sm">
        <SettlementAccountCard account={account} />
      </div>

      <Tabs value={tab} onValueChange={setTab} className="mb-6">
        <TabsList>
          <TabsTrigger value="PENDING,WAITING_VERIFICATION" data-testid="settlement-tab-open">Perlu Tindakan</TabsTrigger>
          <TabsTrigger value="SETTLED" data-testid="settlement-tab-done">Selesai</TabsTrigger>
        </TabsList>
      </Tabs>

      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <div className="space-y-5" data-testid="lender-settlement-list">
          {data.items.map((d) => (
            <div key={d.id} className="rounded-2xl border bg-card p-6 card-soft" data-testid={`settlement-card-${d.id}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-heading text-sm font-semibold num">{d.loan_number}</p>
                  <p className="text-xs text-muted-foreground">
                    {d.borrower_name} · Lunas {formatDateTime(d.paid_at)}
                  </p>
                </div>
                <ShareBadge value={d.lender_settlement_status} />
              </div>

              <div className="mt-5">
                <ShareBreakdown d={d} testId={`breakdown-${d.id}`} />
              </div>

              {d.settlement_rejection_reason && d.lender_settlement_status === "PENDING" && (
                <p className="mt-4 text-sm text-destructive" data-testid={`settlement-rejected-${d.id}`}>
                  Setoran sebelumnya ditolak: {d.settlement_rejection_reason}
                </p>
              )}
              {d.lender_settlement_status === "WAITING_VERIFICATION" && (
                <p className="mt-4 text-xs text-muted-foreground">
                  Bukti setoran dikirim {formatDateTime(d.settlement_submitted_at)} · menunggu verifikasi Superadmin.
                </p>
              )}
              {d.lender_settlement_status === "SETTLED" && (
                <div className="mt-5 grid grid-cols-2 gap-5">
                  <Field label="Diverifikasi" value={formatDateTime(d.settlement_verified_at)} />
                  <Field label="Nominal Setoran" value={rupiah(d.lender_settlement_due)} mono />
                </div>
              )}

              <div className="mt-5 flex flex-wrap gap-2">
                {d.lender_settlement_status === "PENDING" && (
                  <Button data-testid={`settle-btn-${d.id}`} className="rounded-full" onClick={() => setTarget(d)}>
                    Setor Bagi Hasil
                  </Button>
                )}
                <Button variant="ghost" className="rounded-full" onClick={() => navigate(`/loans/${d.loan_id}`)}>
                  Detail Pinjaman
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          testId="empty-lender-settlement"
          title="Belum ada bagi hasil"
          description="Data bagi hasil muncul setelah pinjaman yang Anda danai dinyatakan LUNAS."
        />
      )}

      <Dialog open={!!target} onOpenChange={() => { setTarget(null); setFile(null); }}>
        <DialogContent data-testid="settlement-dialog" className="max-h-[92vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-heading">Setor Bagi Hasil</DialogTitle>
            <DialogDescription>
              Transfer nominal di bawah ini ke rekening settlement pusat, lalu unggah bukti transfer.
            </DialogDescription>
          </DialogHeader>
          {target && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Nominal Wajib Disetor</Label>
                <Input data-testid="settlement-amount-readonly" readOnly value={rupiah(target.lender_settlement_due)} className="h-11 rounded-xl num" />
              </div>
              <ShareBreakdown d={target} testId="settlement-dialog-breakdown" />
              <SettlementAccountCard account={account} />
              <div className="space-y-2">
                <Label>Bukti Transfer (JPG/PNG/WEBP/PDF, maks 5MB)</Label>
                <Input
                  data-testid="settlement-file-input"
                  type="file"
                  accept="image/jpeg,image/png,image/webp,application/pdf"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  className="h-11 rounded-xl"
                />
              </div>
              <p className="rounded-xl bg-muted px-4 py-3 text-xs text-muted-foreground">
                Nominal setoran dihitung sistem dan tidak dapat diubah. Verifikasi dilakukan oleh Superadmin.
              </p>
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setTarget(null)} disabled={busy}>Batal</Button>
            <Button data-testid="settlement-submit-btn" disabled={busy || !file} onClick={submit}>
              {busy ? "Mengirim..." : "Kirim Bukti Setoran"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
