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
    // Concurrency: push polling, the tunnel and the dashboard all hit this DB at
    // once. WAL lets many readers run alongside a writer (needed for the tunnel's
    // tight poll loops on Linux hosts); the busy timeout retries brief write
    // contention, and the tunnel endpoints use short autocommit statements so no
    // lock is held long. (WAL's cross-process reads are flaky only under Windows
    // `php -S`, which isn't a deployment target.)
    $pdo->exec('PRAGMA busy_timeout=8000');
    @$pdo->exec('PRAGMA journal_mode=WAL');
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
    // --- multi-station accounts (self-service onboarding) ------------------
    // A customer account owns one or more stations. On first boot the appliance
    // walks the user through signup/login and claims a subdomain, linking the
    // node to the account — so one account can gather many stations.
    $pdo->exec('CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        pass_hash TEXT NOT NULL,
        created INTEGER NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS account_nodes (
        account_id INTEGER NOT NULL,
        node TEXT NOT NULL,
        subdomain TEXT UNIQUE,
        label TEXT,
        created INTEGER NOT NULL,
        PRIMARY KEY (account_id, node))');
    $pdo->exec('CREATE INDEX IF NOT EXISTS idx_acctnode_node ON account_nodes(node)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS account_sessions (
        token TEXT PRIMARY KEY,
        account_id INTEGER NOT NULL,
        created INTEGER NOT NULL)');
    return $pdo;
}

/** Resolve an account session token to an account id (30-day sessions). */
function account_from_token(PDO $pdo, string $token): ?int {
    if ($token === '') return null;
    $st = $pdo->prepare('SELECT account_id, created FROM account_sessions WHERE token = ?');
    $st->execute([$token]);
    $row = $st->fetch(PDO::FETCH_ASSOC);
    if (!$row) return null;
    if ((int)$row['created'] < time() - 30 * 86400) {
        $pdo->prepare('DELETE FROM account_sessions WHERE token = ?')->execute([$token]);
        return null;
    }
    return (int)$row['account_id'];
}

/** The node a dashboard subdomain maps to (or '' if unclaimed). */
function node_for_subdomain(PDO $pdo, string $sub): string {
    $st = $pdo->prepare('SELECT node FROM account_nodes WHERE subdomain = ?');
    $st->execute([strtolower($sub)]);
    $n = $st->fetchColumn();
    return $n !== false ? (string)$n : '';
}

function new_session_token(): string {
    return bin2hex(random_bytes(24));
}

// Drop tunnel rows older than 60s so a stalled request never lingers.
function tunnel_gc(PDO $pdo): void {
    $pdo->prepare('DELETE FROM tunnel WHERE created < ?')->execute([time() - 60]);
}

/**
 * Proxy the CURRENT browser request to a station over the tunnel: queue it, wait
 * for the appliance to run it and post the response, then emit that response.
 * Ends the request. Shared by the dashboard front controller and the test proxy.
 */
function tunnel_serve(PDO $pdo, string $node): void {
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $path = $_GET['__path'] ?? ($_SERVER['REQUEST_URI'] ?? '/');
    $path = preg_replace('/([?&])__(node|path)=[^&]*/', '$1', $path);
    $path = rtrim(preg_replace('/[?&]$/', '', $path), '?&');
    if ($path === '' || $path[0] !== '/') $path = '/' . $path;

    $fwd = [];
    foreach (($_SERVER ?? []) as $k => $v) {
        if (strpos($k, 'HTTP_') !== 0) continue;
        $name = str_replace(' ', '-', ucwords(strtolower(str_replace('_', ' ', substr($k, 5)))));
        if (in_array(strtolower($name), ['host', 'x-dd-node', 'connection', 'content-length', 'x-dd-tunnel-auth'])) continue;
        $fwd[$name] = $v;
    }
    if (!empty($_SERVER['CONTENT_TYPE'])) $fwd['Content-Type'] = $_SERVER['CONTENT_TYPE'];
    $body = file_get_contents('php://input');

    tunnel_gc($pdo);
    $pdo->prepare('INSERT INTO tunnel (node, method, path, req_headers, req_body, created)
                   VALUES (?,?,?,?,?,?)')
        ->execute([$node, $method, $path, json_encode($fwd),
                   $body === '' ? null : base64_encode($body), time()]);
    $id = (int)$pdo->lastInsertId();

    $sel = $pdo->prepare('SELECT status, res_headers, res_body FROM tunnel WHERE id = ?');
    $deadline = time() + 30;
    do {
        $sel->execute([$id]);
        $row = $sel->fetch(PDO::FETCH_ASSOC);
        if ($row && $row['status'] !== null) {
            http_response_code((int)$row['status']);
            foreach (json_decode($row['res_headers'] ?: '{}', true) as $hk => $hv) {
                if (in_array(strtolower($hk), ['transfer-encoding', 'connection', 'content-length'])) continue;
                header($hk . ': ' . $hv, true);
            }
            echo $row['res_body'] ? base64_decode($row['res_body']) : '';
            $pdo->prepare('DELETE FROM tunnel WHERE id = ?')->execute([$id]);
            exit;
        }
        usleep(250000);
    } while (time() < $deadline);

    http_response_code(504);
    header('Content-Type: text/plain');
    echo "The station is not responding (offline or remote access is off).";
    exit;
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
            // Touch last_seen at most once a minute — the tunnel polls every few
            // hundred ms, and a write per poll would thrash the DB lock.
            $pdo->prepare('UPDATE appliances SET last_seen = ? WHERE node = ? AND last_seen < ?')
                ->execute([time(), $node, time() - 60]);
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
