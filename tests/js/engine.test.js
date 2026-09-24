/* Engine checks for the page's slip maths (index.html), run with `node tests/js/engine.test.js` (pytest runs it too).
   The Scudi block is read straight out of index.html, so the page and the tests can never drift apart. */
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm');
const html = fs.readFileSync(path.join(__dirname, '..', '..', 'index.html'), 'utf8');
const a = html.indexOf('/* ===== Scudi slip maths'), b = html.indexOf("if (typeof module !== 'undefined') module.exports = Scudi;");
const ctx = { module: {}, console };
vm.runInNewContext(html.slice(a, b) + '\nthis.Scudi = Scudi;', ctx);
const S = ctx.Scudi;
/* the screenshot reader's pure part (grid, columns, prices), read out of index.html the same way */
const sa = html.indexOf('/* ===== ShotReader'), sb = html.indexOf('/* ===== end ShotReader');
const sctx = { console }; vm.runInNewContext(html.slice(sa, sb) + '\nthis.ShotReader = ShotReader;', sctx);
const SR = sctx.ShotReader;
let failures = 0, checks = 0;
function ok(cond, msg) { checks++; if (!cond) { failures++; console.error('FAIL: ' + msg); } }
function rng(seed) { let h = seed >>> 0; return () => { h ^= h << 13; h >>>= 0; h ^= h >>> 17; h ^= h << 5; h >>>= 0; return (h % 1000003) / 1000003; }; }

/* synthetic matches: random chances and prices for a random subset of offered pick types */
function synth(r, n, leagues) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const codes = S.OFFERED.filter(() => r() < 0.08).slice(0, 7);
    if (!codes.length) codes.push('1');
    const ch = {}, est = {};
    codes.forEach(c => { const p = 0.15 + r() * 0.75; ch[c] = p; est[c] = Math.max(1.27, Math.round(100 / (p * (1 + 0.02 + r() * 0.1))) / 100); });
    out.push({ id: 'm' + i, lg: leagues[i % leagues.length], home: 'H' + i, away: 'A' + i, pre: { chances: ch, estimate: est } });
  }
  return out;
}
function brute(matches, target, opts) {
  const menus = matches.map(m => S.menuFor(m, opts)), lam = opts.lambda || 0;
  let best = null;
  const lim = opts.groupLimits || {}, locks = opts.locks || {};
  (function rec(i, picks) {
    if (i === matches.length) {
      const k = picks.length; if (!k) return;
      if (!opts.autoLegs && k !== opts.legs) return;
      if (opts.autoLegs && k > opts.legs) return;
      let odds = 1, obj = 0; const by = {};
      picks.forEach(x => { odds *= x.pick.odds; obj += Math.log(x.pick.w); by[x.match.lg] = (by[x.match.lg] || 0) + 1; });
      const need = opts.autoLegs && opts.rowTarget ? opts.rowTarget(k) : target;
      if (odds < need * (1 - 1e-12)) return;
      for (const g in lim) { if ((by[g] || 0) < lim[g][0] || (lim[g][1] != null && by[g] > lim[g][1])) return; }
      if (opts.groupMax) for (const g in by) if (!lim[g] && by[g] > opts.groupMax) return;
      if (Object.keys(locks).some(id => !picks.some(x => x.match.id === id && x.pick.id === locks[id]))) return;
      if (opts.autoLegs && lam) obj += lam * Math.log(1 + S.snaiBonus(k));
      if (!best || obj > best.obj) best = { obj, odds, picks: picks.slice() };
      return;
    }
    if (!locks[matches[i].id]) rec(i + 1, picks);
    menus[i].forEach(p => { picks.push({ match: matches[i], pick: p }); rec(i + 1, picks); picks.pop(); });
  })(0, []);
  return best;
}

