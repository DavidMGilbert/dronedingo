<?php
// An appliance enrolls itself here on first boot: it claims its node id and
// registers a HASH of its own unique key. Thereafter only that key can read the
// node's parked registrations (pending.php / ack.php).
//
// Auth: the firmware bootstrap secret (enroll_secret). This only permits
// claiming/refreshing a node — it never exposes any node's registrations.
// Claim protection: once a node is enrolled, a *different* key is rejected, so
// one appliance cannot hijack another's node id.
require __DIR__ . '/_db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    out(['ok' => false, 'error' => 'POST only'], 405);
}

$b = json_body();
$node = trim((string)($b['node'] ?? ''));
$key = (string)($b['key'] ?? '');
$secret = (string)($b['secret'] ?? '');

if (!hash_equals(enroll_secret(), $secret)) {
    out(['ok' => false, 'error' => 'enrollment not authorised'], 401);
}
if ($node === '' || strlen($node) > 64 || strlen($key) < 16 || strlen($key) > 128) {
    out(['ok' => false, 'error' => 'invalid node or key'], 400);
}

$pdo = db();
$st = $pdo->prepare('SELECT key_hash FROM appliances WHERE node = ?');
$st->execute([$node]);
$hash = $st->fetchColumn();

if ($hash !== false) {
    // Already claimed — only the same key may re-enroll (idempotent, e.g. after
    // a reinstall that kept state). A different key means someone else holds it.
    if (!password_verify($key, $hash)) {
        out(['ok' => false, 'error' => 'node already enrolled to another key'], 409);
    }
    $pdo->prepare('UPDATE appliances SET last_seen = ? WHERE node = ?')
        ->execute([time(), $node]);
    out(['ok' => true, 'enrolled' => true, 'status' => 'refreshed']);
}

$now = time();
$pdo->prepare('INSERT INTO appliances (node, key_hash, created, last_seen) VALUES (?,?,?,?)')
    ->execute([$node, password_hash($key, PASSWORD_DEFAULT), $now, $now]);
out(['ok' => true, 'enrolled' => true, 'status' => 'created']);
