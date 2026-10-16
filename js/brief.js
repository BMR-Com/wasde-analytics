/* WASDE Brief — renders data/brief/<YYYY-MM>.json (built monthly by brief.py). */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var IDX = null, CUR = null, COM = 'Cotton';
  var ATTRS = ['Production', 'Domestic Use', 'Exports', 'Imports', 'Ending Stocks'];
  var md = function (t) { return String(t).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>'); };
  function nd(v) { return Math.abs(v) >= 1000 ? 0 : 2; }
  function num(v, d) { return v == null ? '–' : v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function chg(v, d, invert) {
    if (v == null) return '';
    if (Math.abs(v) < Math.pow(10, -d) / 2) return '<span class="bk-z">unch</span>';
    var good = invert ? v < 0 : v > 0;
    return '<span class="' + (good ? 'bk-up' : 'bk-dn') + '">' + (v > 0 ? '+' : '−') + num(Math.abs(v), d) + '</span>';
  }
  function changesTable(rows, unit) {
    if (!rows || !rows.length) return '';
    var h = '<table class="bk-t"><thead><tr><th class="l">Region</th>' + ATTRS.map(function (a) { return '<th>' + a + '</th>'; }).join('') + '<th>Stocks / use</th></tr></thead><tbody>';
    rows.forEach(function (r) {
      var agg = /^World/.test(r.region);
      h += '<tr' + (agg ? ' class="agg"' : '') + '><td class="l">' + r.region + (unit && r.unit ? '<br><span class="bk-z">' + r.unit + '</span>' : '') + '</td>';
      ATTRS.forEach(function (a) {
        var c = r[a] || {}; var d = nd((r.Production && r.Production.now) || c.now || 0);
        h += '<td>' + (c.now == null ? '<span class="bk-z">–</span>' : '<b>' + num(c.now, d) + '</b><br>' + chg(c.chg, d, false)) + '</td>';
      });
      var s = r['S/U'] || {};
      h += '<td>' + (s.now == null ? '–' : '<b>' + (s.now * 100).toFixed(1) + '%</b><br>' + (s.chg == null ? '' : chg(s.chg * 100, 1, false).replace(/(\d)</, '$1 pts<'))) + '</td></tr>';
    });
    return h + '</tbody></table><div class="bk-note">Focus marketing year; value and change vs the previous report' + '' +
      '. Stocks/use = ending stocks ÷ total use (domestic use for world aggregates, domestic use + exports for countries).</div>';
  }
  function histTable(H, month) {
    if (!H || !H.length) return '';
    var h = '<table class="bk-t"><thead><tr><th class="l">Series</th><th>This report</th><th>Avg ' + month + ' move</th><th>Larger than</th><th>Past ' + month + ' raises</th><th class="l">Context</th></tr></thead><tbody>';
    H.forEach(function (x) {
      var d = Math.abs(x.chg) >= 10 ? 0 : 2;
      h += '<tr><td class="l">' + x.region + ' · ' + x.attr + '</td><td>' + chg(x.chg, d, false) + '</td><td>±' + num(x.avg_abs, d) + '</td><td>' + Math.round(x.pct_abs) + '% of moves</td><td>' +
        Math.round(x.up_share * 100) + '%</td><td class="l bk-ctx">' + x.note + '</td></tr>';
    });
    return h + '</tbody></table><div class="bk-note">Change in this report compared with the same calendar month\'s revision in every year since ' + H[0].since + '.</div>';
  }
  function factorTable(F) {
    if (!F || !F.length) return '';
    return '<table class="bk-t bk-f"><thead><tr><th class="l">Fundamental</th><th>Read</th><th class="l">Detail</th></tr></thead><tbody>' +
      F.map(function (f) { return '<tr><td class="l"><b>' + f.factor + '</b></td><td><span class="bk-tag ' + f.tilt + '">' + f.tilt + '</span></td><td class="l">' + md(f.text) + '</td></tr>'; }).join('') + '</tbody></table>';
  }
  function render() {
    if (!CUR) return;
    var names = ['Cotton'].concat(Object.keys(CUR).filter(function (k) { return k !== 'Cotton' && CUR[k] && CUR[k].brief; }));
    if (names.indexOf(COM) < 0) COM = 'Cotton';
    $('bkPills').innerHTML = names.map(function (n) { return '<button class="bk-pill' + (n === COM ? ' on' : '') + '" data-c="' + n + '">' + n + '</button>'; }).join('');
    var B = CUR[COM], month = CUR.label.split(' ')[0];
    var badge = COM === 'Cotton' ? '<span class="bk-tag big ' + (/bull/.test(B.outlook) ? 'bullish' : /bear/.test(B.outlook) ? 'bearish' : 'neutral') + '">Outlook: ' + B.outlook + '</span>' : '';
    var text = B.brief.map(function (b) { return '<div class="bk-h">' + b.h + '</div><p>' + md(b.t) + '</p>'; }).join('');
    var html = '<div class="bk-top"><div class="bk-title">' + CUR.label + ' WASDE · ' + COM + ' · ' + B.my + '</div>' + badge + '</div>';
    if (COM === 'Cotton') {
      html += '<div class="bk-grid"><div class="bk-text">' + text + '</div><div><div class="bk-sub">Fundamentals check</div>' + factorTable(B.factors) + '</div></div>';
      html += '<div class="bk-sub">Key changes — world and major countries (million 480-lb bales)</div><div class="bk-scroll">' + changesTable(B.changes, '') + '</div>';
    } else {
      html += '<div class="bk-text">' + text + '</div><div class="bk-sub">Key changes</div><div class="bk-scroll">' + changesTable(B.changes, B.unit) + '</div>';
    }
    html += '<div class="bk-sub">This revision vs past ' + month + ' reports</div><div class="bk-scroll">' + histTable(B.history, month) + '</div>';
    $('bkBody').innerHTML = html;
  }
  function load(key) {
    $('bkBody').innerHTML = '<div class="spinner">Loading brief…</div>';
    fetch('./data/brief/' + key + '.json?v=' + encodeURIComponent(IDX.generated)).then(function (r) { return r.json(); })
      .then(function (d) { CUR = d; render(); });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.bk-pill'); if (b) { COM = b.getAttribute('data-c'); render(); }
  });
  fetch('./data/brief/index.json?t=' + Date.now()).then(function (r) { if (!r.ok) throw 0; return r.json(); }).then(function (d) {
    IDX = d;
    var sel = $('bkReport');
    sel.innerHTML = d.reports.map(function (r) { return '<option value="' + r.report + '">' + r.label + ' WASDE</option>'; }).join('');
    sel.onchange = function () { load(sel.value); };
    $('bkGen').textContent = 'Brief built ' + d.generated;
    load(d.reports[0].report);
  }).catch(function () { var s = $('bkSec'); if (s) s.style.display = 'none'; });
})();