/* 1. the optimiser is exact, with the objective's lambda, pruning, rules and locks */
let exact = 0, feasible = 0;
for (let t = 0; t < 260; t++) {
  const r = rng(1000 + t), n = 4 + Math.floor(r() * 3), matches = synth(r, n, ['A', 'B']);
  const lambda = [0, 0, 0.25, 0.5, 1][t % 5], auto = t % 2 === 0, target = [1.5, 3, 6, 12, 30][Math.floor(r() * 5)];
  const opts = { lambda, autoLegs: auto, legs: auto ? n : 1 + Math.floor(r() * n), allowed: null, minLegOdds: 1.27, grid: 0.004 };
  if (t % 7 === 3) opts.groupLimits = { A: [1, 2] };
  if (t % 11 === 5) opts.groupMax = 2;
  if (t % 5 === 4 && auto) opts.rowTarget = k => target / (1 + S.snaiBonus(k));
  if (t % 13 === 6) { const m = matches[0], c = Object.keys(m.pre.chances)[0]; opts.locks = { [m.id]: c }; }
  const got = S.solve(matches, target, Object.assign({}, opts)), want = brute(matches, target, opts);
  if (!want) { ok(!got, 'no slip exists but the solver found one (case ' + t + ')'); continue; }
  feasible++;
  ok(!!got, 'solver found nothing where a slip exists (case ' + t + ')');
  if (!got) continue;
  const need = auto && opts.rowTarget ? opts.rowTarget(got.picks.length) : target;
  ok(got.odds >= need * (1 - 1e-12), 'slip under its target (case ' + t + ')');
  const gap = want.obj - got.obj;
  ok(gap < 1e-9, 'not the best slip: gap ' + gap.toExponential(2) + ' (case ' + t + ', lambda ' + lambda + ')');
  if (gap < 1e-9) exact++;
}
ok(feasible > 150, 'enough feasible cases: ' + feasible);

/* 2. lambda trades chance for return, monotonically */
const r2 = rng(42), pool = synth(r2, 12, ['A']);
let prevP = 2, prevR = -1;
[0, 0.25, 0.5, 0.75, 1].forEach(lam => {
  const s = S.solve(pool, 20, { lambda: lam, autoLegs: true, legs: 12, minLegOdds: 1.27, grid: 0.002 });
  const ret = s.prob * s.odds * (1 + S.snaiBonus(s.picks.length));
  ok(s.prob <= prevP + 1e-12 && ret >= prevR - 1e-12, 'lambda ' + lam + ' is not on the trade-off curve');
  prevP = s.prob; prevR = ret;
});

/* 3. pruning keeps exactly the undominated picks */
const L = S.prune([{ odds: 2, w: 0.4 }, { odds: 1.9, w: 0.45 }, { odds: 1.8, w: 0.44 }, { odds: 2.5, w: 0.3 }, { odds: 2.5, w: 0.2 }]);
ok(L.length === 3 && L.map(x => x.odds).join() === '2.5,2,1.9', 'prune');

/* 4. prudence and signals only change the weight, never the chance printed */
const m4 = { id: 'q', lg: 'A', home: 'H', away: 'A', lh: 1.6, la: 1.0, rho: -0.05, spread: { '1': 0.02, 'X': 0.01, '2': 0.015, '1X': 0.01, 'X2': 0.012, '12': 0.01, 'O25': 0.02, 'U25': 0.02 }, sig: { '1': 0.03, '2': -0.04 } };
const plain = S.menuFor(m4, { minLegOdds: 1.27 }), prud = S.menuFor(m4, { minLegOdds: 1.27, prudent: 1.5 }), sig = S.menuFor(m4, { minLegOdds: 1.27, signals: true });
const one = l => l.filter(c => c.id === '1')[0];
ok(one(prud).p === one(plain).p && one(prud).w < one(plain).w && Math.abs(one(prud).w - (one(plain).p - 1.5 * 0.02)) < 1e-12, 'prudent weight');
ok(one(sig).w > one(plain).w && !sig.some(c => c.id === '2'), 'signals favour moves towards a pick and drop moves of 3+ points against');
ok(Math.abs(S.spreadOf('1X+U35', m4.spread) - Math.hypot(0.01, 0.02)) < 1e-12 && S.spreadOf('MG1-3', m4.spread) === 0.02 && S.spreadOf('1H-1', m4.spread) === 0.02, 'spread of derived picks');

/* 5. learned corrections move the chance in log-odds, per pick type and per competition */
const lp = S.learnedP(0.6, { '1': 0.1, 'lg:A': -0.05 }, '1', 'A');
ok(Math.abs(lp - S.sigmoid(S.logit(0.6) + 0.05)) < 1e-12 && S.learnedP(0.6, null, '1', 'A') === 0.6, 'learned correction');

