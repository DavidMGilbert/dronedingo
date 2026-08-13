<?php
// Link this station (node) to a customer account under a chosen subdomain, so
// it's reachable at <subdomain>.dashboard.dronedingo.com.au and shows up on the
// account. Authenticated on BOTH sides: the appliance proves its node with its
// per-node key, and the user proves the account with their session token.
require __DIR__ . '/_db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    out(['ok' => false, 'error' => 'POST only'], 405);
}

$b = json_body();
$node  = trim((string)($b['node'] ?? ''));
$key   = (string)($b['key'] ?? '');
$token = (string)($b['token'] ?? '');
$sub   = strtolower(trim((string)($b['subdomain'] ?? '')));
$label = trim((string)($b['label'] ?? ''));

$pdo = db();
if (!node_authorized($pdo, $node, $key)) {
    out(['ok' => false, 'error' => 'appliance not authorised'], 401);
}
$account_id = account_from_token($pdo, $token);
if ($account_id === null) {
    out(['ok' => false, 'error' => 'please sign in again'], 401);
}

$reserved = ['www', 'dashboard', 'api', 'app', 'notify', 'admin', 'mail', 'relay'];
if (!preg_match('/^[a-z0-9]([a-z0-9-]{1,38}[a-z0-9])$/', $sub) || in_array($sub, $reserved, true)) {
    out(['ok' => false, 'error' => 'Choose 3–40 chars: lowercase letters, numbers and hyphens.'], 400);
}
if ($label === '') $label = ucfirst($sub);
if (strlen($label) > 80) $label = substr($label, 0, 80);

// Subdomain must be free (unless this very node already holds it).
$st = $pdo->prepare('SELECT node FROM account_nodes WHERE subdomain = ?');
$st->execute([$sub]);
$owner = $st->fetchColumn();
if ($owner !== false && $owner !== $node) {
    out(['ok' => false, 'error' => 'That subdomain is taken — pick another.'], 409);
}

// A node belongs to exactly one account. Re-claiming by the same account just
// updates the subdomain/label; a different account can't steal it.
$st = $pdo->prepare('SELECT account_id FROM account_nodes WHERE node = ?');
$st->execute([$node]);
$cur = $st->fetchColumn();
if ($cur !== false && (int)$cur !== $account_id) {
    out(['ok' => false, 'error' => 'This station is already linked to another account.'], 409);
}

if ($cur === false) {
    $pdo->prepare('INSERT INTO account_nodes (account_id, node, subdomain, label, created)
                   VALUES (?,?,?,?,?)')
        ->execute([$account_id, $node, $sub, $label, time()]);
} else {
    $pdo->prepare('UPDATE account_nodes SET subdomain = ?, label = ? WHERE node = ?')
        ->execute([$sub, $label, $node]);
}

out(['ok' => true, 'subdomain' => $sub, 'label' => $label,
     'url' => 'https://' . $sub . '.dashboard.dronedingo.com.au']);
