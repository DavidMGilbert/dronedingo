<?php
// The dashboard shares the relay's database and PHP helpers (accounts, tunnel,
// subdomain resolution) — same cPanel account, so we just include them rather
// than duplicate. Default assumes the relay docroot is a sibling named
// notify.dronedingo.com.au; override with DRONEDINGO_INCLUDES if it differs.
$__inc = getenv('DRONEDINGO_INCLUDES');
if ($__inc === false || $__inc === '') {
    $__inc = __DIR__ . '/../notify.dronedingo.com.au/api';
}
require $__inc . '/_db.php';

const DASH_BASE = 'dashboard.dronedingo.com.au';

// The account-session cookie is shared across every *.dashboard.dronedingo.com.au
// station, so one login unlocks all stations the account owns. On localhost (dev)
// it falls back to a host-only cookie.
function dash_cookie_domain(): string {
    $host = strtolower($_SERVER['HTTP_HOST'] ?? '');
    return (substr($host, -strlen(DASH_BASE)) === DASH_BASE) ? '.' . DASH_BASE : '';
}

// The station subdomain for this request, or '' when it's the portal host.
function dash_subdomain(): string {
    $host = strtolower(explode(':', $_SERVER['HTTP_HOST'] ?? '')[0]);
    $first = explode('.', $host)[0];
    if (in_array($first, ['dashboard', 'app', 'www', 'localhost', '127'], true)) return '';
    if ($host === DASH_BASE) return '';
    return preg_replace('/[^a-z0-9\-]/', '', $first);
}

function dash_account_id(PDO $pdo): ?int {
    return account_from_token($pdo, $_COOKIE['dd_dash'] ?? '');
}
