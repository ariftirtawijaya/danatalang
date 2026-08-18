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

## Iterasi 2 (16 Agustus 2026) — hardening pra manual test
- **Object storage dikonfirmasi**: semua bukti pencairan & pembayaran di Emergent Managed Object Storage (`pinjamku/{kind}/{user_id}/{uuid}.{ext}`), nama file random, whitelist MIME (jpg/png/webp/pdf), maks 5MB, tanpa local disk. Akses hanya via `GET /api/files/{id}` yang terautentikasi (401 tanpa token, 403 untuk pihak tidak terkait, `Cache-Control: private, no-store`)
- **Emergency Payment Override (Superadmin saja)**: `POST /api/payments/{id}/override` (`verify`/`reject`, alasan min 10 karakter), confirmation dialog di UI, audit log `SUPERADMIN_PAYMENT_OVERRIDE_VERIFY/REJECT` + loan_status_histories. Flow normal tidak berubah: verifikasi pembayaran tetap eksklusif Pendana pemilik loan, Admin tetap 403
- **Normalisasi No HP**: canonical `08xxxxxxxxxx` untuk input `08..`, `62..`, `+62..`, `0062..`; migrasi data lama saat startup; unique index mencegah akun duplikat
- **Reset password**: `POST /api/users/{id}/reset-password` menghasilkan temporary password sistem + `must_change_password=true` (Admin hanya boleh reset Peminjam, tidak boleh reset diri sendiri). Semua endpoint lain diblokir 403 sampai user membuat password baru di halaman wajib ganti password
- Regresi + fitur baru: **70/70 tes backend lolos**; 4 flow UI baru terverifikasi

## Iterasi 3–4 (16 Agustus 2026) — Factory Reset / Clean Install
- **Pengaturan → Sistem → Danger Zone** (Superadmin saja): `GET /api/settings/factory-reset/preview` menampilkan jumlah per kategori + jumlah/ukuran file object storage; `POST /api/settings/factory-reset` menghapus seluruh users (kecuali Superadmin utama dari `SUPERADMIN_PHONE`), loans, disbursements, payments & semua attempt, loan_status_histories, notifications, admin_notes, audit_logs lama, files, counters/sequence, login_attempts, lalu mereset settings/bunga/denda/Telegram/branding ke `DEFAULT_SETTINGS`
- **File bukti dihapus fisik**: object storage Emergent tidak menyediakan verb DELETE (405), sehingga byte tiap objek dihancurkan via overwrite 0 byte (`purge_prefix`, diverifikasi `remaining_bytes == 0`) sebelum referensi DB dihapus
- Pengaman: hanya Superadmin, preview jumlah data, warning irreversible, wajib ketik persis `HAPUS SEMUA DATA`, re-auth password Superadmin, tombol destructive, lock `db.system_locks` anti double-submit (request kedua → 409, bukan 500)
- Audit log baru `SYSTEM_FACTORY_RESET` mencatat pelaksana, timestamp, jumlah data terhapus, hasil purge storage, dan status keberhasilan
- Route `/settings` & `/audit-logs` di frontend di-role-guard superadmin (Admin dialihkan ke dashboard, tab Sistem tidak dirender)
- Hasil tes: **112/112 backend (iterasi 3)** dan **77/77 (iterasi 4: 70 regresi + 7 RBAC)**, frontend Danger Zone 100%

## Iterasi 5–7 (16 Agustus 2026) — perbaikan bug & self-service Superadmin
- **Fix "Failed to fetch" di /profile**: service worker v2 hanya meng-intercept request navigasi (mengecualikan `/api/` & `/cdn-cgi/`), plus guard `unhandledrejection` untuk request yang di-abort saat navigasi. Kartu Identitas staf diperluas (Email, Role, Status, Telegram Chat ID, Login Terakhir, Terdaftar)
- **Superadmin dapat mengubah No HP login sendiri** (`PUT /api/auth/profile` dengan `phone` + `current_password`): validasi format, keunikan, normalisasi canonical, audit `LOGIN_PHONE_CHANGED`. Role lain 403
- **Seed startup idempoten**: Superadmin hanya dibuat bila belum ada superadmin sama sekali; password/nomor tidak pernah ditimpa dari env. Keeper factory reset mengikuti superadmin aktif
- **Re-auth tidak lagi auto-logout**: password salah pada `/auth/profile`, `/auth/password`, `/settings/factory-reset` mengembalikan 400 + interceptor axios mem-whitelist endpoint tersebut; sesi kedaluwarsa asli tetap auto-logout
- Hasil tes: iterasi 5 **77/77**, iterasi 6 **85/85**, iterasi 7 **88/88** backend + frontend 100%