/* 6. first-half picks settle on the half-time score, and wait for it */
ok(S.settles('1TO05', 2, 0, 1, 0) === true && S.settles('1TO05', 2, 0, 0, 0) === false && S.settles('1TO05', 2, 0) === null, 'first-half settle');
ok(S.settles('MG2-4', 2, 1) === true && S.settles('1H-1', 2, 0) === true && S.settles('2H+1', 0, 2) === true && S.settles('X2+U35', 1, 1) === true, 'full-time settle');
ok(S.inplay('1TO05', 1.5, 1, 0, 0, 0, false) > 0.5 && S.inplay('1TO05', 1.5, 1, 0, 0, 44, false) < 0.15 && S.inplay('1TO05', 1.5, 1, 1, 0, 80, false, 0, 0) === 0, 'first-half in play');
ok(Math.abs(S.inplay('MG1-3', 1.5, 1, 0, 0, 0, false) - S.chancesOf({ lh: 1.5, la: 1, rho: 0 }).O15) < 0.4, 'in play at kickoff is near the pre-match view');

/* 7. the SNAI reader: the main page, and the other tabs from their headers */
const wk = [{ id: 'g', home: 'Genoa', away: 'Fiorentina' }, { id: 'i', home: 'Inter', away: 'Parma' }];
const main = S.parseSnai('Serie A\n1 X 2 1X X2 12 U O 2,5 GG NG\nGenoa - Fiorentina 2,75 3,10 2,70 1,45 1,43 1,36 1,72 2,05 1,78 1,95\nInter - Parma 1,30 5,50 10,00 1,06 3,50 1,15 2,40 1,55 2,10 1,68', wk);
ok(main.length === 2 && main[0].ok && main[0].prices['1'] === 2.75 && main[0].prices.NG === 1.95 && main[1].prices['2'] === 10, 'main page');
const mg = S.parseSnai('MULTIGOL\n1-2 1-3 1-4 1-5 2-3 2-4 2-5 7+\nGenoa - Fiorentina 2,20 1,55 1,22 1,08 2,60 1,70 1,40 25,00\nInter - Parma 2,50 1,70 1,30 1,12 2,90 1,65 1,33 15,00', wk);
ok(mg[0].prices['MG1-3'] === 1.55 && mg[0].prices['MG2-5'] === 1.4 && !mg[0].prices['1'] && mg[1].prices['MG1-2'] === 2.5 && mg[0].ok, 'multigol tab');
const cb = S.parseSnai('COMBO\n1X + U 3,5   X2 + U 3,5   1 + O 1,5   GG + O 2,5\nGenoa - Fiorentina 1,85 1,80 3,40 2,30\nInter - Parma 1,95 6,50 1,55 3,60', wk);
ok(cb[0].prices['1X+U35'] === 1.85 && cb[0].prices['GG+O25'] === 2.3 && cb[1].prices['1+O15'] === 1.55, 'combo tab');
const hc = S.parseSnai('HANDICAP (0:1)\n1 X 2\nGenoa - Fiorentina 6,00 4,20 1,40\nInter - Parma 2,10 3,60 2,90', wk);
ok(hc[1].prices['1H-1'] === 2.1 && hc[1].prices['2H-1'] === 2.9 && hc[1].prices['XH-1'] === 3.6 && !hc[1].prices['1'], 'handicap tab');
ok(!S.candidates({ id: 'i', lg: 'A', home: 'Inter', away: 'Parma', lh: 1.9, la: 0.8, snai: hc[1].prices }, 1.01).some(c => c.id === 'XH-1'), 'a type that failed the check is read but never offered');
const ht = S.parseSnai('1° TEMPO\n1 X 2 U 1,5 O 1,5\nGenoa - Fiorentina 3,30 2,00 3,30 1,45 2,60\nInter - Parma 1,90 2,40 9,00 1,75 2,05', wk);
ok(ht[0].prices['1TX'] === 2 && ht[0].prices['1TU15'] === 1.45 && ht[1].prices['1T2'] === 9 && ht[1].prices['1T1'] === 1.9 && ht[0].ok, 'first-half tab');
const tg = S.parseSnai('U/O CASA\nU 1,5 O 1,5\nGenoa - Fiorentina 1,40 2,75\nInter - Parma 2,60 1,45', wk);
ok(tg[0].prices.HU15 === 1.4 && tg[1].prices.HO15 === 1.45, 'team goals tab');

