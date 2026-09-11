# Google sign-in setup

1. In Google Cloud Console configure the OAuth consent screen and create an OAuth **Web application** client. If the app is in testing mode, add your test users.
2. Add `http://localhost:5173` as an Authorized JavaScript origin. This popup credential flow does not need a redirect URI or client secret.
3. Set `GOOGLE_CLIENT_ID` in your server `.env` to that client ID and `FRONTEND_URL=http://localhost:5173`.
4. In the client `.env`, set `VITE_GOOGLE_SIGN_IN_ENABLED=true` and `VITE_API_BASE_URL=http://localhost:8000/api/v1`. Use localhost on both sides, not a mixture of localhost and 127.0.0.1: the sign-in nonce uses a SameSite cookie.
5. From `server`, with the virtual environment active, run `python -m pip install -r requirements.txt`, then `python -m alembic upgrade head`.
6. Restart the backend (`python -m uvicorn app.main:app --reload`) and frontend (`npm run dev` from `client`). Open `http://localhost:5173/login`.

For production use HTTPS and same-site frontend/API hosts, register the exact frontend origin in Google, and update both application URLs. Unrelated frontend/API domains are not supported by the SameSite nonce cookie. A Content Security Policy, if configured by your deployment, must permit Google's GIS script and frames. Do not log credentials or put secrets in frontend environment variables.

Vite development and preview responses set `Cross-Origin-Opener-Policy: same-origin-allow-popups` for Google popup communication. Configure the same response header on your production frontend host (Vite build cannot configure hosting response headers). A popup warning alone does not explain a backend 401: inspect the JSON error code. `GOOGLE_SIGNIN_EXPIRED` indicates a missing/expired nonce cookie; verify matching local hostnames, allow cookies, and reload. `GOOGLE_TOKEN_INVALID` indicates failed credential or nonce verification.

Google sign-in creates an account on first use, then identifies returning users by Google's stable subject ID, not by email. Existing password accounts with the same email are deliberately not automatically linked: use the existing password. Account linking is not part of this implementation. Google-only users cannot use password login. Disabled users remain blocked. App refresh and logout work as before; logging out of InsightForge does not sign the user out of Google.

Manual checks after configuration: new Google account, returning Google account, cancelled popup, blocked Google script, expired sign-in (reload after five minutes), existing-password-email conflict, disabled account, refresh, logout, and ordinary password login. Missing Google configuration leaves email/password authentication available. No live Google request or database migration was performed during implementation.

Reference: https://developers.google.com/identity/gsi/web/guides/verify-google-id-token
