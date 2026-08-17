# Deployment ke VPS — Dana Talang (PWA Manajemen Pinjaman)

Stack: **React (CRA)** + **FastAPI** + **MongoDB**. Panduan ini memakai Docker Compose + Nginx + SSL.

> ✅ **Storage bukti transfer sudah S3-compatible.**
> Upload/download memakai **S3 private bucket** (Cloudflare R2, AWS S3, MinIO, Backblaze B2, dst.) melalui
> boto3, diatur sepenuhnya lewat environment variable. Tidak ada lagi dependensi Emergent Managed Object
> Storage maupun `EMERGENT_LLM_KEY` (aplikasi ini tidak memakai fitur AI/LLM sama sekali).
> Bucket **wajib private**: aplikasi tidak pernah membuat object publik atau presigned URL — semua byte
> mengalir lewat backend setelah pemeriksaan token & RBAC pada `GET /api/files/{id}`.

---

## A. Persiapan VPS
- Ubuntu 22.04/24.04, minimal 2 vCPU / 2 GB RAM / 20 GB disk
- Domain sudah diarahkan ke IP VPS (A record `@` dan `www`)

```bash
ssh root@IP_VPS
apt update && apt upgrade -y
apt install -y git ufw curl
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

## B. Ambil source code
Di Emergent klik **Save to GitHub**, lalu di VPS:
```bash
mkdir -p /opt && cd /opt
git clone https://github.com/USERNAME/REPO.git danatalang
cd danatalang
```

## C. Buat file environment produksi
```bash
cat > /opt/danatalang/.env.prod <<'EOF'
DOMAIN=app.domainanda.com
MONGO_URL=mongodb://mongo:27017
DB_NAME=danatalang
JWT_SECRET=GANTI_DENGAN_HASIL_openssl_rand_hex_32
CORS_ORIGINS=https://app.domainanda.com
SUPERADMIN_NAME=Super Admin
SUPERADMIN_PHONE=08123456789
SUPERADMIN_EMAIL=admin@domainanda.com
SUPERADMIN_PASSWORD=PasswordKuatAnda!2026
S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=r2_access_key_anda
S3_SECRET_ACCESS_KEY=r2_secret_key_anda
S3_BUCKET_NAME=danatalang-bukti
S3_REGION=auto
S3_PREFIX=pinjamku
EOF
chmod 600 /opt/danatalang/.env.prod
openssl rand -hex 32   # tempel hasilnya ke JWT_SECRET
```
Catatan:
- `SUPERADMIN_*` hanya dipakai **saat database masih kosong** (akun Superadmin pertama). Setelah itu tidak pernah menimpa.
- Jangan pernah commit `.env.prod` ke Git.

## C1. Siapkan bucket S3 (Cloudflare R2)
1. Cloudflare Dashboard → **R2** → **Create bucket** (mis. `danatalang-bukti`), biarkan **private**
   (jangan aktifkan Public Development URL / custom domain publik).
2. **R2 → Manage API Tokens → Create API token**, izin **Object Read & Write** untuk bucket tersebut.
   Simpan Access Key ID & Secret Access Key.
3. Endpoint: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, region: `auto`.
4. Provider lain: cukup ganti `S3_ENDPOINT_URL`/`S3_REGION` — AWS S3 (`https://s3.<region>.amazonaws.com`,
   region asli), MinIO (`http://minio:9000`, region `us-east-1`), Backblaze B2 (`https://s3.<region>.backblazeb2.com`).
5. Uji koneksi dari VPS setelah container jalan:
   ```bash
   docker compose --env-file .env.prod logs api | grep "object storage"
   # harus: object storage ready: s3 bucket danatalang-bukti
   ```
   Bila muncul `S3 not configured; using private local storage`, berarti variabel S3 belum terisi —
   aplikasi memakai penyimpanan lokal container (**tidak disarankan untuk produksi** karena hilang saat
   container dibangun ulang, kecuali Anda memasang volume sendiri).

## D. Jalankan aplikasi
```bash
cd /opt/danatalang
docker compose --env-file .env.prod up -d --build
docker compose ps
curl -s localhost/api/health     # harus {"status":"ok"}
```
Arsitektur container: `web` (Nginx: serve React + proxy `/api` → backend) · `api` (FastAPI/uvicorn) · `mongo` (MongoDB + volume persisten).

## E. Pasang SSL (HTTPS)
```bash
docker compose --env-file .env.prod run --rm certbot certonly \
  --webroot -w /var/www/certbot -d app.domainanda.com \
  --email admin@domainanda.com --agree-tos --no-eff-email
sed -i 's|# SSL_START||; s|# SSL_END||' deploy/nginx.conf   # aktifkan blok 443
docker compose --env-file .env.prod restart web
```
Perpanjangan otomatis (cron):
```bash
(crontab -l 2>/dev/null; echo "0 3 * * 1 cd /opt/danatalang && docker compose --env-file .env.prod run --rm certbot renew --webroot -w /var/www/certbot && docker compose --env-file .env.prod restart web") | crontab -
```

