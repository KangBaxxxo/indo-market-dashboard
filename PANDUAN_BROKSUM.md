# 📊 Panduan Sinkronisasi & Optimasi Broker Summary Dashboard

Dokumen ini berisi rangkuman alur logika, formula bandarmologi, serta contekan perintah Git untuk sinkronisasi antar-laptop (Kantor ↔ Rumah).

---

## 🚀 1. Alur Sinkronisasi Git (Solusi Lupa Commit)

Jika Anda mengedit file `app.py` di rumah, lalu mengeditnya lagi di kantor tanpa sempat melakukan *commit/push* sebelumnya, lakukan ritual ini saat kembali ke rumah agar kodingan tidak bentrok:

```bash
# Langkah 1: Amankan kodingan rumah yang belum di-commit ke memori rahasia Git
git stash

# Langkah 2: Tarik pembaruan terbaru yang dikerjakan di kantor
git pull origin main

# Langkah 3: Gabungkan kembali kodingan rumah ke versi kantor terbaru
git stash pop