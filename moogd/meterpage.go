package main

// The meter screen.
//
// A number tells you how loud it is now. A shape tells you whether it is
// growing, which is the question that took an evening to answer on
// 2026-09-12 -- so the chart is the instrument here and the numbers are the
// annotation.

const meterPage = `<!doctype html>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Moog One &middot; meter</title>
<style>
:root{--bg:#141414;--panel:#1c1c1c;--line:#2e2e2e;--ink:#e8e2d5;--dim:#8a8578;
      --gold:#d8a24a;--green:#8fd48f;--red:#d4776a}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);margin:0;
     font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
     padding:max(16px,env(safe-area-inset-top)) 16px 64px;-webkit-text-size-adjust:100%}
h1{font-size:14px;letter-spacing:.18em;color:var(--gold);font-weight:600;margin:0 0 4px}
.sub{color:var(--dim);font-size:12px;margin:0 0 18px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;
       padding:16px;margin:0 0 14px}
.big{font-size:34px;line-height:1;font-weight:600;letter-spacing:-.02em}
.cap{font-size:12px;color:var(--dim);margin-top:6px}
.rising{color:var(--red)} .steady{color:var(--green)}
canvas{width:100%;height:200px;display:block;background:#101010;
       border:1px solid var(--line);border-radius:10px}
.leg{display:flex;gap:16px;font-size:11px;color:var(--dim);margin-top:8px;flex-wrap:wrap}
.sw{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:5px}
.bars{display:grid;grid-template-columns:34px 1fr 64px;gap:10px;align-items:center;
      margin-top:12px}
.bar{height:12px;background:#101010;border-radius:6px;overflow:hidden;position:relative}
.bar i{display:block;height:100%;background:var(--green);transition:width .12s}
.bar i.hot{background:var(--red)}
.k{font-size:11px;color:var(--dim);letter-spacing:.08em}
.v{font-size:13px;text-align:right}
.err{color:var(--red);font-size:13px}
button{font:inherit;color:var(--ink);background:#232323;border:1px solid var(--line);
  border-radius:8px;padding:10px 16px;min-height:44px;cursor:pointer}
</style>

<h1>METER</h1>
<p class=sub>buses 7 and 0 &mdash; the main pair, after every voice and every
effect. The analog voices arrive on bus 12 from the ADC, so this sees all of it.</p>

<div class=panel>
  <div class=big id=state>&hellip;</div>
  <div class=cap id=note>reading the engine</div>
  <div class=bars id=bars></div>
</div>

<div class=panel>
  <canvas id=c width=900 height=400></canvas>
  <div class=leg>
    <span><i class=sw style="background:#8fd48f"></i>left</span>
    <span><i class=sw style="background:#d8a24a"></i>right</span>
    <span><i class=sw style="background:#6a8fd4"></i>slow envelope &mdash; 3 s release</span>
    <span>60 seconds &middot; &minus;90 to 0 dBFS</span>
  </div>
</div>

<button id=stop>stop metering</button>
<div id=err class=err></div>

<script>
const HIST = 300;            // 60 s at 5 Hz
const hist = {l: [], r: [], sl: [], sr: []};
const cv = document.getElementById('c'), cx = cv.getContext('2d');

function db2y(db, h) {
  const lo = -90, hi = 0;
  return h - ((Math.max(lo, Math.min(hi, db)) - lo) / (hi - lo)) * h;
}

function draw() {
  const w = cv.width, h = cv.height;
  cx.clearRect(0, 0, w, h);
  // dB gridlines, because an unlabelled chart of a level is a decoration
  cx.strokeStyle = '#242424'; cx.fillStyle = '#5a5850';
  cx.font = '18px ui-monospace, monospace'; cx.lineWidth = 1;
  for (const db of [-80, -60, -40, -20, 0]) {
    const y = db2y(db, h);
    cx.beginPath(); cx.moveTo(0, y); cx.lineTo(w, y); cx.stroke();
    cx.fillText(db + '', 6, y - 5);
  }
  const line = (arr, colour, width) => {
    if (arr.length < 2) return;
    cx.strokeStyle = colour; cx.lineWidth = width; cx.beginPath();
    arr.forEach((db, i) => {
      const x = (i / (HIST - 1)) * w, y = db2y(db, h);
      i ? cx.lineTo(x, y) : cx.moveTo(x, y);
    });
    cx.stroke();
  };
  line(hist.sl, '#6a8fd4', 2);
  line(hist.sr, '#6a8fd4', 2);
  line(hist.l, '#8fd48f', 3);
  line(hist.r, '#d8a24a', 3);
}

function bar(k, db) {
  const pct = Math.max(0, Math.min(100, ((db + 90) / 90) * 100));
  return '<div class=k>' + k + '</div>' +
    '<div class=bar><i class="' + (db > -6 ? 'hot' : '') + '" style="width:' + pct + '%"></i></div>' +
    '<div class=v>' + (db <= -119 ? '&minus;∞' : db.toFixed(1)) + ' dB</div>';
}

async function tick() {
  const e = document.getElementById('err');
  try {
    const r = await fetch('/api/meter');
    const d = await r.json();
    if (!r.ok) { e.textContent = d.error || ('HTTP ' + r.status); return; }
    e.textContent = '';
    const peak = Math.max(d.left_db, d.right_db);
    const st = document.getElementById('state');
    st.textContent = peak <= -119 ? 'silent' : peak.toFixed(1) + ' dB';
    st.className = 'big ' + (d.rising ? 'rising' : 'steady');
    document.getElementById('note').textContent = d.rising
      ? 'RISING — the level is still building, not just loud'
      : (peak <= -119 ? 'nothing is reaching the main outputs' : 'steady or decaying');
    document.getElementById('bars').innerHTML =
      bar('L', d.left_db) + bar('R', d.right_db);
    for (const [k, v] of [['l', d.left_db], ['r', d.right_db],
                          ['sl', d.left_slow_db], ['sr', d.right_slow_db]]) {
      hist[k].push(v);
      while (hist[k].length > HIST) hist[k].shift();
    }
    draw();
  } catch (err) { e.textContent = String(err); }
}

document.getElementById('stop').onclick = async () => {
  await fetch('/api/meter?stop=1');
  document.getElementById('note').textContent = 'metering stopped — reload to resume';
};

tick(); setInterval(tick, 200);
</script>`
