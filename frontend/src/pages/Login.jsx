import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { useSettings } from "@/context/SettingsContext";
import { errMsg } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ArrowRight, ShieldCheck } from "lucide-react";

const HERO =
  "https://images.unsplash.com/photo-1498262257252-c282316270bc?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDQ2MzR8MHwxfHNlYXJjaHwyfHxhYnN0cmFjdCUyMGFyY2hpdGVjdHVyZSUyMG1pbmltYWx8ZW58MHx8fHwxNzg2ODUyNDk1fDA&ixlib=rb-4.1.0&q=85";

export default function Login() {
  const { login } = useAuth();
  const { settings } = useSettings();
  const navigate = useNavigate();
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    try {
      await login(phone, password);
      toast.success("Berhasil masuk");
      navigate("/dashboard", { replace: true });
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <div className="flex flex-col justify-center px-6 py-14 sm:px-12 lg:px-20">
        <div className="animate-rise w-full max-w-md">
          <div className="mb-10 flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-primary font-heading text-base font-bold text-primary-foreground">
              {(settings?.app_name || "P").slice(0, 1)}
            </span>
            <div>
              <p className="font-heading text-lg font-semibold leading-tight">{settings?.app_name || "PinjamKu"}</p>
              <p className="text-xs text-muted-foreground">{settings?.app_description || "Sistem Manajemen Pinjaman"}</p>
            </div>
          </div>

          <h1 className="font-heading text-4xl font-semibold sm:text-5xl">Masuk</h1>
          <p className="mt-2 text-sm text-muted-foreground">Gunakan nomor HP dan password akun Anda.</p>

          <form onSubmit={submit} className="mt-9 space-y-5" data-testid="login-form">
            <div className="space-y-2">
              <Label htmlFor="phone">Nomor HP</Label>
              <Input
                id="phone"
                data-testid="login-phone-input"
                inputMode="numeric"
                placeholder="08xxxxxxxxxx"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                required
                className="h-12 rounded-xl"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                data-testid="login-password-input"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="h-12 rounded-xl"
              />
            </div>
            <Button
              data-testid="login-submit-btn"
              type="submit"
              disabled={loading}
              className="h-12 w-full rounded-full text-sm font-semibold transition-transform active:scale-[0.98]"
            >
              {loading ? "Memproses..." : "Masuk"}
              {!loading && <ArrowRight className="ml-2 h-4 w-4" />}
            </Button>
          </form>

          <p className="mt-8 text-sm text-muted-foreground">
            Belum punya akun?{" "}
            <Link data-testid="goto-register-link" to="/register" className="font-semibold text-primary underline underline-offset-4">
              Daftar sebagai Peminjam
            </Link>
          </p>
          <p className="mt-10 flex items-center gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="h-4 w-4" /> Data Anda dilindungi & seluruh aktivitas tercatat.
          </p>
        </div>
      </div>
      <div className="relative hidden lg:block">
        <img src={HERO} alt="" className="absolute inset-0 h-full w-full object-cover" />
        <div className="absolute inset-0 bg-ink/85" />
        <div className="relative flex h-full flex-col justify-end p-14 text-primary-foreground">
          <p className="max-w-sm font-heading text-3xl font-semibold leading-tight">
            Kelola pinjaman, pendanaan, dan pelunasan dalam satu alur yang rapi.
          </p>
          <p className="mt-4 max-w-sm text-sm text-primary-foreground/70">
            Verifikasi manual, snapshot bunga, denda harian, dan audit log lengkap.
          </p>
        </div>
      </div>
    </div>
  );
}
