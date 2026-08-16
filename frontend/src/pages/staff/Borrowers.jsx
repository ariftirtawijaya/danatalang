import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { rupiah, formatDate, maskNik } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, StatusBadge } from "@/components/common";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, Download } from "lucide-react";
import { API } from "@/lib/api";

const FILTERS = [
  { value: "ALL", label: "Semua Status" },
  { value: "WAITING_VERIFICATION", label: "Menunggu Verifikasi" },
  { value: "ACTIVE", label: "Aktif" },
  { value: "SUSPENDED", label: "Ditangguhkan" },
  { value: "BLOCKED", label: "Diblokir" },
  { value: "REJECTED", label: "Ditolak" },
];

export default function Borrowers() {
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const accountStatus = params.get("account_status") || "ALL";

  const { data, isLoading } = useQuery({
    queryKey: ["borrowers", q, accountStatus, page],
    queryFn: async () =>
      (
        await api.get("/borrowers", {
          params: { q: q || undefined, account_status: accountStatus === "ALL" ? undefined : accountStatus, page, page_size: 20 },
        })
      ).data,
  });

  const exportCsv = async () => {
    const token = localStorage.getItem("pk_token");
    const res = await fetch(`${API}/export/borrowers`, { headers: { Authorization: `Bearer ${token}` } });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "peminjam.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const totalPages = Math.max(1, Math.ceil((data?.total || 0) / (data?.page_size || 20)));

  return (
    <div>
      <PageHeader title="Peminjam" description="Kelola, verifikasi, dan pantau seluruh Peminjam.">
        <Button variant="outline" className="rounded-full" onClick={exportCsv} data-testid="export-borrowers-btn">
          <Download className="mr-2 h-4 w-4" /> Export CSV
        </Button>
      </PageHeader>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="borrower-search-input"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            placeholder="Cari nama, NIK, No HP, email..."
            className="h-11 rounded-xl pl-10"
          />
        </div>
        <Select
          value={accountStatus}
          onValueChange={(v) => {
            const next = new URLSearchParams(params);
            if (v === "ALL") next.delete("account_status");
            else next.set("account_status", v);
            setParams(next);
            setPage(1);
          }}
        >
          <SelectTrigger data-testid="borrower-status-filter" className="h-11 w-full rounded-xl sm:w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FILTERS.map((f) => (
              <SelectItem key={f.value} value={f.value}>{f.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <>
          <div className="hidden overflow-hidden rounded-2xl border bg-card lg:block">
            <Table data-testid="borrowers-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Nama</TableHead>
                  <TableHead>NIK</TableHead>
                  <TableHead>No HP</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Limit</TableHead>
                  <TableHead className="text-right">Outstanding</TableHead>
                  <TableHead className="text-right">Tersedia</TableHead>
                  <TableHead className="text-center">Aktif</TableHead>
                  <TableHead className="text-center">Lunas</TableHead>
                  <TableHead>Registrasi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((b) => (
                  <TableRow key={b.id} className="cursor-pointer">
                    <TableCell>
                      <Link to={`/borrowers/${b.id}`} data-testid={`borrower-link-${b.id}`} className="font-medium hover:underline">
                        {b.full_name}
                      </Link>
                    </TableCell>
                    <TableCell className="num text-xs">{b.nik_masked}</TableCell>
                    <TableCell className="num text-xs">{b.phone}</TableCell>
                    <TableCell><StatusBadge value={b.account_status} map="account" /></TableCell>
                    <TableCell className="num text-right">{rupiah(b.borrower_limit)}</TableCell>
                    <TableCell className="num text-right">{rupiah(b.outstanding_principal)}</TableCell>
                    <TableCell className="num text-right">{rupiah(b.available_limit)}</TableCell>
                    <TableCell className="num text-center">{b.active_loans}/{b.max_active_loans}</TableCell>
                    <TableCell className="num text-center">{b.completed_loans}</TableCell>
                    <TableCell className="text-xs">{formatDate(b.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="space-y-4 lg:hidden" data-testid="borrowers-cards">
            {data.items.map((b) => (
              <Link key={b.id} to={`/borrowers/${b.id}`} className="block rounded-2xl border bg-card p-5 card-soft">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-heading text-sm font-semibold">{b.full_name}</p>
                    <p className="num text-xs text-muted-foreground">{maskNik(b.nik_masked)} · {b.phone}</p>
                  </div>
                  <StatusBadge value={b.account_status} map="account" />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
                  <div>
                    <p className="uppercase tracking-widest text-muted-foreground">Limit</p>
                    <p className="num font-semibold">{rupiah(b.borrower_limit)}</p>
                  </div>
                  <div>
                    <p className="uppercase tracking-widest text-muted-foreground">Terpakai</p>
                    <p className="num font-semibold">{rupiah(b.outstanding_principal)}</p>
                  </div>
                  <div>
                    <p className="uppercase tracking-widest text-muted-foreground">Aktif</p>
                    <p className="num font-semibold">{b.active_loans}/{b.max_active_loans}</p>
                  </div>
                </div>
              </Link>
            ))}
          </div>

          <div className="mt-6 flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              {data.total} peminjam · halaman {page} dari {totalPages}
            </p>
            <div className="flex gap-2">
              <Button data-testid="prev-page-btn" variant="outline" size="sm" className="rounded-full" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Sebelumnya
              </Button>
              <Button data-testid="next-page-btn" variant="outline" size="sm" className="rounded-full" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                Berikutnya
              </Button>
            </div>
          </div>
        </>
      ) : (
        <EmptyState testId="empty-borrowers" title="Belum ada peminjam" description="Peminjam yang mendaftar akan muncul di sini." />
      )}
    </div>
  );
}
