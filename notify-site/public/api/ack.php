<?php
// The appliance calls this after ingesting, to clear the parked rows it took.
require __DIR__ . '/_db.php';

$b = json_body();
$key = (string)($b['key'] ?? '');
$ids = $b['ids'] ?? [];

if (!hash_equals(relay_key(), $key)) {
    out(['ok' => false, 'error' => 'unauthorized'], 401);
}
$ids = array_values(array_filter(array_map('intval', is_array($ids) ? $ids : [])));
if (!$ids) {
    out(['ok' => true, 'deleted' => 0]);
}

$in = implode(',', array_fill(0, count($ids), '?'));
$pdo = db();
$st = $pdo->prepare("DELETE FROM pending WHERE id IN ($in)");
$st->execute($ids);

out(['ok' => true, 'deleted' => $st->rowCount()]);
