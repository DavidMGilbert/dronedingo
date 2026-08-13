# Remote access — CMS (Laravel) integration spec

How the remote-access dashboard links to the **existing** dronedingo.com.au store
accounts and appliance registry, instead of a separate account system.

## Roles (federated, each owns one thing)

- **CMS (Laravel)** — the authority for **identity + ownership**: customers
  (`users.role='customer'`, already there) and appliances (`appliances` table,
  already there). We add the link `appliance → user + subdomain`, and let the
  CMS mint short **signed grants** to open a station.
- **Relay (PHP + SQLite, notify/dashboard cPanel)** — **transport only**: the
  tunnel request queue and the per-node device key. It does NOT store accounts;
  it verifies a CMS grant, then proxies to the node over the tunnel.
- **Appliance** — enrolls with the relay for the tunnel (per-node key), and
  during first-boot claims itself to a customer account **via the CMS**, proving
  its node with the `updates.token` it already ships with.

The appliance's `node_id` is the shared key between CMS and relay. Nothing else
is duplicated. The relay's standalone `accounts` / `account_nodes` /
`account-signup|login|station-claim` are **retired** — the CMS replaces them.

---

## 1. CMS changes (apply in the Laravel app)

### 1a. Migration — link appliances to customers + a subdomain
```php
Schema::table('appliances', function (Blueprint $t) {
    $t->foreignId('user_id')->nullable()->after('label')->constrained('users')->nullOnDelete();
    $t->string('subdomain')->nullable()->unique()->after('user_id');
    $t->timestamp('claimed_at')->nullable()->after('subdomain');
});
```

### 1b. Models
```php
// User.php
public function appliances(){ return $this->hasMany(\App\Models\Appliance::class); }
// Appliance.php  (add to $casts as needed; guarded=[] already allows fill)
public function user(){ return $this->belongsTo(User::class); }
```

### 1c. Config — the grant secret shared with the relay
`config/services.php`:
```php
'dashboard' => [
    'grant_secret' => env('DASHBOARD_GRANT_SECRET'),   // 32+ random bytes, hex
    'base'         => env('DASHBOARD_BASE', 'dashboard.dronedingo.com.au'),
],
```
Set the **same** `DASHBOARD_GRANT_SECRET` in the relay (see §2).

### 1d. Routes (`routes/web.php`)
```php
// Appliance-facing claim API (bearer = the appliance's updates.token)
Route::post('/api/v1/stations/claim',   [StationController::class,'claim'])->middleware('throttle:20,1');
Route::get ('/api/v1/stations/subdomain-available', [StationController::class,'available'])->middleware('throttle:60,1');

// Customer-facing: inside the existing account portal (session guard)
Route::prefix('account')->group(function () {
    Route::get('/stations',                 [StationController::class,'mine'])->name('portal.stations');
    Route::get('/stations/{appliance}/open',[StationController::class,'open'])->name('portal.station.open');
});
```

