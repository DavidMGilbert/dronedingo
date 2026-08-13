<?php
// Dashboard front controller for *.dashboard.dronedingo.com.au.
//   • base host (dashboard.dronedingo.com.au) → account portal (login + stations)
//   • <station>.dashboard…            → account-gated proxy to that appliance
// An .htaccess rewrite routes every non-file path here.
require __DIR__ . '/_boot.php';

$pdo = db();
$sub = $_GET['__sub'] ?? dash_subdomain();   // ?__sub= for local testing

if ($sub === '') {
    require __DIR__ . '/portal.php';          // account portal
    exit;
}

$node = node_for_subdomain($pdo, $sub);
if ($node === '') {
    http_response_code(404);
    header('Content-Type: text/html');
    echo "<h1>Unknown station</h1><p>No DroneDingo is registered at <b>"
       . htmlspecialchars($sub) . "</b>.</p>";
    exit;
}

// Access control: the logged-in account must own this station. This is the real
// security boundary — the appliance trusts anything the tunnel delivers.
$aid = dash_account_id($pdo);
$owns = false;
if ($aid !== null) {
    $st = $pdo->prepare('SELECT 1 FROM account_nodes WHERE account_id = ? AND node = ?');
    $st->execute([$aid, $node]);
    $owns = (bool)$st->fetchColumn();
}
if (!$owns) {
    $nextUrl = 'https://' . ($_SERVER['HTTP_HOST'] ?? '') . ($_SERVER['REQUEST_URI'] ?? '/');
    header('Location: https://' . DASH_BASE . '/?next=' . urlencode($nextUrl));
    exit;
}

// Authorised — proxy the request to the station over the tunnel.
tunnel_serve($pdo, $node);
