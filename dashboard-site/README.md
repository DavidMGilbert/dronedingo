# dashboard.dronedingo.com.au — remote-access dashboard

The cloud front door for remote access. It authenticates a customer account and
proxies each request to their appliance over the tunnel (the appliance connects
out only — no port forwarding, works behind DHCP/CGNAT). It reuses the relay's
database and PHP helpers, so it lives on the **same cPanel account** as
notify.dronedingo.com.au.

## How it routes
- **`dashboard.dronedingo.com.au`** → account portal (login + list of stations).
- **`<station>.dashboard.dronedingo.com.au`** → account-gated proxy to that
  appliance's full UI. Requires a wildcard subdomain + wildcard TLS for
  `*.dashboard.dronedingo.com.au`.

Access control lives here (account login + station ownership); the appliance
trusts anything the tunnel delivers via a per-boot in-memory secret, so a remote
user signs in once at the dashboard — no second appliance login.

## Deploy (same account as the relay)
1. Create the subdomain `dashboard.dronedingo.com.au` **and a wildcard**
   `*.dashboard.dronedingo.com.au`, both pointing at this docroot. Issue a
   wildcard TLS cert (AutoSSL wildcard, or DNS-01).
2. Upload the **contents** of `public/` into that docroot (so `index.php`,
   `_boot.php`, `portal.php`, `api/` are at the root).
3. This site shares the relay's database and code. By default `_boot.php`
   expects the relay docroot as a sibling named `notify.dronedingo.com.au`; if
   yours differs, set `DRONEDINGO_INCLUDES` to the relay's `api/` path.
4. Requires `mod_rewrite` (the front-controller `.htaccess`) and `mod_headers`.

## Notes
- One account can own many stations — they all appear on the portal and share a
  single login (cookie scoped to `.dashboard.dronedingo.com.au`).
- Live map updates use the appliance's `/ws`; over the polling tunnel that
  becomes short-poll of `/api/active` (frontend adapts when loaded remotely).
