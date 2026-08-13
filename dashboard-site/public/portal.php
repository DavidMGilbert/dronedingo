<?php
// Account portal — login, then the list of the account's stations. Included by
// index.php on the base host, so $pdo is available and _boot.php is loaded.
$aid = dash_account_id($pdo);
$stations = [];
if ($aid !== null) {
    $st = $pdo->prepare(
        'SELECT an.subdomain, an.label, an.node, ap.last_seen
           FROM account_nodes an LEFT JOIN appliances ap ON ap.node = an.node
          WHERE an.account_id = ? ORDER BY an.label');
    $st->execute([$aid]);
    $stations = $st->fetchAll(PDO::FETCH_ASSOC);
}
$now = time();
header('Content-Type: text/html; charset=utf-8');
?><!doctype html>
<html lang="en-AU"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DroneDingo Dashboard</title>
<style>
  :root{--accent:#ed9800;--vfd:#68ead0;--danger:#ef5d61}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;min-height:100dvh;display:grid;place-items:center;padding:22px;
    color:#edf5f2;font:400 16px/1.5 system-ui,"Segoe UI",sans-serif;
    background:radial-gradient(circle at 80% 8%,rgba(237,152,0,.14),transparent 32%),
               radial-gradient(circle at 12% 92%,rgba(104,234,208,.10),transparent 36%),#061416}
  .card{width:min(94vw,460px);background:rgba(14,36,38,.86);border:1px solid rgba(255,255,255,.14);
    border-radius:22px;padding:28px 26px;box-shadow:inset 1px 1px rgba(255,255,255,.08),0 20px 60px rgba(0,0,0,.45)}
  h1{font-size:26px;margin:0 0 2px}h1 span{color:var(--accent)}
  .tag{color:#93a9a5;font-size:13px;margin:0 0 20px}
  label{display:block;font-size:13px;color:#bcd;margin:12px 0 4px}
  input{width:100%;padding:12px;border:1px solid rgba(255,255,255,.16);border-radius:12px;
    background:rgba(0,0,0,.25);color:#edf5f2;font-size:15px}
  button{width:100%;margin-top:18px;padding:14px;border:0;border-radius:12px;cursor:pointer;
    background:var(--accent);color:#14100a;font:600 15px system-ui}
  .err{color:var(--danger);font-size:14px;margin-top:12px;min-height:18px}
  .station{display:flex;align-items:center;justify-content:space-between;gap:12px;
    padding:14px 16px;margin-top:12px;border:1px solid rgba(255,255,255,.12);border-radius:14px;
    background:rgba(255,255,255,.03)}
  .station a{color:#14100a;background:var(--accent);text-decoration:none;padding:9px 14px;border-radius:10px;font-weight:600;font-size:14px}
  .dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:7px}
  .on{background:var(--vfd);box-shadow:0 0 8px var(--vfd)} .off{background:#5c6b68}
  .muted{color:#8098944}.small{color:#7d9390;font-size:12px}
  .row{display:flex;justify-content:space-between;align-items:center;margin-top:6px}
  .link{background:none;color:#8fb;width:auto;margin:0;padding:0;font-size:13px}
</style></head><body>
<div class="card">
<?php if ($aid === null): ?>
  <h1>Drone<span>Dingo</span></h1>
  <p class="tag">Sign in to your dashboard</p>
  <form method="POST" action="/api/portal-login.php">
    <input type="hidden" name="next" value="<?= htmlspecialchars($_GET['next'] ?? '') ?>">
    <label>Email</label><input name="email" type="email" autocomplete="username" required>
    <label>Password</label><input name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Sign in</button>
    <div class="err"><?= isset($_GET['e']) ? 'Wrong email or password.' : '' ?></div>
  </form>
<?php else: ?>
  <div class="row"><h1>Your stations</h1>
    <form method="POST" action="/api/portal-logout.php"><button class="link" type="submit">Sign out</button></form></div>
  <?php if (!$stations): ?>
    <p class="small">No stations yet. On a DroneDingo appliance, finish the setup wizard to add it to this account.</p>
  <?php else: foreach ($stations as $s):
      $online = $s['last_seen'] && ((int)$s['last_seen'] > $now - 120); ?>
    <div class="station">
      <div><span class="dot <?= $online ? 'on' : 'off' ?>"></span><b><?= htmlspecialchars($s['label']) ?></b>
        <div class="small"><?= htmlspecialchars($s['subdomain']) ?>.dashboard.dronedingo.com.au · <?= $online ? 'online' : 'offline' ?></div></div>
      <a href="https://<?= htmlspecialchars($s['subdomain']) ?>.<?= DASH_BASE ?>/">Open</a>
    </div>
  <?php endforeach; endif; ?>
<?php endif; ?>
</div></body></html>
