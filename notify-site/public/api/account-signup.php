<?php
// Create a DroneDingo cloud account (first-boot wizard) and return a session
// token. One account can own many stations.
require __DIR__ . '/_db.php';

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    out(['ok' => false, 'error' => 'POST only'], 405);
}

$b = json_body();
$email = strtolower(trim((string)($b['email'] ?? '')));
$pass  = (string)($b['password'] ?? '');

if (!filter_var($email, FILTER_VALIDATE_EMAIL) || strlen($email) > 190) {
    out(['ok' => false, 'error' => 'Enter a valid email address.'], 400);
}
if (strlen($pass) < 8) {
    out(['ok' => false, 'error' => 'Password must be at least 8 characters.'], 400);
}

$pdo = db();
$exists = $pdo->prepare('SELECT 1 FROM accounts WHERE email = ?');
$exists->execute([$email]);
if ($exists->fetchColumn()) {
    out(['ok' => false, 'error' => 'An account with that email already exists — log in instead.'], 409);
}

$pdo->prepare('INSERT INTO accounts (email, pass_hash, created) VALUES (?,?,?)')
    ->execute([$email, password_hash($pass, PASSWORD_DEFAULT), time()]);
$account_id = (int)$pdo->lastInsertId();

$token = new_session_token();
$pdo->prepare('INSERT INTO account_sessions (token, account_id, created) VALUES (?,?,?)')
    ->execute([$token, $account_id, time()]);

out(['ok' => true, 'token' => $token, 'email' => $email]);
