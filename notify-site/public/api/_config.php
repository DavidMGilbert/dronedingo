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

// SQLite mailbox, kept one level ABOVE the web root.
function db_path(): string {
    return __DIR__ . '/../../../notify-data/notify.sqlite';
}
