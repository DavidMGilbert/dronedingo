<?php
// Registration page, served through PHP so the manifest <link> carries this
// registration's params in the FIRST HTML iOS parses. iOS captures start_url
// from the manifest present at "Add to Home Screen" time and ignores later JS
// edits to the link href, so the params must be here server-side — not swapped
// in by script. The installed app then relaunches at start_url WITH node/t/k.
function dd_clean(string $v): string {
    return preg_replace('/[^A-Za-z0-9_.\-]/', '', $v);
}
$node = dd_clean((string)($_GET['node'] ?? ''));
$t    = dd_clean((string)($_GET['t'] ?? ($_GET['token'] ?? '')));
$k    = dd_clean((string)($_GET['k'] ?? ''));
$has_reg = ($node !== '' && $t !== '' && $k !== '');

$manifest = '/manifest.webmanifest';
if ($has_reg) {
    $manifest = '/manifest.php?node=' . rawurlencode($node)
              . '&t=' . rawurlencode($t) . '&k=' . rawurlencode($k);
}
?><!doctype html>
<html lang="en-AU">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>DroneDingo Alerts</title>
  <link rel="manifest" href="<?= htmlspecialchars($manifest, ENT_QUOTES) ?>" />
  <meta name="mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-title" content="DroneDingo" />
  <link rel="icon" type="image/png" href="/icons/favicon-64.png" />
  <link rel="apple-touch-icon" href="/icons/icon-192.png" />
  <meta name="theme-color" content="#0c2224" />
  <script>
    // Registration details injected server-side, so the app never depends on the
    // query string surviving the install/relaunch. (It also will, via start_url.)
    window.__DDREG = <?= $has_reg ? json_encode(['node' => $node, 't' => $t, 'k' => $k]) : 'null' ?>;
  </script>
  <style>
    @font-face{font-family:"Barlow";font-weight:400;font-display:swap;src:url("/icons/barlow-400.woff2") format("woff2")}
    @font-face{font-family:"Barlow";font-weight:600;font-display:swap;src:url("/icons/barlow-600.woff2") format("woff2")}
    @font-face{font-family:"Barlow Condensed";font-weight:800;font-display:swap;src:url("/icons/barlowcondensed-800.woff2") format("woff2")}
    :root{--accent:#ed9800;--vfd:#68ead0;--danger:#ef5d61}
    *{box-sizing:border-box}
    body{margin:0;min-height:100vh;min-height:100dvh;display:grid;place-items:center;padding:22px;
      color:#edf5f2;font:400 16px/1.5 "Barlow",system-ui,sans-serif;
      background:radial-gradient(circle at 80% 8%,rgba(237,152,0,.14),transparent 32%),
                 radial-gradient(circle at 12% 92%,rgba(104,234,208,.10),transparent 36%),#061416}
    .card{width:min(94vw,420px);background:rgba(14,36,38,.86);border:1px solid rgba(255,255,255,.14);
      border-radius:22px;padding:30px 26px;text-align:center;
      box-shadow:inset 1px 1px rgba(255,255,255,.08),0 20px 60px rgba(0,0,0,.45);
      backdrop-filter:blur(24px) saturate(140%);-webkit-backdrop-filter:blur(24px) saturate(140%)}
    img.mark{height:64px}
    h1{font-family:"Barlow Condensed",sans-serif;font-weight:800;font-size:30px;margin:14px 0 2px}
    h1 span{color:var(--accent)}
    .tag{color:#93a9a5;font-size:13px;margin:0 0 22px}
    p{color:#cfe0dc}
    button{width:100%;margin-top:18px;padding:15px;border:0;border-radius:14px;cursor:pointer;
      background:var(--accent);color:#14100a;font:600 16px "Barlow",sans-serif}
    button:disabled{opacity:.6}
    .status{margin-top:16px;min-height:22px;font-size:14px}
    .ok{color:var(--vfd)} .bad{color:var(--danger)}
    .hint{margin-top:18px;color:#7d938e;font-size:12px;line-height:1.5}
  </style>
</head>
<body>
  <div class="card">
    <img class="mark" src="/icons/mark-dark.png" alt="" />
    <h1>Drone<span>Dingo</span> Alerts</h1>
    <p class="tag">Your watchdog for the sky</p>
    <p id="lead">Enable alerts on this phone to be notified the moment a drone is
       detected near the property.</p>
    <button id="enable">Enable alerts on this phone</button>
    <div class="status" id="status"></div>
    <p class="hint" id="hint"></p>
  </div>
  <script src="/app.js?v=4"></script>
</body>
</html>
