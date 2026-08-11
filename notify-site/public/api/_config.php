<?php
// Shared secret the appliances present when polling for their subscriptions.
// Prefer the environment variable; edit the fallback only for a quick start.
const RELAY_KEY_FALLBACK = 'CHANGE-ME-to-a-long-random-shared-secret';

function relay_key(): string {
    $k = getenv('DRONEDINGO_RELAY_KEY');
    return ($k !== false && $k !== '') ? $k : RELAY_KEY_FALLBACK;
}

// SQLite mailbox, kept one level ABOVE the web root.
function db_path(): string {
    return __DIR__ . '/../../../notify-data/notify.sqlite';
}
