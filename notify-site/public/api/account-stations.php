<?php
// List the stations owned by an account (dashboard portal + wizard confirmation).
require __DIR__ . '/_db.php';

$b = json_body();
$token = (string)($b['token'] ?? $_GET['token'] ?? '');

$pdo = db();
$account_id = account_from_token($pdo, $token);
if ($account_id === null) {
    out(['ok' => false, 'error' => 'unauthorized'], 401);
}

$st = $pdo->prepare(
    'SELECT an.node, an.subdomain, an.label, ap.last_seen
       FROM account_nodes an
       LEFT JOIN appliances ap ON ap.node = an.node
      WHERE an.account_id = ?
      ORDER BY an.label');
$st->execute([$account_id]);
$now = time();
$stations = array_map(fn($r) => [
    'node'      => $r['node'],
    'subdomain' => $r['subdomain'],
    'label'     => $r['label'],
    'url'       => 'https://' . $r['subdomain'] . '.dashboard.dronedingo.com.au',
    'last_seen' => $r['last_seen'] ? (int)$r['last_seen'] : null,
    'online'    => $r['last_seen'] && ((int)$r['last_seen'] > $now - 120),
], $st->fetchAll(PDO::FETCH_ASSOC));

out(['ok' => true, 'stations' => $stations]);
