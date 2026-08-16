import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { rupiah, rupiahShort } from "@/lib/format";
import { StatCard, PageHeader, LoadingRows, EmptyState } from "@/components/common";
import { Button } from "@/components/ui/button";
import {
  Users, UserCheck, UserPlus, Shield, HandCoins, Wallet, ClipboardList, BadgeCheck,
  AlertTriangle, Receipt, Coins, TrendingUp,
} from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, PieChart, Pie, Cell, Legend } from "recharts";

const COLORS = ["#3B82F6", "#F97316", "#10B981", "#F59E0B"];

export default function StaffDashboard() {
  const { user } = useAuth();
  const isSuper = user?.role === "superadmin";
  const { data: s, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: async () => (await api.get("/dashboard")).data });

  const actions = [
    { label: "Peminjam Menunggu Verifikasi", count: s?.waiting_verification, to: "/borrowers?account_status=WAITING_VERIFICATION" },
    { label: "Pengajuan Menunggu Approval", count: s?.waiting_approval, to: "/loans?status=WAITING_ADMIN_APPROVAL" },
    { label: "Pencairan Menunggu Konfirmasi", count: s?.waiting_disbursement, to: "/loans?status=WAITING_DISBURSEMENT_CONFIRMATION" },
    { label: "Laporan Pembayaran Baru", count: s?.waiting_payment_verification, to: "/loans?status=WAITING_PAYMENT_VERIFICATION" },
  ].filter((a) => (a.count ?? 0) > 0);

  return (
    <div>
      <PageHeader
        title={isSuper ? "Dashboard Superadmin" : "Dashboard Admin"}
        description="Ringkasan operasional pinjaman dan tindakan yang perlu diproses."
      />

      {isLoading ? (
        <LoadingRows rows={4} />
      ) : (
        <>
          <section className="mb-9">
            <h2 className="mb-4 font-heading text-lg font-semibold">Perlu Tindakan</h2>
            {actions.length ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="action-required">
                {actions.map((a) => (
                  <Link
                    key={a.to}
                    to={a.to}
                    data-testid={`action-${a.to}`}
                    className="rounded-2xl border border-amber-300/50 bg-amber-50 p-5 transition-transform hover:-translate-y-0.5 dark:bg-amber-500/10"
                  >
                    <p className="font-heading text-2xl font-semibold num">{a.count}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{a.label}</p>
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState testId="empty-actions" title="Tidak ada tindakan tertunda" description="Semua proses sudah ditangani." />
            )}
          </section>

          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
            <StatCard testId="stat-total-borrowers" label="Total Peminjam" value={s?.total_borrowers ?? 0} icon={Users} />
            <StatCard testId="stat-active-borrowers" label="Peminjam Aktif" value={s?.active_borrowers ?? 0} icon={UserCheck} tone="success" />
            <StatCard testId="stat-waiting-verification" label="Menunggu Verifikasi" value={s?.waiting_verification ?? 0} icon={UserPlus} tone="pending" />
            {isSuper && <StatCard testId="stat-total-admins" label="Total Admin" value={s?.total_admins ?? 0} icon={Shield} />}
            <StatCard testId="stat-total-lenders" label="Total Pendana" value={s?.total_lenders ?? 0} icon={HandCoins} />
            <StatCard testId="stat-total-loans" label="Total Pinjaman" value={s?.total_loans ?? 0} icon={Wallet} />
            <StatCard testId="stat-waiting-approval" label="Menunggu Approval" value={s?.waiting_approval ?? 0} icon={ClipboardList} tone="pending" />
            <StatCard testId="stat-waiting-funding" label="Menunggu Pendanaan" value={s?.waiting_funding ?? 0} icon={HandCoins} tone="pending" />
            <StatCard testId="stat-active-loans" label="Pinjaman Aktif" value={s?.active_loans ?? 0} icon={BadgeCheck} tone="active" />
            <StatCard testId="stat-overdue-loans" label="Pinjaman Terlambat" value={s?.overdue_loans ?? 0} icon={AlertTriangle} tone="warning" />
            <StatCard testId="stat-paid-loans" label="Pinjaman Lunas" value={s?.paid_loans ?? 0} icon={BadgeCheck} tone="success" />
            <StatCard testId="stat-outstanding" label="Outstanding Pokok" value={rupiah(s?.total_outstanding_principal)} icon={Coins} tone="active" />
            <StatCard testId="stat-disbursed" label="Total Pencairan" value={rupiah(s?.total_disbursed)} icon={TrendingUp} />
            <StatCard testId="stat-payments" label="Total Pembayaran" value={rupiah(s?.total_payments)} icon={Receipt} tone="success" />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            <div className="rounded-2xl border bg-card p-6 card-soft lg:col-span-2">
              <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Pinjaman per Bulan</p>
              <div className="mt-5 h-64 w-full" style={{ minHeight: 256, minWidth: 240 }}>
                <ResponsiveContainer width="99%" height={256} minWidth={240}>
                  <BarChart data={s?.monthly || []}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" />
                    <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} tickFormatter={rupiahShort} width={70} />
                    <Tooltip formatter={(v, n) => (n === "count" ? v : rupiah(v))} />
                    <Bar dataKey="principal" name="Nominal Diajukan" fill="hsl(var(--chart-1))" radius={[6, 6, 0, 0]} />
                    <Bar dataKey="disbursed" name="Dicairkan" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="rounded-2xl border bg-card p-6 card-soft">
              <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Komposisi Status</p>
              <div className="mt-5 h-64 w-full" style={{ minHeight: 256, minWidth: 240 }}>
                <ResponsiveContainer width="99%" height={256} minWidth={240}>
                  <PieChart>
                    <Pie data={s?.status_breakdown || []} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={3}>
                      {(s?.status_breakdown || []).map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap gap-3">
            <Button asChild variant="outline" className="rounded-full">
              <Link to="/borrowers" data-testid="quick-borrowers-btn">Kelola Peminjam</Link>
            </Button>
            <Button asChild variant="outline" className="rounded-full">
              <Link to="/loans" data-testid="quick-loans-btn">Semua Pinjaman</Link>
            </Button>
            <Button asChild variant="outline" className="rounded-full">
              <Link to="/reports" data-testid="quick-reports-btn">Laporan</Link>
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
