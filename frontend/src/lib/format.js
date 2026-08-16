export const rupiah = (n) => {
  const v = Number(n || 0);
  return "Rp" + Math.round(v).toLocaleString("id-ID");
};

export const rupiahShort = (n) => {
  const v = Number(n || 0);
  if (v >= 1_000_000_000) return "Rp" + (v / 1_000_000_000).toFixed(1).replace(".", ",") + " M";
  if (v >= 1_000_000) return "Rp" + (v / 1_000_000).toFixed(1).replace(".", ",") + " jt";
  if (v >= 1_000) return "Rp" + Math.round(v / 1_000) + " rb";
  return rupiah(v);
};

export const onlyDigits = (s) => String(s || "").replace(/\D/g, "");

export const formatThousand = (s) => {
  const d = onlyDigits(s);
  return d ? Number(d).toLocaleString("id-ID") : "";
};

const MONTHS = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember",
];

const toDate = (v) => {
  if (!v) return null;
  const d = new Date(v);
  return isNaN(d.getTime()) ? null : d;
};

export const formatDate = (v) => {
  const d = toDate(v);
  if (!d) return "-";
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
};

export const formatDateTime = (v) => {
  const d = toDate(v);
  if (!d) return "-";
  return `${formatDate(v)} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

export const formatShortDateTime = (v) => {
  const d = toDate(v);
  if (!d) return "-";
  return `${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)} ${String(d.getHours()).padStart(2, "0")}:${String(
    d.getMinutes()
  ).padStart(2, "0")}`;
};

export const maskNik = (nik) => (nik && nik.length >= 8 ? `${nik.slice(0, 4)}********${nik.slice(-4)}` : nik || "-");
