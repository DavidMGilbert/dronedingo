# Remote access — accounts & the optional CMS bridge

The remote-access dashboard (dashboard.dronedingo.com.au) is **self-contained**:
it has its own accounts, its own station claiming, and its own portal on the
relay (PHP + SQLite). It does **not** depend on the CMS. Linking to the store is
a single **optional** convenience: a customer can reuse their dronedingo.com.au
password instead of making a new one.

## Two ways a customer gets a dashboard account (first-boot wizard)

1. **Create a new dashboard account** — email + password, stored on the relay
   (`accounts` table). Zero CMS involvement.
2. **Use my dronedingo.com.au account** — the appliance sends the entered email +
   password to the relay's `account-import.php`, which asks the CMS "are these
   valid?" and, if so, creates a matching dashboard account (same email; the
   password is verified by the CMS and a hash stored on the relay so future
   dashboard logins work offline of the CMS). This is a one-time **copy**, not a
   live federation — the dashboard keeps working if the CMS is down or changes.

Everything else (station claim, subdomain, portal, tunnel) is unchanged and
already built on the relay.

---

## The ONE CMS change (apply in the Laravel app)

A single read-only endpoint that answers "are these customer credentials valid?"
Nothing else in the CMS changes; no schema changes.

`routes/web.php`:
```php
Route::post('/api/v1/verify-customer', [PortalController::class,'verifyCustomer'])
    ->middleware('throttle:20,1');
```

`PortalController`:
```php
// POST /api/v1/verify-customer  { email, password }
// Header: X-DD-Bridge: <shared secret>   (config: services.dashboard.bridge_secret)
public function verifyCustomer(Request $r) {
    if (!hash_equals((string)config('services.dashboard.bridge_secret'),
                     (string)$r->header('X-DD-Bridge')))
        return response()->json(['ok'=>false,'error'=>'unauthorised'], 401);
    $v = $r->validate(['email'=>'required|email','password'=>'required']);
    $u = \App\Models\User::where('email',$v['email'])->where('role','customer')->first();
    if (!$u || !\Hash::check($v['password'],$u->password))
        return response()->json(['ok'=>false], 200);        // do not reveal which
    return response()->json(['ok'=>true,'name'=>$u->name,'email'=>$u->email]);
}
```

`config/services.php`:
```php
'dashboard' => ['bridge_secret' => env('DASHBOARD_BRIDGE_SECRET')],
```
Set the same `DASHBOARD_BRIDGE_SECRET` on the relay (its `_config.php` /
`DRONEDINGO_BRIDGE_SECRET`). The bridge secret only authorises the yes/no
credential check — it grants no access to customer data.

That's the entire CMS surface. If you'd rather not touch the CMS at all yet,
skip it — option 1 (fresh dashboard account) works with nothing added, and the
import can be switched on later.

---

## Relay side (built here)

- `account-import.php` — `{email,password}` → calls the CMS
  `/api/v1/verify-customer` with the bridge secret; on `ok`, upserts a dashboard
  `accounts` row (email + a PBKDF2/bcrypt hash of the just-verified password) and
  returns a session token, exactly like `account-login.php`.
- Existing `account-signup.php`, `account-login.php`, `station-claim.php`,
  `subdomain-check.php`, `account-stations.php`, the portal and the tunnel are
  unchanged.

## Appliance side (built here)

First-boot wizard → **Remote access** step:
1. Choose: *Create account* / *I have a dashboard account* / *Use my
   dronedingo.com.au account*.
2. Enter email + password (→ signup / login / import on the relay).
3. Pick a subdomain (live availability) + station name → claim → enable remote
   access. Multiple stations = claim each to the same account.
