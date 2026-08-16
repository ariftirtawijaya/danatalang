import { useState } from "react";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, Field, StatusBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { rupiah, maskNik, formatDate } from "@/lib/format";

export default function Profile() {
  const { user, refresh } = useAuth();
  const [form, setForm] = useState({
    full_name: user?.full_name || "",
    email: user?.email || "",
    bank_name: user?.bank_name || "",
    account_number: user?.account_number || "",
    account_holder: user?.account_holder || "",
    telegram_chat_id: user?.telegram_chat_id || "",
  });
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [saving, setSaving] = useState(false);
  const [savingPw, setSavingPw] = useState(false);
  const isLender = user?.role === "lender";
  const isBorrower = user?.role === "borrower";

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { full_name: form.full_name, email: form.email };
      if (isLender) {
        payload.bank_name = form.bank_name;
        payload.account_number = form.account_number;
        payload.account_holder = form.account_holder;
      }
      if (!isBorrower) payload.telegram_chat_id = form.telegram_chat_id;
      await api.put("/auth/profile", payload);
      await refresh();
      toast.success("Profil diperbarui");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSaving(false);
    }
  };

  const changePassword = async (e) => {
    e.preventDefault();
    setSavingPw(true);
    try {
      await api.put("/auth/password", pw);
      setPw({ current_password: "", new_password: "" });
      toast.success("Password berhasil diubah");
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setSavingPw(false);
    }
  };

  return (
    <div>
      <PageHeader title="Profil" description="Kelola data akun dan keamanan Anda." />
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-2xl border bg-card p-6 card-soft">
          <div className="mb-5 flex items-center justify-between">
            <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Identitas</p>
            {isBorrower && <StatusBadge value={user?.account_status} map="account" />}
          </div>
          <div className="grid grid-cols-2 gap-5">
            <Field label="Nomor HP" value={user?.phone} mono />
            {isBorrower && <Field label="NIK" value={maskNik(user?.nik)} mono />}
            {isBorrower && <Field label="Tanggal Lahir" value={user?.birth_date ? formatDate(user.birth_date) : "-"} />}
            {isBorrower && <Field label="Limit" value={rupiah(user?.credit?.borrower_limit)} mono />}
            {isBorrower && <Field label="Limit Tersedia" value={rupiah(user?.credit?.available_limit)} mono />}
            {isBorrower && <Field label="Maks. Pinjaman Aktif" value={user?.max_active_loans} />}
          </div>
          {isBorrower && (
            <div className="mt-5 grid grid-cols-2 gap-5 border-t pt-5">
              <Field label="Jenis Rekening" value={user?.bank_name} />
              <Field label="Nomor Rekening" value={user?.account_number} mono />
              <Field label="Nama Rekening" value={user?.account_holder} />
            </div>
          )}
        </section>

        <section className="rounded-2xl border bg-card p-6 card-soft">
          <p className="mb-5 font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Ubah Data</p>
          <form onSubmit={save} className="space-y-4" data-testid="profile-form">
            <div className="space-y-2">
              <Label>Nama Lengkap</Label>
              <Input data-testid="profile-name-input" value={form.full_name} onChange={set("full_name")} className="h-11 rounded-xl" />
            </div>
            <div className="space-y-2">
              <Label>Email</Label>
              <Input data-testid="profile-email-input" type="email" value={form.email} onChange={set("email")} className="h-11 rounded-xl" />
            </div>
            {isLender && (
              <>
                <div className="space-y-2">
                  <Label>Nama Bank</Label>
                  <Input data-testid="profile-bank-input" value={form.bank_name} onChange={set("bank_name")} className="h-11 rounded-xl" />
                </div>
                <div className="space-y-2">
                  <Label>Nomor Rekening</Label>
                  <Input data-testid="profile-account-input" value={form.account_number} onChange={set("account_number")} className="h-11 rounded-xl num" />
                </div>
                <div className="space-y-2">
                  <Label>Nama Pemilik Rekening</Label>
                  <Input data-testid="profile-holder-input" value={form.account_holder} onChange={set("account_holder")} className="h-11 rounded-xl" />
                </div>
              </>
            )}
            {!isBorrower && (
              <div className="space-y-2">
                <Label>Telegram Chat ID</Label>
                <Input data-testid="profile-telegram-input" value={form.telegram_chat_id} onChange={set("telegram_chat_id")} placeholder="misal 123456789" className="h-11 rounded-xl num" />
              </div>
            )}
            <Button data-testid="profile-save-btn" type="submit" disabled={saving} className="h-11 w-full rounded-full">
              {saving ? "Menyimpan..." : "Simpan Perubahan"}
            </Button>
          </form>
        </section>

        <section className="rounded-2xl border bg-card p-6 card-soft lg:col-span-2">
          <p className="mb-5 font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Keamanan</p>
          <form onSubmit={changePassword} className="grid gap-4 sm:grid-cols-3 sm:items-end" data-testid="password-form">
            <div className="space-y-2">
              <Label>Password Saat Ini</Label>
              <Input data-testid="current-password-input" type="password" value={pw.current_password} onChange={(e) => setPw((p) => ({ ...p, current_password: e.target.value }))} className="h-11 rounded-xl" required />
            </div>
            <div className="space-y-2">
              <Label>Password Baru</Label>
              <Input data-testid="new-password-input" type="password" value={pw.new_password} onChange={(e) => setPw((p) => ({ ...p, new_password: e.target.value }))} className="h-11 rounded-xl" required minLength={8} />
            </div>
            <Button data-testid="change-password-btn" type="submit" disabled={savingPw} className="h-11 rounded-full">
              {savingPw ? "Menyimpan..." : "Ubah Password"}
            </Button>
          </form>
        </section>
      </div>
    </div>
  );
}
