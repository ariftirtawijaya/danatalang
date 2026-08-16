import { useState } from "react";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ShieldAlert, LogOut } from "lucide-react";

export default function ForcePassword() {
  const { user, refresh, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (next !== confirm) return toast.error("Konfirmasi password tidak sama");
    if (next.length < 8) return toast.error("Password minimal 8 karakter");
    setBusy(true);
    try {
      await api.put("/auth/password", { current_password: current, new_password: next });
      toast.success("Password baru berhasil dibuat");
      await refresh();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-background px-5 py-10">
      <div className="w-full max-w-md animate-rise" data-testid="force-password-page">
        <div className="mb-6 flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-amber-100 text-amber-700 dark:bg-amber-500/15">
            <ShieldAlert className="h-5 w-5" />
          </span>
          <div>
            <h1 className="font-heading text-2xl font-semibold">Buat Password Baru</h1>
            <p className="text-xs text-muted-foreground">{user?.full_name} · {user?.phone}</p>
          </div>
        </div>
        <p className="mb-7 rounded-xl bg-amber-50 px-4 py-3 text-sm text-muted-foreground dark:bg-amber-500/10">
          Password Anda baru saja direset oleh Admin. Masukkan password sementara yang Anda terima, lalu buat password baru
          milik Anda sendiri untuk melanjutkan.
        </p>
        <form onSubmit={submit} className="space-y-5" data-testid="force-password-form">
          <div className="space-y-2">
            <Label>Password Sementara</Label>
            <Input data-testid="force-current-input" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required className="h-12 rounded-xl" />
          </div>
          <div className="space-y-2">
            <Label>Password Baru (min. 8 karakter)</Label>
            <Input data-testid="force-new-input" type="password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} className="h-12 rounded-xl" />
          </div>
          <div className="space-y-2">
            <Label>Konfirmasi Password Baru</Label>
            <Input data-testid="force-confirm-input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required className="h-12 rounded-xl" />
          </div>
          <Button data-testid="force-submit-btn" type="submit" disabled={busy} className="h-12 w-full rounded-full text-sm font-semibold">
            {busy ? "Menyimpan..." : "Simpan & Lanjutkan"}
          </Button>
        </form>
        <Button data-testid="force-logout-btn" variant="ghost" className="mt-4 w-full rounded-full" onClick={logout}>
          <LogOut className="mr-2 h-4 w-4" /> Keluar
        </Button>
      </div>
    </div>
  );
}