## Iterasi 8–11 (16 Agustus 2026) — pemulihan akses & hardening login
- **Diagnosis bug user** ("superadmin/admin tidak bisa login"): tidak ada satu pun entri audit `PASSWORD_CHANGED` dari user → perubahan password tidak pernah tersimpan; akun juga terkunci 5 percobaan dengan pesan generik
- **Ganti password**: menolak password baru yang sama, membersihkan lock login akun tersebut, dan memaksa re-login (auto logout + redirect `/login`) sehingga user pasti tahu password aktif
- **Pesan login informatif**: percobaan 1–4 → 401 dengan sisa percobaan; percobaan ke-5 dst → 429 "Akun terkunci sementara, coba lagi dalam 15 menit"
- **Rate limit per akun** (`phone:<nomor>`), bukan per IP proxy ingress; IP klien dari `X-Forwarded-For` hanya untuk pencatatan
- **Break-glass Superadmin**: `SUPERADMIN_RECOVERY=true` di `backend/.env` memulihkan password Superadmin dari env saat startup + audit `SUPERADMIN_PASSWORD_RECOVERED`
- **Remediasi data**: Admin Billy Aldy direset ke password sementara, lock login dibersihkan, dan 40 akun + 10 pinjaman sisa pengujian dihapus sehingga hanya 3 akun milik user yang tersisa
- Hasil tes: iterasi 9 **96/96**, iterasi 10 **102/103** (1 bug boundary), iterasi 11 **103/103 + 7/7 lockout strict**, frontend 100%

## Iterasi 12–14 (16 Agustus 2026) — label UI berbahasa Indonesia
- `src/lib/status.js` menjadi satu sumber label: `statusLabel()` (status pinjaman/akun/pembayaran), `actionLabel()` (aksi audit), `entityLabel()` (jenis entitas), plus fallback title-case agar aksi baru tidak pernah bocor sebagai enum
- **Timeline detail pinjaman** kini penuh bahasa Indonesia (Menunggu Approval → Menunggu Pendanaan → Menunggu Pencairan → Konfirmasi Pencairan → Aktif → Verifikasi Pembayaran → Lunas); nol enum mentah
- Audit Log (aksi/role/entitas), detail Peminjam (Status Akun, tab Audit, dropdown Ubah Status "Aktif/Ditangguhkan/Diblokir" dengan nilai enum tetap dikirim ke backend), daftar Pengguna (role), daftar Pinjaman & Pembayaran ikut dirapikan
- Label "Overdue" diganti "Terlambat" di menu sidebar, filter status, tab Pendana, kolom laporan, kartu statistik dashboard, dan label pie chart backend
- Suite regresi dilepas dari kredensial user: `tests/conftest.py` + `_setup_temp_super.py` membuat superadmin sementara (UUID string) lalu menghapusnya
- Hasil tes: iterasi 13 frontend **100%**; iterasi 14 **102 lolos / 1 skip / 0 gagal** + UI 100%, data user tetap utuh (5 akun, 2 pinjaman)

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

## Update 2026-08-17 — Deployment varian VPS (existing host Nginx)
- `docker-compose.vps.yml`: tanpa Mongo & Certbot container, web bind 127.0.0.1:8080, api internal-only
- `deploy/nginx.internal.conf` (nginx dalam container, no SSL) & `deploy/nginx.host.danatalang.conf` (contoh vhost host + Certbot)
- Mongo container di `docker-compose.yml` jadi opsional (profile `localdb`); produksi pakai MongoDB Atlas (mongodb+srv)
- `REQUIRE_S3=true`: startup gagal bila konfigurasi S3 tidak lengkap atau head_bucket gagal, tanpa fallback local storage
- Default `S3_PREFIX` diganti ke `danatalang`
- DEPLOYMENT.md: Bagian 1 (varian VPS host Nginx + Atlas + R2) dan Bagian 2 (portable)

