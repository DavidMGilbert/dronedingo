<?php
// Dynamic web app manifest.
//
// When a phone "Adds to Home Screen", both Android (Chrome/WebAPK) and iOS
// launch the INSTALLED app at the manifest's start_url — not the URL that was
// open — so a static start_url of "/" drops the scanned registration params
// (node/token/key). We therefore bake those params into start_url here: the
// index page points this manifest's <link> at manifest.php + the same query, so
// the Home-Screen launch reopens the page WITH the registration intact.
header('Content-Type: application/manifest+json');
header('Cache-Control: no-store');

// Registration params are short and from a base64url alphabet; hard-filter them.
function clean(string $v): string {
    return preg_replace('/[^A-Za-z0-9_.\-]/', '', $v);
}
$node = clean((string)($_GET['node'] ?? ''));
$t    = clean((string)($_GET['t'] ?? ($_GET['token'] ?? '')));
$k    = clean((string)($_GET['k'] ?? ''));

$start = '/';
if ($node !== '' && $t !== '' && $k !== '') {
    $start = '/?node=' . rawurlencode($node)
           . '&t=' . rawurlencode($t)
           . '&k=' . rawurlencode($k);
}

echo json_encode([
    'name'             => 'DroneDingo Alerts',
    'short_name'       => 'DroneDingo',
    'description'      => 'Drone detection alerts for your property',
    'start_url'        => $start,
    'scope'            => '/',
    'display'          => 'standalone',
    'background_color' => '#061416',
    'theme_color'      => '#0c2224',
    'icons'            => [
        ['src' => '/icons/icon-192.png', 'sizes' => '192x192', 'type' => 'image/png', 'purpose' => 'any'],
        ['src' => '/icons/icon-512.png', 'sizes' => '512x512', 'type' => 'image/png', 'purpose' => 'any maskable'],
    ],
], JSON_UNESCAPED_SLASHES);
