<?php
// The appliance long-polls this for browser requests queued for its node. It
// authenticates with its own per-node key (same identity as push enrollment),
// so it can only ever see requests addressed to itself. Returns as soon as work
// is available, or an empty list after a short hold (the appliance re-polls).
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
tunnel_gc($pdo);

// Hold the connection up to ~25s, checking a few times a second. Kept under the
// typical 30s shared-host limit so the request completes cleanly, then the
// appliance immediately re-polls.
$deadline = time() + 25;
do {
    $pdo->beginTransaction();
    $st = $pdo->prepare(
        'SELECT id, method, path, req_headers, req_body FROM tunnel
         WHERE node = ? AND status IS NULL AND claimed IS NULL
         ORDER BY id LIMIT 20');
    $st->execute([$node]);
    $rows = $st->fetchAll(PDO::FETCH_ASSOC);
    if ($rows) {
        $ids = array_column($rows, 'id');
        $in = implode(',', array_fill(0, count($ids), '?'));
        $pdo->prepare("UPDATE tunnel SET claimed = ? WHERE id IN ($in)")
            ->execute(array_merge([time()], $ids));
        $pdo->commit();
        $reqs = array_map(fn($r) => [
            'id' => (int)$r['id'], 'method' => $r['method'], 'path' => $r['path'],
            'headers' => json_decode($r['req_headers'] ?: '{}', true),
            'body' => $r['req_body'],       // base64 or null
        ], $rows);
        out(['ok' => true, 'requests' => $reqs]);
    }
    $pdo->commit();
    usleep(300000);   // 300ms
} while (time() < $deadline);

out(['ok' => true, 'requests' => []]);