/* 4. the new markets are offered only from 30% up (where they were checked); classic picks keep their full range */
const wide = S.candidates({ id: 'w', lg: 'A', home: 'Inter', away: 'Parma', lh: 2.6, la: 0.5, rho: -0.06 }, 1.01);
const newOnes = wide.filter(c => !S.CLASSIC_IDS.includes(c.id)), classicLow = wide.filter(c => S.CLASSIC_IDS.includes(c.id) && c.p0 < S.NEW_FLOOR);
ok(S.NEW_FLOOR === 0.3 && newOnes.length > 10 && newOnes.every(c => c.p0 >= S.NEW_FLOOR) && classicLow.length > 0, 'new markets from 30% up only');
const allNew = S.OFFERED.filter(id => !S.CLASSIC_IDS.includes(id)), ch = S.chancesOf({ lh: 2.6, la: 0.5, rho: -0.06 });
ok(allNew.filter(id => ch[id] != null && ch[id] < S.NEW_FLOOR).every(id => !wide.some(c => c.id === id)), 'every new type under 30% is left out');

/* 8. text further up the page never changes the columns (a breadcrumb, a tab bar, the site's menus) */
const crumbs = 'Home > Calcio > Italia > Serie A\nPrincipali Multigol Combo Handicap 1° Tempo U/O Casa\nSerie A\n1 X 2 1X X2 12 U O 2,5 GG NG\nsab 10/10\n15:00 Genoa - Fiorentina 2,75 3,10 2,70 1,45 1,43 1,36 1,72 2,05 1,78 1,95\n20:45 Inter - Parma 1,30 5,50 10,00 1,06 3,50 1,15 2,40 1,55 2,10 1,68';
const mc = S.parseSnai(crumbs, wk);
ok(mc[0].main && mc[0].prices.U25 === 1.72 && mc[0].prices.O25 === 2.05 && !mc[0].prices.HU25 && mc[1].prices['2'] === 10, 'main page under a breadcrumb and a tab bar');
const mgBar = S.parseSnai('Home > Calcio\nPrincipali Multigol Combo Handicap\nMULTIGOL\n1-2 1-3 1-4 1-5 2-3 2-4 2-5 7+\nGenoa - Fiorentina 2,20 1,55 1,22 1,08 2,60 1,70 1,40 25,00', wk);
ok(mgBar[0].prices['MG1-3'] === 1.55 && !mgBar[0].main, 'multigol tab under a tab bar');
/* 9. a price far from the market's chance is a column read wrong: left out */
const wk2 = [{ id: 'g', home: 'Genoa', away: 'Fiorentina', ref: { lh: 1.3, la: 1.2, rho: -0.06 } }];
const bad = S.parseSnai('U/O CASA\nU 2,5 O 2,5\nGenoa - Fiorentina 1,72 2,05', wk2);
ok(bad[0].odd.indexOf('HU25') > -1 && !bad[0].prices.HU25, 'an implausible price is left out');

/* 10. SNAI's list page as it really is (Nations League, 24-25 Sep 2026): national teams in Italian, the 2.5 selector
   between the columns, padlocked prices that print nothing, the goals-total column and the "+641" link after */
const nat = [
  { id: 'a', home: 'Andorra', away: 'Malta', names: [['Andorra'], ['Malta']] },
  { id: 'l', home: 'Liechtenstein', away: 'Lithuania', names: [['Liechtenstein'], ['Lithuania', 'Lituania']] },
  { id: 'p', home: 'Portugal', away: 'Wales', names: [['Portugal', 'Portogallo'], ['Wales', 'Galles']] },
  { id: 'g', home: 'Georgia', away: 'Northern Ireland', names: [['Georgia'], ['Northern Ireland', 'Irlanda del Nord', 'irlanda nord']] }];
