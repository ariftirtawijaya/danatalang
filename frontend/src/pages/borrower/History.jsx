import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageHeader, EmptyState, LoadingRows } from "@/components/common";
import { LoanCard } from "@/pages/borrower/Home";

export default function History() {
  const { data, isLoading } = useQuery({
    queryKey: ["loans", "borrower-history"],
    queryFn: async () => (await api.get("/loans", { params: { status: "PAID,REJECTED,CANCELLED", page_size: 50 } })).data,
  });

  return (
    <div>
      <PageHeader title="Riwayat" description="Pinjaman yang telah lunas, ditolak, atau dibatalkan." />
      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <div className="space-y-4" data-testid="history-list">
          {data.items.map((l) => (
            <LoanCard key={l.id} loan={l} />
          ))}
        </div>
      ) : (
        <EmptyState testId="empty-history" title="Belum ada riwayat" description="Anda belum memiliki riwayat pinjaman." />
      )}
    </div>
  );
}
