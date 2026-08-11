<?php
// The appliance polls this to collect subscriptions parked for its node.
// Requires the shared relay key so parked subscriptions can't be read by anyone
// else. Does not delete — the appliance calls ack.php after it has ingested.
require __DIR__ . '/_db.php';

$b = json_body();
$node = trim((string)($b['node'] ?? $_GET['node'] ?? ''));
$key = (string)($b['key'] ?? $_GET['key'] ?? '');

if (!hash_equals(relay_key(), $key)) {
    out(['ok' => false, 'error' => 'unauthorized'], 401);
}
if ($node === '') {
    out(['ok' => false, 'error' => 'node required'], 400);
}

$pdo = db();
$st = $pdo->prepare('SELECT id, token, subscription FROM pending WHERE node = ? ORDER BY id LIMIT 100');
$st->execute([$node]);
$rows = array_map(fn($r) => [
    'id' => (int)$r['id'],
    'token' => $r['token'],
    'subscription' => json_decode($r['subscription'], true),
], $st->fetchAll(PDO::FETCH_ASSOC));

out(['ok' => true, 'pending' => $rows]);
