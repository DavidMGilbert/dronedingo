<?php
// Test/utility proxy: forward a request to a node over the tunnel. Node comes
// from ?__node= / X-DD-Node header / <node>.host subdomain. The real, access-
// controlled entry point is the dashboard front controller (dashboard-site).
require __DIR__ . '/api/_db.php';

$node = '';
if (!empty($_GET['__node'])) $node = preg_replace('/[^A-Za-z0-9_.\-]/', '', $_GET['__node']);
elseif (!empty($_SERVER['HTTP_X_DD_NODE'])) $node = preg_replace('/[^A-Za-z0-9_.\-]/', '', $_SERVER['HTTP_X_DD_NODE']);
else {
    $parts = explode('.', $_SERVER['HTTP_HOST'] ?? '');
    if (count($parts) >= 4) $node = preg_replace('/[^A-Za-z0-9_.\-]/', '', $parts[0]);
}
if ($node === '') { http_response_code(400); header('Content-Type: text/plain'); echo "No appliance specified."; exit; }

tunnel_serve(db(), $node);
