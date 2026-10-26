<?php
// VisionPanel public API (PHP edition).
//
// Optional standalone backend for shared PHP hosting: serves the same public
// read endpoints as the FastAPI backend, reading the same SQLite database.
// The desktop client keeps using the FastAPI host; this file exists so the
// panel can also be deployed on PHP-only hosting.
//
// Endpoints:
//   GET  /api/public/verified/{telegram_id}   -> {telegram_id, verified}
//   POST /api/public/verified                 -> {verified: [ids]}
//   GET  /api/public/avatar-shape/{id}        -> {telegram_id, shape}
//   POST /api/public/avatar-shapes            -> {shapes: [...]}
//   GET  /health                              -> {ok: true}

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Authorization');

if (($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'OPTIONS') {
    http_response_code(204);
    exit;
}

$dbPath = getenv('DB_PATH') ?: (dirname(__DIR__) . DIRECTORY_SEPARATOR . 'visiongram.db');
if (!is_file($dbPath)) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'database not found']);
    exit;
}

try {
    $db = new PDO('sqlite:' . $dbPath, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'database unavailable']);
    exit;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/';
$body = json_decode((string) file_get_contents('php://input'), true) ?: [];

function send(array $payload, int $code = 200): void {
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

function isVerifiedRow(PDO $db, int $telegramId): bool {
    $statement = $db->prepare('SELECT 1 FROM verified WHERE telegram_id = :id');
    $statement->bindValue(':id', $telegramId, PDO::PARAM_INT);
    $statement->execute();
    return $statement->fetchColumn() !== false;
}

function avatarShapeRow(PDO $db, int $telegramId): string {
    $statement = $db->prepare('SELECT shape FROM avatar_shapes WHERE telegram_id = :id');
    $statement->bindValue(':id', $telegramId, PDO::PARAM_INT);
    $statement->execute();
    $shape = $statement->fetchColumn();
    return is_string($shape) && $shape !== '' ? $shape : 'circle';
}

if ($uri === '/health' && $method === 'GET') {
    send(['ok' => true, 'service' => 'visionpanel-php']);
}

if (preg_match('#^/api/public/verified/(\d+)$#', $uri, $matches) && $method === 'GET') {
    $telegramId = (int) $matches[1];
    send([
        'telegram_id' => $telegramId,
        'verified' => isVerifiedRow($db, $telegramId),
    ]);
}

if ($uri === '/api/public/verified' && $method === 'POST') {
    $ids = array_values(array_unique(array_map('intval', $body['telegram_ids'] ?? [])));
    $verified = array_values(array_filter(
        $ids,
        fn (int $id): bool => isVerifiedRow($db, $id)
    ));
    send(['verified' => $verified]);
}

if (preg_match('#^/api/public/avatar-shape/(\d+)$#', $uri, $matches) && $method === 'GET') {
    $telegramId = (int) $matches[1];
    send([
        'telegram_id' => $telegramId,
        'shape' => avatarShapeRow($db, $telegramId),
    ]);
}

if ($uri === '/api/public/avatar-shapes' && $method === 'POST') {
    $ids = array_values(array_unique(array_map('intval', $body['telegram_ids'] ?? [])));
    $shapes = array_map(
        fn (int $id): array => ['telegram_id' => $id, 'shape' => avatarShapeRow($db, $id)],
        $ids
    );
    send(['shapes' => $shapes]);
}

send(['ok' => false, 'error' => 'not found'], 404);
