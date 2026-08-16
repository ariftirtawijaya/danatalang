import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, API } from "@/lib/api";
import { rupiah, formatDateTime } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, StatusBadge, ProofImage, Field } from "@/components/common";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Search, Download } from "lucide-react";

export default function StaffPayments() {
  const [tab, setTab] = useState("PENDING");
  const [q, setQ] = useState("");
  const { data, isLoading } = useQuery({
    queryKey: ["payments", "staff", tab, q],
    queryFn: async () => (await api.get("/payments", { params: { status: tab, q: q || undefined, page_size: 50 } })).data,
  });

  const exportCsv = async () => {
    const token = localStorage.getItem("pk_token");
    const res = await fetch(`${API}/export/payments`, { headers: { Authorization: `Bearer ${token}` } });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "pembayaran.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <PageHeader title="Monitoring Pembayaran" description="Admin hanya memantau. Verifikasi pembayaran dilakukan oleh Pendana pemilik pinjaman.">
        <Button variant="outline" className="rounded-full" onClick={exportCsv} data-testid="export-payments-btn">
          <Download className="mr-2 h-4 w-4" /> Export CSV
        </Button>
      </PageHeader>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="PENDING" data-testid="staff-payments-pending">Menunggu Verifikasi</TabsTrigger>
            <TabsTrigger value="VERIFIED" data-testid="staff-payments-verified">Diterima</TabsTrigger>
            <TabsTrigger value="REJECTED" data-testid="staff-payments-rejected">Ditolak</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input data-testid="payment-search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nomor pinjaman / peminjam" className="h-11 rounded-xl pl-10" />
        </div>
      </div>

      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <div className="space-y-5" data-testid="staff-payments-list">
          {data.items.map((p) => (
            <div key={p.id} className="rounded-2xl border bg-card p-6 card-soft">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <Link to={`/loans/${p.loan_id}`} className="num font-heading text-sm font-semibold hover:underline">
                    {p.loan_number}
                  </Link>
                  <p className="text-xs text-muted-foreground">{p.borrower_name} · Pendana: {p.lender_name || "-"} · Attempt #{p.attempt_no}</p>
                </div>
                <StatusBadge value={p.status} map="payment" />
              </div>
              <div className="mt-5 grid grid-cols-2 gap-5 sm:grid-cols-4">
                <Field label="Total Tagihan" value={rupiah(p.amount_due_at_submission)} mono />
                <Field label="Dilaporkan Dibayar" value={rupiah(p.amount_paid)} mono />
                <Field label="Denda" value={rupiah(p.late_fee_at_submission)} mono />
                <Field label="Waktu Lapor" value={formatDateTime(p.payment_submitted_at)} />
              </div>
              {p.rejection_reason && <p className="mt-3 text-sm text-destructive">Ditolak: {p.rejection_reason}</p>}
              <div className="mt-5">
                <ProofImage fileId={p.proof_file_id} label="Lihat Bukti" testId={`staff-proof-${p.id}`} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState testId="empty-staff-payments" title="Belum ada pembayaran" description="Laporan pembayaran dari Peminjam akan muncul di sini." />
      )}
    </div>
  );
}
