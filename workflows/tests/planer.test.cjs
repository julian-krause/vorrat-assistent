const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const { code, laufen } = require('./harness.cjs');
const vg = JSON.parse(fs.readFileSync(__dirname + '/vorgaben_restlicher_tag.json', 'utf8'));

const profil = { chat_id: '42', kcal: 2400, protein_g: 180, fett_g: 70, kh_g: 270, mahlzeiten_pro_tag: 3, vorlieben: '' };
const norm = { modus: 'wochenplan', hinweis: '', tage: 1, start: '2026-09-30', anzahl: 3, ziel_kcal: 0, ziel_protein: 0, mahlzeit: '',
  kcal_ziel: 2800, mahlzeiten: '2', restlicher_tag: true, ausschluesse: 'Avocado, Walnüsse', bereits_vorgeschlagen: '' };
const einheiten = [{ id: 4, name: 'Gramm' }, { id: 5, name: 'Stück' }, { id: 6, name: 'Milliliter' }];
const bestand = [
  { product_id: 1, amount: 2, best_before_date: '2026-10-01', product: { name: 'Avocado', qu_id_stock: 5 } },
  { product_id: 2, amount: 500, best_before_date: '2026-10-05', product: { name: 'Haferflocken', qu_id_stock: 4 } }];
const nw = [{ grocy_product_id: 1, name: 'Avocado', kcal_100: 160, protein_100: 2, fett_100: 15, kh_100: 2, gramm_pro_stk: 150, naehrwert_rang: 2 },
  { grocy_product_id: 2, name: 'Haferflocken', kcal_100: 370, protein_100: 13, fett_100: 7, kh_100: 59, naehrwert_rang: 2 }];

async function kontext() {
  const nodes = { 'Eingabe normalisieren': [norm], 'Profil laden': [profil], 'Grocy-Einheiten laden': einheiten, 'Nährwerte laden': nw,
    'Grocy-Bestand laden': bestand, 'Vorgaben berechnen': [vg], 'Heutige Vorschläge laden': [{ titel: 'Skyr-Bowl' }] };
  const erg = await laufen(code('02-planer.json', 'Kontext bauen'), nodes);
  return { nodes, ctx: erg[0].json };
}

test('Kontext: Ziele, Mahlzeiten und Ausschlüsse kommen aus den Vorgaben; Ausgeschlossenes wird nicht priorisiert', async () => {
  const { ctx } = await kontext();
  assert.deepStrictEqual(ctx.slots.map(s => s.name), ['Mittag', 'Abend']);
  assert.strictEqual(ctx.ziel.kcal, 1900);                       // 2800 − 900 schon gegessen
  assert.deepStrictEqual(ctx.vorrat.map(v => v.name), ['Haferflocken']);   // Avocado (läuft bald ab) ist ausgeschlossen
  assert.match(ctx.prompt, /AUSSCHLÜSSE[^\n]*avocado/);
  assert.match(ctx.prompt, /BEREITS VORGESCHLAGEN[^\n]*Skyr-Bowl/);
  assert.match(ctx.prompt, /REST VON HEUTE/);
  assert.ok(!/"name":"Avocado"/.test(ctx.prompt));
});

function ki(rezepte) { return { choices: [{ finish_reason: 'stop', message: { content: JSON.stringify({ hinweis: 'x', rezepte }) } }] }; }
const z = (name, menge, einheit, pro, extra = {}) => ({ product_id: null, name, menge, einheit, pro_100g: pro, ...extra });
const REZEPTE = [
  { titel: 'Hähnchen-Reis', tag: '2026-09-30', mahlzeit: 'Mittag', dauer_min: 25, anleitung: ['a', 'b'], zutaten: [
    z('Hähnchenbrust', 200, 'g', { kcal: 110, p: 23, f: 1.5, kh: 0 }), z('Reis', 100, 'g', { kcal: 350, p: 7, f: 1, kh: 77 }), z('Olivenöl', 15, 'ml', { kcal: 884, p: 0, f: 100, kh: 0 }, { basis: true })] },
  { titel: 'Lachs mit Kartoffeln', tag: '2026-09-30', mahlzeit: 'Abend', dauer_min: 30, anleitung: ['a'], zutaten: [
    z('Lachs', 200, 'g', { kcal: 200, p: 20, f: 13, kh: 0 }), z('Kartoffeln', 400, 'g', { kcal: 77, p: 2, f: 0.1, kh: 17 }), z('Rapsöl', 10, 'ml', { kcal: 884, p: 0, f: 100, kh: 0 })] },
];

async function auswerten(rezepte, wahl = {}) {
  const { nodes, ctx } = await kontext();
  const kand = { 'Nüsse gehackt': [{ rewe_product_id: '9001', name: 'Walnusskerne 200g', preis_aktuell: 3, kcal_100: 690, protein_100: 15, fett_100: 65, kh_100: 7, size_value: 200, size_unit: 'g' }] };
  const n2 = { ...nodes, 'Kontext bauen': [ctx], 'KI-Antwort bereit': [ki(rezepte)], 'REWE-Kandidaten': [{ kandidaten: kand }],
    'MiniMax wählt Produkte': [{ choices: [{ message: { content: JSON.stringify({ wahl }) } }] }] };
  return { ctx, out: (await laufen(code('02-planer.json', 'Antwort auswerten'), n2)).map(i => i.json) };
}

