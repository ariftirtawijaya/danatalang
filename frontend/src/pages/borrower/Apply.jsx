import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useSettings } from "@/context/SettingsContext";
import { rupiah, formatThousand, onlyDigits } from "@/lib/format";
import { PageHeader, ConfirmDialog } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";

export default function Apply() {
  const { user } = useAuth();
  const { settings } = useSettings();
  const navigate = useNavigate();
  const { data: credit } = useQuery({ queryKey: ["dashboard"], queryFn: async () => (await api.get("/dashboard")).data });
  const [amount, setAmount] = useState("");
  const [days, setDays] = useState(14);
  const [confirm, setConfirm] = useState(false);
  const [loading, setLoading] = useState(false);

  const principal = Number(onlyDigits(amount) || 0);
  const rate = Number(settings?.interest_rate || 0);
  const interest = Math.round((principal * rate) / 100);

  const maxDays = credit?.max_duration_days || 30;
  const available = credit?.available_limit || 0;

  const error = useMemo(() => {
    if (!principal) return null;
    if (principal > available) return `Nominal melebihi limit tersedia Anda (${rupiah(available)}).`;
    if (days > maxDays) return `Durasi maksimal Anda adalah ${maxDays} hari.`;
    if ((credit?.active_loans ?? 0) >= (credit?.max_active_loans ?? 0))
      return `Anda telah mencapai maksimal ${credit?.max_active_loans} pinjaman aktif.`;
    return null;
  }, [principal, available, days, maxDays, credit]);

  if (user?.account_status !== "ACTIVE") {
    return (
      <div className="rounded-2xl border border-dashed p-10 text-center" data-testid="apply-blocked">
        <p className="font-heading text-lg font-semibold">Belum dapat mengajukan pinjaman</p>
        <p className="mt-2 text-sm text-muted-foreground">Akun Anda sedang menunggu verifikasi Admin.</p>
      </div>
    );
  }

  const submit = async () => {
    setLoading(true);
    try {
      const { data } = await api.post("/loans", { principal_amount: principal, duration_days: days });
      toast.success(`Pengajuan ${data.loan_number} berhasil dikirim`);
      navigate(`/loans/${data.id}`, { replace: true });
    } catch (err) {
      toast.error(errMsg(err));
    } finally {
      setLoading(false);
      setConfirm(false);
    }
  };

  return (
    <div>
      <PageHeader title="Ajukan Pinjaman" description={`Limit tersedia Anda ${rupiah(available)} · durasi maksimal ${maxDays} hari`} />

      <div className="space-y-6">
        <div className="space-y-5 rounded-2xl border bg-card p-6 card-soft">
          <div className="space-y-2">
            <Label htmlFor="amount">Nominal Pinjaman</Label>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">Rp</span>
              <Input
                id="amount"
                data-testid="apply-amount-input"
                inputMode="numeric"
                value={formatThousand(amount)}
                onChange={(e) => setAmount(onlyDigits(e.target.value))}
                placeholder="0"
                className="h-14 rounded-xl pl-10 font-heading text-xl num"
              />
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {[500000, 1000000, 2000000, 5000000].filter((v) => v <= available).map((v) => (
                <button
                  key={v}
                  type="button"
                  data-testid={`quick-amount-${v}`}
                  onClick={() => setAmount(String(v))}
                  className="rounded-full border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
                >
                  {rupiah(v)}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <Label>Durasi Pinjaman</Label>
              <span className="font-heading text-sm font-semibold num">{days} hari</span>
            </div>
            <Slider
              data-testid="apply-duration-slider"
              value={[days]}
              min={1}
              max={maxDays}
              step={1}
              onValueChange={([v]) => setDays(v)}
            />
            <div className="flex justify-between text-[10px] uppercase tracking-widest text-muted-foreground">
              <span>1 hari</span>
              <span>{maxDays} hari</span>
            </div>
          </div>
        </div>

        <div className="rounded-2xl border bg-card p-6 card-soft" data-testid="loan-simulation">
          <p className="font-heading text-sm font-semibold uppercase tracking-widest text-muted-foreground">Simulasi</p>
          <dl className="mt-5 space-y-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Nominal Pinjaman</dt>
              <dd className="font-semibold num">{rupiah(principal)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Durasi</dt>
              <dd className="font-semibold num">{days} Hari</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Bunga</dt>
              <dd className="font-semibold num">{rate}%</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted-foreground">Nominal Bunga</dt>
              <dd className="font-semibold num">{rupiah(interest)}</dd>
            </div>
            <div className="mt-2 flex justify-between border-t pt-4">
              <dt className="font-heading font-semibold">Total Pengembalian</dt>
              <dd data-testid="simulation-total" className="font-heading text-lg font-semibold num">{rupiah(principal + interest)}</dd>
            </div>
          </dl>
          <p className="mt-4 text-xs text-muted-foreground">
            Denda keterlambatan {settings?.late_fee_rate_per_day}% per hari dari pokok apabila melewati jatuh tempo.
          </p>
        </div>

        {error && (
          <p data-testid="apply-error" className="rounded-xl bg-destructive/10 px-4 py-3 text-sm font-medium text-destructive">
            {error}
          </p>
        )}

        <Button
          data-testid="apply-submit-btn"
          disabled={!principal || !!error || loading}
          onClick={() => setConfirm(true)}
          className="h-12 w-full rounded-full text-sm font-semibold"
        >
          Ajukan Pinjaman
        </Button>
      </div>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        testId="apply-confirm-dialog"
        title="Ajukan pinjaman?"
        description={`Anda mengajukan ${rupiah(principal)} untuk ${days} hari dengan total pengembalian ${rupiah(
          principal + interest
        )}. Lanjutkan?`}
        confirmLabel="Ya, Ajukan"
        loading={loading}
        onConfirm={submit}
      />
    </div>
  );
}
