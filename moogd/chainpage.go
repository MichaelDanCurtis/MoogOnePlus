package main

// The patch designer.
//
// A chain, top to bottom, the way a signal actually travels. Not a node graph:
// drag-to-connect is fiddly on glass and an arbitrary graph can be wired into
// nonsense, while a chain is ordered by construction.
//
// Two things are always on screen because they decide whether the next thing
// you do works: the headroom on the audio core, and the level at the output.
// Everything else is subordinate to those.

const chainPage = `<!doctype html>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Moog One &middot; patch</title>
<style>
:root{--bg:#141414;--panel:#1c1c1c;--line:#2e2e2e;--ink:#e8e2d5;--dim:#8a8578;
      --gold:#d8a24a;--green:#8fd48f;--red:#d4776a;--blue:#6a8fd4}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0;
     font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
     padding:max(16px,env(safe-area-inset-top)) 16px 80px;-webkit-text-size-adjust:100%}
h1{font-size:14px;letter-spacing:.18em;color:var(--gold);font-weight:600;margin:0 0 4px}
.sub{color:var(--dim);font-size:12px;margin:0 0 16px}
h2{font-size:11px;letter-spacing:.14em;color:var(--dim);text-transform:uppercase;
   font-weight:600;margin:26px 0 10px}
.top{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:0 0 16px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}
.big{font-size:30px;line-height:1;font-weight:600;letter-spacing:-.02em}
.ok{color:var(--green)} .warn{color:var(--gold)} .bad{color:var(--red)}
.cap{font-size:11px;color:var(--dim);margin-top:5px}
.meter{height:8px;background:#101010;border-radius:4px;overflow:hidden;margin-top:10px}
.meter i{display:block;height:100%;background:var(--green);transition:width .15s}
.meter i.hot{background:var(--red)}
.step{background:var(--panel);border:1px solid var(--line);border-radius:12px;
      padding:13px;margin:0 0 10px;position:relative}
.step .n{position:absolute;left:-2px;top:14px;width:22px;text-align:center;
         font-size:11px;color:var(--dim)}
.step .body{margin-left:22px}
.hd{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.t{font-size:15px}
.meta{font-size:10px;color:var(--dim);letter-spacing:.08em;text-transform:uppercase}
.blurb{color:var(--dim);font-size:12px;margin:6px 0 10px}
.row{display:grid;grid-template-columns:80px 1fr 66px;gap:10px;align-items:center;margin:0 0 6px}
.row label{font-size:11px;letter-spacing:.06em;color:var(--dim);text-transform:uppercase}
.row output{font-size:13px;color:var(--green);text-align:right}
input[type=range]{width:100%;accent-color:var(--gold)}
button{font:inherit;color:var(--ink);background:#232323;border:1px solid var(--line);
  border-radius:8px;padding:9px 14px;min-height:44px;cursor:pointer}
button.primary{border-color:var(--gold);color:var(--gold)}
button.danger{border-color:var(--red);color:var(--red)}
button.sm{min-height:34px;padding:4px 11px;font-size:12px}
button[disabled]{opacity:.35;cursor:not-allowed}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 14px}
.pal{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.pal button{text-align:left;padding:11px 13px;min-height:0}
.pal .c{display:block;font-size:10px;color:var(--dim);text-transform:uppercase;
        letter-spacing:.08em;margin-top:3px}
.warnbox{border-left:3px solid var(--gold);padding:10px 14px;margin:0 0 16px;
         color:var(--dim);font-size:12px;background:#191713}
.err{color:var(--red);font-size:13px;margin-top:10px}
.flow{color:var(--dim);font-size:11px;text-align:center;margin:-4px 0 6px}
input[type=text]{font:inherit;color:var(--ink);background:var(--panel);
  border:1px solid var(--line);border-radius:8px;padding:9px 12px;min-height:44px}
</style>

<h1>PATCH</h1>
<p class=sub id=sub>&nbsp;</p>

<div class=warnbox>
  A patch is a chain: your instrument's own output goes in at the top, through each
  block in order, and back out to the main pair. It is compiled <b>on the
  instrument</b> &mdash; no SuperCollider anywhere in your path &mdash; and it is
  gone on restart. The last block is always a limiter you cannot remove.
</div>

<div class=top>
  <div class=stat>
    <div class="big" id=head>&mdash;</div>
    <div class=cap>points free on the audio core</div>
  </div>
  <div class=stat>
    <div class="big" id=lvl>&mdash;</div>
    <div class=cap>output level</div>
    <div class=meter><i id=lvlbar style="width:0%"></i></div>
  </div>
</div>

<div class=bar>
  <input type=text id=name placeholder="patch name" value="myPatch" size=14>
  <button id=run class=primary>run</button>
  <button id=stop class=danger>stop all</button>
  <button id=clear class=sm>clear</button>
  <button id=reset class=sm>reset</button>
</div>

<div class=warnbox id=resetbox hidden>
  <b>Reset the audio engine?</b><br>
  This runs <code>/etc/init.d/S42sc restart</code> &mdash; the thing that clears a
  stuck note when nothing else will. Two consequences worth knowing before you tap it:
  <br><br>
  &bull; <b>Sound stops until you load a preset.</b> <code>las-frontend</code> does not
  re-push its state to a new engine.<br>
  &bull; It re-runs the <b>boot-time firmware check</b> on the voice controller and
  voice cards. That is exactly what happens at every power-on and the versions match,
  so nothing is written &mdash; but a voice card has no software recovery, so it is
  said out loud rather than buried.
  <div style="margin-top:10px;display:flex;gap:8px">
    <button id=resetgo class=danger>restart the engine</button>
    <button id=resetno class=sm>cancel</button>
  </div>
</div>

<div id=chain></div>
<h2>Add a block</h2>
<div class=pal id=pal></div>
<div id=err class=err></div>

<script>
let CAT = [], chain = [], running = null, byId = {};

function readout(p, v) {
  if (!p.readout || !p.readout.length) {
    const d = (p.step && p.step < 1) ? 2 : 0;
    return (+v).toFixed(d) + (p.unit ? ' ' + p.unit : '');
  }
  const r = p.readout;
  if (v <= r[0][0]) return r[0][1] + (p.readout_unit || '');
  for (let i = 1; i < r.length; i++) {
    if (v <= r[i][0]) {
      const [x0,y0] = r[i-1], [x1,y1] = r[i];
      const y = y0 + (y1-y0) * ((v-x0)/(x1-x0));
      return (y < 10 ? y.toFixed(1) : y.toFixed(0)) + (p.readout_unit || '');
    }
  }
  return r[r.length-1][1] + (p.readout_unit || '');
}

function drawChain() {
  const el = document.getElementById('chain');
  if (!chain.length) {
    el.innerHTML = '<div class=blurb style="text-align:center;padding:20px">' +
      'nothing yet &mdash; add a block below</div>';
    return;
  }
  el.innerHTML = '<div class=flow>&#9679; the instrument\'s output</div>' +
    chain.map((s, i) => {
      const b = byId[s.block];
      return '<div class=flow>&#8595;</div><div class=step><div class=n>' + (i+1) + '</div>' +
        '<div class=body><div class=hd><span class=t>' + b.title + '</span>' +
        '<span class=meta>' + b.cost + ' cost' + (b.stereo ? ' &middot; stereo' : '') +
        '</span></div><div class=blurb>' + b.blurb + '</div>' +
        (b.params||[]).map(p =>
          '<div class=row><label>' + p.label + '</label>' +
          '<input type=range min=' + p.min + ' max=' + p.max + ' step=' + p.step +
            ' value="' + s.params[p.name] + '" data-i="' + i + '" data-p="' + p.name + '">' +
          '<output id="o' + i + p.name + '">' + readout(p, s.params[p.name]) +
          '</output></div>').join('') +
        '<div style="margin-top:8px;display:flex;gap:6px">' +
        (i > 0 ? '<button class=sm data-up="' + i + '">&#8593;</button>' : '') +
        (i < chain.length-1 ? '<button class=sm data-down="' + i + '">&#8595;</button>' : '') +
        '<button class=sm data-del="' + i + '">remove</button></div>' +
        '</div></div>';
    }).join('') +
    '<div class=flow>&#8595;</div><div class=flow>&#9679; limiter, then the main pair</div>';
}

function drawPalette() {
  document.getElementById('pal').innerHTML = CAT.map(b =>
    '<button data-add="' + b.id + '">' + b.title +
    '<span class=c>' + b.cost + ' cost' + (b.stereo ? ' &middot; stereo' : '') +
    '</span></button>').join('');
}

async function api(path, body) {
  const e = document.getElementById('err');
  try {
    const r = await fetch(path, body ? {method:'POST',
      headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)} : undefined);
    const d = await r.json();
    if (!r.ok) { e.textContent = d.error || ('HTTP ' + r.status); return null; }
    e.textContent = '';
    return d;
  } catch (err) { e.textContent = String(err); return null; }
}

async function poll() {
  const d = await api('/api/chain');
  if (!d) return;
  if (!CAT.length) { CAT = d.blocks; for (const b of CAT) byId[b.id] = b; drawPalette(); drawChain(); }
  const h = d.headroom, cls = h > 25 ? 'ok' : h > d.floor ? 'warn' : 'bad';
  const he = document.getElementById('head');
  he.textContent = h.toFixed(0); he.className = 'big ' + cls;
  document.getElementById('run').disabled = h < d.floor || !chain.length;
  document.getElementById('stop').disabled = !d.units.length;
  document.getElementById('sub').textContent =
    CAT.length + ' blocks · ' + d.units.length + ' running' +
    (running ? ' · ' + running : '');
  const m = await api('/api/meter');
  if (m) {
    const pk = Math.max(m.left_db, m.right_db);
    const le = document.getElementById('lvl');
    le.textContent = pk <= -119 ? 'silent' : pk.toFixed(1) + ' dB';
    le.className = 'big ' + (pk > -6 ? 'bad' : 'ok');
    const bar = document.getElementById('lvlbar');
    bar.style.width = Math.max(0, Math.min(100, ((pk + 90) / 90) * 100)) + '%';
    bar.className = pk > -6 ? 'hot' : '';
  }
}

document.addEventListener('click', async e => {
  const d = e.target.dataset;
  if (d.add) {
    const b = byId[d.add], params = {};
    for (const p of b.params || []) params[p.name] = p.default;
    chain.push({block: b.id, params}); drawChain(); poll();
  } else if (d.del !== undefined) {
    chain.splice(+d.del, 1); drawChain(); poll();
  } else if (d.up !== undefined) {
    const i = +d.up; [chain[i-1], chain[i]] = [chain[i], chain[i-1]]; drawChain();
  } else if (d.down !== undefined) {
    const i = +d.down; [chain[i], chain[i+1]] = [chain[i+1], chain[i]]; drawChain();
  } else if (e.target.id === 'run') {
    const name = document.getElementById('name').value || 'myPatch';
    // One patch at a time: stacking two chains means each replaces the other's
    // output and only the last one is audible.
    await api('/api/engine/remove', {all: true});
    const r = await api('/api/engine/chain', {name, steps: chain});
    if (r) running = r.unit.title + ' · ' + r.ugens + ' ugens';
    poll();
  } else if (e.target.id === 'stop') {
    await api('/api/engine/remove', {all: true}); running = null; poll();
  } else if (e.target.id === 'clear') {
    chain = []; drawChain(); poll();
  } else if (e.target.id === 'reset') {
    // The safe one happens immediately; the disruptive one asks first.
    const r = await api('/api/engine/reset', {level: 'soft'});
    if (r) { running = null; document.getElementById('err').textContent = r.note; }
    document.getElementById('resetbox').hidden = false;
    poll();
  } else if (e.target.id === 'resetno') {
    document.getElementById('resetbox').hidden = true;
  } else if (e.target.id === 'resetgo') {
    e.target.disabled = true;
    e.target.textContent = 'restarting\u2026';
    const r = await api('/api/engine/reset', {level: 'engine'});
    e.target.disabled = false; e.target.textContent = 'restart the engine';
    document.getElementById('resetbox').hidden = true;
    if (r) { running = null; document.getElementById('err').textContent = r.note; }
    poll();
  }
});

// Sliders move the RUNNING patch. Rebuilding it to change a number would click,
// and a control you cannot hear moving is a control you cannot set.
document.addEventListener('input', async e => {
  const i = e.target.dataset.i, name = e.target.dataset.p;
  if (i === undefined) return;
  const v = +e.target.value;
  chain[i].params[name] = v;
  const b = byId[chain[i].block];
  const p = (b.params || []).find(x => x.name === name);
  document.getElementById('o' + i + name).textContent = readout(p, v);
  if (running) {
    const units = (await api('/api/chain'))?.units || [];
    if (units.length) {
      api('/api/engine/set', {node: units[0].node, param: 's' + i + '_' + name, value: v});
    }
  }
});

poll(); setInterval(poll, 2500);
</script>`
