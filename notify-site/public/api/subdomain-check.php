<?php
// Live availability check for the first-boot wizard's subdomain field.
require __DIR__ . '/_db.php';

$sub = strtolower(trim((string)($_GET['s'] ?? '')));
$reserved = ['www', 'dashboard', 'api', 'app', 'notify', 'admin', 'mail', 'relay'];

if (!preg_match('/^[a-z0-9]([a-z0-9-]{1,38}[a-z0-9])$/', $sub) || in_array($sub, $reserved, true)) {
    out(['ok' => true, 'valid' => false, 'available' => false,
         'reason' => '3–40 chars: lowercase letters, numbers, hyphens']);
}
$pdo = db();
$st = $pdo->prepare('SELECT 1 FROM account_nodes WHERE subdomain = ?');
$st->execute([$sub]);
out(['ok' => true, 'valid' => true, 'available' => !$st->fetchColumn()]);
