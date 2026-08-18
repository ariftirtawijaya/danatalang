export const LOAN_STATUS = {
  WAITING_ADMIN_APPROVAL: { label: "Menunggu Approval", tone: "pending" },
  REJECTED: { label: "Ditolak", tone: "rejected" },
  WAITING_FUNDING: { label: "Menunggu Pendanaan", tone: "pending" },
  FUNDING_CLAIMED: { label: "Menunggu Pencairan", tone: "pending" },
  WAITING_DISBURSEMENT_CONFIRMATION: { label: "Konfirmasi Pencairan", tone: "pending" },
  ACTIVE: { label: "Aktif", tone: "active" },
  OVERDUE: { label: "Terlambat", tone: "warning" },
  WAITING_PAYMENT_VERIFICATION: { label: "Verifikasi Pembayaran", tone: "pending" },
  PAYMENT_COLLECTED: { label: "Pembayaran Diterima Admin", tone: "active" },
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

export const statusLabel = (value) => {
  if (!value) return "-";
  return (LOAN_STATUS[value] || ACCOUNT_STATUS[value] || PAYMENT_STATUS[value] || {}).label || value;
};

export const ACTION_LABELS = {
  LOGIN: "Login",
  LOGOUT: "Logout",
  BORROWER_REGISTERED: "Registrasi Peminjam",
  BORROWER_VERIFIED: "Peminjam Disetujui",
  BORROWER_REJECTED: "Peminjam Ditolak",
  BORROWER_LIMITS_UPDATED: "Limit Peminjam Diubah",
  BORROWER_STATUS_CHANGED: "Status Peminjam Diubah",
  ADMIN_NOTE_ADDED: "Catatan Internal Ditambahkan",
  LOAN_SUBMITTED: "Pengajuan Pinjaman",
  LOAN_APPROVED: "Pengajuan Disetujui",
  LOAN_REJECTED: "Pengajuan Ditolak",
  FUNDING_CLAIMED: "Pendanaan Diambil",
  DISBURSEMENT_REPORTED: "Pencairan Dilaporkan",
  DISBURSEMENT_CONFIRMED: "Pencairan Dikonfirmasi",
  PAYMENT_SUBMITTED: "Pembayaran Dilaporkan",
  PAYMENT_VERIFIED: "Pembayaran Diverifikasi",
  PAYMENT_REJECTED: "Pembayaran Ditolak",
  SUPERADMIN_PAYMENT_OVERRIDE_VERIFY: "Override Superadmin — Ditandai Lunas",
  SUPERADMIN_PAYMENT_OVERRIDE_REJECT: "Override Superadmin — Pembayaran Ditolak",
  USER_CREATED: "Pengguna Dibuat",
  USER_UPDATED: "Pengguna Diperbarui",
  PROFILE_UPDATED: "Profil Diperbarui",
  PASSWORD_CHANGED: "Password Diubah",
  PASSWORD_RESET: "Password Direset",
  LOGIN_PHONE_CHANGED: "Nomor HP Login Diubah",
  SUPERADMIN_PASSWORD_RECOVERED: "Password Superadmin Dipulihkan",
  SETTINGS_GENERAL_UPDATED: "Pengaturan Umum Diubah",
  SETTINGS_BRANDING_UPDATED: "Logo/Icon Diubah",
  SETTINGS_LOAN_UPDATED: "Bunga & Denda Diubah",
  SETTINGS_TELEGRAM_UPDATED: "Pengaturan Telegram Diubah",
  PROFIT_SHARE_SETTINGS_UPDATED: "Persentase Bagi Hasil Diubah",
  SETTLEMENT_ACCOUNT_UPDATED: "Rekening Settlement Diubah",
  LOAN_PROFIT_SHARE_SNAPSHOTTED: "Snapshot Bagi Hasil Pinjaman",
  LOAN_ASSIGNED_ADMIN_CHANGED: "Admin Penanggung Jawab Diubah",
  PROFIT_DISTRIBUTION_CREATED: "Pembagian Hasil Dibuat",
  LENDER_SETTLEMENT_SUBMITTED: "Setoran Bagi Hasil Dilaporkan",
  LENDER_SETTLEMENT_VERIFIED: "Setoran Bagi Hasil Diverifikasi",
  LENDER_SETTLEMENT_REJECTED: "Setoran Bagi Hasil Ditolak",
  ADMIN_PAYOUT_MARKED_PAID: "Payout Admin Ditandai Dibayar",
  PROFIT_DISTRIBUTION_REVERSED: "Pembagian Hasil Dibatalkan",
  PROFIT_DISTRIBUTION_CORRECTED: "Koreksi Finansial Pembagian Hasil",
  ADMIN_COLLECTION_CREATED: "Pembayaran Diterima Admin",
  ADMIN_COLLECTION_REVERSED: "Penerimaan Admin Dibatalkan",
  ADMIN_REMITTANCE_PREPARED: "Setoran Bulk Disiapkan",
  ADMIN_REMITTANCE_SUBMITTED: "Bukti Setoran Dikirim",
  ADMIN_REMITTANCE_VERIFIED: "Setoran Admin Diverifikasi",
  ADMIN_REMITTANCE_REJECTED: "Setoran Admin Ditolak",
  SYSTEM_FACTORY_RESET: "Factory Reset Sistem",
};

export const actionLabel = (action) =>
  ACTION_LABELS[action] ||
  String(action || "-")
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

export const ENTITY_LABELS = {
  user: "Pengguna",
  loan: "Pinjaman",
  payment: "Pembayaran",
  profit_distribution: "Pembagian Hasil",
  admin_remittance: "Setoran Admin",
  settings: "Pengaturan",
  system: "Sistem",
};

export const entityLabel = (entity) => ENTITY_LABELS[entity] || entity || "-";

export const TONE_CLASS = {
  pending: "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300",
  active: "bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-300",
  success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300",
  warning: "bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-500/15 dark:text-slate-300",
};
