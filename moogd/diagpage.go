package main

// The diagnostics screen.
//
// One number leads, because one number decides whether the next thing you do
// works: how close the audio core is to the realtime throttle. A musician
// wants to know "can I add this reverb", and that is the figure that answers
// it. Everything below the headline is context, and the deep material -- thread
// affinities, interrupt counts, the kernel command line -- is behind a fold,
// because it is for us and not for someone in the middle of playing.
//
// Built for a tablet: large type, no hover, one column on a narrow screen.

const diagPage = `<!doctype html>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Moog One &middot; diagnostics</title>
<style>
:root{
  --bg:#141414; --panel:#1c1c1c; --line:#2e2e2e; --ink:#e8e2d5; --dim:#8a8578;
  --gold:#d8a24a; --green:#8fd48f; --amber:#d8a24a; --red:#d4776a;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0;
     font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
     padding:max(16px,env(safe-area-inset-top)) 16px 64px;-webkit-text-size-adjust:100%}
h1{font-size:14px;letter-spacing:.18em;color:var(--gold);font-weight:600;margin:0 0 20px}
h2{font-size:11px;letter-spacing:.14em;color:var(--dim);text-transform:uppercase;
   font-weight:600;margin:28px 0 10px}
.hero{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px;
      margin:0 0 16px}
.big{font-size:44px;line-height:1;font-weight:600;letter-spacing:-.02em}
.big.ok{color:var(--green)} .big.warn{color:var(--amber)} .big.bad{color:var(--red)}
.cap{font-size:12px;color:var(--dim);margin-top:6px}
.meter{height:10px;background:#101010;border-radius:5px;overflow:hidden;margin:16px 0 6px;
       position:relative}
.meter i{display:block;height:100%;background:var(--green);transition:width .4s}
.meter i.warn{background:var(--amber)} .meter i.bad{background:var(--red)}
.meter b{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--red);opacity:.8}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.k{font-size:11px;letter-spacing:.1em;color:var(--dim);text-transform:uppercase}
.v{font-size:22px;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:13px}
td,th{padding:6px 10px 6px 0;text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:11px;letter-spacing:.1em;text-transform:uppercase}
tr.audio td{color:var(--gold)}
.def{border-left:3px solid var(--dim);padding:10px 14px;margin:0 0 10px;background:#191713;
     font-size:13px}
.def.warn{border-left-color:var(--amber)}
.def .t{color:var(--ink)} .def .d{color:var(--dim);font-size:12px;margin-top:4px}
details{margin-top:24px} summary{cursor:pointer;color:var(--dim);font-size:12px;
  letter-spacing:.1em;text-transform:uppercase;padding:10px 0}
pre{background:#101010;border:1px solid var(--line);border-radius:8px;padding:12px;
    overflow-x:auto;font-size:11px;color:var(--dim);white-space:pre-wrap;word-break:break-all}
.err{color:var(--red)}
</style>

<h1>DIAGNOSTICS</h1>
<div id=app>reading the instrument&hellip;</div>

<script>
const kb = n => n > 1048576 ? (n/1048576).toFixed(1)+' GB'
             : n > 1024 ? (n/1024).toFixed(0)+' MB' : n+' kB';

function hero(d) {
  // The headline: how much of the audio core is left before the kernel
  // deschedules the engine. Bands are deliberately conservative -- a dropout
  // is far worse than a cautious warning.
  const head = d.headroom_pct, busy = d.audio_core_busy * 100,
        ceil = d.throttle_at * 100;
  const cls = head > 20 ? 'ok' : head > 8 ? 'warn' : 'bad';
  const word = head > 20 ? 'plenty of room'
             : head > 8  ? 'getting tight'
             : 'at the edge';
  return ` + "`" + `
  <div class=hero>
    <div class="big ${cls}">${head.toFixed(0)}<span style="font-size:20px"> points free</span></div>
    <div class=cap>audio core at ${busy.toFixed(0)}% &middot; the kernel cuts the sound
      off above ${ceil.toFixed(2)}% &middot; <b>${word}</b></div>
    <div class=meter>
      <i class="${cls}" style="width:${Math.min(busy,100)}%"></i>
      <b style="left:${Math.min(ceil,100)}%"></b>
    </div>
    <div class=cap>this is cpu1, where the engine's realtime thread runs &mdash;
      not overall CPU</div>
  </div>` + "`" + `;
}

function cards(d) {
  const e = d.engine, c = d.cores || {};
  const rows = [
    ['temperature', d.temp_c ? d.temp_c.toFixed(1)+' &deg;C' : '&mdash;'],
    ['cpu0 (everything else)', ((c.cpu0||0)*100).toFixed(0)+'%'],
    ['ugens', e ? e.Ugens : '&mdash;'],
    ['synths', e ? e.Synths : '&mdash;'],
    ['synthdefs', e ? e.Defs : '&mdash;'],
    ['sample rate', e ? e.SampleRate.toFixed(0)+' Hz' : '&mdash;'],
  ];
  return '<div class=grid>' + rows.map(([k,v]) =>
    '<div class=card><div class=k>'+k+'</div><div class=v>'+v+'</div></div>').join('') + '</div>';
}

function defects(d) {
  const list = (d.defects||[]).filter(x => x.present);
  if (!list.length) return '';
  return '<h2>Findings</h2>' + list.map(x =>
    '<div class="def '+(x.severity==='warn'?'warn':'')+'">' +
    '<div class=t>'+x.title+'</div><div class=d>'+x.detail+'</div></div>').join('');
}

function disks(d) {
  return '<h2>Storage</h2><table><tr><th>mount</th><th>free</th><th>used</th><th></th></tr>' +
    (d.disks||[]).filter(x => x.total_kb).map(x =>
      '<tr><td>'+x.mount+'</td><td>'+kb(x.free_kb)+'</td><td>'+x.used_pct.toFixed(0)+'%</td>' +
      '<td style="color:var(--dim)">'+(x.note||'')+'</td></tr>').join('') + '</table>';
}

function deep(d) {
  const th = (d.threads||[]).map(t =>
    '<tr class="'+(t.audio?'audio':'')+'"><td>'+t.tid+'</td><td>'+t.policy+'</td>' +
    '<td>'+t.rt_priority+'</td><td>'+t.last_cpu+'</td><td>'+t.affinity+'</td>' +
    '<td>'+(t.audio?'the audio thread':'')+'</td></tr>').join('');
  const irq = (d.irqs||[]).map(i =>
    '<tr><td>'+i.name+'</td><td>'+(i.counts||[]).join(' / ')+'</td></tr>').join('');
  return ` + "`" + `<details><summary>&#9656; deeper &mdash; threads, interrupts, kernel</summary>
    <h2>scsynth threads</h2>
    <p style="color:var(--dim);font-size:12px;margin:0 0 8px">
      <code>taskset -p</code> shows only the first row. That is why cpu1 looked idle
      for months.</p>
    <table><tr><th>tid</th><th>policy</th><th>rt prio</th><th>last cpu</th>
      <th>allowed</th><th></th></tr>${th}</table>
    <h2>audio interrupts</h2>
    <p style="color:var(--dim);font-size:12px;margin:0 0 8px">
      counts per core. <code>sdma</code> runs the audio transfer;
      <code>esai</code> has never fired.</p>
    <table><tr><th>irq</th><th>cpu0 / cpu1</th></tr>${irq}</table>
    <h2>system</h2>
    <table>
      <tr><th>firmware</th><td>${d.version||'&mdash;'}</td></tr>
      <tr><th>uptime</th><td>${d.uptime ? (d.uptime/3600).toFixed(1)+' h' : '&mdash;'}</td></tr>
    </table>
    <pre>${d.cmdline||''}</pre>
  </details>` + "`" + `;
}

async function tick() {
  const app = document.getElementById('app');
  // The whole panel re-renders every few seconds, which would otherwise slam the
  // details fold shut while someone is reading it. Carry the open state across.
  const wasOpen = !!app.querySelector('details[open]');
  try {
    const d = await (await fetch('/api/diag')).json();
    app.innerHTML = hero(d) + cards(d) + defects(d) + disks(d) + deep(d);
    const det = app.querySelector('details');
    if (det) det.open = wasOpen;
  } catch (e) {
    app.innerHTML = '<span class=err>cannot reach the instrument: ' + e + '</span>';
  }
}
tick(); setInterval(tick, 3000);
</script>`