const natText = 'UEFA Nations League\n1\tX\t2\t1X\tX2\t12\tU\tO\tGG\tNG\n' +
  '24/09\n17:00\nAndorra\nMalta\n3.50\t2.70\t2.35\t1.50\t1.25\t1.40\t2.5\t1.30\t3.10\t2.30\t1.52\t0\t5.00\t+\t+641\n' +
  '24/09\n19:45\nLiechtenstein\nLituania\n11.00\t4.25\t1.30\t3.00\t1.15\t2.5\t1.70\t2.00\t2.40\t1.45\t0\t9.00\t+\t+645\n' +
  '24/09\n19:45\nPortogallo\nGalles\n1.20\t6.50\t15.00\t4.25\t1.10\t2.5\t2.40\t1.52\t2.10\t1.65\t0\t16.00\t+\t+2545\n' +
  '25/09\n17:00\nGeorgia\nIrlanda Del Nord\n1.80\t3.60\t4.25\t1.18\t1.90\t1.25\t1.5\t3.40\t1.30\t1.90\t1.80\t0\t9.00\t+\t+1824';
const nr = S.parseSnai(natText, nat), byId = {}; nr.forEach(r => { byId[r.match.id] = r.prices; });
ok(nr.length === 4 && byId.a.U25 === 1.3 && byId.a.O25 === 3.1 && byId.a.NG === 1.52, 'national list page read');
ok(byId.l['1X'] === 3 && byId.l['12'] === 1.15 && byId.l.X2 === undefined && byId.l.U25 === 1.7, 'a padlocked X2 is left empty, the rest stays in place');
ok(byId.p['1X'] === undefined && byId.p.X2 === 4.25 && byId.p['12'] === 1.1 && byId.p.GG === 2.1, 'a padlocked 1X is left empty, the rest stays in place');
ok(byId.g.O15 === 1.3 && byId.g.U25 === undefined && byId.g.O25 === undefined && byId.g.GG === 1.9, 'the selector on 1.5 reads over 1.5, not over 2.5');

/* 11. the screenshot reader: words with their positions (as the recogniser returns them) → rows, columns, prices */
ok(SR.priceOf('270') === 2.7 && SR.priceOf('1500') === 15 && SR.priceOf('2.35') === 2.35 && SR.priceOf('1,O7') === 1.07 && SR.priceOf('25') === null && SR.lineOf('25') === '2' && SR.lineOf('1.5') === '1', 'screenshot prices and goals line');
const shotRows = [
  ['Andorra', 'Malta', ['3.50', '2.70', '2.35', '1.50', '1.25', '1.40', '25', '1.30', '3.10', '2.30', '1.52', '0', '5.00']],
  ['Liechtenstein', 'Lituania', ['1100', '4.25', '1.30', '3.00', null, '1.15', '25', '1.70', '2.00', '2.40', '1.45', '0', '9.00']],
  ['Portogallo', 'Galles', ['1.20', '6.50', '15.00', null, '4.25', '1.10', '25', '2.40', '1.52', '2.10', '1.65', '0', '16.00']],
  ['Georgia', 'Irlanda Del Nord', ['1.80', '3.60', '4.25', '1.18', '1.90', '1.25', '15', '3.40', '1.30', '1.90', '1.80', '0', '9.00']]];
