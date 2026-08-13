<?php
// The appliance posts the response to a proxied request here. The waiting
// browser side (tunnel proxy) picks it up and returns it to the client.
require __DIR__ . '/_db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    out(['ok' => false, 'error' => 'POST only'], 405);
}

$b = json_body();
$node = trim((string)($b['node'] ?? ''));
$key  = (string)($b['key'] ?? '');

$pdo = db();
if (!node_authorized($pdo, $node, $key)) {
    out(['ok' => false, 'error' => 'unauthorized'], 401);
}

$id      = (int)($b['id'] ?? 0);
$status  = (int)($b['status'] ?? 502);
$headers = json_encode($b['headers'] ?? new stdClass());
$body    = (string)($b['body'] ?? '');       // base64

// Only the node that owns the row may answer it.
$st = $pdo->prepare(
    'UPDATE tunnel SET status = ?, res_headers = ?, res_body = ?, done = ?
     WHERE id = ? AND node = ?');
$st->execute([$status, $headers, $body, time(), $id, $node]);

out(['ok' => true, 'updated' => $st->rowCount()]);
