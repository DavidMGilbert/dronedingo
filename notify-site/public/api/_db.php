<?php
require __DIR__ . '/_config.php';

function db(): PDO {
    $path = db_path();
    $dir = dirname($path);
    if (!is_dir($dir)) {
        @mkdir($dir, 0770, true);
    }
    $pdo = new PDO('sqlite:' . $path);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec('CREATE TABLE IF NOT EXISTS pending (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        node TEXT NOT NULL,
        token TEXT NOT NULL,
        subscription TEXT NOT NULL,
        created INTEGER NOT NULL)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS idx_pending_node ON pending(node)');
    // One row per enrolled appliance. Each holds only a HASH of that
    // appliance's unique key, so a database leak never yields usable keys.
    $pdo->exec('CREATE TABLE IF NOT EXISTS appliances (
        node TEXT PRIMARY KEY,
        key_hash TEXT NOT NULL,
        created INTEGER NOT NULL,
        last_seen INTEGER NOT NULL)');
    // Remote-access tunnel queue: one row per proxied browser request. The
    // browser side inserts a request and waits; the appliance long-polls, runs
    // it locally and writes the response back. Store-and-forward, like push —
    // no persistent connection, so it runs on shared PHP hosting.
    $pdo->exec('CREATE TABLE IF NOT EXISTS tunnel (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        node TEXT NOT NULL,
        method TEXT NOT NULL,
        path TEXT NOT NULL,
        req_headers TEXT,
        req_body TEXT,
        claimed INTEGER,
        status INTEGER,
        res_headers TEXT,
        res_body TEXT,
        created INTEGER NOT NULL,
        done INTEGER)');
    $pdo->exec('CREATE INDEX IF NOT EXISTS idx_tunnel_node ON tunnel(node, status)');
    return $pdo;
}

// Drop tunnel rows older than 60s so a stalled request never lingers.
function tunnel_gc(PDO $pdo): void {
    $pdo->prepare('DELETE FROM tunnel WHERE created < ?')->execute([time() - 60]);
}

/**
 * Authorise an appliance for a node. Each appliance may only touch its own
 * mailbox: the presented key must match the hash stored at enrollment.
 *
 * Migration grace: if the node has never enrolled AND a legacy global relay
 * key is still configured, accept that instead — so a fleet can roll over to
 * per-node keys without a flag day. Once a node enrolls, only its own key works.
 */
function node_authorized(PDO $pdo, string $node, string $key): bool {
    if ($node === '' || $key === '') {
        return false;
    }
    $st = $pdo->prepare('SELECT key_hash FROM appliances WHERE node = ?');
    $st->execute([$node]);
    $hash = $st->fetchColumn();
    if ($hash !== false) {
        if (password_verify($key, $hash)) {
            $pdo->prepare('UPDATE appliances SET last_seen = ? WHERE node = ?')
                ->execute([time(), $node]);
            return true;
        }
        return false;
    }
    // Not enrolled yet — allow the legacy shared key during rollout, if set.
    $legacy = relay_key();
    return $legacy !== '' && hash_equals($legacy, $key);
}

function json_body(): array {
    $d = json_decode(file_get_contents('php://input'), true);
    return is_array($d) ? $d : [];
}

function out($data, int $code = 200): void {
    http_response_code($code);
    header('Content-Type: application/json');
    header('Cache-Control: no-store');
    echo json_encode($data);
    exit;
}
