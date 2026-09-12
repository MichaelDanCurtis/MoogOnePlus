package main

// The Engine screen.
//
// The instrument has 734 registered, idle UGens and no way to name them. This
// offers a few of them, and puts the only number that decides whether you can
// have one -- the audio core's remaining headroom -- at the top, where it
// belongs. Everything else on this page is subordinate to it.

const enginePage = `<!doctype html>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Moog One &middot; engine</title>
<style>
:root{
  --bg:#141414; --panel:#1c1c1c; --line:#2e2e2e; --ink:#e8e2d5;
  --dim:#8a8578; --gold:#d8a24a; --green:#8fd48f; --red:#d4776a;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0;
     font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
     padding:max(16px,env(safe-area-inset-top)) 16px 64px;-webkit-text-size-adjust:100%}
h1{font-size:14px;letter-spacing:.18em;color:var(--gold);font-weight:600;margin:0 0 4px}
.sub{color:var(--dim);font-size:12px;margin:0 0 20px}
h2{font-size:11px;letter-spacing:.14em;color:var(--dim);text-transform:uppercase;
   font-weight:600;margin:28px 0 10px}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:14px;
      padding:18px;margin:0 0 18px}
.big{font-size:40px;line-height:1;font-weight:600;letter-spacing:-.02em}
.big.ok{color:var(--green)} .big.warn{color:var(--gold)} .big.bad{color:var(--red)}
.cap{font-size:12px;color:var(--dim);margin-top:6px}
.meter{height:10px;background:#101010;border-radius:5px;overflow:hidden;margin:14px 0 4px;
       position:relative}
.meter i{display:block;height:100%;background:var(--green);transition:width .4s}
.meter i.warn{background:var(--gold)} .meter i.bad{background:var(--red)}
.meter b{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--red);opacity:.8}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
      padding:14px;margin:0 0 12px}
.head{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.t{font-size:15px;color:var(--ink)}
.meta{font-size:11px;color:var(--dim);letter-spacing:.08em;text-transform:uppercase}
.blurb{color:var(--dim);font-size:12px;margin:8px 0 12px}
button{font:inherit;color:var(--ink);background:#232323;border:1px solid var(--line);
  border-radius:8px;padding:10px 16px;min-height:44px;cursor:pointer}
button.primary{border-color:var(--gold);color:var(--gold)}
button.danger{border-color:var(--red);color:var(--red)}
button[disabled]{opacity:.35;cursor:not-allowed}
.row{display:grid;grid-template-columns:92px 1fr 62px;gap:12px;align-items:center;
     margin:0 0 8px}
.row label{font-size:11px;letter-spacing:.08em;color:var(--dim);text-transform:uppercase}
.row output{font-size:13px;color:var(--green);text-align:right}
input[type=range]{width:100%;accent-color:var(--gold)}
.warn{border-left:3px solid var(--gold);padding:10px 14px;margin:0 0 18px;
      color:var(--dim);font-size:12px;background:#191713}
.err{color:var(--red);font-size:13px;margin-top:10px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 12px}
</style>

<h1>ENGINE</h1>
<p class=sub id=sub>&nbsp;</p>

<div class=warn>
  These effects are built from DSP that is <b>already loaded on your instrument</b>
  and that your instrument cannot name. <code>scsynth</code> registers 795 UGens at
  boot; the client beside it has classes for 360 of them. <code>ReverbUGens.so</code>
  has none, so <code>FreeVerb2</code> and <code>GVerb</code> have sat resident and
  unreachable since the machine shipped. The definitions here were compiled on a
  workstation and sent over; the server resolves a UGen by name, so it does not care
  where the definition came from. Nothing is written to disk &mdash; a restart clears
  all of it.
</div>

<div id=hero></div>
<div class=bar><button id=panic class=danger>remove everything</button></div>
<div id=running></div>
<h2>Available</h2>
<div id=cat></div>
<div id=err class=err></div>

<script>
let C = null;

function hero(d) {
  const h = d.headroom, cls = h > 25 ? 'ok' : h > d.floor ? 'warn' : 'bad';
  const word = h > 25 ? 'room for another' : h > d.floor ? 'getting tight' : 'nothing more fits';
  return '<div class=hero>' +
    '<div class="big ' + cls + '">' + h.toFixed(0) +
      '<span style="font-size:19px"> points free</span></div>' +
    '<div class=cap>on the audio core &middot; the floor is ' + d.floor.toFixed(0) +
      ' &middot; <b>' + word + '</b></div>' +
    '<div class=meter><i class="' + cls + '" style="width:' +
      Math.min(100 - h, 100) + '%"></i></div>' +
    '<div class=cap>an effect is refused below the floor, because this instrument\'s ' +
      'realtime throttle has already fired three times and a dropout is worse than a ' +
      'missing reverb</div></div>';
}

// A control reads in whatever unit was actually measured for it. "0.80" tells a
// musician nothing; "2.4 s" tells them what the reverb will do. The pairs come
// from rendering an impulse through the real UGen, so this interpolates between
// measurements rather than inventing a curve between them.
function readout(p, v) {
  if (!p.readout || !p.readout.length) return (+v).toFixed(2);
  const r = p.readout;
  if (v <= r[0][0]) return r[0][1] + (p.readout_unit || '');
  for (let i = 1; i < r.length; i++) {
    if (v <= r[i][0]) {
      const [x0, y0] = r[i-1], [x1, y1] = r[i];
      const y = y0 + (y1 - y0) * ((v - x0) / (x1 - x0));
      return (y < 10 ? y.toFixed(1) : y.toFixed(0)) + (p.readout_unit || '');
    }
  }
  return r[r.length-1][1] + (p.readout_unit || '');
}

function controls(u, eff) {
  return eff.params.map(p =>
    '<div class=row><label>' + p.label +
      (p.readout_note ? '<br><span style="text-transform:none;letter-spacing:0">' +
        p.readout_note + '</span>' : '') + '</label>' +
    '<input type=range min=' + p.min + ' max=' + p.max + ' step=' + p.step +
      ' value="' + u.params[p.name] + '" data-node="' + u.node + '" data-p="' + p.name +
      '" data-eff="' + u.effect + '">' +
    '<output id="o' + u.node + p.name + '">' + readout(p, u.params[p.name]) + '</output></div>'
  ).join('');
}

function render(d) {
  C = d;
  document.getElementById('sub').textContent =
    d.catalogue.length + ' effects available · ' + d.units.length + ' running';
  document.getElementById('hero').innerHTML = hero(d);
  const byName = {};
  for (const e of d.catalogue) byName[e.name] = e;
  document.getElementById('running').innerHTML = !d.units.length ? '' :
    '<h2>Running</h2>' + d.units.map(u =>
      '<div class=card><div class=head><span class=t>' + u.title + '</span>' +
      '<span class=meta>node ' + u.node + '</span></div>' +
      controls(u, byName[u.effect]) +
      '<div style="margin-top:10px"><button data-free="' + u.node + '">remove</button></div>' +
      '</div>').join('');
  document.getElementById('cat').innerHTML = d.catalogue.map(e =>
    '<div class=card><div class=head><span class=t>' + e.title + '</span>' +
    '<span class=meta>' + e.ugen + ' &middot; ' + e.cost + ' cost</span></div>' +
    '<div class=blurb>' + e.blurb + '</div>' +
    '<button class=primary data-add="' + e.name + '"' +
      (d.headroom < d.floor ? ' disabled' : '') + '>add</button></div>').join('');
  document.getElementById('panic').disabled = !d.units.length;
}

async function api(path, body) {
  const e = document.getElementById('err');
  e.textContent = '';
  try {
    const r = await fetch(path, body ? {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    } : undefined);
    const d = await r.json();
    if (!r.ok) { e.textContent = d.error || ('HTTP ' + r.status); return null; }
    return d;
  } catch (err) { e.textContent = String(err); return null; }
}

async function refresh() {
  const d = await api('/api/engine');
  if (d) render(d);
}

document.addEventListener('click', async e => {
  const add = e.target.dataset.add, free = e.target.dataset.free;
  if (add) { e.target.disabled = true; await api('/api/engine/add', {effect: add}); refresh(); }
  else if (free) { await api('/api/engine/remove', {node: +free}); refresh(); }
  else if (e.target.id === 'panic') { await api('/api/engine/remove', {all: true}); refresh(); }
});

// Sliders send while dragging -- a reverb you cannot hear changing is a reverb
// you cannot set -- but the page is not re-rendered underneath your finger.
document.addEventListener('input', e => {
  const node = e.target.dataset.node, name = e.target.dataset.p;
  if (!node) return;
  const eff = C && C.catalogue.find(x => x.name === e.target.dataset.eff);
  const p = eff && eff.params.find(x => x.name === name);
  document.getElementById('o' + node + name).textContent =
    p ? readout(p, +e.target.value) : (+e.target.value).toFixed(2);
  api('/api/engine/set', {node: +node, param: name, value: +e.target.value});
});

refresh();
setInterval(() => { if (!document.querySelector('input[type=range]:active')) refresh(); }, 4000);
</script>`
