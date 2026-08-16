import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatDateTime, onlyDigits } from "@/lib/format";
import { PageHeader, EmptyState, LoadingRows, StatusBadge } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Search, UserPlus } from "lucide-react";

const emptyForm = {
  full_name: "", phone: "", email: "", password: "", telegram_chat_id: "",
  notify_telegram: true, bank_name: "", account_number: "", account_holder: "", is_active: true,
};

export default function Users() {
  const [params, setParams] = useSearchParams();
  const role = params.get("role") || "admin";
  const { user } = useAuth();
  const isSuper = user?.role === "superadmin";
  const [q, setQ] = useState("");
  const [dialog, setDialog] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [editing, setEditing] = useState(null);
  const [busy, setBusy] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["users", role, q],
    queryFn: async () => (await api.get("/users", { params: { role, q: q || undefined, page_size: 50 } })).data,
  });

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setBusy(true);
    try {
      if (editing) {
        const payload = {
          full_name: form.full_name, phone: form.phone, email: form.email,
          telegram_chat_id: form.telegram_chat_id, notify_telegram: form.notify_telegram,
          is_active: form.is_active,
        };
        if (role === "lender") {
          payload.bank_name = form.bank_name;
          payload.account_number = form.account_number;
          payload.account_holder = form.account_holder;
        }
        if (form.password) payload.new_password = form.password;
        await api.put(`/users/${editing.id}`, payload);
        toast.success("Data pengguna diperbarui");
      } else {
        await api.post("/users", { ...form, role });
        toast.success(`${role === "admin" ? "Admin" : "Pendana"} berhasil dibuat`);
      }
      setDialog(null);
      setEditing(null);
      setForm(emptyForm);
      await refetch();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (u) => {
    try {
      await api.put(`/users/${u.id}`, { is_active: !u.is_active });
      toast.success(u.is_active ? "Pengguna dinonaktifkan" : "Pengguna diaktifkan");
      refetch();
    } catch (err) {
      toast.error(errMsg(err));
    }
  };

  const title = role === "admin" ? "Admin" : role === "lender" ? "Pendana" : "Pengguna";

  return (
    <div>
      <PageHeader title={title} description={role === "lender" ? "Pendana dibuat oleh Superadmin. Tidak tersedia registrasi publik." : "Kelola akun staf aplikasi."}>
        <div className="flex gap-2">
          {isSuper && (
            <>
              <Button variant={role === "admin" ? "default" : "outline"} className="rounded-full" onClick={() => setParams({ role: "admin" })} data-testid="tab-admin-users">Admin</Button>
              <Button variant={role === "lender" ? "default" : "outline"} className="rounded-full" onClick={() => setParams({ role: "lender" })} data-testid="tab-lender-users">Pendana</Button>
            </>
          )}
          {isSuper && (
            <Button
              className="rounded-full"
              data-testid="create-user-btn"
              onClick={() => {
                setEditing(null);
                setForm(emptyForm);
                setDialog("form");
              }}
            >
              <UserPlus className="mr-2 h-4 w-4" /> Tambah {title}
            </Button>
          )}
        </div>
      </PageHeader>

      <div className="relative mb-6">
        <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input data-testid="user-search-input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari nama, email, No HP" className="h-11 rounded-xl pl-10" />
      </div>

      {isLoading ? (
        <LoadingRows />
      ) : data?.items?.length ? (
        <div className="overflow-x-auto rounded-2xl border bg-card">
          <Table data-testid="users-table">
            <TableHeader>
              <TableRow>
                <TableHead>Nama</TableHead>
                <TableHead>No HP</TableHead>
                <TableHead>Email</TableHead>
                <TableHead>Role</TableHead>
                {role === "lender" && <TableHead>Rekening</TableHead>}
                <TableHead>Telegram</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Login Terakhir</TableHead>
                {isSuper && <TableHead className="text-right">Aksi</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((u) => (
                <TableRow key={u.id}>
                  <TableCell className="font-medium">{u.full_name}</TableCell>
                  <TableCell className="num text-xs">{u.phone}</TableCell>
                  <TableCell className="text-xs">{u.email}</TableCell>
                  <TableCell className="text-xs uppercase">{u.role}</TableCell>
                  {role === "lender" && (
                    <TableCell className="text-xs">
                      {u.bank_name ? `${u.bank_name} · ${u.account_number}` : "-"}
                    </TableCell>
                  )}
                  <TableCell className="text-xs">{u.has_telegram ? "Terhubung" : "-"}</TableCell>
                  <TableCell>
                    <StatusBadge value={u.is_active ? "ACTIVE" : "SUSPENDED"} map="account" />
                  </TableCell>
                  <TableCell className="text-xs">{u.last_login_at ? formatDateTime(u.last_login_at) : "-"}</TableCell>
                  {isSuper && (
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          className="rounded-full"
                          data-testid={`edit-user-${u.id}`}
                          onClick={() => {
                            setEditing(u);
                            setForm({
                              ...emptyForm, ...u, password: "",
                              telegram_chat_id: u.telegram_chat_id || "",
                              bank_name: u.bank_name || "", account_number: "", account_holder: u.account_holder || "",
                            });
                            setDialog("form");
                          }}
                        >
                          Edit
                        </Button>
                        <Button size="sm" variant="ghost" className="rounded-full" data-testid={`toggle-user-${u.id}`} onClick={() => toggleActive(u)}>
                          {u.is_active ? "Nonaktifkan" : "Aktifkan"}
                        </Button>
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <EmptyState testId="empty-users" title={`Belum ada ${title}`} description={isSuper ? `Tambahkan ${title} baru untuk mulai.` : ""} />
      )}

      <Dialog open={dialog === "form"} onOpenChange={() => setDialog(null)}>
        <DialogContent data-testid="user-form-dialog" className="max-h-[92vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-heading">{editing ? `Edit ${title}` : `Tambah ${title}`}</DialogTitle>
            <DialogDescription>
              {role === "lender" ? "Data rekening digunakan Peminjam untuk melakukan pembayaran." : "Admin dapat memverifikasi Peminjam dan pengajuan pinjaman."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Nama Lengkap</Label>
              <Input data-testid="user-name-input" value={form.full_name} onChange={set("full_name")} className="h-11 rounded-xl" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Nomor HP</Label>
                <Input data-testid="user-phone-input" value={form.phone} onChange={(e) => setForm((f) => ({ ...f, phone: onlyDigits(e.target.value) }))} className="h-11 rounded-xl num" />
              </div>
              <div className="space-y-2">
                <Label>Email</Label>
                <Input data-testid="user-email-input" type="email" value={form.email} onChange={set("email")} className="h-11 rounded-xl" />
              </div>
            </div>
            <div className="space-y-2">
              <Label>{editing ? "Password Baru (opsional)" : "Password (min. 8 karakter)"}</Label>
              <Input data-testid="user-password-input" type="password" value={form.password} onChange={set("password")} className="h-11 rounded-xl" />
            </div>
            {role === "lender" && (
              <div className="grid gap-4 sm:grid-cols-3">
                <div className="space-y-2">
                  <Label>Nama Bank</Label>
                  <Input data-testid="user-bank-input" value={form.bank_name} onChange={set("bank_name")} className="h-11 rounded-xl" />
                </div>
                <div className="space-y-2">
                  <Label>Nomor Rekening</Label>
                  <Input data-testid="user-account-input" value={form.account_number} onChange={(e) => setForm((f) => ({ ...f, account_number: onlyDigits(e.target.value) }))} className="h-11 rounded-xl num" />
                </div>
                <div className="space-y-2">
                  <Label>Nama Pemilik</Label>
                  <Input data-testid="user-holder-input" value={form.account_holder} onChange={set("account_holder")} className="h-11 rounded-xl" />
                </div>
              </div>
            )}
            <div className="space-y-2">
              <Label>Telegram Chat ID</Label>
              <Input data-testid="user-telegram-input" value={form.telegram_chat_id} onChange={(e) => setForm((f) => ({ ...f, telegram_chat_id: e.target.value }))} placeholder="misal 123456789" className="h-11 rounded-xl num" />
            </div>
            <div className="flex items-center justify-between rounded-xl border p-4">
              <div>
                <p className="text-sm font-medium">Terima Notifikasi Telegram</p>
                <p className="text-xs text-muted-foreground">Kirim notifikasi event penting ke Chat ID di atas.</p>
              </div>
              <Switch data-testid="user-notify-switch" checked={form.notify_telegram} onCheckedChange={(v) => setForm((f) => ({ ...f, notify_telegram: v }))} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialog(null)} disabled={busy}>Batal</Button>
            <Button data-testid="user-save-btn" onClick={save} disabled={busy || !form.full_name || !form.phone || !form.email || (!editing && form.password.length < 8)}>
              {busy ? "Menyimpan..." : "Simpan"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
