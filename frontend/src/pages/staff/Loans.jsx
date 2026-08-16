import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, API } from "@/lib/api";
import { rupiah, formatDateTime } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, StatusBadge } from "@/components/common";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, Download } from "lucide-react";

const STATUS_OPTIONS = [
  { value: "ALL", label: "Semua Status" },
  { value: "WAITING_ADMIN_APPROVAL", label: "Menunggu Approval" },
  { value: "WAITING_FUNDING", label: "Menunggu Pendanaan" },
  { value: "FUNDING_CLAIMED", label: "Sudah Diklaim Pendana" },
  { value: "WAITING_DISBURSEMENT_CONFIRMATION", label: "Konfirmasi Pencairan" },
  { value: "ACTIVE", label: "Aktif" },
  { value: "OVERDUE", label: "Overdue" },
  { value: "WAITING_PAYMENT_VERIFICATION", label: "Verifikasi Pembayaran" },
  { value: "PAID", label: "Lunas" },
  { value: "REJECTED", label: "Ditolak" },
];

export default function Loans() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") || "ALL";
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery({
    queryKey: ["loans", "staff", status, q, page],
    queryFn: async () =>
      (await api.get("/loans", { params: { status: status === "ALL" ? undefined : status, q: q || undefined, page, page_size: 20 } })).data,
  });

  const exportCsv = async () => {
    const token = localStorage.getItem("pk_token");
    const res = await fetch(`${API}/export/loans`, { headers: { Authorization: `Bearer ${token}` } });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "pinjaman.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const totalPages = Math.max(1, Math.ceil((data?.total || 0) / (data?.page_size || 20)));
  const label = STATUS_OPTIONS.find((s) => s.value === status)?.label;

  return (
    <div>
      <PageHeader title="Pinjaman" description={`Menampilkan: ${label}`}>
        <Button variant="outline" className="rounded-full" onClick={exportCsv} data-testid="export-loans-btn">
          <Download className="mr-2 h-4 w-4" /> Export CSV
        </Button>
      </PageHeader>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="loan-search-input"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            placeholder="Cari nomor pinjaman, nama peminjam, NIK..."
            className="h-11 rounded-xl pl-10"
          />
        </div>
        <Select
          value={status}
          onValueChange={(v) => {
            const next = new URLSearchParams(params);
            if (v === "ALL") next.delete("status");
            else next.set("status", v);
            setParams(next);
            setPage(1);
          }}
        >
          <SelectTrigger data-testid="loan-status-filter" className="h-11 w-full rounded-xl sm:w-64">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((s) => (
              <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <>
          <div className="hidden overflow-hidden rounded-2xl border bg-card lg:block">
            <Table data-testid="loans-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Nomor</TableHead>
                  <TableHead>Peminjam</TableHead>
                  <TableHead>Pendana</TableHead>
                  <TableHead className="text-right">Pokok</TableHead>
                  <TableHead className="text-right">Total Tagihan</TableHead>
                  <TableHead className="text-center">Durasi</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Diajukan</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((l) => (
                  <TableRow key={l.id}>
                    <TableCell>
                      <Link to={`/loans/${l.id}`} data-testid={`loan-link-${l.loan_number}`} className="num font-medium hover:underline">
                        {l.loan_number}
                      </Link>
                    </TableCell>
                    <TableCell>{l.borrower_name}</TableCell>
                    <TableCell>{l.lender_name || "-"}</TableCell>
                    <TableCell className="num text-right">{rupiah(l.principal_amount)}</TableCell>
                    <TableCell className="num text-right">{rupiah(l.total_due)}</TableCell>
                    <TableCell className="num text-center">{l.duration_days}h</TableCell>
                    <TableCell><StatusBadge value={l.effective_status} /></TableCell>
                    <TableCell className="text-xs">{formatDateTime(l.submitted_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="space-y-4 lg:hidden">
            {data.items.map((l) => (
              <Link key={l.id} to={`/loans/${l.id}`} className="block rounded-2xl border bg-card p-5 card-soft">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="num font-heading text-sm font-semibold">{l.loan_number}</p>
                    <p className="text-xs text-muted-foreground">{l.borrower_name}</p>
                  </div>
                  <StatusBadge value={l.effective_status} />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
                  <div>
                    <p className="uppercase tracking-widest text-muted-foreground">Pokok</p>
                    <p className="num font-semibold">{rupiah(l.principal_amount)}</p>
                  </div>
                  <div>
                    <p className="uppercase tracking-widest text-muted-foreground">Tagihan</p>
                    <p className="num font-semibold">{rupiah(l.total_due)}</p>
                  </div>
                  <div>
                    <p className="uppercase tracking-widest text-muted-foreground">Pendana</p>
                    <p className="font-semibold">{l.lender_name || "-"}</p>
                  </div>
                </div>
              </Link>
            ))}
          </div>

          <div className="mt-6 flex items-center justify-between">
            <p className="text-xs text-muted-foreground">{data.total} pinjaman · halaman {page} dari {totalPages}</p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" className="rounded-full" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} data-testid="loans-prev-btn">
                Sebelumnya
              </Button>
              <Button variant="outline" size="sm" className="rounded-full" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} data-testid="loans-next-btn">
                Berikutnya
              </Button>
            </div>
          </div>
        </>
      ) : (
        <EmptyState testId="empty-loans" title="Belum ada pinjaman" description="Tidak ada pinjaman pada filter ini." />
      )}
    </div>
  );
}
