<?php
// Browser-facing side of the remote-access tunnel. Every request for a client's
// appliance lands here (as the dashboard front controller): it queues the
// request for that node, waits for the appliance to run it and post the
// response back, then returns that response to the browser.
//
// In production this is the dashboard docroot's front controller (an .htaccess
// rewrite sends all paths to it) and the node comes from the subdomain
// <node>.dashboard.dronedingo.com.au. For local testing, pass ?__node= & ?__path=.
require __DIR__ . '/api/_db.php';

// --- which appliance? ------------------------------------------------------
function tunnel_node(): string {
    if (!empty($_GET['__node'])) return preg_replace('/[^A-Za-z0-9_.\-]/', '', $_GET['__node']);
    if (!empty($_SERVER['HTTP_X_DD_NODE'])) return preg_replace('/[^A-Za-z0-9_.\-]/', '', $_SERVER['HTTP_X_DD_NODE']);
    // <node>.dashboard.dronedingo.com.au  → first label is the node id
    $host = $_SERVER['HTTP_HOST'] ?? '';
    $parts = explode('.', $host);
    if (count($parts) >= 4) return preg_replace('/[^A-Za-z0-9_.\-]/', '', $parts[0]);
    return '';
}

$node = tunnel_node();
if ($node === '') {
    http_response_code(400);
    header('Content-Type: text/plain');
    echo "No appliance specified."; exit;
}

// --- reconstruct the browser request --------------------------------------
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = $_GET['__path'] ?? ($_SERVER['REQUEST_URI'] ?? '/');
// Strip our own query markers when they were used for local testing.
$path = preg_replace('/([?&])__(node|path)=[^&]*/', '$1', $path);
$path = rtrim(preg_replace('/[?&]$/', '', $path), '?&');
if ($path === '' || $path[0] !== '/') $path = '/' . $path;

$fwd = [];
foreach (($_SERVER ?? []) as $k => $v) {
    if (strpos($k, 'HTTP_') !== 0) continue;
    $name = str_replace(' ', '-', ucwords(strtolower(str_replace('_', ' ', substr($k, 5)))));
    if (in_array(strtolower($name), ['host', 'x-dd-node', 'connection', 'content-length'])) continue;
    $fwd[$name] = $v;
}
if (!empty($_SERVER['CONTENT_TYPE'])) $fwd['Content-Type'] = $_SERVER['CONTENT_TYPE'];
$body = file_get_contents('php://input');

// --- queue it and wait for the appliance ----------------------------------
$pdo = db();
tunnel_gc($pdo);
$ins = $pdo->prepare(
    'INSERT INTO tunnel (node, method, path, req_headers, req_body, created)
     VALUES (?,?,?,?,?,?)');
$ins->execute([$node, $method, $path, json_encode($fwd),
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
    usleep(250000);   // 250ms
} while (time() < $deadline);

// Appliance never answered — offline or remote access disabled.
http_response_code(504);
header('Content-Type: text/plain');
echo "The appliance is not responding (offline or remote access is off).";