const W = (text, x, y) => ({ text, conf: 90, x0: x - 18, x1: x + 18, y0: y - 7, y1: y + 7, cx: x, cy: y, h: 14, w: 36 });
const ws = [];
shotRows.forEach((r, i) => {
  const y = 50 + i * 60;
  ws.push(W('24/09', 30, y - 8), W('19:45', 30, y + 8), W(r[0].split(' ')[0], 100, y - 12), W(r[1].split(' ')[0], 100, y + 12));
  if (r[1].split(' ').length > 1) r[1].split(' ').slice(1).forEach((t, k) => ws.push(W(t, 150 + k * 40, y + 12)));
  r[2].forEach((t, k) => { if (t) ws.push(W(t, 260 + k * 57, y)); });
});
const G = SR.grid(ws), rd = G ? SR.reading(G) : [];
ok(rd.length === 4 && rd[0].home === 'Andorra' && rd[0].away === 'Malta' && rd[3].away === 'Irlanda Del Nord', 'screenshot rows and team names');
ok(rd[0].prices['1'] === 3.5 && rd[0].prices.NG === 1.52 && rd[0].prices.U === 1.3 && rd[0].line === '2' && !rd[0].issues.length, 'screenshot main row');
ok(rd[1].prices['1'] === 11 && rd[1].prices.X2 === undefined && rd[1].prices['12'] === 1.15 && rd[2].prices['1X'] === undefined && rd[2].prices.X2 === 4.25, 'screenshot padlocked cells stay empty');
ok(rd[3].line === '1' && rd[3].prices.O === 1.3, 'screenshot goals line on 1.5');
const txt = SR.asText('', rd.map((r, i) => Object.assign({}, r, { name: ['Andorra - Malta', 'Liechtenstein - Lithuania', 'Portugal - Wales', 'Georgia - Northern Ireland'][i] })));
const back = S.parseSnai(txt, [['a', 'Andorra', 'Malta'], ['l', 'Liechtenstein', 'Lithuania'], ['p', 'Portugal', 'Wales'], ['g', 'Georgia', 'Northern Ireland']].map(x => ({ id: x[0], home: x[1], away: x[2], names: [[x[1]], [x[2]]] })));
const bk = {}; back.forEach(r => { bk[r.match.id] = r.prices; });
ok(back.length === 4 && bk.a.U25 === 1.3 && bk.a.O25 === 3.1 && bk.l.X2 === undefined && bk.p['1X'] === undefined && bk.p.X2 === 4.25 && bk.g.O15 === 1.3 && bk.g.O25 === undefined, 'screenshot rows through the page reader');
/* decision 82: kick-off read from the row, tall boxes, bands */
ok(rd[0].when && rd[0].when.d === 24 && rd[0].when.mo === 9 && rd[0].when.hh === 19 && rd[0].when.mi === 45, 'screenshot kick-off date and time read');
const wsTall = ws.map(w => Object.assign({}, w));
const tallBox = wsTall.filter(w => w.text === '2.70')[0]; tallBox.y1 += 22; tallBox.h += 22; tallBox.cy += 11;   /* the recogniser's box runs into the row below */
const rdT = SR.reading(SR.grid(wsTall));
ok(rdT.length === 4 && rdT[0].prices.X === 2.7 && rdT[1].prices.X === 4.25, 'a tall word box stays in its own row');
const bs = SR.bandsOf(1815, 3), cover = bs.every((b, i) => !i || bs[i - 1].y0 + bs[i - 1].h - b.y0 >= 260);
ok(SR.bandsOf(900, 3).length === 1 && bs.length === 3 && bs[0].y0 === 0 && bs[2].y0 + bs[2].h === 1815 && cover, 'screenshot bands overlap by more than a row');
ok(SR.bandsOf(9000, 2).length >= 5, 'a very tall screenshot is cut into bands of at most about 1,900 pixels');
ok(SR.rowIssues({ '1': 1.75, X: 2.75, '2': 4.25 }).indexOf('1X2') > -1 && !SR.rowIssues({ '1': 1.75, X: 3.75, '2': 4.25 }).length, 'a misread price that breaks the margin is flagged');
const badRow = SR.rowIssues({ '1': 2.7, X: 3.25, '2': 27 });
ok(badRow.indexOf('1X2') > -1 && !SR.rowIssues({ '1': 2.7, X: 3.25, '2': 2.7, '1X': 1.45, X2: 1.45, '12': 1.36 }).length, 'screenshot row checks');