## Update 2026-08-17 — Startup race-safe
- `core.get_settings()`: atomic upsert (`$setOnInsert` + `upsert=True`, `ReturnDocument.AFTER`) — tidak lagi insert manual
- `server.seed_superadmin()`: insert dibungkus try/except `DuplicateKeyError` (unique index `phone`) → idempotent pada startup bersamaan
- `backend/Dockerfile`: uvicorn `--workers 1` (overdue_worker in-process, hindari eksekusi ganda)

## Update 2026-08-17 — MODUL PEMBAGIAN HASIL (PROFIT SHARING) + SETTLEMENT

### Konsep
- Pokok 100% hak Pendana. Profit pool = bunga terealisasi + denda terealisasi (frozen dari payment attempt yang diverifikasi).
- Default 60/25/15 (lender_share / admin_share / platform_share = Pendana / Admin / Aplikator), global setting Superadmin, total wajib 100%, di-SNAPSHOT ke loan saat approval.
- Distribusi HANYA dibuat saat loan menjadi PAID; idempotent via unique index profit_distributions.loan_id.
- Alur uang V1: Pendana menerima seluruh pembayaran, lalu wajib setor (admin_profit + platform_profit) ke rekening settlement pusat. Superadmin verify/reject. Setelah SETTLED, payout Admin PENDING -> Superadmin mark PAID + bukti.
- Rounding: Decimal ROUND_HALF_UP untuk lender & admin, platform = sisa (total selalu = profit_pool).

### File baru
- backend/profit_service.py, backend/profit_routes.py, backend/tests/test_iter16_profit_sharing.py
- frontend/src/components/profit.jsx, pages/staff/ProfitSharing.jsx, pages/staff/MyEarnings.jsx, pages/lender/Settlement.jsx

### File diubah
- backend/core.py (DEFAULT_SETTINGS profit_share_*/settlement_account_*, 6 index profit_distributions)
- backend/loan_routes.py (approve snapshot + assigned_admin_id, guard PAID, hook distribusi pada verify & override, RBAC file settlement/payout, PUT /loans/{id}/assigned-admin, POST /loans/{id}/profit-share/backfill, section profit_share di detail, None-guard borrower_credit)
- backend/admin_routes.py (Factory Reset: wipe profit_distributions + hitungan bukti settlement/payout)
- backend/server.py (include profit_routes)
- frontend: App.js (route /profit-sharing, /earnings, /settlement), Layout.jsx (nav), LoanDetail.jsx (section Pembagian Hasil + dialog pilih/ubah Admin), staff/Settings.jsx (tab Bagi Hasil), lib/status.js (label audit baru)

### Status testing
- Backend pytest: 16/16 lulus (settings, snapshot, assignment, kalkulasi, rounding, freeze denda, double-verify, RBAC, settlement, reject, payout, file RBAC, legacy, reversal, index).
- Regresi lama: 55/55 lulus. Frontend E2E iteration_16.json: 0 bug UI.

## Update 2026-08-18 — Hardening bagi hasil (final verification sebelum push)
- Reversal guard: reverse hanya untuk settlement PENDING & payout != PAID; WAITING/SETTLED/PAID -> 409. Endpoint baru POST /api/profit-distributions/{id}/financial-correction (Superadmin, reason >=20, confirmation "KOREKSI FINANSIAL", acknowledge_funds_moved) + audit PROFIT_DISTRIBUTION_CORRECTED.
- Rekening payout Admin memakai field user existing bank_name/account_number/account_holder; payout diblokir 409 bila belum lengkap, UI menampilkan rekening + tombol disabled.
- settlement_attempts kini array attempt immutable (attempt_no, amount, proof_file_id, submitted_*, status SUBMITTED/REJECTED/VERIFIED, rejection_reason, verified_*) + settlement_attempt_count.
- Factory Reset integration test terisolasi: tests/_factory_reset_isolated.py (DB fr_isolated_*, bucket+prefix moto S3 khusus test) dipanggil dari tests/test_iter17_profit_hardening.py.
- Catatan environment preview: MinIO pod lama tidak ada; tests/_preview_s3_server.py (moto) dijalankan di 127.0.0.1:9100 agar upload preview berfungsi. Produksi tetap Cloudflare R2.
- Test: iter17 8/8, iter16 16/16, regresi lama 55/55.

