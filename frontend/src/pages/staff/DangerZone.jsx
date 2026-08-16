import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useSettings } from "@/context/SettingsContext";
import { LoadingRows } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { ShieldAlert, Trash2 } from "lucide-react";

const ROWS = [
  ["admins", "Admin"],
  ["lenders", "Pendana"],
  ["borrowers", "Peminjam"],
  ["other_superadmins", "Superadmin lain"],
  ["loans", "Pinjaman"],
  ["disbursements", "Pencairan"],
  ["payments", "Pembayaran (semua attempt)"],
  ["loan_status_histories", "Riwayat status pinjaman"],
  ["notifications", "Log notifikasi"],
  ["admin_notes", "Catatan internal"],
  ["audit_logs", "Audit log lama"],
  ["files", "Referensi file bukti"],
  ["counters", "Sequence/counter transaksi"],
];

export default function DangerZone() {
  const { user, logout } = useAuth();
  const { reload } = useSettings();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["factory-reset-preview"],
    queryFn: async () => (await api.get("/settings/factory-reset/preview")).data,
  });

  const canSubmit = confirmation.trim() === "HAPUS SEMUA DATA" && password.length >= 6 && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      const { data: res } = await api.post("/settings/factory-reset", { confirmation, password });
      setResult(res);
      setOpen(false);
      setConfirmation("");
      setPassword("");
      toast.success("Factory reset selesai. Aplikasi kembali ke kondisi bersih.");
      qc.clear();
      await refetch();
      await reload();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  if (isLoading) return <LoadingRows rows={3} />;

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border bg-card p-6 card-soft">
        <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Informasi Sistem</p>
        <div className="mt-5 grid grid-cols-2 gap-5 text-sm sm:grid-cols-3">
          <div>
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Superadmin Utama</p>
            <p className="font-medium">{data?.keeper?.full_name}</p>
            <p className="num text-xs text-muted-foreground">{data?.keeper?.phone}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wider text-muted-foreground">Total Record Data</p>
            <p data-testid="reset-total-records" className="num font-heading text-xl font-semibold">{data?.total_records ?? 0}</p>
          </div>
          <div>
            <p className="text-xs uppercase tracking-wider text-muted-foreground">File di Object Storage</p>
            <p data-testid="reset-storage-objects" className="num font-heading text-xl font-semibold">
              {data?.storage_objects ?? "-"}
              {data?.storage_bytes ? ` · ${Math.round(data.storage_bytes / 1024)} KB` : ""}
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border-2 border-destructive/50 bg-destructive/5 p-6" data-testid="danger-zone">
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
          <div>
            <p className="font-heading text-base font-semibold text-destructive">Danger Zone — Factory Reset / Clean Install</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Menghapus <strong>seluruh</strong> data aplikasi secara permanen dan mengembalikan pengaturan (nama aplikasi, logo,
              bunga, denda, Telegram) ke kondisi default. Hanya akun Superadmin utama yang dipertahankan.
              Tindakan ini <strong>tidak dapat dibatalkan</strong>.
            </p>
          </div>
        </div>

        <div className="mt-6 overflow-hidden rounded-xl border bg-card">
          <table className="w-full text-sm" data-testid="reset-preview-table">
            <tbody>
              {ROWS.map(([key, label]) => (
                <tr key={key} className="border-b last:border-0">
                  <td className="px-4 py-2.5 text-muted-foreground">{label}</td>
                  <td data-testid={`reset-count-${key}`} className="num px-4 py-2.5 text-right font-semibold">{data?.[key] ?? 0}</td>
                </tr>
              ))}
              <tr className="bg-destructive/10">
                <td className="px-4 py-2.5 font-medium">File bukti di Object Storage (dihapus fisik)</td>
                <td className="num px-4 py-2.5 text-right font-semibold">{data?.storage_objects ?? "-"}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <Button
          data-testid="open-factory-reset-btn"
          variant="destructive"
          className="mt-6 rounded-full"
          onClick={() => {
            refetch();
            setOpen(true);
          }}
        >
          <Trash2 className="mr-2 h-4 w-4" /> Factory Reset Sekarang
        </Button>
      </section>

      {result && (
        <section className="rounded-2xl border bg-card p-6 card-soft" data-testid="reset-result">
          <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Hasil Factory Reset</p>
          <p className="mt-3 text-sm">
            Status: <span className={result.status === "SUCCESS" ? "font-semibold text-emerald-600" : "font-semibold text-amber-600"}>{result.status}</span>
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Objek storage dihapus: {result.storage?.purged ?? 0} · gagal: {result.storage?.failed ?? 0}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">Superadmin dipertahankan: {result.kept_superadmin?.full_name} ({result.kept_superadmin?.phone})</p>
        </section>
      )}

      <Dialog open={open} onOpenChange={(v) => !busy && setOpen(v)}>
        <DialogContent data-testid="factory-reset-dialog" className="max-h-[92vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-heading text-destructive">Konfirmasi Factory Reset</DialogTitle>
            <DialogDescription>
              Anda akan menghapus permanen {data?.total_records ?? 0} record dan {data?.storage_objects ?? 0} file bukti.
              Tindakan ini <strong>irreversible</strong> — data tidak dapat dipulihkan.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Ketik persis: <span className="font-semibold">HAPUS SEMUA DATA</span></Label>
              <Input
                data-testid="factory-reset-confirmation-input"
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
                placeholder="HAPUS SEMUA DATA"
                className="h-11 rounded-xl"
                autoComplete="off"
              />
            </div>
            <div className="space-y-2">
              <Label>Password Superadmin ({user?.phone})</Label>
              <Input
                data-testid="factory-reset-password-input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-11 rounded-xl"
                autoComplete="current-password"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>Batal</Button>
            <Button data-testid="factory-reset-submit-btn" variant="destructive" disabled={!canSubmit} onClick={submit}>
              {busy ? "Menghapus semua data..." : "HAPUS SEMUA DATA PERMANEN"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
