<?php
// Portal login: verify the account and set the shared HttpOnly session cookie
// (dd_dash), scoped to *.dashboard.dronedingo.com.au so one login unlocks all
// the account's stations. Redirects back to the portal (or ?next=).
require __DIR__ . '/../_boot.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') { http_response_code(405); exit; }

$email = strtolower(trim((string)($_POST['email'] ?? '')));
$pass  = (string)($_POST['password'] ?? '');
$next  = (string)($_POST['next'] ?? '');

$pdo = db();
$st = $pdo->prepare('SELECT id, pass_hash FROM accounts WHERE email = ?');
$st->execute([$email]);
$acc = $st->fetch(PDO::FETCH_ASSOC);

if (!$acc || !password_verify($pass, $acc['pass_hash'])) {
    header('Location: /?e=1' . ($next !== '' ? '&next=' . urlencode($next) : ''));
    exit;
}

$token = new_session_token();
$pdo->prepare('INSERT INTO account_sessions (token, account_id, created) VALUES (?,?,?)')
    ->execute([$token, (int)$acc['id'], time()]);

$secure = (($_SERVER['HTTPS'] ?? '') !== '') || (($_SERVER['SERVER_PORT'] ?? '') == 443);
setcookie('dd_dash', $token, [
    'expires' => time() + 30 * 86400,
    'path' => '/',
    'domain' => dash_cookie_domain() ?: '',
    'secure' => $secure,
    'httponly' => true,
    'samesite' => 'Lax',
]);

// Only allow same-site redirects.
$dest = '/';
if ($next !== '' && preg_match('#^https://[a-z0-9\-]+\.' . preg_quote(DASH_BASE, '#') . '/#i', $next)) {
    $dest = $next;
}
header('Location: ' . $dest);