/* live: ESPN's goal list, regular-time settlement, and the story rebuilt from it (decision 80), on real ESPN boards */
const EV = JSON.parse(fs.readFileSync(path.join(__dirname, 'espn_live_sample.json'), 'utf8'));
const evOf = n => EV.filter(e => e.name === n)[0];
const fio = evOf('Napoli at Fiorentina'), nor = evOf('England at Norway'), ger = evOf('Paraguay at Germany'), aus = evOf('Egypt at Australia'), fro = evOf('Como at Frosinone');
const legFio = { code: '1', p: 0.35, lh: 1.2, la: 1.5, th: '109', ta: '114', kick: fio.date };
let st = S.espnState(legFio, fio);
ok(st.state === 'post' && st.h === 1 && st.a === 1 && st.goals.length === 2 && st.hh === 0 && st.ha === 1 && !st.et, 'ESPN full time: score, goals, half time');
const stSw = S.espnState(Object.assign({}, legFio, { th: '114', ta: '109' }), fio);
ok(stSw.h === 1 && stSw.a === 1 && stSw.hh === 1 && stSw.ha === 0 && stSw.goals[0].s === 'h', 'ESPN swapped home and away');
st = S.espnState({ code: '1', p: 0.5, th: '4057', ta: '2572', kick: fro.date }, fro);
ok(st.hh === 2 && st.ha === 0 && st.goals[1].d === "45'+3'", "a 45'+3' goal belongs to the first half");
/* extra time: England won 2-1 after extra time, but at 90 minutes it was 1-1, and SNAI settles on the 90 minutes */
st = S.espnState({ code: 'X', p: 0.3, th: '464', ta: '448', kick: nor.date }, nor);
ok(st.state === 'post' && st.et && st.h === 1 && st.a === 1 && st.goals.length === 2, 'extra time: settled on the 90-minute score');
ok(S.settles('X', st.h, st.a) === true && S.settles('2', st.h, st.a) === false, 'extra time: a draw pick wins');
/* penalties: shoot-out kicks are not goals, so the list adds up and the half-time score is known */
st = S.espnState({ code: '1TO05', p: 0.4, th: '481', ta: '210', kick: ger.date }, ger);
ok(st.state === 'post' && st.h === 1 && st.a === 1 && st.goals.length === 2 && st.hh === 0 && st.ha === 1, 'shoot-out kicks left out');
st = S.espnState({ code: '1', p: 0.4, th: '628', ta: '2620', kick: aus.date }, aus);
ok(st.goals && st.h === 1 && st.a === 1 && st.goals.filter(g => g.s === 'h').length === 1, 'own goal credited to the side it helps');
/* in play: the same match at the 60th minute */
const live = JSON.parse(JSON.stringify(fio)), lc = live.competitions[0];
lc.status = { period: 2, displayClock: "60'", type: { name: 'STATUS_SECOND_HALF', state: 'in', completed: false, shortDetail: "60'" } };
lc.details = lc.details.slice(0, 2); lc.competitors.forEach(c => { c.score = '1'; });
st = S.espnState(legFio, live);
ok(st.state === 'in' && st.minute === 60 && st.hh === 0 && st.ha === 1 && st.goals.length === 2, 'in play: minute, half time from the goals');
const late = S.lateBy(st, 63 + 15 + 4);
ok(Math.abs(late - 4) < 1e-9 && S.lateBy({ state: 'in', minute: 20, period: 1 }, 25) === 5 && S.lateBy({ state: 'post' }, 99) === null, 'how late a match runs');
const a30 = S.stateAt(st, 30), a10 = S.stateAt(st, 10), a55 = S.stateAt(st, 55);
ok(a10.h === 0 && a10.a === 0 && a30.a === 1 && a30.h === 0 && a30.hh === null && a55.hh === 0 && a55.ha === 1 && a55.minute === 45, 'a leg rebuilt at an earlier minute');
/* the story of a two-leg slip: Fiorentina to win (in play, 60') and a second leg not started yet */
const legB = { code: 'O15', p: 0.7, lh: 1.4, la: 1.2, kick: new Date(Date.parse(fio.date) + 180 * 6e4).toISOString() };
const sty = S.story([legFio, legB], [st, { state: 'pre' }], [0, 180], 63 + 15);
ok(sty && sty.pts.length > 20 && sty.pts.every((q, i, a) => !i || q.t > a[i - 1].t) && sty.ev.length === 2, 'story: ordered points, both goals');
const g23 = sty.ev[1], g51 = sty.ev[0];
ok(g23.md === "23'" && g23.after < g23.before && g51.after > g51.before && g51.h === 1 && g51.a === 1, 'story: the away goal hurts, the equaliser helps');
ok(Math.abs(sty.pts[0].p - legFio.p * legB.p) < 0.02 && Math.abs(sty.pts[sty.pts.length - 1].p - S.legLive(legFio, st).p * legB.p) < 1e-12, 'story: starts at the kick-off chance, ends at the chance now');
ok(S.story([legFio], [{ state: 'in', h: 1, a: 0, minute: 30, goals: null }], [0], 30) === null, 'story: no goal list, no story');
const fin = S.story([legFio], [S.espnState(legFio, fio)], [0], 200);
ok(fin.pts[fin.pts.length - 1].p === 0 && fin.pts.some(q => q.t > 100 && q.p > 0), 'story: a finished leg ends at its result');

