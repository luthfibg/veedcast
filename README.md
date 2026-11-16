# Veedcast

Konten Instagram klien tayang otomatis di layar digital signage.

Veedcast mengambil video terbaru dari akun Instagram profesional yang sudah memberi izin, memprosesnya (rotasi, kompresi) agar siap tayang di perangkat signage, lalu menyediakannya untuk CMS lewat API. Tidak perlu lagi mengunduh, memutar, dan mengunggah video secara manual.

> **Status:** tahap awal pengembangan. Belum siap produksi.

## Cara kerja

```
Akun Instagram ──► Veedcast ──► Storage (R2) ──► CMS ──► Playlist ──► Player (Android / Windows)
   (izin klien)    cek, unduh,    video siap      mengambil
                   proses FFmpeg   tayang          lewat API
```

1. Klien menghubungkan akun Instagram lewat tombol **Connect** di CMS (OAuth resmi, tanpa password).
2. Worker memeriksa konten baru secara berkala.
3. Video diunduh, diproses dengan FFmpeg, lalu disimpan.
4. CMS mengambil video hasil proses dan memasukkannya ke playlist klien.

## Fitur

- [x] Landing page dan panel developer (kerangka)
- [ ] Database dan multi-tenant
- [ ] API untuk CMS (API key, connect session, webhook)
- [ ] OAuth Instagram dan penyimpanan token terenkripsi
- [ ] Worker: deteksi video baru, rotasi, kompresi
- [ ] Panel monitoring: akun terhubung, audit log, traffic download/upload
- [ ] Penagihan berbasis penggunaan

## Stack

| Bagian | Teknologi |
|---|---|
| API, panel, landing | FastAPI, Jinja2, HTMX, Tailwind |
| Database | PostgreSQL (Neon), SQLAlchemy, Alembic |
| Storage video | Cloudflare R2 |
| Worker | Python, FFmpeg |
| Hosting | Vercel (API/panel), worker terpisah |

## Menjalankan secara lokal

Prasyarat: Python 3.12.

```bash
git clone https://github.com/<username>/veedcast.git
cd veedcast

python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env             # lalu isi nilainya

uvicorn app.main:app --reload
```

| Alamat | Fungsi |
|---|---|
| `http://127.0.0.1:8000/` | Landing page |
| `http://127.0.0.1:8000/admin/` | Panel developer (login `admin` + `ADMIN_PASSWORD`) |
| `http://127.0.0.1:8000/docs` | Dokumentasi API (Swagger) |
| `http://127.0.0.1:8000/health` | Cek status |

## Konfigurasi

Salin `.env.example` menjadi `.env`:

| Variabel | Keterangan |
|---|---|
| `APP_NAME` | Nama aplikasi |
| `ENVIRONMENT` | `development` atau `production` |
| `ADMIN_PASSWORD` | Password panel admin |

Jangan pernah meng-commit file `.env`.

## Struktur project

```
app/
├── main.py          # entry point FastAPI
├── config.py        # pengaturan dari .env
├── routers/         # public (landing) dan admin (panel)
└── templates/       # halaman HTML
```

## Catatan

Veedcast tidak berafiliasi dengan, didukung, atau disponsori oleh Instagram atau Meta. Hanya akun yang telah memberi izin eksplisit yang dapat dihubungkan.

## Lisensi

Belum ditentukan.