### 1e. `StationController`
```php
// bearer updates.token -> Appliance (reuses the update service's scheme)
private function appliance(Request $r): Appliance {
    $plain = (string) $r->bearerToken();
    $a = Appliance::where('token_hash', hash('sha256', $plain))->first();
    abort_unless($a && $a->active, 401, 'Invalid or revoked appliance token.');
    return $a;
}

// POST /api/v1/stations/claim  { email, password, subdomain, label }  (+ bearer token)
public function claim(Request $r) {
    $a = $this->appliance($r);
    $v = $r->validate([
        'email'=>'required|email','password'=>'required',
        'subdomain'=>'required|regex:/^[a-z0-9]([a-z0-9-]{1,38}[a-z0-9])$/',
        'label'=>'nullable|max:80',
    ]);
    $reserved=['www','dashboard','api','app','notify','admin','mail','relay','update'];
    if (in_array($v['subdomain'],$reserved,true))
        return response()->json(['ok'=>false,'error'=>'That subdomain is reserved.'],422);
    $u = User::where('email',$v['email'])->where('role','customer')->first();
    if (!$u || !Hash::check($v['password'],$u->password))
        return response()->json(['ok'=>false,'error'=>'Wrong email or password.'],401);
    $taken = Appliance::where('subdomain',$v['subdomain'])->where('id','!=',$a->id)->exists();
    if ($taken) return response()->json(['ok'=>false,'error'=>'That subdomain is taken.'],409);
    if ($a->user_id && $a->user_id !== $u->id)
        return response()->json(['ok'=>false,'error'=>'This station is linked to another account.'],409);
    $a->update(['user_id'=>$u->id,'subdomain'=>$v['subdomain'],
                'label'=>$v['label']??$a->label,'claimed_at'=>now()]);
    return response()->json(['ok'=>true,'subdomain'=>$a->subdomain,
        'url'=>'https://'.$a->subdomain.'.'.config('services.dashboard.base').'/']);
}

// GET /api/v1/stations/subdomain-available?s=foo
public function available(Request $r) {
    $s = strtolower((string)$r->query('s',''));
    $ok = preg_match('/^[a-z0-9]([a-z0-9-]{1,38}[a-z0-9])$/',$s)
        && !in_array($s,['www','dashboard','api','app','notify','admin','mail','relay','update'],true);
    $free = $ok && !Appliance::where('subdomain',$s)->exists();
    return response()->json(['ok'=>true,'valid'=>(bool)$ok,'available'=>$free]);
}

// GET /account/stations -> list the customer's stations (portal view)
public function mine() {
    $u = auth()->user(); abort_unless($u && $u->role==='customer',403);
    return view('portal.stations', ['stations'=>$u->appliances()->get()]);
}

// GET /account/stations/{appliance}/open -> mint a grant + redirect to the station
public function open(Appliance $appliance) {
    $u = auth()->user(); abort_unless($u && $u->role==='customer',403);
    abort_unless($appliance->user_id === $u->id && $appliance->subdomain, 403);
    $exp = time() + 90;                       // grant is single-use-ish, short lived
    $msg = $appliance->node_id.'|'.$u->id.'|'.$exp;
    $sig = hash_hmac('sha256', $msg, config('services.dashboard.grant_secret'));
    $q = http_build_query(['n'=>$appliance->node_id,'u'=>$u->id,'e'=>$exp,'s'=>$sig]);
    return redirect()->away('https://'.$appliance->subdomain.'.'.config('services.dashboard.base').'/__grant?'.$q);
}
```

### 1f. Portal view `resources/views/portal/stations.blade.php`
A simple list of `$stations` (label, subdomain, `last_seen_at` for online) with an
**Open** button linking to `route('portal.station.open',$s)`. Add a "Your
DroneDingo stations" card/link to the existing `portal.dashboard` view.

---

## 2. Relay changes (I build)

- `__grant` handler on `*.dashboard`: verify `hash_hmac` with the shared
  `DASHBOARD_GRANT_SECRET`, check `e` (expiry) and that `n` matches the host's
  subdomain's node, then set a short **HttpOnly session cookie** and redirect to
  `/`. Subsequent requests proxy via the tunnel using `n` from the cookie.
- Subdomain→node: carried in the grant (`n`), so the relay needs no account DB.
- Retire `account-signup.php`, `account-login.php`, `station-claim.php`,
  `account-stations.php`, `subdomain-check.php`, and the standalone portal/login;
  the CMS owns all of that now. Keep `tunnel-poll/respond`, `enroll`, push.

## 3. Appliance changes (I build)

- First-boot wizard: after admin password + Home Base, a **Remote access** step:
  "Sign in with your dronedingo.com.au account" (email + password) + choose a
  subdomain (live availability via the CMS) + station name → the appliance POSTs
  to the CMS `/api/v1/stations/claim` with its `updates.token` as the bearer →
  on success, enable remote access (start the tunnel) and store the URL.
- Settings → System → Remote access shows the linked account + station URL.

## Security notes

- The customer authenticates with their **store** password (bcrypt, via
  `Hash::check`); the appliance proves its identity with the `updates.token` it
  already holds — so only the genuine device can claim, and only to an account
  whose credentials the person at the device knows.
- The grant is HMAC-signed, node-bound and ~90s TTL; the relay never trusts a
  subdomain→node mapping it wasn't handed in a valid grant.
- Multiple stations on one account: a customer claims each unit to the same
  login; the `/account` portal lists them all.
