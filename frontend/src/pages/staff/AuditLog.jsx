import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { actionLabel, entityLabel } from "@/lib/status";
import { PageHeader, EmptyState, LoadingRows } from "@/components/common";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Search } from "lucide-react";

export default function AuditLog() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const { data, isLoading } = useQuery({
    queryKey: ["audit", q, page],
    queryFn: async () => (await api.get("/audit-logs", { params: { q: q || undefined, page, page_size: 25 } })).data,
  });
  const totalPages = Math.max(1, Math.ceil((data?.total || 0) / (data?.page_size || 25)));

  return (
    <div>
      <PageHeader title="Audit Log" description="Seluruh aktivitas kritikal tercatat dan tidak dapat diubah dari UI." />
      <div className="relative mb-6">
        <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input data-testid="audit-search-input" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} placeholder="Cari aksi, deskripsi, atau nama pengguna" className="h-11 rounded-xl pl-10" />
      </div>

      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <>
          <div className="overflow-x-auto rounded-2xl border bg-card">
            <Table data-testid="audit-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Waktu</TableHead>
                  <TableHead>Pengguna</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Aksi</TableHead>
                  <TableHead>Deskripsi</TableHead>
                  <TableHead>Entitas</TableHead>
                  <TableHead>IP</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.items.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="whitespace-nowrap text-xs">{formatDateTime(a.created_at)}</TableCell>
                    <TableCell className="text-xs font-medium">{a.user_name || "-"}</TableCell>
                    <TableCell className="text-xs">{{ superadmin: "Superadmin", admin: "Admin", lender: "Pendana", borrower: "Peminjam" }[a.role] || "-"}</TableCell>
                    <TableCell className="text-xs font-semibold">{actionLabel(a.action)}</TableCell>
                    <TableCell className="max-w-sm text-xs">{a.description}</TableCell>
                    <TableCell className="text-xs">{entityLabel(a.entity_type)}</TableCell>
                    <TableCell className="num text-xs">{a.ip_address || "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="mt-6 flex items-center justify-between">
            <p className="text-xs text-muted-foreground">{data.total} entri · halaman {page} dari {totalPages}</p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" className="rounded-full" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} data-testid="audit-prev-btn">Sebelumnya</Button>
              <Button variant="outline" size="sm" className="rounded-full" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} data-testid="audit-next-btn">Berikutnya</Button>
            </div>
          </div>
        </>
      ) : (
        <EmptyState testId="empty-audit" title="Belum ada audit log" />
      )}
    </div>
  );
}
