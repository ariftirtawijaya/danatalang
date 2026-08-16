import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { rupiah, formatDate, formatDateTime, formatThousand, onlyDigits } from "@/lib/format";
import { PageHeader, LoadingRows, StatusBadge, Field, EmptyState, ConfirmDialog } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LoanCard } from "@/pages/borrower/Home";
import { ArrowLeft } from "lucide-react";

export default function BorrowerDetail() {
  const { id } = useParams();
  const [dialog, setDialog] = useState(null);
  const [busy, setBusy] = useState(false);
  const [limits, setLimits] = useState({ borrower_limit: "", max_duration_days: "30", max_active_loans: "2" });
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [newStatus, setNewStatus] = useState("SUSPENDED");
  const [tempPassword, setTempPassword] = useState(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["borrower", id],
    queryFn: async () => (await api.get(`/borrowers/${id}`)).data,
  });

  const run = async (fn, msg) => {
    setBusy(true);
    try {
      await fn();
      toast.success(msg);
      setDialog(null);
      setReason("");
      setNote("");
      await refetch();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  if (isLoading) return <LoadingRows rows={5} />;
  if (!data) return <p className="text-sm text-muted-foreground">Peminjam tidak ditemukan.</p>;

  const p = data.profile;
  const c = data.credit;
  const activeLoans = data.loans.filter((l) => !["PAID", "REJECTED", "CANCELLED"].includes(l.status));
  const historyLoans = data.loans.filter((l) => ["PAID", "REJECTED", "CANCELLED"].includes(l.status));

  return (
    <div>
      <Link to="/borrowers" data-testid="back-to-borrowers" className="mb-5 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Semua Peminjam
      </Link>
      <PageHeader title={p.full_name} description={`Registrasi ${formatDateTime(p.created_at)}`}>
        <StatusBadge value={p.account_status} map="account" />
        {p.account_status === "WAITING_VERIFICATION" ? (
          <>
            <Button data-testid="verify-approve-btn" className="rounded-full" onClick={() => setDialog("approve")}>Setujui</Button>
            <Button data-testid="verify-reject-btn" variant="outline" className="rounded-full" onClick={() => setDialog("reject")}>Tolak</Button>
          </>
        ) : (
          <>
            <Button
              data-testid="edit-limits-btn"
              variant="outline"
              className="rounded-full"
              onClick={() => {
                setLimits({
                  borrower_limit: String(c.borrower_limit || ""),
                  max_duration_days: String(c.max_duration_days || 30),
                  max_active_loans: String(c.max_active_loans || 1),
                });
                setDialog("limits");
              }}
            >
              Ubah Limit
            </Button>
            <Button data-testid="change-status-btn" variant="outline" className="rounded-full" onClick={() => setDialog("status")}>
              Ubah Status
            </Button>
            <Button data-testid="reset-borrower-password-btn" variant="outline" className="rounded-full" onClick={() => setDialog("reset")}>
              Reset Password
            </Button>
          </>
        )}
      </PageHeader>

      <Tabs defaultValue="profile">
        <TabsList className="mb-6 w-full justify-start overflow-x-auto">
          <TabsTrigger value="profile" data-testid="tab-profile">Profil</TabsTrigger>
          <TabsTrigger value="limits" data-testid="tab-limits">Limit & Aturan</TabsTrigger>
          <TabsTrigger value="active" data-testid="tab-active">Pinjaman Aktif</TabsTrigger>
          <TabsTrigger value="history" data-testid="tab-history">Riwayat</TabsTrigger>
          <TabsTrigger value="credit" data-testid="tab-credit">Credit History</TabsTrigger>
          <TabsTrigger value="notes" data-testid="tab-notes">Catatan</TabsTrigger>
          <TabsTrigger value="audit" data-testid="tab-audit">Audit</TabsTrigger>
        </TabsList>

        <TabsContent value="profile">
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border bg-card p-6 card-soft">
              <p className="mb-5 font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Identitas</p>
              <div className="grid grid-cols-2 gap-5">
                <Field label="Nama Lengkap" value={p.full_name} />
                <Field label="NIK" value={p.nik} mono />
                <Field label="Tanggal Lahir" value={p.birth_date ? formatDate(p.birth_date) : "-"} />
                <Field label="No HP" value={p.phone} mono />
                <Field label="Email" value={p.email} />
                <Field label="Status Akun" value={p.account_status} />
                {p.verified_by_name && <Field label="Diverifikasi Oleh" value={p.verified_by_name} />}
                {p.verified_at && <Field label="Waktu Verifikasi" value={formatDateTime(p.verified_at)} />}
                {p.rejection_reason && <Field label="Alasan Penolakan" value={p.rejection_reason} />}
              </div>
            </section>
            <section className="rounded-2xl border bg-card p-6 card-soft">
              <p className="mb-5 font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Rekening</p>
              <div className="grid grid-cols-2 gap-5">
                <Field label="Metode" value={p.bank_name} />
                <Field label="Nomor" value={p.account_number} mono />
                <Field label="Nama Pemilik" value={p.account_holder} />
              </div>
            </section>
          </div>
        </TabsContent>

        <TabsContent value="limits">
          <div className="grid grid-cols-2 gap-5 rounded-2xl border bg-card p-6 card-soft sm:grid-cols-3">
            <Field label="Limit Pinjaman" value={rupiah(c.borrower_limit)} mono />
            <Field label="Outstanding" value={rupiah(c.outstanding_principal)} mono />
            <Field label="Tersedia" value={rupiah(c.available_limit)} mono />
            <Field label="Durasi Maksimal" value={`${c.max_duration_days} hari`} />
            <Field label="Maks. Pinjaman Aktif" value={c.max_active_loans} />
            <Field label="Pinjaman Aktif" value={c.active_loans} />
          </div>
        </TabsContent>

        <TabsContent value="active">
          {activeLoans.length ? (
            <div className="space-y-4">{activeLoans.map((l) => <LoanCard key={l.id} loan={l} />)}</div>
          ) : (
            <EmptyState testId="empty-borrower-active" title="Tidak ada pinjaman aktif" />
          )}
        </TabsContent>

        <TabsContent value="history">
          {historyLoans.length ? (
            <div className="space-y-4">{historyLoans.map((l) => <LoanCard key={l.id} loan={l} />)}</div>
          ) : (
            <EmptyState testId="empty-borrower-history" title="Belum ada riwayat pinjaman" />
          )}
        </TabsContent>

        <TabsContent value="credit">
          <div className="grid grid-cols-2 gap-5 rounded-2xl border bg-card p-6 card-soft sm:grid-cols-4" data-testid="credit-stats">
            <Field label="Total Pengajuan" value={c.total_applications} />
            <Field label="Disetujui" value={c.total_approved} />
            <Field label="Ditolak" value={c.total_rejected} />
            <Field label="Pernah Dicairkan" value={c.total_disbursed_count} />
            <Field label="Total Dipinjam" value={rupiah(c.total_borrowed_amount)} mono />
            <Field label="Pinjaman Aktif" value={c.active_loans} />
            <Field label="Lunas" value={c.completed_loans} />
            <Field label="Lunas Tepat Waktu" value={c.paid_on_time} />
            <Field label="Pernah Terlambat" value={c.paid_late} />
            <Field label="Total Hari Terlambat" value={c.total_late_days} />
            <Field label="Terlambat Terlama" value={`${c.longest_late_days} hari`} />
            <Field label="Outstanding" value={rupiah(c.outstanding_principal)} mono />
          </div>
        </TabsContent>

        <TabsContent value="notes">
          <div className="space-y-5">
            <div className="rounded-2xl border bg-card p-6 card-soft">
              <Label>Tambah Catatan Internal</Label>
              <Textarea data-testid="note-input" value={note} onChange={(e) => setNote(e.target.value)} rows={3} className="mt-2" placeholder="Catatan hanya terlihat oleh Admin/Superadmin" />
              <Button
                data-testid="add-note-btn"
                className="mt-3 rounded-full"
                disabled={busy || note.trim().length < 2}
                onClick={() => run(() => api.post(`/borrowers/${id}/notes`, { note }), "Catatan ditambahkan")}
              >
                Simpan Catatan
              </Button>
            </div>
            {data.notes.length ? (
              <div className="space-y-3">
                {data.notes.map((n) => (
                  <div key={n.id} className="rounded-xl border bg-card p-5">
                    <p className="text-sm">{n.note}</p>
                    <p className="mt-2 text-xs text-muted-foreground">{n.author} · {formatDateTime(n.created_at)}</p>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState testId="empty-notes" title="Belum ada catatan" />
            )}
          </div>
        </TabsContent>

        <TabsContent value="audit">
          {data.audit.length ? (
            <div className="space-y-3">
              {data.audit.map((a, i) => (
                <div key={i} className="rounded-xl border bg-card p-4">
                  <p className="text-sm font-medium">{a.action}</p>
                  <p className="text-xs text-muted-foreground">{a.description}</p>
                  <p className="mt-1 text-[10px] uppercase tracking-widest text-muted-foreground">{a.user_name} · {formatDateTime(a.created_at)}</p>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState testId="empty-borrower-audit" title="Belum ada aktivitas" />
          )}
        </TabsContent>
      </Tabs>

      {/* Approve dialog */}
      <Dialog open={dialog === "approve" || dialog === "limits"} onOpenChange={() => setDialog(null)}>
        <DialogContent data-testid="verify-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">{dialog === "approve" ? "Setujui Peminjam" : "Ubah Limit & Aturan"}</DialogTitle>
            <DialogDescription>Tetapkan limit pinjaman, durasi maksimal, dan maksimal pinjaman aktif.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Limit Pinjaman</Label>
              <Input
                data-testid="limit-input"
                inputMode="numeric"
                value={formatThousand(limits.borrower_limit)}
                onChange={(e) => setLimits((l) => ({ ...l, borrower_limit: onlyDigits(e.target.value) }))}
                className="h-11 rounded-xl num"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Durasi Maksimal (hari)</Label>
                <Input
                  data-testid="max-duration-input"
                  inputMode="numeric"
                  value={limits.max_duration_days}
                  onChange={(e) => setLimits((l) => ({ ...l, max_duration_days: onlyDigits(e.target.value) }))}
                  className="h-11 rounded-xl num"
                />
              </div>
              <div className="space-y-2">
                <Label>Maks. Pinjaman Aktif</Label>
                <Input
                  data-testid="max-active-input"
                  inputMode="numeric"
                  value={limits.max_active_loans}
                  onChange={(e) => setLimits((l) => ({ ...l, max_active_loans: onlyDigits(e.target.value) }))}
                  className="h-11 rounded-xl num"
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialog(null)} disabled={busy}>Batal</Button>
            <Button
              data-testid="verify-submit-btn"
              disabled={busy || !limits.borrower_limit || !limits.max_duration_days || !limits.max_active_loans}
              onClick={() =>
                dialog === "approve"
                  ? run(
                      () =>
                        api.post(`/borrowers/${id}/verify`, {
                          approve: true,
                          borrower_limit: Number(limits.borrower_limit),
                          max_duration_days: Number(limits.max_duration_days),
                          max_active_loans: Number(limits.max_active_loans),
                        }),
                      "Peminjam disetujui dan akun menjadi ACTIVE"
                    )
                  : run(
                      () =>
                        api.put(`/borrowers/${id}/limits`, {
                          borrower_limit: Number(limits.borrower_limit),
                          max_duration_days: Number(limits.max_duration_days),
                          max_active_loans: Number(limits.max_active_loans),
                        }),
                      "Limit diperbarui"
                    )
              }
            >
              {busy ? "Memproses..." : "Simpan"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reject dialog */}
      <Dialog open={dialog === "reject"} onOpenChange={() => setDialog(null)}>
        <DialogContent data-testid="reject-borrower-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Tolak Peminjam</DialogTitle>
            <DialogDescription>Alasan wajib diisi dan tercatat pada audit log.</DialogDescription>
          </DialogHeader>
          <Textarea data-testid="reject-reason-input" value={reason} onChange={(e) => setReason(e.target.value)} rows={4} />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialog(null)} disabled={busy}>Batal</Button>
            <Button
              data-testid="reject-borrower-submit-btn"
              variant="destructive"
              disabled={busy || reason.trim().length < 3}
              onClick={() => run(() => api.post(`/borrowers/${id}/verify`, { approve: false, reason }), "Peminjam ditolak")}
            >
              Tolak
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Status dialog */}
      <Dialog open={dialog === "status"} onOpenChange={() => setDialog(null)}>
        <DialogContent data-testid="status-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Ubah Status Akun</DialogTitle>
            <DialogDescription>Perubahan status akan tercatat pada audit log.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Select value={newStatus} onValueChange={setNewStatus}>
              <SelectTrigger data-testid="status-select" className="h-11 rounded-xl">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ACTIVE">ACTIVE</SelectItem>
                <SelectItem value="SUSPENDED">SUSPENDED</SelectItem>
                <SelectItem value="BLOCKED">BLOCKED</SelectItem>
              </SelectContent>
            </Select>
            <Textarea data-testid="status-reason-input" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} placeholder="Alasan (opsional)" />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialog(null)} disabled={busy}>Batal</Button>
            <Button
              data-testid="status-submit-btn"
              disabled={busy}
              onClick={() => run(() => api.put(`/borrowers/${id}/status`, { account_status: newStatus, reason }), "Status akun diperbarui")}
            >
              Simpan
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={dialog === "reset"}
        onOpenChange={() => setDialog(null)}
        testId="reset-borrower-password-dialog"
        title="Reset password Peminjam?"
        description={`Sistem akan membuat password sementara untuk ${p.full_name}. Password lama tidak dapat dilihat siapa pun, dan Peminjam wajib membuat password baru saat login berikutnya. Tindakan ini tercatat pada Audit Log.`}
        confirmLabel="Reset Password"
        loading={busy}
        onConfirm={async () => {
          setBusy(true);
          try {
            const { data: res } = await api.post(`/users/${id}/reset-password`);
            setTempPassword(res);
            setDialog(null);
            toast.success("Password direset");
          } catch (err) {
            toast.error(errMsg(err));
          } finally {
            setBusy(false);
          }
        }}
      />

      <Dialog open={!!tempPassword} onOpenChange={() => setTempPassword(null)}>
        <DialogContent data-testid="borrower-temp-password-dialog">
          <DialogHeader>
            <DialogTitle className="font-heading">Password Sementara</DialogTitle>
            <DialogDescription>
              Bagikan kepada {tempPassword?.full_name} ({tempPassword?.phone}) melalui kanal aman. Hanya ditampilkan sekali.
            </DialogDescription>
          </DialogHeader>
          <p data-testid="borrower-temp-password-value" className="num rounded-xl border bg-muted px-4 py-4 text-center font-heading text-xl font-semibold tracking-widest">
            {tempPassword?.temporary_password}
          </p>
          <DialogFooter>
            <Button data-testid="borrower-temp-password-close-btn" onClick={() => setTempPassword(null)}>Selesai</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
