/* Checks for the scudi-notify function's pure parts (decision 95): Web Push encryption and signature (push.mjs) and what
   is worth a notification (alerts.mjs, on the page's own live maths). Run with `node tests/js/notify.test.mjs`. */
import { encrypt, b64u, unb64u, newKeys, vapidAuth, request, outcome } from '../../supabase/functions/scudi-notify/push.mjs';
import * as A from '../../supabase/functions/scudi-notify/alerts.mjs';
import { Scudi } from '../../supabase/functions/scudi-notify/site.mjs';

let failures = 0, checks = 0;
function ok(cond, msg) { checks++; if (!cond) { failures++; console.error('FAIL: ' + msg); } }
const subtle = globalThis.crypto.subtle, te = new TextEncoder();

/* ---------- push.mjs ---------- */
/* RFC 8291, Appendix A: the worked example, byte for byte */
const ex = await encrypt({ endpoint: 'https://push.example.net/push/JzLQ3raZJfFBR0aqvOMsLrt54w4rJUsV', p256dh: 'BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4', auth: 'BTBZMqHH6r4Tts7J_aSIgg' },
  'When I grow up, I want to be a watermelon',
  { privateKey: 'yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw', publicKey: 'BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8', salt: 'DGv6ra1nlYgDCS1FRnbzlw' });
ok(b64u(ex) === 'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN',
  'RFC 8291 worked example reproduced');

