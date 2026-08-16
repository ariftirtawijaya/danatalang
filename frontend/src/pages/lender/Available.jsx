import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { rupiah, formatDateTime } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, ConfirmDialog, StatusBadge } from "@/components/common";
import { Button } from "@/components/ui/button";

export default function Available() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [target, setTarget] = useState(null);
  const [busy, setBusy] = useState(false);
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["loans", "available"],
    queryFn: async () => (await api.get("/loans", { params: { status: "WAITING_FUNDING", page_size: 50 } })).data,
  });

  const claim = async () => {
    setBusy(true);
    try {
      await api.post(`/loans/${target.id}/claim`);
      toast.success("Pendanaan berhasil diambil");
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      navigate(`/loans/${target.id}`);
    } catch (err) {
      toast.error(errMsg(err));
      refetch();
    } finally {
      setBusy(false);
      setTarget(null);
    }
  };

  return (
    <div>
      <PageHeader title="Pinjaman Siap Didanai" description="Pinjaman yang telah disetujui Admin dan belum diambil Pendana lain." />
      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <div className="grid gap-4 lg:grid-cols-2" data-testid="available-list">
          {data.items.map((l) => (
            <div key={l.id} className="rounded-2xl border bg-card p-6 card-soft" data-testid={`available-card-${l.loan_number}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-heading text-sm font-semibold num">{l.loan_number}</p>
                  <p className="text-xs text-muted-foreground">{l.borrower_name}</p>
                </div>
                <StatusBadge value={l.effective_status} />
              </div>
              <div className="mt-5 grid grid-cols-2 gap-4">
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Nominal</p>
                  <p className="font-heading text-lg font-semibold num">{rupiah(l.principal_amount)}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Total Pengembalian</p>
                  <p className="font-heading text-lg font-semibold num">{rupiah(l.base_repayment_amount)}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Durasi / Bunga</p>
                  <p className="text-sm font-medium num">{l.duration_days} hari · {l.interest_rate}%</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Disetujui</p>
                  <p className="text-sm font-medium">{formatDateTime(l.approved_at)}</p>
                </div>
              </div>
              <div className="mt-5 flex gap-2">
                <Button data-testid={`claim-btn-${l.loan_number}`} className="flex-1 rounded-full" onClick={() => setTarget(l)}>
                  Ambil Pendanaan
                </Button>
                <Button variant="outline" className="rounded-full" onClick={() => navigate(`/loans/${l.id}`)}>
                  Detail
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState testId="empty-available" title="Belum ada pinjaman yang siap didanai" description="Anda akan mendapat notifikasi Telegram ketika ada pinjaman baru yang siap didanai." />
      )}

      <ConfirmDialog
        open={!!target}
        onOpenChange={() => setTarget(null)}
        testId="claim-dialog"
        title="Ambil pendanaan?"
        description={target ? `Yakin ingin mengambil pendanaan ${rupiah(target.principal_amount)} untuk ${target.loan_number}?` : ""}
        confirmLabel="Ya, Ambil"
        loading={busy}
        onConfirm={claim}
      />
    </div>
  );
}
