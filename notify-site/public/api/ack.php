<?php
// The appliance calls this after ingesting, to clear the parked rows it took.
require __DIR__ . '/_db.php';

$b = json_body();
$node = trim((string)($b['node'] ?? ''));
$key = (string)($b['key'] ?? '');
$ids = $b['ids'] ?? [];

$pdo = db();
if (!node_authorized($pdo, $node, $key)) {
    out(['ok' => false, 'error' => 'unauthorized'], 401);
}
$ids = array_values(array_filter(array_map('intval', is_array($ids) ? $ids : [])));
if (!$ids) {
    out(['ok' => true, 'deleted' => 0]);
}

// Scope the delete to this node so an appliance can only clear its own rows.
$in = implode(',', array_fill(0, count($ids), '?'));
$st = $pdo->prepare("DELETE FROM pending WHERE node = ? AND id IN ($in)");
$st->execute(array_merge([$node], $ids));

out(['ok' => true, 'deleted' => $st->rowCount()]);
