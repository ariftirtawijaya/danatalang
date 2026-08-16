import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { useSettings } from "@/context/SettingsContext";
import { errMsg } from "@/lib/api";
import { onlyDigits } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ArrowLeft } from "lucide-react";

const initial = {
  nik: "",
  full_name: "",
  birth_date: "",
  phone: "",
  email: "",
  password: "",
  confirm_password: "",
  bank_name: "BCA",
  account_number: "",
  account_holder: "",
};

export default function Register() {
  const { register } = useAuth();
  const { settings } = useSettings();
  const navigate = useNavigate();
  const [form, setForm] = useState(initial);
  const [loading, setLoading] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (loading) return;
    if (form.nik.length !== 16) return toast.error("NIK harus 16 digit");
    if (form.password !== form.confirm_password) return toast.error("Konfirmasi password tidak sama");
    if (form.password.length < 8) return toast.error("Password minimal 8 karakter");
    setLoading(true);
    try {
      await register(form);
      toast.success("Registrasi berhasil. Akun Anda menunggu verifikasi Admin.");
      navigate("/dashboard", { replace: true });
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background px-5 py-10 sm:px-8">
      <div className="mx-auto w-full max-w-2xl animate-rise">
        <Link to="/login" data-testid="back-to-login-link" className="mb-8 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" /> Kembali ke Masuk
        </Link>
        <h1 className="font-heading text-3xl font-semibold sm:text-4xl">Daftar sebagai Peminjam</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Lengkapi data berikut. Akun akan aktif setelah diverifikasi Admin {settings?.app_name || ""}.
        </p>

        <form onSubmit={submit} data-testid="register-form" className="mt-9 space-y-8">
          <section className="space-y-5 rounded-2xl border bg-card p-6 card-soft">
            <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Data Diri</p>
            <div className="grid gap-5 sm:grid-cols-2">
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="full_name">Nama Lengkap</Label>
                <Input id="full_name" data-testid="reg-name-input" value={form.full_name} onChange={set("full_name")} required className="h-11 rounded-xl" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="nik">NIK (16 digit)</Label>
                <Input
                  id="nik"
                  data-testid="reg-nik-input"
                  inputMode="numeric"
                  maxLength={16}
                  value={form.nik}
                  onChange={(e) => setForm((f) => ({ ...f, nik: onlyDigits(e.target.value).slice(0, 16) }))}
                  required
                  className="h-11 rounded-xl num"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="birth_date">Tanggal Lahir</Label>
                <Input id="birth_date" data-testid="reg-birthdate-input" type="date" value={form.birth_date} onChange={set("birth_date")} required className="h-11 rounded-xl" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="phone">Nomor HP</Label>
                <Input
                  id="phone"
                  data-testid="reg-phone-input"
                  inputMode="numeric"
                  placeholder="08xxxxxxxxxx"
                  value={form.phone}
                  onChange={(e) => setForm((f) => ({ ...f, phone: onlyDigits(e.target.value) }))}
                  required
                  className="h-11 rounded-xl num"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" data-testid="reg-email-input" type="email" value={form.email} onChange={set("email")} required className="h-11 rounded-xl" />
              </div>
            </div>
          </section>

          <section className="space-y-5 rounded-2xl border bg-card p-6 card-soft">
            <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Rekening Pencairan</p>
            <div className="grid gap-5 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>Jenis Rekening</Label>
                <Select value={form.bank_name} onValueChange={(v) => setForm((f) => ({ ...f, bank_name: v }))}>
                  <SelectTrigger data-testid="reg-bank-select" className="h-11 rounded-xl">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="BCA">BCA</SelectItem>
                    <SelectItem value="GoPay">GoPay</SelectItem>
                    <SelectItem value="DANA">DANA</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="account_number">Nomor Rekening / E-Wallet</Label>
                <Input
                  id="account_number"
                  data-testid="reg-account-number-input"
                  inputMode="numeric"
                  value={form.account_number}
                  onChange={(e) => setForm((f) => ({ ...f, account_number: onlyDigits(e.target.value) }))}
                  required
                  className="h-11 rounded-xl num"
                />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="account_holder">Nama Pemilik Rekening</Label>
                <Input id="account_holder" data-testid="reg-account-holder-input" value={form.account_holder} onChange={set("account_holder")} required className="h-11 rounded-xl" />
              </div>
            </div>
          </section>

          <section className="space-y-5 rounded-2xl border bg-card p-6 card-soft">
            <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Keamanan</p>
            <div className="grid gap-5 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="password">Password (min. 8 karakter)</Label>
                <Input id="password" data-testid="reg-password-input" type="password" value={form.password} onChange={set("password")} required className="h-11 rounded-xl" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirm_password">Konfirmasi Password</Label>
                <Input id="confirm_password" data-testid="reg-confirm-password-input" type="password" value={form.confirm_password} onChange={set("confirm_password")} required className="h-11 rounded-xl" />
              </div>
            </div>
          </section>

          <Button data-testid="register-submit-btn" type="submit" disabled={loading} className="h-12 w-full rounded-full text-sm font-semibold">
            {loading ? "Mendaftar..." : "Daftar Sekarang"}
          </Button>
        </form>
      </div>
    </div>
  );
}
