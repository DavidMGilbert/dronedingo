<?php
// "Use my dronedingo.com.au account": verify the entered credentials against the
// CMS (via the bridge), then create/refresh a matching dashboard account and
// return a session token — a one-time copy, so the dashboard keeps working even
// if the CMS is later unreachable.
require __DIR__ . '/_db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    out(['ok' => false, 'error' => 'POST only'], 405);
}

$b = json_body();
$email = strtolower(trim((string)($b['email'] ?? '')));
$pass  = (string)($b['password'] ?? '');

if (!filter_var($email, FILTER_VALIDATE_EMAIL) || $pass === '') {
    out(['ok' => false, 'error' => 'Enter your email and password.'], 400);
}
if (cms_bridge_secret() === '') {
    out(['ok' => false, 'error' => 'Store sign-in is not available — create a dashboard account instead.'], 501);
}
if (!cms_verify_customer($email, $pass)) {
    out(['ok' => false, 'error' => 'Those details do not match your dronedingo.com.au account.'], 401);
}

$pdo = db();
$hash = password_hash($pass, PASSWORD_DEFAULT);   // so future dashboard logins work offline of the CMS
$st = $pdo->prepare('SELECT id FROM accounts WHERE email = ?');
$st->execute([$email]);
$id = $st->fetchColumn();
if ($id === false) {
    $pdo->prepare('INSERT INTO accounts (email, pass_hash, created) VALUES (?,?,?)')
        ->execute([$email, $hash, time()]);
    $id = (int)$pdo->lastInsertId();
} else {
    $pdo->prepare('UPDATE accounts SET pass_hash = ? WHERE id = ?')->execute([$hash, (int)$id]);
}

$token = new_session_token();
$pdo->prepare('INSERT INTO account_sessions (token, account_id, created) VALUES (?,?,?)')
    ->execute([$token, (int)$id, time()]);

out(['ok' => true, 'token' => $token, 'email' => $email, 'imported' => true]);
