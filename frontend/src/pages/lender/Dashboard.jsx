import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { rupiah } from "@/lib/format";
import { StatCard, PageHeader, EmptyState, LoadingRows } from "@/components/common";
import { LoanCard } from "@/pages/borrower/Home";
import { Button } from "@/components/ui/button";
import { HandCoins, Wallet, Receipt, AlertTriangle, TrendingUp, Coins, BadgeCheck, Clock } from "lucide-react";

export default function LenderDashboard() {
  const { data: s, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: async () => (await api.get("/dashboard")).data });
  const { data: todo } = useQuery({
    queryKey: ["loans", "lender-todo"],
    queryFn: async () => (await api.get("/loans", { params: { status: "FUNDING_CLAIMED,WAITING_PAYMENT_VERIFICATION", page_size: 20 } })).data,
  });

  return (
    <div>
      <PageHeader title="Dashboard Pendana" description="Ringkasan pendanaan dan tindakan yang perlu Anda lakukan.">
        <Button asChild data-testid="goto-available-btn" className="rounded-full">
          <Link to="/available">Lihat Pinjaman Siap Didanai</Link>
        </Button>
      </PageHeader>

      {isLoading ? (
        <LoadingRows rows={3} />
      ) : (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
          <StatCard testId="stat-available" label="Siap Didanai" value={s?.available_loans ?? 0} icon={HandCoins} tone="pending" />
          <StatCard testId="stat-claimed" label="Menunggu Pencairan" value={s?.claimed_not_disbursed ?? 0} icon={Clock} tone="pending" />
          <StatCard testId="stat-active" label="Pinjaman Aktif" value={s?.active_loans ?? 0} icon={Wallet} tone="active" />
          <StatCard testId="stat-verify" label="Verifikasi Pembayaran" value={s?.waiting_payment_verification ?? 0} icon={Receipt} tone="pending" />
          <StatCard testId="stat-overdue" label="Terlambat" value={s?.overdue_loans ?? 0} icon={AlertTriangle} tone="warning" />
          <StatCard testId="stat-active-principal" label="Total Pokok Aktif" value={rupiah(s?.total_active_principal)} icon={Coins} tone="active" />
          <StatCard testId="stat-disbursed" label="Total Dicairkan" value={rupiah(s?.total_disbursed)} icon={TrendingUp} />
          <StatCard testId="stat-returned" label="Pokok Kembali" value={rupiah(s?.total_principal_returned)} icon={BadgeCheck} tone="success" />
          <StatCard testId="stat-interest" label="Bunga Diterima" value={rupiah(s?.total_interest_earned)} icon={TrendingUp} tone="success" />
          <StatCard testId="stat-paid" label="Pinjaman Lunas" value={s?.paid_loans ?? 0} icon={BadgeCheck} tone="success" />
        </div>
      )}

      <section className="mt-10 space-y-4">
        <h2 className="font-heading text-lg font-semibold">Perlu Tindakan</h2>
        {todo?.items?.length ? (
          <div className="space-y-4" data-testid="lender-todo-list">
            {todo.items.map((l) => (
              <LoanCard key={l.id} loan={l} />
            ))}
          </div>
        ) : (
          <EmptyState testId="empty-lender-todo" title="Tidak ada tindakan tertunda" description="Semua pendanaan dan pembayaran Anda sudah terproses." />
        )}
      </section>
    </div>
  );
}