test('Plan: Summe innerhalb ±5 % von Tagesziel minus Gegessenes, 2 Mahlzeiten', async () => {
  const { ctx, out } = await auswerten(REZEPTE);
  assert.strictEqual(out.length, 2);
  const summe = out.reduce((a, o) => a + o.kcal, 0);
  assert.ok(Math.abs(summe - ctx.ziel.kcal) / ctx.ziel.kcal <= 0.05, `Summe ${summe} vs ${ctx.ziel.kcal}`);
  assert.ok(out.every(o => o.status === 'vorgeschlagen'));
});

test('Ziel bleibt im Rahmen auch bei sehr kleinen Ausgangsmengen', async () => {
  const klein = REZEPTE.map(r => ({ ...r, zutaten: r.zutaten.map(x => ({ ...x, menge: x.menge / 5 })) }));
  const { ctx, out } = await auswerten(klein);
  const summe = out.reduce((a, o) => a + o.kcal, 0);
  assert.ok(Math.abs(summe - ctx.ziel.kcal) / ctx.ziel.kcal <= 0.05, `Summe ${summe}`);
});

test('Ausschluss: Avocado und Walnüsse (auch über das gewählte REWE-Produkt) tauchen nicht auf', async () => {
  const mit = [
    { titel: 'Avocado-Bowl', tag: '2026-09-30', mahlzeit: 'Abend', anleitung: ['a'], zutaten: [z('Avocado', 1, 'stk', { kcal: 160, p: 2, f: 15, kh: 2 }, { gramm: 150 })] },
    { titel: 'Nuss-Porridge', tag: '2026-09-30', mahlzeit: 'Mittag', anleitung: ['a'], zutaten: [z('Nüsse gehackt', 50, 'g', { kcal: 600, p: 15, f: 55, kh: 10 })] },
    ...REZEPTE];
  const { out } = await auswerten(mit, { 'Nüsse gehackt': '9001' });
  const alles = out.map(o => o.titel + o.zutaten_json + o.nachricht).join(' ').toLowerCase();
  assert.ok(!/avocado|walnuss|walnüss/.test(alles), alles.slice(0, 300));
  assert.ok(/wegen deiner ausschlüsse/i.test(out[0].uebersicht), out[0].uebersicht);
});

test('Ausschlussprüfung der KI-Antwort verlangt Ersatz und sammelt ihn ein', async () => {
  const { nodes, ctx } = await kontext();
  const schlecht = { titel: 'Avocado-Bowl', tag: '2026-09-30', mahlzeit: 'Abend', zutaten: [z('Avocado', 1, 'stk', null)] };
  const nodes2 = { ...nodes, 'Kontext bauen': [ctx], 'MiniMax plant Rezepte': [ki([REZEPTE[0], schlecht])] };
  const pr = (await laufen(code('02-planer.json', 'Ausschlüsse prüfen'), nodes2))[0].json;
  assert.strictEqual(pr.ok, false);
  assert.deepStrictEqual(pr.schlecht.map(s => s.mahlzeit), ['Abend']);
  assert.match(pr.prompt, /NUR Ersatz für genau diese Mahlzeiten/);
  const nodes3 = { ...nodes2, 'Ausschlüsse prüfen': [pr] };
  const ersatzKi = ki([REZEPTE[1], { ...schlecht, titel: 'Immer noch Avocado' }]);
  const fertig = (await laufen(code('02-planer.json', 'KI-Antwort bereit'), nodes3, [ersatzKi]))[0].json;
  const rez = JSON.parse(fertig.choices[0].message.content).rezepte;
  assert.deepStrictEqual(rez.map(r => r.titel), ['Hähnchen-Reis', 'Lachs mit Kartoffeln']);
  // ohne Verstoß: unverändert durchreichen
  const ok = (await laufen(code('02-planer.json', 'Ausschlüsse prüfen'), { ...nodes2, 'MiniMax plant Rezepte': [ki(REZEPTE)] }))[0].json;
  assert.strictEqual(ok.ok, true);
});

test('Dubletten: schon vorgeschlagenes Rezept wird im Rezept-Modus verworfen', async () => {
  const { nodes, ctx } = await kontext();
  const c2 = { ...ctx, modus: 'rezepte', anzahl_rezepte: 3, rezept_ziel: null };
  const n2 = { ...nodes, 'Kontext bauen': [c2], 'KI-Antwort bereit': [ki([{ ...REZEPTE[0], titel: 'Skyr-Bowl' }, REZEPTE[1]])],
    'REWE-Kandidaten': [{ kandidaten: {} }], 'MiniMax wählt Produkte': [{ choices: [{ message: { content: '{"wahl":{}}' } }] }] };
  const out = (await laufen(code('02-planer.json', 'Antwort auswerten'), n2)).map(i => i.json);
  assert.deepStrictEqual(out.map(o => o.titel), ['Lachs mit Kartoffeln']);
});
