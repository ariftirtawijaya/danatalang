# PRD — PinjamKu (PWA Manajemen Pinjaman)

## Problem Statement (asli, ringkas)
Aplikasi web PWA manajemen pinjaman uang, berfungsi end-to-end (bukan mockup), 4 role: Superadmin, Admin, Peminjam, Pendana. Lifecycle: Registrasi → Verifikasi Peminjam + set limit → Pengajuan → Approval Admin → Funding claim Pendana → Pencairan manual + bukti → Konfirmasi Admin → ACTIVE → Overdue/denda → Lapor pembayaran + bukti → Verifikasi Pendana → PAID. Tanpa cicilan, tanpa partial payment, tanpa approval otomatis, tanpa transfer otomatis. Dua Telegram bot (Registrasi & Pinjaman), audit log, snapshot bunga/denda, PWA installable.

## Pilihan User
- Stack: React + FastAPI + MongoDB
- Login: **No HP + Password** (JWT, bcrypt, rate limit)
- Upload bukti: Emergent object storage
- Telegram: token diisi user nanti dari menu Pengaturan
- Seed: hanya Superadmin (dari environment variable)

## Arsitektur
- Backend: FastAPI (`server.py`, `core.py`, `auth_routes.py`, `loan_routes.py`, `admin_routes.py`, `loan_service.py`, `notif.py`, `storage.py`), semua route prefiks `/api`
- Frontend: React + Tailwind + shadcn/ui, react-query, recharts; pages per role di `src/pages/{borrower,lender,staff}`
- DB: MongoDB — users, loans, loan_status_histories, disbursements, payments, settings, audit_logs, notifications, admin_notes, files, counters, login_attempts
- Uang disimpan sebagai integer rupiah (tanpa float)
- Financial calc terpusat di `loan_service.py` (backend = source of truth)

## Persona
- **Superadmin**: akses penuh, kelola Admin/Pendana, pengaturan bunga/denda/branding/Telegram, audit log, laporan
- **Admin**: verifikasi Peminjam + set limit, approve/reject pengajuan, konfirmasi pencairan, monitoring pembayaran (TIDAK boleh verifikasi pembayaran)
- **Peminjam**: registrasi mandiri, ajukan pinjaman, lihat limit/tagihan/denda, lapor pembayaran + bukti
- **Pendana**: dibuat Superadmin, claim pendanaan (1 loan = 1 pendana), pencairan manual + bukti, verifikasi/tolak pembayaran

## Implemented (16 Agustus 2026)
- Auth JWT via No HP, bcrypt, lockout 5x/15 menit, seed superadmin dari env (tanpa hardcode)
- RBAC server-side ketat (48/48 tes backend lolos, termasuk semua uji 403)
- Registrasi Peminjam (NIK/email/HP unik) → WAITING_VERIFICATION; verifikasi Admin + limit/max durasi/max pinjaman aktif
- Loan engine: nomor `PIN-YYYYMMDD-XXXX` atomic, snapshot bunga & denda, validasi limit/durasi/max aktif, simulasi live
- Funding claim atomic (anti double funding), pencairan + upload bukti, konfirmasi Admin, due_date dari pencairan aktual
- Overdue harian (Asia/Jakarta) + denda dinamis; payment freeze saat lapor bayar; payment rejection membuka freeze; histori multi payment attempt
- Telegram 2 bot (Registrasi & Pinjaman) + test connection + notification log (gagal tidak menggagalkan transaksi)
- Dashboard 4 role, tabel search/filter/pagination, export CSV, audit log, laporan + performa Pendana
- PWA: manifest, service worker (API tidak di-cache), offline fallback, icon 192/512, standalone

## Backlog
- P1: Grafik tren pelunasan & aging overdue; notifikasi in-app
- P1: Reset password mandiri (OTP/WA) untuk Peminjam
- P2: Detail halaman Pendana untuk Superadmin (saat ini via API `/api/lenders/{id}`)
- P2: Streaming export untuk dataset besar; rate limit terdistribusi
- P2: Dark mode toggle di UI

## Next tasks
1. Isi 2 Bot Token Telegram di Pengaturan → Telegram, set Telegram Chat ID pada profil Admin/Pendana, lalu Test Bot
2. Buat Admin + Pendana produksi via menu Pengguna
3. Set bunga & denda global di Pengaturan → Pinjaman
4. Ganti `SUPERADMIN_PASSWORD` & `JWT_SECRET` di `backend/.env` untuk produksi
