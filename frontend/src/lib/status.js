export const LOAN_STATUS = {
  WAITING_ADMIN_APPROVAL: { label: "Menunggu Approval", tone: "pending" },
  REJECTED: { label: "Ditolak", tone: "rejected" },
  WAITING_FUNDING: { label: "Menunggu Pendanaan", tone: "pending" },
  FUNDING_CLAIMED: { label: "Menunggu Pencairan", tone: "pending" },
  WAITING_DISBURSEMENT_CONFIRMATION: { label: "Konfirmasi Pencairan", tone: "pending" },
  ACTIVE: { label: "Aktif", tone: "active" },
  OVERDUE: { label: "Terlambat", tone: "warning" },
  WAITING_PAYMENT_VERIFICATION: { label: "Verifikasi Pembayaran", tone: "pending" },
  PAID: { label: "Lunas", tone: "success" },
  CANCELLED: { label: "Dibatalkan", tone: "rejected" },
};

export const ACCOUNT_STATUS = {
  WAITING_VERIFICATION: { label: "Menunggu Verifikasi", tone: "pending" },
  ACTIVE: { label: "Aktif", tone: "success" },
  REJECTED: { label: "Ditolak", tone: "rejected" },
  SUSPENDED: { label: "Ditangguhkan", tone: "warning" },
  BLOCKED: { label: "Diblokir", tone: "rejected" },
};

export const PAYMENT_STATUS = {
  PENDING: { label: "Menunggu Verifikasi", tone: "pending" },
  VERIFIED: { label: "Diterima", tone: "success" },
  REJECTED: { label: "Ditolak", tone: "rejected" },
};

export const TONE_CLASS = {
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  active: "bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-300",
  success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
  warning: "bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300",
};
