<?php
// Log in to an existing DroneDingo cloud account and return a session token.
// Used by the first-boot wizard when the customer already has an account (e.g.
// installing a second station), and by the dashboard portal.
require __DIR__ . '/_db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    out(['ok' => false, 'error' => 'POST only'], 405);
}

$b = json_body();
$email = strtolower(trim((string)($b['email'] ?? '')));
$pass  = (string)($b['password'] ?? '');

$pdo = db();
$st = $pdo->prepare('SELECT id, pass_hash FROM accounts WHERE email = ?');
$st->execute([$email]);
$acc = $st->fetch(PDO::FETCH_ASSOC);

// Constant-ish work whether or not the account exists.
if (!$acc || !password_verify($pass, $acc['pass_hash'])) {
    out(['ok' => false, 'error' => 'Wrong email or password.'], 401);
}

$token = new_session_token();
$pdo->prepare('INSERT INTO account_sessions (token, account_id, created) VALUES (?,?,?)')
    ->execute([$token, (int)$acc['id'], time()]);

out(['ok' => true, 'token' => $token, 'email' => $email]);
