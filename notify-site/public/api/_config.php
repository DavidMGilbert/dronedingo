<?php
// Legacy fleet-wide relay key. With per-appliance enrollment this is now only a
// migration fallback for nodes that haven't enrolled yet (see node_authorized).
// Leave empty to require enrollment for everyone.
const RELAY_KEY_FALLBACK = '';

function relay_key(): string {
    $k = getenv('DRONEDINGO_RELAY_KEY');
    return ($k !== false && $k !== '') ? $k : RELAY_KEY_FALLBACK;
}

// Bootstrap secret an appliance presents to ENROLL itself (claim a node and
// register its own unique key). It only gates enrollment — it never grants
// access to any node's parked registrations, so it is far less sensitive than
// a per-node key. This default matches the firmware's DEFAULT_ENROLL_SECRET so
// appliances enroll out of the box; override with DRONEDINGO_ENROLL_SECRET.
const ENROLL_SECRET_FALLBACK = 'dd-enroll-ff250ec00af0b87fbac714941f3e8c1569cea4b507d2fb03';

function enroll_secret(): string {
    $k = getenv('DRONEDINGO_ENROLL_SECRET');
    return ($k !== false && $k !== '') ? $k : ENROLL_SECRET_FALLBACK;
}

// Optional bridge to the dronedingo.com.au CMS so a customer can reuse their
// store password instead of making a new dashboard account. Set both to enable;
// leave the secret empty to disable import (fresh signup still works).
function cms_bridge_secret(): string {
    $k = getenv('DRONEDINGO_BRIDGE_SECRET');
    return ($k !== false && $k !== '') ? $k : '';   // set to enable import
}
function cms_base_url(): string {
    $k = getenv('DRONEDINGO_CMS_URL');
    return ($k !== false && $k !== '') ? rtrim($k, '/') : 'https://dronedingo.com.au';
}
/** Ask the CMS whether these customer credentials are valid. yes/no only. */
function cms_verify_customer(string $email, string $pass): bool {
    $secret = cms_bridge_secret();
    if ($secret === '' || !function_exists('curl_init')) return false;
    $ch = curl_init(cms_base_url() . '/api/v1/verify-customer');
    curl_setopt_array($ch, [
        CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 10,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'X-DD-Bridge: ' . $secret],
        CURLOPT_POSTFIELDS => json_encode(['email' => $email, 'password' => $pass]),
    ]);
    $res = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($code !== 200 || !$res) return false;
    $d = json_decode($res, true);
    return is_array($d) && !empty($d['ok']);
}

// SQLite database. On shared hosting everything must live under public_html, so
// it sits in a `dd-data/` folder inside the docroot that is blocked from the web
// by its own deny-all .htaccess (and a global rule in the site .htaccess). It is
// therefore inside the web root but NOT downloadable. Set DRONEDINGO_DB_PATH to
// override (e.g. a path above the docroot on hosts that allow it).
//
//   Holds two tables — no detection data is ever stored here:
//     • pending    — parked push subscriptions awaiting appliance pickup
//                    (transient: deleted on ack, auto-tidied after 24h)
//     • appliances — one small row per enrolled device (node → key_hash)
function db_path(): string {
    $p = getenv('DRONEDINGO_DB_PATH');
    return ($p !== false && $p !== '') ? $p
        : __DIR__ . '/../dd-data/notify.sqlite';
}
