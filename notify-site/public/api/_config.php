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
// a per-node key. Must match the firmware's DRONEDINGO_ENROLL_SECRET.
const ENROLL_SECRET_FALLBACK = 'CHANGE-ME-to-a-long-random-enrollment-secret';

function enroll_secret(): string {
    $k = getenv('DRONEDINGO_ENROLL_SECRET');
    return ($k !== false && $k !== '') ? $k : ENROLL_SECRET_FALLBACK;
}

// SQLite database, kept OUTSIDE the web root so it is never downloadable.
// Default: a `notify-data/` dir a few levels above public/api (see below). On
// hosts with a different layout, set DRONEDINGO_DB_PATH to any writable path
// outside the docroot — e.g. /home/you/notify-data/notify.sqlite.
//
//   __DIR__ = <docroot>/api  →  ../../../notify-data resolves to a sibling of
//   the app folder, above the docroot. Holds two tables:
//     • pending    — parked push subscriptions awaiting appliance pickup
//                    (transient: deleted on ack, auto-tidied after 24h)
//     • appliances — one small row per enrolled device (node → key_hash)
//   No detection data is ever stored here.
function db_path(): string {
    $p = getenv('DRONEDINGO_DB_PATH');
    return ($p !== false && $p !== '') ? $p
        : __DIR__ . '/../../../notify-data/notify.sqlite';
}
