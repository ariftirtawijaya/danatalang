import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageHeader, EmptyState, LoadingRows } from "@/components/common";
import { LoanCard } from "@/pages/borrower/Home";

export default function MyLoans() {
  const { data, isLoading } = useQuery({
    queryKey: ["loans", "borrower-all-open"],
    queryFn: async () =>
      (
        await api.get("/loans", {
          params: {
            status: "WAITING_ADMIN_APPROVAL,WAITING_FUNDING,FUNDING_CLAIMED,WAITING_DISBURSEMENT_CONFIRMATION,ACTIVE,OVERDUE,WAITING_PAYMENT_VERIFICATION",
            page_size: 50,
          },
        })
      ).data,
  });

  return (
    <div>
      <PageHeader title="Pinjaman Saya" description="Semua pinjaman yang sedang dalam proses maupun berjalan." />
      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <div className="space-y-4" data-testid="my-loans-list">
          {data.items.map((l) => (
            <LoanCard key={l.id} loan={l} />
          ))}
        </div>
      ) : (
        <EmptyState testId="empty-my-loans" title="Belum ada pinjaman" description="Anda belum memiliki pinjaman yang sedang berjalan." />
      )}
    </div>
  );
}
