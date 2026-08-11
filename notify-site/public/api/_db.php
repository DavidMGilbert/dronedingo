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
    return $pdo;
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