## F. Login pertama
1. Buka `https://app.domainanda.com`
2. Login dengan `SUPERADMIN_PHONE` + `SUPERADMIN_PASSWORD`
3. **Segera ganti password** di Profil (sistem akan meminta login ulang)
4. Isi **Pengaturan → Umum** (nama aplikasi, logo), **→ Pinjaman** (bunga & denda), **→ Telegram** (2 bot token)
5. Buat Admin & Pendana di menu **Pengguna**

## G. Backup database (wajib)
```bash
mkdir -p /opt/backup
cat > /usr/local/bin/danatalang-backup.sh <<'EOF'
#!/bin/bash
set -e
TS=$(date +%F_%H%M)
docker exec danatalang-mongo mongodump --db danatalang --archive=/tmp/db.gz --gzip
docker cp danatalang-mongo:/tmp/db.gz /opt/backup/db_$TS.gz
find /opt/backup -name 'db_*.gz' -mtime +14 -delete
EOF
chmod +x /usr/local/bin/danatalang-backup.sh
(crontab -l 2>/dev/null; echo "30 2 * * * /usr/local/bin/danatalang-backup.sh") | crontab -
```
Restore: `docker cp file.gz danatalang-mongo:/tmp/db.gz && docker exec danatalang-mongo mongorestore --drop --gzip --archive=/tmp/db.gz`

## H. Update aplikasi
```bash
cd /opt/danatalang && git pull
docker compose --env-file .env.prod up -d --build
```

## I. Operasional harian
```bash
docker compose logs -f api          # log backend
docker compose logs -f web          # log nginx
docker compose restart api          # restart backend
```

## J. Pemulihan darurat Superadmin (lupa password)
Tambahkan sementara ke `.env.prod`:
```
SUPERADMIN_RECOVERY=true
```
lalu `docker compose --env-file .env.prod up -d api`. Password Superadmin dipulihkan ke `SUPERADMIN_PASSWORD`
dan tercatat di Audit Log. **Hapus kembali baris tersebut** lalu restart.
Untuk Admin/Pendana/Peminjam: Superadmin → **Pengguna → Reset Password** (password sementara).

## K. Checklist keamanan sebelum go-live
- [ ] `JWT_SECRET` acak 32 byte, `SUPERADMIN_PASSWORD` kuat, `.env.prod` mode 600
- [ ] `CORS_ORIGINS` hanya domain Anda (bukan `*`)
- [ ] HTTPS aktif dan HTTP redirect ke HTTPS
- [ ] Port 27017 (MongoDB) **tidak** dibuka ke internet (default compose: internal saja)
- [ ] Backup harian aktif dan sudah diuji restore
- [ ] Bucket S3 **private**, kredensial R2 hanya ada di `.env.prod` (bukan di repo/frontend)
- [ ] Log backend menampilkan `object storage ready: s3 bucket ...`
- [ ] Bot Telegram diuji lewat tombol **Test Bot**
- [ ] Jalankan **Factory Reset** bila ingin mulai dari data bersih

## Referensi variabel environment
| Variabel | Wajib | Keterangan |
|---|---|---|
| `MONGO_URL` | ya | `mongodb://mongo:27017` (atau URI MongoDB Atlas) |
| `DB_NAME` | ya | nama database |
| `JWT_SECRET` | ya | kunci tanda tangan token sesi |
| `CORS_ORIGINS` | ya | daftar origin dipisah koma |
| `SUPERADMIN_PHONE` / `_PASSWORD` / `_NAME` / `_EMAIL` | ya | hanya untuk akun pertama |
| `SUPERADMIN_RECOVERY` | tidak | `true` = pulihkan password Superadmin saat start |
| `S3_ENDPOINT_URL` | ya | endpoint S3-compatible (R2/AWS/MinIO/B2) |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | ya | kredensial bucket, **hanya di backend** |
| `S3_BUCKET_NAME` | ya | nama bucket **private** |
| `S3_REGION` | tidak | `auto` untuk R2, region asli untuk AWS |
| `S3_PREFIX` | tidak | prefix object, default `pinjamku` |
| `REACT_APP_BACKEND_URL` | build | dikirim otomatis oleh compose (`https://$DOMAIN`) |

## Catatan storage
- Nama object: `<prefix>/<jenis>/<user_id>/<uuid>.<ext>` — nama file asli pengguna tidak pernah dipakai.
- MIME whitelist: JPG, PNG, WEBP, PDF · ukuran maksimal 5 MB (divalidasi di backend).
- Database hanya menyimpan referensi (`storage_path`, `kind`, `uploaded_by`, `content_type`, `size`).
- `GET /api/files/{id}`: tanpa token → 401, bukan pihak terkait → 403, respons selalu `Cache-Control: private, no-store`.
- **Factory Reset** memanggil `DeleteObject`/`DeleteObjects` sehingga object benar-benar hilang dari bucket,
  lalu referensi database dihapus. Hasilnya diverifikasi (`remaining_objects` harus 0).
- Kredensial S3 tidak pernah dikirim ke frontend; seluruh upload/download melalui backend.
