package main

// The modulation matrix editor, served to whatever is on the network.
//
// Built for a tablet held in two hands: touch targets are large, nothing
// depends on hover, and the layout collapses to one column on a narrow screen.
//
// It composes a matrix; it does not send one, and there is no switch to make it
// send one. The modulation matrix has no live OSC endpoint -- las-sc contains
// zero modmatrix code and matrix_expression_slots is a field in a preset file.
// See ErrNoLiveMatrix in lassc.go for how that was established. What this page
// produces is the exact token array to put into a preset, which is worth having
// because the encoder round-trips all 300 factory matrices byte-for-byte.
//
// Ids that no factory preset has ever used are marked, because "the symbol
// table says this exists" is a weaker claim than "we have watched the
// instrument do this".

const matrixPage = `<!doctype html>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Moog One &middot; modulation matrix</title>
<style>
:root{
  --bg:#141414; --panel:#1c1c1c; --line:#2e2e2e; --ink:#e8e2d5;
  --dim:#8a8578; --gold:#d8a24a; --green:#8fd48f; --red:#d4776a;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0;
     font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
     padding:max(16px,env(safe-area-inset-top)) 16px 64px;
     -webkit-text-size-adjust:100%}
h1{font-size:14px;letter-spacing:.18em;color:var(--gold);font-weight:600;margin:0 0 4px}
.sub{color:var(--dim);font-size:12px;margin:0 0 20px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 20px}
button,select,input{font:inherit;color:var(--ink);background:var(--panel);
  border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-height:44px}
button{cursor:pointer}
button:active{background:#262626}
button.primary{border-color:var(--gold);color:var(--gold)}
button[disabled]{opacity:.4;cursor:not-allowed}
.t{display:flex;gap:6px}
.t button.on{border-color:var(--gold);color:var(--gold)}
.row{background:var(--panel);border:1px solid var(--line);border-radius:12px;
     padding:14px;margin:0 0 12px}
.grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
label{display:block;font-size:11px;letter-spacing:.1em;color:var(--dim);
      text-transform:uppercase;margin:0 0 4px}
select,input[type=number]{width:100%}
.reads{margin-top:10px;color:var(--green);font-size:13px;word-break:break-word}
.reads .un{color:var(--gold)}
.head{display:flex;justify-content:space-between;align-items:center;margin:0 0 10px}
.n{color:var(--dim);font-size:12px;letter-spacing:.1em}
.x{background:none;border:none;color:var(--dim);padding:4px 10px;min-height:0;font-size:18px}
pre{background:#101010;border:1px solid var(--line);border-radius:8px;padding:12px;
    overflow-x:auto;font-size:12px;color:var(--dim);white-space:pre-wrap;word-break:break-all}
.warn{border-left:3px solid var(--gold);padding:10px 14px;margin:0 0 20px;
      color:var(--dim);font-size:12px;background:#191713}
.err{color:var(--red)}
#graph{background:var(--panel);border:1px solid var(--line);border-radius:12px;
       padding:10px;margin:0 0 16px;overflow-x:auto}
#graph svg{display:block;min-width:100%}
#graph text{font:11px ui-monospace,monospace;fill:var(--dim)}
#graph text.n{fill:var(--ink);font-size:12px}
#graph text.un{fill:var(--gold)}
#graph path{fill:none;stroke:var(--green);stroke-opacity:.55}
#graph path.sel{stroke:var(--gold);stroke-opacity:1}
#graph .empty{fill:var(--dim);font-size:12px}
</style>

<h1>MODULATION MATRIX</h1>
<p class=sub id=sub>the engine runs on the voice controller, so a row costs nothing
on either CPU</p>

<div class=warn id=warn>checking write state&hellip;</div>

<div class=bar>
  <div class=t id=timbres></div>
  <button id=add>+ row</button>
  <button id=preview class=primary>preview</button>
</div>

<div id=graph></div>
<div id=rows></div>
<pre id=out hidden></pre>

<script>
let T = null, timbre = 1, rows = [];

const opt = (e, sel) =>
  '<option value="' + e.id + '"' + (e.id === sel ? ' selected' : '') + '>' +
  (e.attested ? '' : '• ') + e.name + '</option>';

function options(list, sel, noneId, noneLabel) {
  let h = '';
  if (noneId !== undefined) {
    h += '<option value="' + noneId + '"' + (sel === noneId ? ' selected' : '') +
         '>' + noneLabel + '</option>';
  }
  for (const e of list) if (e.id !== noneId) h += opt(e, sel);
  return h;
}

function blank() {
  return {src: T.src_none, src_amt: 1, ctl: T.src_none, ctl_amt: 1,
          transform: T.transform_none, transform_amt: 0, dest: T.dest_none[0]};
}

// The matrix drawn as what it is -- a graph. Moog show it as twenty rows of
// soft-knob scrolling, which is the worst available presentation of a graph.
//
// Sources left, destinations right, one curve per routed row, thickness by
// amount. Deliberately NOT drag-to-connect: that is fiddly on a tablet and
// precision belongs in the numeric fields below. Tapping a curve scrolls to its
// row, so the graph is for comprehension and the rows are for editing.
function graph() {
  const routed = rows.map((r, i) => ({r, i})).filter(x => !T.dest_none.includes(x.r.dest));
  if (!routed.length)
    return '<svg height=54><text class=empty x=12 y=32>nothing routed yet — ' +
           'add a row and pick a destination</text></svg>';

  // One lane per distinct endpoint, so two rows from MOD WHEEL share a lane.
  const key = (side, r) => side === 'L'
        ? (r.src !== T.src_none ? 's' + r.src : 'c' + r.ctl)
        : 'd' + r.dest;
  const lanes = side => {
    const seen = [];
    for (const {r} of routed) { const k = key(side, r); if (!seen.includes(k)) seen.push(k); }
    return seen;
  };
  const L = lanes('L'), R = lanes('R');
  const step = 30, pad = 22;
  const h = Math.max(L.length, R.length) * step + pad * 2;
  const w = 560, xL = 150, xR = w - 150;

  const labelFor = (k) => {
    const id = +k.slice(1);
    const list = k[0] === 'd' ? T.destinations : T.sources;
    const e = list.find(x => x.id === id);
    if (!e) return {name: '#' + id, un: false};
    return {name: e.name, un: !e.attested};
  };

  let out = '<svg viewBox="0 0 ' + w + ' ' + h + '" height="' + h + '">';
  // curves first, so labels sit on top
  for (const {r, i} of routed) {
    const y1 = pad + L.indexOf(key('L', r)) * step;
    const y2 = pad + R.indexOf(key('R', r)) * step;
    const amt = Math.abs(r.src_amt * r.ctl_amt);
    const wgt = Math.max(1, Math.min(6, 1 + amt * 4));
    const mx = (xL + xR) / 2;
    out += '<path d="M' + xL + ' ' + y1 + ' C' + mx + ' ' + y1 + ' ' + mx + ' ' + y2 +
           ' ' + xR + ' ' + y2 + '" stroke-width="' + wgt.toFixed(1) + '"' +
           ' data-row="' + i + '"><title>row ' + (i + 1) + '</title></path>';
  }
  L.forEach((k, n) => {
    const {name, un} = labelFor(k);
    out += '<text class="n ' + (un ? 'un' : '') + '" x="' + (xL - 8) + '" y="' +
           (pad + n * step + 4) + '" text-anchor="end">' + name + '</text>';
  });
  R.forEach((k, n) => {
    const {name, un} = labelFor(k);
    out += '<text class="n ' + (un ? 'un' : '') + '" x="' + (xR + 8) + '" y="' +
           (pad + n * step + 4) + '">' + name + '</text>';
  });
  return out + '</svg>';
}

function render() {
  document.getElementById('rows').innerHTML = rows.map((r, i) => ` + "`" + `
    <div class=row>
      <div class=head><span class=n>ROW ${i + 1}</span>
        <button class=x data-del="${i}" aria-label="remove row">&times;</button></div>
      <div class=grid>
        <div><label>source</label><select data-i="${i}" data-k="src">
          ${options(T.sources, r.src, T.src_none, '(none)')}</select></div>
        <div><label>amount</label>
          <input type=number step=any data-i="${i}" data-k="src_amt" value="${r.src_amt}"></div>
        <div><label>controller</label><select data-i="${i}" data-k="ctl">
          ${options(T.sources, r.ctl, T.src_none, '(none)')}</select></div>
        <div><label>amount</label>
          <input type=number step=any data-i="${i}" data-k="ctl_amt" value="${r.ctl_amt}"></div>
        <div><label>transform</label><select data-i="${i}" data-k="transform">
          ${options(T.transforms, r.transform, T.transform_none, '(none)')}</select></div>
        <div><label>amount</label>
          <input type=number step=any data-i="${i}" data-k="transform_amt" value="${r.transform_amt}"></div>
        <div><label>destination</label><select data-i="${i}" data-k="dest">
          ${options(T.destinations, r.dest, T.dest_none[0], '(unrouted)')}</select></div>
      </div>
      <div class=reads>${describe(r)}</div>
    </div>` + "`" + `).join('');
  document.getElementById('graph').innerHTML = graph();
}

const find = (list, id) => list.find(e => e.id === id);

function nameOf(list, id) {
  const e = find(list, id);
  if (!e) return '#' + id + '?';
  return e.attested ? e.name : '<span class=un>' + e.name + '•</span>';
}

function describe(r) {
  if (T.dest_none.includes(r.dest)) return '(unrouted)';
  let s = r.src === T.src_none ? '1' : nameOf(T.sources, r.src);
  if (r.src_amt !== 1) s += ' × ' + r.src_amt;
  if (r.ctl !== T.src_none) {
    s += ' · ' + nameOf(T.sources, r.ctl);
    if (r.ctl_amt !== 1) s += ' × ' + r.ctl_amt;
  }
  if (r.transform !== T.transform_none) {
    s += ' → ' + nameOf(T.transforms, r.transform);
    if (r.transform_amt !== 0) s += '(' + r.transform_amt + ')';
  }
  return s + ' ⇒ ' + nameOf(T.destinations, r.dest);
}

document.addEventListener('change', e => {
  const i = e.target.dataset.i, k = e.target.dataset.k;
  if (i === undefined || k === undefined) return;
  const v = parseFloat(e.target.value);
  rows[i][k] = Number.isFinite(v) ? v : 0;
  render();
});

document.addEventListener('click', e => {
  const d = e.target.dataset.del;
  if (d !== undefined) { rows.splice(+d, 1); render(); return; }
  // Tapping a curve takes you to the row that draws it.
  const path = e.target.closest && e.target.closest('path[data-row]');
  if (path) {
    document.querySelectorAll('#graph path').forEach(p => p.classList.remove('sel'));
    path.classList.add('sel');
    const card = document.querySelectorAll('#rows .row')[+path.dataset.row];
    if (card) card.scrollIntoView({behavior: 'smooth', block: 'center'});
  }
});

document.getElementById('add').onclick = () => { rows.push(blank()); render(); };

async function post(dry) {
  const out = document.getElementById('out');
  out.hidden = false;
  out.textContent = dry ? 'previewing…' : 'sending…';
  try {
    const r = await fetch('/api/modmatrix/write', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({timbre: timbre, slots: rows, dry_run: dry})
    });
    const d = await r.json();
    if (!r.ok) { out.innerHTML = '<span class=err>' + (d.error || r.status) + '</span>'; return; }
    out.textContent =
      d.address + '\n\n' +
      d.reads.map((s, i) => String(i + 1).padStart(2) + '  ' + s).join('\n') +
      '\n\n' + d.rows + ' rows, ' + d.tokens.length + ' tokens\n' +
      JSON.stringify(d.tokens) +
      (d.sent ? '\n\nSENT' : '\n\nnot sent — ' + d.why);
  } catch (err) {
    out.innerHTML = '<span class=err>' + err + '</span>';
  }
}
document.getElementById('preview').onclick = () => post(true);

(async function init() {
  T = await (await fetch('/api/modmatrix')).json();
  // Count from the tables rather than hardcoding, so the page cannot drift from
  // them -- and say plainly how much of each is attested, since the destination
  // table is derived from the engine's symbol table while the source and
  // transform tables are only what factory presets happen to use.
  const att = l => l.filter(e => e.attested).length;
  document.getElementById('sub').textContent =
    T.destinations.length + ' destinations (' + att(T.destinations) + ' used by the factory) · ' +
    T.sources.length + ' known sources · ' + T.transforms.length + ' known transforms · ' +
    'the engine runs on the voice controller, so a row costs nothing on either CPU';
  document.getElementById('timbres').innerHTML = [1, 2, 3].map(n =>
    '<button data-t="' + n + '" class="' + (n === 1 ? 'on' : '') + '">SYNTH ' + n + '</button>'
  ).join('');
  document.querySelectorAll('[data-t]').forEach(b => b.onclick = () => {
    timbre = +b.dataset.t;
    document.querySelectorAll('[data-t]').forEach(x => x.classList.toggle('on', x === b));
  });

  const w = document.getElementById('warn');
  // The send path is gone on purpose, not switched off pending a fix. There is
  // no live OSC endpoint for the modulation matrix: las-sc contains zero
  // modmatrix code, and matrix_expression_slots is a preset-file field. Proven
  // by reading the binary and confirmed on the wire — see lassc.go.
  w.innerHTML = 'This composes a matrix; it does not send one. ' +
    '<b>The modulation matrix has no live OSC endpoint</b> — <code>las-sc</code> ' +
    'contains no matrix code at all, and <code>matrix_expression_slots</code> is a ' +
    'field in a preset file, not an address. Build a matrix here, hit ' +
    '<b>preview</b>, and put the token array into a preset. The encoder round-trips ' +
    'all 300 factory matrices byte-for-byte, so what you get is what Moog would write.';
  rows = [blank()];
  render();
})();
</script>`
