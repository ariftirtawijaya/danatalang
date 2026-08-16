import { useQuery } from "@tanstack/react-query";
import { api, API } from "@/lib/api";
import { rupiah } from "@/lib/format";
import { PageHeader, LoadingRows, StatCard, EmptyState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Coins, TrendingUp, BadgeCheck, AlertTriangle, Wallet, Users, Download, Receipt } from "lucide-react";

const download = async (entity, filename) => {
  const token = localStorage.getItem("pk_token");
  const res = await fetch(`${API}/export/${entity}`, { headers: { Authorization: `Bearer ${token}` } });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
};

export default function Reports() {
  const { data, isLoading } = useQuery({ queryKey: ["reports"], queryFn: async () => (await api.get("/reports")).data });

  if (isLoading) return <LoadingRows rows={4} />;

  return (
    <div>
      <PageHeader title="Laporan" description="Ringkasan performa portofolio pinjaman.">
        <Button variant="outline" className="rounded-full" onClick={() => download("loans", "pinjaman.csv")} data-testid="report-export-loans">
          <Download className="mr-2 h-4 w-4" /> Pinjaman
        </Button>
        <Button variant="outline" className="rounded-full" onClick={() => download("payments", "pembayaran.csv")} data-testid="report-export-payments">
          <Download className="mr-2 h-4 w-4" /> Pembayaran
        </Button>
        <Button variant="outline" className="rounded-full" onClick={() => download("fundings", "pendanaan.csv")} data-testid="report-export-fundings">
          <Download className="mr-2 h-4 w-4" /> Pendanaan
        </Button>
      </PageHeader>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
        <StatCard testId="report-disbursed" label="Total Pokok Dicairkan" value={rupiah(data?.total_principal_disbursed)} icon={TrendingUp} />
        <StatCard testId="report-outstanding" label="Outstanding Pokok" value={rupiah(data?.total_outstanding_principal)} icon={Coins} tone="active" />
        <StatCard testId="report-paid" label="Pokok Terbayar" value={rupiah(data?.total_principal_paid)} icon={BadgeCheck} tone="success" />
        <StatCard testId="report-interest" label="Bunga Terbayar" value={rupiah(data?.total_interest_paid)} icon={Receipt} tone="success" />
        <StatCard testId="report-latefee" label="Denda Terbayar" value={rupiah(data?.total_late_fee_paid)} icon={AlertTriangle} tone="warning" />
        <StatCard testId="report-active" label="Pinjaman Aktif" value={data?.active_loans ?? 0} icon={Wallet} tone="active" />
        <StatCard testId="report-overdue" label="Pinjaman Terlambat" value={data?.overdue_loans ?? 0} icon={AlertTriangle} tone="warning" />
        <StatCard testId="report-lunas" label="Pinjaman Lunas" value={data?.paid_loans ?? 0} icon={BadgeCheck} tone="success" />
        <StatCard testId="report-borrowers" label="Total Peminjam" value={data?.borrower_count ?? 0} icon={Users} />
        <StatCard testId="report-active-borrowers" label="Peminjam Aktif" value={data?.active_borrower_count ?? 0} icon={Users} tone="success" />
      </div>

      <section className="mt-8">
        <h2 className="mb-4 font-heading text-lg font-semibold">Performa Pendana</h2>
        {data?.lender_performance?.length ? (
          <div className="overflow-x-auto rounded-2xl border bg-card">
            <Table data-testid="lender-performance-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Pendana</TableHead>
                  <TableHead className="text-center">Pinjaman Didanai</TableHead>
                  <TableHead className="text-center">Aktif</TableHead>
                  <TableHead className="text-center">Terlambat</TableHead>
                  <TableHead className="text-right">Total Dicairkan</TableHead>
                  <TableHead className="text-right">Pokok Kembali</TableHead>
                  <TableHead className="text-right">Bunga Diterima</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.lender_performance.map((l) => (
                  <TableRow key={l.id}>
                    <TableCell className="font-medium">{l.name}</TableCell>
                    <TableCell className="num text-center">{l.loans_funded}</TableCell>
                    <TableCell className="num text-center">{l.active_loans}</TableCell>
                    <TableCell className="num text-center">{l.overdue_loans}</TableCell>
                    <TableCell className="num text-right">{rupiah(l.total_disbursed)}</TableCell>
                    <TableCell className="num text-right">{rupiah(l.principal_returned)}</TableCell>
                    <TableCell className="num text-right">{rupiah(l.interest_earned)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState testId="empty-lender-performance" title="Belum ada data pendana" />
        )}
      </section>
    </div>
  );
}
