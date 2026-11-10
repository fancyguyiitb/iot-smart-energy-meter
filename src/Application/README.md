# ⚡ Voltix – Smart Energy Meter App

Voltix is a mobile app for monitoring and controlling a 3-phase IoT-based smart energy meter.

> **Status:** the Dart source (`lib/`) was never committed. The repo's root `.gitignore` had a bare `lib/` rule that also matched this folder; it's fixed now. Until the app is rewritten, [`src/WebApp`](../WebApp) is the reference client. It covers the same features against the current API (see `src/Server/README.md`). API changes a rewrite must follow:
> * Log in with a JSON body `{username, password}` (not HTTP Basic). Sign up with `{username, password, claim_code}`, where `claim_code` is the text of the meter's QR code.
> * Send `Authorization: Bearer <token>` on every call. Data routes take an optional `device_id` and default to the user's meter.
> * `POST /remote-control` returns the relay state the meter confirmed, or 409 (offline) / 504 (no confirmation).

---

## 🔍 Features

- Live voltage, current, power & THD readings
- Remote supply control via relay
- Analytics on consumption & power quality
- Cloud storage with historical trends

---

## 🚀 Getting Started

```bash
git clone https://github.com/your-username/voltix.git
cd voltix
flutter pub get
flutter run
```

---

## 📦 Build APK

```bash
flutter build apk --release
```
