import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { rupiah, formatDateTime } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, StatCard } from "@/components/common";
import { ShareBadge } from "@/components/profit";
import { Button } from "@/components/ui/button";
import { Wallet, Clock, CheckCircle2 } from "lucide-react";

export default function AdminEarnings() {
  const navigate = useNavigate();
  const { data: summary, isLoading: loadingSummary } = useQuery({
    queryKey: ["my-earnings-summary"],
    queryFn: async () => (await api.get("/profit-distributions/summary")).data,
  });
  const { data, isLoading } = useQuery({
    queryKey: ["my-earnings"],
    queryFn: async () => (await api.get("/profit-distributions", { params: { page_size: 50 } })).data,
  });

  return (
    <div>
      <PageHeader title="Penghasilan" description="Bagian Admin dari pembagian hasil pinjaman yang menjadi tanggung jawab Anda." />

      {loadingSummary ? (
        <LoadingRows rows={2} />
      ) : (
        <div className="mb-8 grid gap-4 sm:grid-cols-3" data-testid="admin-earnings-summary">
          <StatCard testId="stat-admin-earned" label="Total Earned" value={rupiah(summary?.admin_earned)} icon={Wallet} tone="active" sub={`${summary?.count || 0} pinjaman lunas`} />
          <StatCard testId="stat-admin-payable" label="Belum Dibayar" value={rupiah(summary?.admin_payable)} icon={Clock} tone="pending" sub="Setoran Pendana sudah diterima" />
          <StatCard testId="stat-admin-paid" label="Sudah Dibayar" value={rupiah(summary?.admin_paid)} icon={CheckCircle2} tone="success" />
        </div>
      )}

      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <div className="space-y-4" data-testid="admin-earnings-list">
          {data.items.map((d) => (
            <div key={d.id} className="rounded-2xl border bg-card p-6 card-soft" data-testid={`earning-card-${d.id}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-heading text-sm font-semibold num">{d.loan_number}</p>
                  <p className="text-xs text-muted-foreground">
                    {d.borrower_name} · Pendana {d.lender_name} · Lunas {formatDateTime(d.paid_at)}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <ShareBadge value={d.lender_settlement_status} />
                  <ShareBadge value={d.admin_payout_status} map="payout" />
                </div>
              </div>
              <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Profit Pool</p>
                  <p className="num text-sm font-medium">{rupiah(d.profit_pool)}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Bagian Admin ({d.admin_pct_snapshot}%)</p>
                  <p className="num text-sm font-semibold text-primary">{rupiah(d.admin_profit)}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Setoran Pendana</p>
                  <p className="text-sm font-medium">{d.settlement_verified_at ? formatDateTime(d.settlement_verified_at) : "Belum diterima"}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">Payout</p>
                  <p className="text-sm font-medium">{d.admin_payout_paid_at ? formatDateTime(d.admin_payout_paid_at) : "Belum dibayar"}</p>
                </div>
              </div>
              <div className="mt-5">
                <Button variant="ghost" className="rounded-full" onClick={() => navigate(`/loans/${d.loan_id}`)}>
                  Detail Pinjaman
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState
          testId="empty-admin-earnings"
          title="Belum ada penghasilan"
          description="Penghasilan terbentuk ketika pinjaman yang Anda tangani dinyatakan LUNAS."
        />
      )}
      <p className="mt-6 text-xs text-muted-foreground">
        Catatan: verifikasi setoran Pendana dan penandaan payout hanya dapat dilakukan oleh Superadmin.
      </p>
    </div>
  );
}
