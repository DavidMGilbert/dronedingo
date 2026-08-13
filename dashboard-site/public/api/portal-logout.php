<?php
require __DIR__ . '/../_boot.php';
$pdo = db();
$tok = $_COOKIE['dd_dash'] ?? '';
if ($tok !== '') {
    $pdo->prepare('DELETE FROM account_sessions WHERE token = ?')->execute([$tok]);
}
setcookie('dd_dash', '', [
    'expires' => time() - 3600, 'path' => '/',
    'domain' => dash_cookie_domain() ?: '', 'httponly' => true, 'samesite' => 'Lax',
]);
header('Location: /');
