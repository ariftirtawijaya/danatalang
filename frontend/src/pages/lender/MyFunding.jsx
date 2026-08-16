import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { PageHeader, EmptyState, LoadingRows } from "@/components/common";
import { LoanCard } from "@/pages/borrower/Home";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const TABS = [
  { key: "open", label: "Berjalan", status: "FUNDING_CLAIMED,WAITING_DISBURSEMENT_CONFIRMATION,ACTIVE,OVERDUE,WAITING_PAYMENT_VERIFICATION" },
  { key: "active", label: "Aktif", status: "ACTIVE" },
  { key: "overdue", label: "Terlambat", status: "OVERDUE" },
  { key: "paid", label: "Lunas", status: "PAID" },
];

export default function MyFunding() {
  const [tab, setTab] = useState("open");
  const status = TABS.find((t) => t.key === tab).status;
  const { data, isLoading } = useQuery({
    queryKey: ["loans", "lender-funding", tab],
    queryFn: async () => (await api.get("/loans", { params: { status, page_size: 50 } })).data,
  });

  return (
    <div>
      <PageHeader title="Pendanaan Saya" description="Seluruh pinjaman yang Anda danai." />
      <Tabs value={tab} onValueChange={setTab} className="mb-6">
        <TabsList className="w-full justify-start overflow-x-auto">
          {TABS.map((t) => (
            <TabsTrigger key={t.key} value={t.key} data-testid={`funding-tab-${t.key}`}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <div className="space-y-4" data-testid="funding-list">
          {data.items.map((l) => (
            <LoanCard key={l.id} loan={l} />
          ))}
        </div>
      ) : (
        <EmptyState testId="empty-funding" title="Belum ada pendanaan" description="Anda belum memiliki pendanaan pada kategori ini." />
      )}
    </div>
  );
}