/* a random device: what the function sends, the device can read (decrypted here as a browser would) */
async function hmac(k, d) { return new Uint8Array(await subtle.sign('HMAC', await subtle.importKey('raw', k, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']), d)); }
const cat = (...p) => { const o = new Uint8Array(p.reduce((a, x) => a + x.length, 0)); let i = 0; for (const x of p) { o.set(x, i); i += x.length; } return o; };
async function hkdf(salt, ikm, info, n) { return (await hmac(await hmac(salt, ikm), cat(info, new Uint8Array([1])))).subarray(0, n); }
async function device() {
  const kp = await subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const pub = new Uint8Array(await subtle.exportKey('raw', kp.publicKey)), auth = crypto.getRandomValues(new Uint8Array(16));
  return { kp, sub: { endpoint: 'https://web.push.apple.com/QGx1y2z', p256dh: b64u(pub), auth: b64u(auth) }, pub, auth };
}
async function decrypt(dev, body) {
  const salt = body.subarray(0, 16), rs = new DataView(body.buffer, body.byteOffset).getUint32(16), idlen = body[20], asPub = body.subarray(21, 21 + idlen), ct = body.subarray(21 + idlen);
  const asKey = await subtle.importKey('raw', asPub, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const ecdh = new Uint8Array(await subtle.deriveBits({ name: 'ECDH', public: asKey }, dev.kp.privateKey, 256));
  const ikm = await hkdf(dev.auth, ecdh, cat(te.encode('WebPush: info\0'), dev.pub, asPub), 32);
  const cek = await hkdf(salt, ikm, te.encode('Content-Encoding: aes128gcm\0'), 16), nonce = await hkdf(salt, ikm, te.encode('Content-Encoding: nonce\0'), 12);
  const plain = new Uint8Array(await subtle.decrypt({ name: 'AES-GCM', iv: nonce }, await subtle.importKey('raw', cek, { name: 'AES-GCM' }, false, ['decrypt']), ct));
  return { rs, idlen, text: new TextDecoder().decode(plain.subarray(0, plain.lastIndexOf(2))), delim: plain[plain.length - 1] };
}
const dev = await device(), keys = await newKeys();
ok(unb64u(keys.public_key).length === 65 && unb64u(keys.public_key)[0] === 4 && keys.private_jwk.d && keys.private_jwk.crv === 'P-256', 'a VAPID pair: an uncompressed P-256 point and a private JWK');
const msg = { title: 'Gol 67\' · Inter 2–1 Juventus', body: 'Ora 41% — è tutto “vero”', url: 'https://scudi26.github.io/schedine-website/#live' };
const req = await request(dev.sub, msg, keys, { ttl: 900, urgency: 'high', topic: 'g:401234/x' });
const dec = await decrypt(dev, req.init.body);
ok(dec.text === JSON.stringify(msg) && dec.delim === 2 && dec.rs === 4096 && dec.idlen === 65, 'a device decrypts the message (UTF-8 kept, one record, rs 4096)');
ok(req.url === dev.sub.endpoint && req.init.method === 'POST' && req.init.headers['Content-Encoding'] === 'aes128gcm' && req.init.headers.TTL === '900' && req.init.headers.Urgency === 'high', 'the request\'s headers');
ok(req.init.headers.Topic === 'g401234x', 'a topic of safe characters only');
const twice = await request(dev.sub, msg, keys, {});
ok(b64u(twice.init.body) !== b64u(req.init.body), 'a fresh salt and key for every message');
/* the VAPID token: the push service's origin, a near expiry, a contact, signed by the stored key */
const m = /^vapid t=([^.]+)\.([^.]+)\.([^,]+), k=(.+)$/.exec(req.init.headers.Authorization);
ok(!!m && m[4] === keys.public_key, 'Authorization: vapid t=…, k=<public key>');
const claims = JSON.parse(new TextDecoder().decode(unb64u(m[2])));
ok(claims.aud === 'https://web.push.apple.com' && claims.exp - Date.now() / 1000 > 11 * 3600 && claims.exp - Date.now() / 1000 <= 12 * 3600 + 5 && /^https:\/\//.test(claims.sub), 'the claims: aud, exp within 24 h, sub');
ok(JSON.parse(new TextDecoder().decode(unb64u(m[1]))).alg === 'ES256', 'ES256');
const vk = await subtle.importKey('raw', unb64u(keys.public_key), { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
ok(await subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, vk, unb64u(m[3]), te.encode(m[1] + '.' + m[2])), 'the signature verifies with the public key');
ok(unb64u(m[3]).length === 64, 'the signature is r ‖ s (64 bytes), as JWS wants');
let threw = false; try { await request(dev.sub, 'x'.repeat(5000), keys, {}); } catch (e) { threw = /too long/.test(e.message); }
ok(threw, 'a message over 4 KB is refused');
threw = false; try { await encrypt({ endpoint: 'https://x', p256dh: 'AAAA', auth: dev.sub.auth }, 'x'); } catch (e) { threw = true; }
ok(threw, 'bad subscription keys are refused');
ok(outcome(201) === 'ok' && outcome(410) === 'gone' && outcome(404) === 'gone' && outcome(403) === 'failed' && outcome(0) === 'failed', 'push service answers');
ok(/^vapid t=/.test(await vapidAuth('https://fcm.googleapis.com/fcm/send/abc', keys, 'https://x/', Date.now())), 'a token for another push service');

/* ---------- alerts.mjs ---------- */
const NOW = Date.parse('2026-10-11T19:30:00Z');   /* Sunday, 21:30 in Rome */
function ev(id, home, away, kickIso, o) {
  o = o || {};
  return { id, name: away[1] + ' at ' + home[1], date: kickIso, competitions: [{
    status: { period: o.period || 0, displayClock: o.clock || "0'", type: { name: o.name || 'STATUS_SCHEDULED', state: o.state || 'pre', completed: !!o.completed, shortDetail: o.short || '' } },
    competitors: [{ homeAway: 'home', score: String(o.h || 0), team: { id: home[0], displayName: home[1] } }, { homeAway: 'away', score: String(o.a || 0), team: { id: away[0], displayName: away[1] } }],
    details: o.details || [] }] };
}
const goal = (team, clock, who) => ({ scoringPlay: true, shootout: false, ownGoal: false, clock: { displayValue: clock }, team: { id: team }, athletesInvolved: who ? [{ displayName: who, shortName: who }] : [] });
const red = (team, clock, who) => ({ redCard: true, clock: { displayValue: clock }, team: { id: team }, athletesInvolved: [{ displayName: who }] });
const leg = (mid, home, away, th, ta, lg, kick, code, p) => ({ mid, home, away, th, ta, lg, kick, code, label: code, p, p0: p, odds: 1 / p, lh: 1.5, la: 1.1, rho: -0.05 });
const slipA = { id: 101, name: 'Serie A Sunday', stake: 5, pays: 12.5, odds: 12.5, at: '2026-10-11T08:00:00Z', legs: [
  leg('m1', 'Inter', 'Juventus', '110', '111', 'Serie A', '2026-10-11T18:45:00Z', '1X', 0.75),
  leg('m2', 'Roma', 'Lazio', '104', '112', 'Serie A', '2026-10-11T16:00:00Z', 'O15', 0.72),
  leg('m3', 'Napoli', 'Milan', '114', '103', 'Serie A', '2026-10-12T18:45:00Z', '1', 0.45)] };
const slipB = { id: 102, name: 'Two legs', stake: 2, pays: 3.1, odds: 3.1, at: '2026-10-11T08:00:00Z', legs: [
  leg('m1', 'Inter', 'Juventus', '110', '111', 'Serie A', '2026-10-11T18:45:00Z', 'GG', 0.55),
  leg('m4', 'Atalanta', 'Torino', '105', '239', 'Serie A', '2026-10-11T13:00:00Z', '1', 0.6)] };
const slipOld = { id: 103, name: 'Old', stake: 1, pays: 2, legs: [leg('m9', 'A', 'B', '1', '2', 'Serie A', '2026-10-01T18:45:00Z', '1', 0.5)] };
const slipFar = { id: 104, name: 'Next week', stake: 1, pays: 2, legs: [leg('m8', 'C', 'D', '3', '4', 'Serie A', '2026-10-18T18:45:00Z', '1', 0.5)] };
const placed = [slipA, slipB, slipOld, slipFar];

const w0 = A.watched(placed, NOW);
ok(w0.length === 2 && w0[0].id === 101 && w0[1].id === 102, 'watched: the slips on now (not one long gone, not next week)');
const bd = A.boards(w0, NOW, {}).map((x) => x.join('|')).sort();
ok(bd.length === 1 && bd[0] === 'ita.1|20261011', 'one scoreboard for Sunday\'s Serie A (Monday\'s leg not read yet)');
ok(A.boards(w0, NOW, { '101:0': {}, '101:1': {}, '102:0': {}, '102:1': {} }).length === 0, 'legs known finished are not read again');
ok(A.espnDate('2026-10-11T22:30:00Z') === '20261012', 'ESPN\'s day is Rome\'s day');

/* Inter 1-0 Juventus at 67', Roma-Lazio finished 2-1, Atalanta-Torino finished 0-1 */
const evs = [
  ev('401', ['110', 'Internazionale'], ['111', 'Juventus'], '2026-10-11T18:45Z', { state: 'in', period: 2, clock: "67'", h: 1, a: 0, details: [goal('110', "67'", 'Lautaro Martínez')] }),
  ev('402', ['104', 'AS Roma'], ['112', 'Lazio'], '2026-10-11T16:00Z', { state: 'post', completed: true, period: 2, clock: "90'+4'", name: 'STATUS_FULL_TIME', h: 2, a: 1, details: [goal('104', "12'"), goal('112', "40'"), goal('104', "77'")] }),
  ev('403', ['105', 'Atalanta'], ['239', 'Torino'], '2026-10-11T13:00Z', { state: 'post', completed: true, period: 2, clock: "90'+2'", name: 'STATUS_FULL_TIME', h: 0, a: 1, details: [goal('239', "55'")] })];
const st1 = A.legStates(w0, evs, NOW, {});
ok(st1.length === 5 && st1.filter((s) => s.ev).length === 4, 'every leg matched to its event (Monday\'s still ahead)');
ok(A.eventFor({ home: 'Inter', away: 'Juventus', kick: '2026-10-11T18:45:00Z' }, evs) === evs[0], 'matched by name through the aliases (Inter = Internazionale)');
ok(!A.eventFor({ home: 'Inter', away: 'Juventus', kick: '2026-10-13T18:45:00Z' }, evs), 'not a match two days away');
const sA0 = st1.find((s) => s.slip.id === 101 && s.i === 0);
ok(sA0.st.state === 'in' && sA0.st.h === 1 && sA0.live.now === true && sA0.live.p > 0.75, 'Inter 1-0 at 67\': 1X winning, its chance up');
const al1 = A.alerts({ now: NOW, lang: 'en', states: st1, site: 'https://s/' });
const g1 = al1.find((a) => a.ref === 'goal:401:1-0');
ok(!!g1 && /Goal 67' · Internazionale 1–0 Juventus/.test(g1.title), 'a goal alert: minute and score');
ok(g1 && /^Lautaro Martínez\n/.test(g1.body) && /1X winning/.test(g1.body) && /Both score losing/.test(g1.body) && /“Serie A Sunday”: now \d+%/.test(g1.body), 'its body: the picks on the match and the slips\' chances');
ok(g1 && g1.urgency === 'high' && g1.url === 'https://s/#live', 'urgent, opening the Live screen');
ok(al1.some((a) => a.ref === 'ft:402' && /Full time · AS Roma 2–1 Lazio/.test(a.title) && /Over 1.5 ✓ won/.test(a.body) && /2 of 3 won|1 of 3 won/.test(a.body)), 'full time: the leg won, the slip\'s tally');
ok(!al1.some((a) => a.ref === 'ft:403') && /“Two legs” is out/.test(g1.body), 'a final whistle six hours ago is not reported late; its slip shows as out');
const ft3 = A.alerts({ now: Date.parse('2026-10-11T15:00:00Z'), lang: 'en', states: A.legStates(w0, evs.slice(2), Date.parse('2026-10-11T15:00:00Z'), {}) }).find((a) => a.ref === 'ft:403');
ok(ft3 && /1 ✗ lost/.test(ft3.body) && /“Two legs” is out/.test(ft3.body), 'full time on time: a leg lost and the slip out');
ok(!al1.some((a) => a.ref.startsWith('hedge:')), 'no hedge while two legs are open');
ok(!al1.some((a) => a.ref.startsWith('land:')), 'nothing landed');
ok(A.alerts({ now: NOW, lang: 'en', states: st1, sent: new Set(al1.map((a) => a.ref)) }).length === 0, 'nothing twice');
ok(A.alerts({ now: NOW, lang: 'en', states: st1, prefs: { on: false } }).length === 0, 'all off');
ok(!A.alerts({ now: NOW, lang: 'en', states: st1, prefs: { goals: false } }).some((a) => a.ref.startsWith('goal:')), 'goals off');
const it1 = A.alerts({ now: NOW, lang: 'it', states: st1 });
ok(it1.some((a) => /^Gol 67' · /.test(a.title) && /in vantaggio/.test(a.body) && /: ora \d+%/.test(a.body) && /“Two legs” è persa/.test(a.body)) && it1.some((a) => /^Finale · /.test(a.title) && /✓ vinto/.test(a.body) && /1 su 3 vinti, 2 da giocare/.test(a.body)), 'in Italian');

/* a red card */
const evRed = JSON.parse(JSON.stringify(evs)); evRed[0].competitions[0].details.push(red('111', "70'", 'Bremer'));
const al2 = A.alerts({ now: NOW, lang: 'en', states: A.legStates(w0, evRed, NOW, {}) });
ok(al2.some((a) => a.ref === 'red:401:1' && /Red card 70'/.test(a.title) && /Juventus down to ten \(Bremer\)/.test(a.body)), 'a red card: who and when');
/* the score state is the ref: a second goal is a new alert, the first one is not repeated */
const evG2 = JSON.parse(JSON.stringify(evs)); evG2[0].competitions[0].competitors[0].score = '2'; evG2[0].competitions[0].details.push(goal('110', "81'")); evG2[0].competitions[0].status.displayClock = "81'";
const al3 = A.alerts({ now: NOW + 14 * 6e4, lang: 'en', states: A.legStates(w0, evG2, NOW + 14 * 6e4, {}), sent: new Set(al1.map((a) => a.ref)) });
ok(al3.length === 1 && al3[0].ref === 'goal:401:2-0', 'the next goal, alone');

/* Inter-Juventus ends 1-1: slip A has its first two legs won (1X, Over 1.5) and one left on Monday → the hedge */
const evFT = JSON.parse(JSON.stringify(evs));
Object.assign(evFT[0].competitions[0].status, { period: 2, displayClock: "90'+5'", type: { name: 'STATUS_FULL_TIME', state: 'post', completed: true, shortDetail: 'FT' } });
evFT[0].competitions[0].competitors[1].score = '1'; evFT[0].competitions[0].details.push(goal('111', "88'"));
const NOW2 = NOW + 60 * 6e4, st4 = A.legStates(w0, evFT, NOW2, {});
const prices = { m3: [[3, 0, 1, 2.05], [3, 0, 2, 3.4], [3, 0, 3, 3.9], [28319, 0, 3, 1.62], [28319, 0, 1, 1.25]] };
const al4 = A.alerts({ now: NOW2, lang: 'en', states: st4, prices });
const hg = al4.find((a) => a.ref === 'hedge:101');
const P = 5 * 12.5, H = P / 1.62;
ok(!!hg && /One leg left · “Serie A Sunday”/.test(hg.title) && /Napoli – Milan: 1 · kick-off Mon 20:45/.test(hg.body), 'one leg left: which, and when (Rome time)');
ok(hg && hg.body.includes('It pays €62.50 if it lands.') && hg.body.includes(`Cover it: €${H.toFixed(2)} on X2 at SNAI's 1.62 → €62.50 whatever happens (€${(P - 5 - H).toFixed(2)} profit locked)`), 'the hedge from SNAI\'s price for the complement (X2)');
ok(al4.some((a) => a.ref === 'ft:401' && /GG ✓ won|Both score ✓ won/.test(a.body)), 'GG won at 1-1');
const al4b = A.alerts({ now: NOW2, lang: 'en', states: st4 });
ok(al4b.find((a) => a.ref === 'hedge:101').body.includes('type SNAI\'s live price'), 'without a price: open Scudi for the live price');
const memo = A.memoOf(st4, {}, NOW2);
ok(Object.keys(memo).sort().join(',') === '101:0,101:1,102:0,102:1' && memo['101:0'].h === 1 && memo['101:0'].a === 1, 'the final scores remembered');
ok(A.boards(w0, NOW2, memo).length === 0, 'and not read again');
ok(Object.keys(A.memoOf(st4, { 'x:1': { at: NOW2 - 11 * 864e5 } }, NOW2)).length === 4, 'old memo entries dropped');

/* Monday: Napoli-Milan 2-0 → slip A landed */
const NOW3 = Date.parse('2026-10-12T20:40:00Z');
const evMon = [ev('404', ['114', 'Napoli'], ['103', 'AC Milan'], '2026-10-12T18:45Z', { state: 'post', completed: true, period: 2, clock: "90'+3'", name: 'STATUS_FULL_TIME', h: 2, a: 0, details: [goal('114', "30'"), goal('114', "60'")] })];
const wM = A.watched(placed, NOW3);
ok(wM.length === 1 && wM[0].id === 101, 'Monday: slip A still on, slip B over');
const st5 = A.legStates(wM, evMon, NOW3, memo);
const al5 = A.alerts({ now: NOW3, lang: 'en', states: st5, sent: new Set(['hedge:101']) });
ok(al5.some((a) => a.ref === 'land:101' && /It landed! “Serie A Sunday”/.test(a.title) && /pays €62.50/.test(a.body)), 'landed, with the payout');
ok(al5.some((a) => a.ref === 'ft:404' && /“Serie A Sunday” pays €62.50/.test(a.body)), 'the final whistle says it too');
ok(!al5.some((a) => a.ref.startsWith('goal:')), 'no goal alerts after the match');

/* line-ups: 70 minutes before kick-off, ESPN's match page, the last XI from the team data */
const NOW6 = Date.parse('2026-10-12T17:50:00Z'), evPre = [ev('404', ['114', 'Napoli'], ['103', 'AC Milan'], '2026-10-12T18:45Z')];
const st6 = A.legStates(wM, evPre, NOW6, memo);
const want = A.lineupsWanted(st6, NOW6, new Set(), A.DEFAULTS);
ok(want.length === 1 && want[0].id === '404' && want[0].slug === 'ita.1', 'line-ups looked for 55 minutes before');
ok(A.lineupsWanted(st6, NOW6, new Set(['lu:404']), A.DEFAULTS).length === 0 && A.lineupsWanted(st6, NOW6, new Set(), { lineups: false }).length === 0, 'not once reported, not when off');
ok(A.lineupsWanted(st6, NOW6 - 30 * 6e4, new Set(), A.DEFAULTS).length === 0, 'not 85 minutes before');
const starters = (ids, names) => ids.map((id, i) => ({ starter: true, athlete: { id: String(id), displayName: names[i], lastName: names[i].split(' ').slice(1).join(' ') } }));
const nap = starters([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], ['Alex Meret', 'Giovanni Di Lorenzo', 'Amir Rrahmani', 'Alessandro Buongiorno', 'Mathías Olivera', 'Frank Anguissa', 'Stanislav Lobotka', 'Scott McTominay', 'Matteo Politano', 'Romelu Lukaku', 'David Neres']);
const mil = starters([21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31], ['Mike Maignan', 'Kyle Walker', 'Fikayo Tomori', 'Strahinja Pavlovic', 'Theo Hernandez', 'Youssouf Fofana', 'Tijjani Reijnders', 'Christian Pulisic', 'Rafael Leao', 'Alvaro Morata', 'Ruben Loftus-Cheek']);
const summary = { rosters: [{ homeAway: 'home', team: { id: '114', displayName: 'Napoli' }, roster: nap.concat([{ starter: false, athlete: { id: '12', displayName: 'Khvicha Kvaratskhelia' } }]) }, { homeAway: 'away', team: { id: '103', displayName: 'AC Milan' }, roster: mil }] };
const teams = { '114': { last: { xi: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12].map((id) => ({ id })) }, players: [{ id: 12, short: 'K. Kvaratskhelia' }, { id: 11, short: 'D. Neres' }] } };
const al6 = A.alerts({ now: NOW6, lang: 'en', states: st6, summaries: { [want[0].eid]: summary }, teams, sent: new Set(['hedge:101']) });
const lu = al6.find((a) => a.ref === 'lu:404');
ok(!!lu && /^Line-ups · Napoli – Milan \(20:45\)$/.test(lu.title), 'line-ups: the match and its kick-off');
ok(lu && /Not starting from the last XI: K\. Kvaratskhelia\./.test(lu.body) && /Napoli: Meret, Di Lorenzo/.test(lu.body) && /AC Milan: Maignan, Walker/.test(lu.body), 'who is out of the last XI, and both elevens');
ok(!A.alerts({ now: NOW6, lang: 'en', states: st6, summaries: { [want[0].eid]: { rosters: [] } } }).some((a) => a.ref.startsWith('lu:')), 'no line-ups yet: nothing');

/* the helpers */
ok(['1:X2', 'X:12', '2:1X', '1X:2', 'X2:1', '12:X', 'GG:NG', 'NG:GG', 'O25:U25', 'U35:O35', 'O15:U15', 'HO05:HU05', 'AU15:AO15', '1T1:1TX2', '1TO05:1TU05', '1TGG:1TNG'].every((x) => A.complement(x.split(':')[0]) === x.split(':')[1]), 'complements');
ok(['MG1-3', '1+O25', 'XH-1', 'HMG1-2'].every((c) => A.complement(c) === null), 'no single market covers these');
const mk = [[3, 0, 1, 2.1], [3, 0, 2, 3.3], [3, 0, 3, 3.6], [28319, 0, 1, 1.3], [28319, 0, 2, 1.35], [28319, 0, 3, 1.7], [7989, 250, 1, 1.9], [7989, 250, 2, 1.85], [7989, 150, 1, 3.2], [18, 0, 1, 1.75], [18, 0, 2, null]];
ok(A.snaiPrice('1', mk) === 2.1 && A.snaiPrice('X', mk) === 3.3 && A.snaiPrice('X2', mk) === 1.7 && A.snaiPrice('12', mk) === 1.35 && A.snaiPrice('U25', mk) === 1.9 && A.snaiPrice('O25', mk) === 1.85 && A.snaiPrice('U15', mk) === 3.2 && A.snaiPrice('GG', mk) === 1.75, 'SNAI\'s codes read');
ok(A.snaiPrice('NG', mk) === null && A.snaiPrice('O35', mk) === null && A.snaiPrice('MG1-3', mk) === null, 'padlocked or missing: no price');
const h = A.hedge(100, 10, 2.5);
ok(Math.abs(h.H - 40) < 1e-9 && Math.abs(h.locked - 50) < 1e-9 && Math.abs(h.B - 10 / 1.5) < 1e-9 && Math.abs(h.ifWins - (90 - 10 / 1.5)) < 1e-9, 'hedge: full cover H = P/q, locked P − S − H; break-even S/(q − 1)');
ok(A.hedge(100, 10, 1) === null && A.hedge(0, 10, 2) === null, 'no hedge without a price above 1');
ok(A.pickName('O25') === 'Over 2.5' && A.pickName('1TU15', 'it') === 'Under 1.5 1° tempo' && A.pickName('HO05') === 'Home over 0.5' && A.pickName('MG2-4') === 'Multigol 2-4', 'pick names');
ok(A.euro(62.5) === '€62.50' && A.euro(62.5, 'it') === '62,50 €', 'euros');
ok(Scudi.settles('O15', 2, 1) === true && Scudi.settles('1', 0, 1) === false, 'the page\'s settling, from site.mjs');

console.log(`${checks - failures}/${checks} notify checks passed`);
if (failures) process.exit(1);