/* review fixes (decision 80): suspended, postponed, extra time without goals, stoppage goal, same minute, just scored */
const mk = (name, state, completed, period, clock, h, a, details) => { const e = JSON.parse(JSON.stringify(fio)), c = e.competitions[0];
  c.status = { period: period, displayClock: clock, type: { name: name, state: state, completed: completed, shortDetail: '' } };
  c.competitors.forEach(x => { x.score = String(x.homeAway === 'home' ? h : a); }); c.details = details || []; return e; };
const gd = (clock, team) => ({ scoringPlay: true, shootout: false, ownGoal: false, clock: { displayValue: clock }, team: { id: team } });
st = S.espnState(legFio, mk('STATUS_SUSPENDED', 'post', false, 1, "30'", 0, 0));
ok(st.state === 'unknown' && !st.et, 'a suspended match is not over');
st = S.espnState(legFio, mk('STATUS_POSTPONED', 'post', false, 0, "0'", 0, 0));
ok(st.state === 'unknown', 'a postponed match is not a 0-0');
const nor2 = JSON.parse(JSON.stringify(nor)); nor2.competitions[0].details = nor2.competitions[0].details.slice(0, 1);
st = S.espnState({ code: 'X', p: 0.3, th: '464', ta: '448', kick: nor.date }, nor2);
ok(st.state === 'unknown' && st.et, 'extra time without a goal list that adds up: left open');
st = S.espnState(legFio, mk('STATUS_FULL_TIME', 'post', true, 2, "90'+5'", 2, 1, [gd("23'", '109'), gd("51'", '114'), gd("93'", '109')]));
ok(st.state === 'post' && st.h === 2 && st.a === 1, 'no extra time: a goal written 93\' still counts');
ok(S.lateBy({ state: 'in', minute: 45, ht: true, hh: 0, ha: 0, period: 1 }, 55) === null && S.lateBy({ state: 'in', minute: 90, period: 2 }, 110) === null, 'no delay read at the break or in stoppage');
/* two matches at the same time, a goal in each at 30': one helps (home win, home scores), one hurts (home win, away scores) */
const L1 = { code: '1', p: 0.45, lh: 1.4, la: 1.1 }, L2 = { code: '1', p: 0.45, lh: 1.4, la: 1.1 };
const s1 = { state: 'in', minute: 40, period: 1, h: 1, a: 0, hh: null, ha: null, goals: [{ m: 30, x: 0, d: "30'", s: 'h' }] };
const s2 = { state: 'in', minute: 40, period: 1, h: 0, a: 1, hh: null, ha: null, goals: [{ m: 30, x: 0, d: "30'", s: 'a' }] };
const same = S.story([L1, L2], [s1, s2], [0, 0], 40);
const e1 = same.ev.filter(e => e.i === 0)[0], e2 = same.ev.filter(e => e.i === 1)[0];
ok(e1.after > e1.before && e2.after < e2.before, 'same-minute goals each show their own effect');
/* read in the very minute of the goal: it counts at once */
const s3 = { state: 'in', minute: 51, period: 2, h: 1, a: 1, hh: 0, ha: 1, goals: [{ m: 23, x: 0, d: "23'", s: 'a' }, { m: 51, x: 0, d: "51'", s: 'h' }] };
const just = S.story([legFio], [s3], [0], 63 + 6);
ok(just.ev[0].md === "51'" && just.ev[0].after > just.ev[0].before && just.ev[0].h === 1, 'a goal read in its own minute counts');

console.log(checks + ' checks, ' + failures + ' failed; optimiser exact in ' + exact + ' of ' + feasible + ' feasible cases');
process.exit(failures ? 1 : 0);