### Catatan UI hardening (2026-08-18)
- Dialog Koreksi Finansial (staff/ProfitSharing.jsx) diverifikasi terbuka & validasi tombol (disabled sampai alasan >=20, checkbox ack, dan teks "KOREKSI FINANSIAL" benar).
- Riwayat setoran per attempt tampil di kartu Superadmin (#1 ditolak + alasan, #2 diverifikasi, tombol Bukti per attempt).
- Tombol "Tandai Payout Dibayar" disabled bila rekening Admin belum lengkap.

## Update 2026-08-18 — Final hardening 5 temuan tambahan
1. Factory Reset: storage_ok boolean + status SUCCESS/PARTIAL/FAILED; exception purge -> FAILED (tidak pernah SUCCESS), audit mencatat error.
2. serialize_distribution(viewer=user): admin_bank hanya untuk Superadmin & Admin pemilik; Pendana tidak menerima rekening Admin.
3. Notifikasi LENDER_SETTLEMENT_SUBMITTED -> notify_superadmins (Admin biasa tidak lagi menerima); Admin pemilik menerima ADMIN_PAYABLE_READY setelah SETTLED.
4. Rounding: split_pool() largest remainder (floor + alokasi sisa deterministik) -> tidak pernah negatif, total selalu = profit_pool.
5. Cleanup orphan proof: _discard_upload() menghapus doc files + object storage untuk request yang kalah (409) pada settlement & admin payout.
- Test baru iter18: 9 passed. iter17 8, iter16 16, regresi lama 55.

### Fail-safe Factory Reset (2026-08-18)
- Storage purge dijalankan lebih dulu; MongoDB/settings/users HANYA dihapus bila storage benar-benar bersih (failed==0, remaining_objects==0, remaining_bytes==0, tanpa error).
- Bila purge gagal/partial: proses STOP sebelum wipe DB, response ok=false status FAILED/PARTIAL + aborted_before_db_wipe=true, audit mencatat "DIBATALKAN", data & primary Superadmin tetap utuh, reset bisa di-retry.
- Test: mode storage-fail memverifikasi DB utuh (1 distribusi, 1 loan, 2 file, 4 user, settings 70/20/10 belum direset) + retry setelah storage sehat menghasilkan SUCCESS penuh.

### Fail-safe _discard_upload (2026-08-18)
- Object storage dihapus LEBIH DULU (purge_object dikonfirmasi), metadata files baru dihapus bila object benar-benar hilang.
- Bila purge gagal/exception: metadata dipertahankan + ditandai is_deleted=true, cleanup_pending=true, cleanup_error, cleanup_requested_at; file tidak dapat diakses via GET /api/files/{id} (404); request loser tetap 409; log warning.
- Berlaku untuk settlement dan admin payout (jalur yang sama).
- Test iter18 bertambah: race normal (metadata+object loser hilang) dan simulated purge failure per kind (settlement & admin_payout).

### Catatan environment (2026-08-18)
- 38 record files lama (prefix pinjamku/) menunjuk object yang hilang bersama MinIO pod sebelumnya; record stale tersebut dibersihkan agar regresi test_iter2 ObjectStorage kembali hijau. Bukan akibat perubahan kode.

### Regresi penuh (2026-08-18)
- iter18 13, iter17 8, iter16 16, iter4+flow 55, iter2/6/8/10/15 (batch) — semua hijau.
- tests/test_iter3_factory_reset.py TIDAK dijalankan: suite destruktif (menjalankan factory reset nyata pada DB preview) dan butuh password Superadmin milik user. Cakupan factory reset dipenuhi oleh tests/_factory_reset_isolated.py (DB + bucket terisolasi, jalur SUCCESS & storage-fail).

## Update 2026-08-18 — MODUL ADMIN COLLECTION + BULK REMITTANCE
- payments diperluas: payment_channel (DIRECT_TO_LENDER default / ADMIN_COLLECTION), collection_number COL-YYYYMMDD-XXXX, collection_method, collector_admin_id, snapshot (principal/interest/late_days/late_fee/total_collected), collection_status, remittance_id.
- Koleksi baru admin_remittances: REM-YYYYMMDD-XXXX, status PREPARED/WAITING_VERIFICATION/VERIFYING/VERIFIED/REJECTED + remittance_attempts[] immutable.
- Status loan baru PAYMENT_COLLECTED (masuk CLOSED_STATUSES sehingga limit/outstanding/active count peminjam langsung pulih, denda beku).
- File baru: backend/collection_service.py, backend/collection_routes.py, frontend staff/Collections.jsx, lender/AdminRemittance.jsx, tests/test_iter19_admin_collection.py.
- Test: iter19 17/17; regresi iter16 16, iter17+18 21, iter4+flow 55, iter2/6/8/10/15 66 (1 skip).

## Update 2026-06 (iterasi 20) — CRASH-SAFETY ADMIN COLLECTION & REMITTANCE
Prinsip: **TRANSACTION jika tersedia + IDEMPOTENT RECOVERY sebagai safety net** (tidak bergantung replica set).
- `collection_service.transaction_supported()` mendeteksi kapabilitas nyata (mencoba transaction sungguhan lalu abort), hasil di-cache; `atomic(op)` menjalankan op dalam transaction bila didukung, fallback tanpa session (op ditulis idempoten). Pod preview = MongoDB standalone → memakai jalur fallback.
- Collect: payment ditulis lebih dulu dengan `commit_state=PENDING`, lalu loan → PAYMENT_COLLECTED, lalu `commit_state=COMMITTED`. Item PENDING/ABORTED disembunyikan dari daftar & summary (`visible_collection_filter`). `recover_pending_collections()` melanjutkan (forward) bila loan masih ACTIVE/OVERDUE/COLLECTED, atau meng-ABORT + REVERSED bila loan tak valid.
- Bulk prepare: lifecycle PREPARING → PREPARED. Parent remittance dibuat lebih dulu (status PREPARING + `reservation_token` + `requested_ids`), lalu reservasi item, lalu `finish_prepare()`. Tidak pernah ada item RESERVED tanpa parent recoverable.
- `recover_stale_reservations()` hanya menyentuh yang benar-benar stale/orphan: PREPARING melewati lease 120 detik (lanjut ke PREPARED bila seluruh requested_ids ter-reserve, selain itu dilepas + CANCELLED) dan item RESERVED yang parent-nya hilang/CANCELLED. Reservasi PREPARED valid tidak pernah dilepas. Dipicu sebelum prepare baru, saat halaman koleksi/setoran dibuka Admin, dan lewat tombol Superadmin.
- Endpoint baru: `POST /api/admin-remittances/{id}/cancel` (Admin pemilik + Superadmin, hanya PREPARED tanpa attempt/proof, reason ≥5 karakter, item kembali COLLECTED, record CANCELLED immutable) dan `POST /api/admin-remittances/recover-stale` (Superadmin).
- `/finalize` diperketat: hanya state VERIFYING (VERIFIED → idempotent 200), tidak bisa melewati verifikasi Pendana; unauth 401, Admin/Peminjam/Pendana lain 403. `POST /verify` milik Pendana otomatis melanjutkan state VERIFYING yang macet.
- UI: tombol Superadmin "Bersihkan Reservasi Terlantar" (`recover-stale-btn`), tombol "Batalkan Setoran" + dialog (`cancel-rem-btn-<id>`, `cancel-rem-dialog`, `cancel-rem-reason`, `cancel-rem-confirm`), label status "Dibatalkan" dan tab Riwayat memuat CANCELLED.
- Test: tests/test_iter20_crash_safety.py 14/14 (failure-injection collect & bulk prepare, orphan release, guard PREPARED tidak dilepas, RBAC cancel/recover/finalize). Regresi: iter19 17, iter18 13, iter16+17 24, iter4 7 — semua hijau. UI smoke 4 role desktop+mobile 390px: tidak ada bug (test_reports/iteration_17.json).

### Backlog (belum dikerjakan)
- P1: seed skenario demo end-to-end agar UI live test bisa klik Buat Setoran Bulk/Kirim Bukti/Verifikasi dengan akun QA.
- P1: konfirmasi apakah rekening Pendana pada loan detail jalur pembayaran langsung perlu disembunyikan dari Peminjam.
- P0 (menunggu user): push GitHub & deploy — DITAHAN sesuai instruksi user.
