/* Scudi · SNAI — the reading itself (the same reading as the bookmark's, decision 83, kept identical by the tests).
   For each match on the SNAI list shown: SNAI's event number, the two names, the kick-off as printed, the competition
   and every price button with SNAI's own code (esito_<palinsesto>_<event>_<market>_<line>_<outcome>); a padlocked
   (disabled) button is a price SNAI has suspended. It only looks at what the page already shows. */
/* exported scudiReadSnai */
function scudiReadSnai(D) {
  /* the text of an element, piece by piece (a <br> between date and time keeps them apart) */
  function words(e) {
    var out = [], w = D.createTreeWalker(e, 4, null, false), n, s;
    while ((n = w.nextNode())) { s = n.data.replace(/\s+/g, ' ').trim(); if (s) out.push(s); }
    return out;
  }
  var titles = [];
  function compOf(row) {
    var sec = row.closest('[id^="fr-competition-detail"]') || row.closest('[class*="competitionDetails"]'), i;
    if (!sec) return '';
    for (i = 0; i < titles.length; i++) if (titles[i][0] === sec) return titles[i][1];
    var w = D.createTreeWalker(sec, 4, null, false), n, t = '';
    while ((n = w.nextNode()) && !(t = n.data.replace(/\s+/g, ' ').trim())) {}
    titles.push([sec, t]);
    return t;
  }
  var links = D.querySelectorAll('a[data-qa^="regulator-link-"]'), out = [], seen = {}, i, j, k;
  for (i = 0; i < links.length; i++) {
    var a = links[i], id = String(a.getAttribute('data-qa')).slice(15), row = a.closest('[class*="mg-row-wrapper"]') || a.closest('[class*="mg-row"]');
    if (!row || !row.querySelector('button[data-qa^="esito_"]')) { row = a; for (k = 0; k < 7 && row && !row.querySelector('button[data-qa^="esito_"]'); k++) row = row.parentElement; }
    if (!row || !id) continue;
    var bs = row.querySelectorAll('button[data-qa^="esito_"]'), nm = words(a), m = [], qs = [], ev = {}, top = '', most = 0;
    if (!bs.length || nm.length < 2) continue;
    for (j = 0; j < bs.length; j++) {
      var q = /^esito_(\d+)_(\d+)_(\d+)_(-?\d+)_(\d+)$/.exec(bs[j].getAttribute('data-qa') || '');
      if (!q) continue;
      qs.push([q, bs[j]]); ev[q[1] + '_' + q[2]] = (ev[q[1] + '_' + q[2]] || 0) + 1;
    }
    for (k in ev) if (ev[k] > most) { most = ev[k]; top = k; }
    for (j = 0; j < qs.length; j++) {
      var qq = qs[j][0], b = qs[j][1];
      if (qq[1] + '_' + qq[2] !== top) continue;
      var t = words(b).join('');
      if (b.disabled || b.querySelector('[class*="ock"]')) m.push([+qq[3], +qq[4], +qq[5], null]);
      else if (/^\d{1,4}([.,]\d{1,2})?$/.test(t)) m.push([+qq[3], +qq[4], +qq[5], parseFloat(t.replace(',', '.'))]);
    }
    var tb = row.querySelector('[class*="dateTimeBox"], [class*="regulatorTime"]'), rec = { id: id, home: nm[0], away: nm[1], when: tb ? words(tb).join(' ') : '', comp: compOf(row), m: m };
    if (seen[id] != null) { if (m.length > out[seen[id]].m.length) out[seen[id]] = rec; continue; }
    seen[id] = out.length;
    out.push(rec);
  }
  return out;
}
