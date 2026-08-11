<?php
// A phone posts its push subscription here after subscribing with the
// appliance's VAPID key. Unauthenticated by design: the appliance only ACCEPTS
// a subscription whose one-time token it actually minted, so junk is discarded
// on the appliance and never becomes a live subscription.
require __DIR__ . '/_db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    out(['ok' => false, 'error' => 'POST only'], 405);
}

$b = json_body();
$node = trim((string)($b['node'] ?? ''));
$token = trim((string)($b['token'] ?? ''));
$sub = $b['subscription'] ?? null;

if ($node === '' || $token === '' || !is_array($sub)
    || empty($sub['endpoint']) || empty($sub['keys']['p256dh']) || empty($sub['keys']['auth'])) {
    out(['ok' => false, 'error' => 'invalid registration'], 400);
}
if (strlen($node) > 64 || strlen($token) > 64 || strlen(json_encode($sub)) > 4000) {
    out(['ok' => false, 'error' => 'too large'], 400);
}

$pdo = db();
$pdo->exec('DELETE FROM pending WHERE created < ' . (time() - 86400)); // tidy old
$st = $pdo->prepare('INSERT INTO pending (node, token, subscription, created) VALUES (?,?,?,?)');
$st->execute([$node, $token, json_encode($sub), time()]);

out(['ok' => true]);
