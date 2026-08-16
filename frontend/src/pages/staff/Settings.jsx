import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useSettings } from "@/context/SettingsContext";
import { useAuth } from "@/context/AuthContext";
import { PageHeader, LoadingRows, EmptyState } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { formatDateTime } from "@/lib/format";
import DangerZone from "@/pages/staff/DangerZone";
import { AlertTriangle } from "lucide-react";

export default function Settings() {
  const { reload } = useSettings();
  const { user } = useAuth();
  const isSuper = user?.role === "superadmin";
  const [busy, setBusy] = useState(null);
  const { data, isLoading, refetch } = useQuery({ queryKey: ["settings"], queryFn: async () => (await api.get("/settings")).data });
  const { data: notif } = useQuery({ queryKey: ["notif-log"], queryFn: async () => (await api.get("/notifications", { params: { page_size: 20 } })).data });

  const [general, setGeneral] = useState({ app_name: "", app_description: "" });
  const [loan, setLoan] = useState({ interest_rate: "", late_fee_rate_per_day: "" });
  const [tg, setTg] = useState({ telegram_reg_enabled: false, telegram_loan_enabled: false, telegram_reg_token: "", telegram_loan_token: "" });

  useEffect(() => {
    if (data) {
      setGeneral({ app_name: data.app_name || "", app_description: data.app_description || "" });
      setLoan({ interest_rate: String(data.interest_rate ?? ""), late_fee_rate_per_day: String(data.late_fee_rate_per_day ?? "") });
      setTg((t) => ({ ...t, telegram_reg_enabled: !!data.telegram_reg_enabled, telegram_loan_enabled: !!data.telegram_loan_enabled }));
    }
  }, [data]);

  const run = async (key, fn, msg) => {
    setBusy(key);
    try {
      await fn();
      toast.success(msg);
      await refetch();
      await reload();
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setBusy(null);
    }
  };

  const uploadBranding = async (kind, file) => {
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    await run(kind, () => api.post(`/settings/logo?kind=${kind}`, fd), `${kind === "logo" ? "Logo" : "Favicon"} diperbarui`);
  };

  if (isLoading) return <LoadingRows rows={4} />;

  return (
    <div>
      <PageHeader title="Pengaturan" description="Branding aplikasi, parameter pinjaman, dan integrasi Telegram." />
      <Tabs defaultValue="umum">
        <TabsList className="mb-6">
          <TabsTrigger value="umum" data-testid="settings-tab-general">Umum</TabsTrigger>
          <TabsTrigger value="pinjaman" data-testid="settings-tab-loan">Pinjaman</TabsTrigger>
          <TabsTrigger value="telegram" data-testid="settings-tab-telegram">Telegram</TabsTrigger>
          {isSuper && <TabsTrigger value="sistem" data-testid="settings-tab-system">Sistem</TabsTrigger>}
        </TabsList>

        <TabsContent value="umum">
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-2xl border bg-card p-6 card-soft">
              <p className="mb-5 font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Identitas Aplikasi</p>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>Nama Aplikasi</Label>
                  <Input data-testid="app-name-input" value={general.app_name} onChange={(e) => setGeneral((g) => ({ ...g, app_name: e.target.value }))} className="h-11 rounded-xl" />
                </div>
                <div className="space-y-2">
                  <Label>Deskripsi Singkat</Label>
                  <Textarea data-testid="app-description-input" value={general.app_description} onChange={(e) => setGeneral((g) => ({ ...g, app_description: e.target.value }))} rows={2} />
                </div>
                <Button
                  data-testid="save-general-btn"
                  className="rounded-full"
                  disabled={busy === "general"}
                  onClick={() => run("general", () => api.put("/settings/general", general), "Pengaturan umum disimpan")}
                >
                  {busy === "general" ? "Menyimpan..." : "Simpan"}
                </Button>
              </div>
            </section>
            <section className="rounded-2xl border bg-card p-6 card-soft">
              <p className="mb-5 font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Logo & Icon</p>
              <div className="space-y-5">
                <div className="space-y-2">
                  <Label>Logo Aplikasi</Label>
                  {data?.logo_url && <img src={`${process.env.REACT_APP_BACKEND_URL}${data.logo_url}`} alt="logo" className="h-16 w-16 rounded-xl border object-cover" />}
                  <Input data-testid="logo-upload-input" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => uploadBranding("logo", e.target.files?.[0])} className="h-11 rounded-xl" />
                </div>
                <div className="space-y-2">
                  <Label>Favicon / Icon</Label>
                  {data?.favicon_url && <img src={`${process.env.REACT_APP_BACKEND_URL}${data.favicon_url}`} alt="favicon" className="h-10 w-10 rounded-lg border object-cover" />}
                  <Input data-testid="favicon-upload-input" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => uploadBranding("favicon", e.target.files?.[0])} className="h-11 rounded-xl" />
                </div>
              </div>
            </section>
          </div>
        </TabsContent>

        <TabsContent value="pinjaman">
          <section className="max-w-xl rounded-2xl border bg-card p-6 card-soft">
            <p className="mb-5 font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Parameter Pinjaman</p>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>Bunga Pinjaman (%)</Label>
                <Input data-testid="interest-rate-input" inputMode="decimal" value={loan.interest_rate} onChange={(e) => setLoan((l) => ({ ...l, interest_rate: e.target.value }))} className="h-11 rounded-xl num" />
              </div>
              <div className="space-y-2">
                <Label>Denda Keterlambatan (% / Hari)</Label>
                <Input data-testid="late-fee-input" inputMode="decimal" value={loan.late_fee_rate_per_day} onChange={(e) => setLoan((l) => ({ ...l, late_fee_rate_per_day: e.target.value }))} className="h-11 rounded-xl num" />
              </div>
              <div className="flex gap-3 rounded-xl bg-amber-50 p-4 dark:bg-amber-500/10">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                <p className="text-xs text-muted-foreground">
                  Perubahan hanya berlaku untuk pinjaman baru. Pinjaman yang sudah dibuat menggunakan snapshot bunga dan denda saat pengajuan.
                </p>
              </div>
              <Button
                data-testid="save-loan-settings-btn"
                className="rounded-full"
                disabled={busy === "loan"}
                onClick={() =>
                  run("loan", () => api.put("/settings/loan", { interest_rate: Number(loan.interest_rate), late_fee_rate_per_day: Number(loan.late_fee_rate_per_day) }), "Pengaturan pinjaman disimpan")
                }
              >
                {busy === "loan" ? "Menyimpan..." : "Simpan"}
              </Button>
            </div>
          </section>
        </TabsContent>

        <TabsContent value="telegram">
          <div className="grid gap-6 lg:grid-cols-2">
            {[
              { key: "reg", title: "Bot 1 — Registrasi Pengguna", enabledKey: "telegram_reg_enabled", tokenKey: "telegram_reg_token", masked: data?.telegram_reg_token_masked, desc: "Notifikasi Peminjam baru & event akun." },
              { key: "loan", title: "Bot 2 — Pinjaman", enabledKey: "telegram_loan_enabled", tokenKey: "telegram_loan_token", masked: data?.telegram_loan_token_masked, desc: "Pengajuan, approval, pendanaan, pencairan, pembayaran, overdue." },
            ].map((bot) => (
              <section key={bot.key} className="rounded-2xl border bg-card p-6 card-soft">
                <p className="font-heading text-sm font-semibold">{bot.title}</p>
                <p className="mt-1 text-xs text-muted-foreground">{bot.desc}</p>
                <div className="mt-5 space-y-4">
                  <div className="flex items-center justify-between rounded-xl border p-4">
                    <p className="text-sm font-medium">Aktifkan Notifikasi</p>
                    <Switch
                      data-testid={`telegram-${bot.key}-switch`}
                      checked={tg[bot.enabledKey]}
                      onCheckedChange={(v) => setTg((t) => ({ ...t, [bot.enabledKey]: v }))}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Bot Token {bot.masked ? `(tersimpan: ${bot.masked})` : ""}</Label>
                    <Input
                      data-testid={`telegram-${bot.key}-token-input`}
                      type="password"
                      placeholder={bot.masked ? "Biarkan kosong untuk tidak mengubah" : "123456:ABC-DEF..."}
                      value={tg[bot.tokenKey]}
                      onChange={(e) => setTg((t) => ({ ...t, [bot.tokenKey]: e.target.value }))}
                      className="h-11 rounded-xl"
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      data-testid={`save-telegram-btn-${bot.key}`}
                      className="rounded-full"
                      disabled={busy === "tg"}
                      onClick={() => run("tg", () => api.put("/settings/telegram", tg), "Pengaturan Telegram disimpan")}
                    >
                      {busy === "tg" ? "Menyimpan..." : "Simpan"}
                    </Button>
                    <Button
                      data-testid={`test-telegram-btn-${bot.key}`}
                      variant="outline"
                      className="rounded-full"
                      disabled={busy === `test-${bot.key}`}
                      onClick={() =>
                        run(`test-${bot.key}`, async () => {
                          const { data: res } = await api.post("/settings/telegram/test", { bot: bot.key });
                          toast.success(res.message);
                        }, "Tes terkirim")
                      }
                    >
                      Test Bot {bot.key === "reg" ? "Registrasi" : "Pinjaman"}
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Tes dikirim ke Telegram Chat ID pada profil Anda. Token hanya diproses di server dan tidak pernah ditampilkan penuh.
                  </p>
                </div>
              </section>
            ))}
          </div>

          <section className="mt-6 rounded-2xl border bg-card p-6 card-soft">
            <p className="mb-5 font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Log Notifikasi Terakhir</p>
            {notif?.items?.length ? (
              <div className="space-y-2" data-testid="notification-log">
                {notif.items.map((n) => (
                  <div key={n.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border px-4 py-3 text-xs">
                    <span className="font-medium">{n.notification_type}</span>
                    <span className="text-muted-foreground">{n.recipient}</span>
                    <span className={n.status === "SENT" ? "text-emerald-600" : n.status === "FAILED" ? "text-destructive" : "text-muted-foreground"}>
                      {n.status}{n.error_message ? ` · ${n.error_message}` : ""}
                    </span>
                    <span className="text-muted-foreground">{formatDateTime(n.sent_at)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState testId="empty-notif-log" title="Belum ada notifikasi terkirim" />
            )}
          </section>
        </TabsContent>

        <TabsContent value="sistem">
          {isSuper && <DangerZone />}
        </TabsContent>
      </Tabs>
    </div>
  );
}
