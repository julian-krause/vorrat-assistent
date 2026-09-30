const test = require('node:test');
const assert = require('node:assert');
const { code, laufen } = require('./harness.cjs');

// Bon vom 30.09.2026 (nachgebaut, siehe rewe-service/tests/test_bon.py): KI-Artikel, die den Preis als Menge lesen
const ki = (name, bon_text, menge, einheit) => ({ name, bon_text, off_suche: name, frischware: false, kategorie: 'Sonstiges', menge, einheit, packungen: 1,
  menge_geschaetzt: false, gramm_pro_stk: null, lagerort: 'Kühlschrank', haltbarkeit_tage: 7, kaufdatum: '2026-09-30', mhd: '2026-10-07', bon_id: 'b1', bon_summe: 22.45 });
const artikel = [ki('Kefir', 'BIO KEFIR', 149, 'g'), ki('Hähnchenbrust', 'HAEHNCHENBRUST', 445, 'g'), ki('Ingwer', 'INGWER BIO', 17, 'g'), ki('Kichererbsen', 'KICHERERBSEN', 59, 'g'),
  ki('Rheinfels', 'RHEINFELS KLASSI', 59, 'ml')];
const mi = (menge, einheit, quelle) => menge === null ? { menge: null, einheit: null, quelle: null, offen: true } : { menge, einheit, quelle, offen: false };
const prod = { rewe_product_id: '7', name: 'ja! Kichererbsen 265g', brand: 'ja!', ean: '4337', kcal_100: 120, protein_100: 7, fett_100: 2, kh_100: 17, price: 0.79, size_value: 265, size_unit: 'g' };
const antwort = { artikel: [
  { zeile_id: 1, bon_text: 'BIO KEFIR', anzahl: 1, einzelpreis: 1.29, status: 'unsicher', kandidaten: [{ rewe_product_id: '1', name: 'REWE Bio Kefir Natur 500g', price: 1.19, anzeige: 'REWE Bio Kefir Natur 500g · 1,19 € · 500 g' }], menge_info: mi(null), zeile_text: '1,29 €' },
  { zeile_id: 2, bon_text: 'HAEHNCHENBRUST', anzahl: 1, einzelpreis: 4.45, status: 'unsicher', kandidaten: [], menge_info: mi(null), zeile_text: '4,45 €' },
  { zeile_id: 3, bon_text: 'INGWER BIO', anzahl: 1, gewicht_kg: 0.034, kilopreis: 4.90, einzelpreis: null, status: 'unsicher', kandidaten: [{ rewe_product_id: '2', name: 'Ingwer 1kg', anzeige: 'Ingwer 1kg · 4,99 € · 4,99 €/kg · 1 kg' }], menge_info: mi(34, 'g', 'bon_gewicht'), zeile_text: '0,034 kg × 4,90 €/kg = 0,17 €' },
  { zeile_id: 4, bon_text: 'KICHERERBSEN', anzahl: 1, einzelpreis: 0.79, status: 'sicher', produkt: prod, kandidaten: [], menge_info: mi(265, 'g', 'packung_sicher'), zeile_text: '0,79 €' },
  { ignorieren: true, bon_text: 'RHEINFELS KLASSI', grund: 'Wasser' }] };

async function uebernehmen() {
  const nodes = { 'Artikel aufbereiten': artikel, 'REWE-Anfrage bauen': [{ bon_id: 'b1' }] };
  const out = await laufen(code('01-ebon-import.json', 'REWE-Daten übernehmen'), nodes, [antwort]);
  return out.map(i => i.json);
}

test('Menge kommt nur aus Bon oder Packungsgröße – nie aus dem Preis; Wasser wird nicht gebucht', async () => {
  const arts = await uebernehmen();
  const nach = Object.fromEntries(arts.map(a => [a.bon_text, a]));
  assert.ok(!nach['RHEINFELS KLASSI'], 'Rheinfels darf nicht weiterlaufen');
  assert.strictEqual(nach['BIO KEFIR'].menge, null);            // KI sagte 149 g (= Preis 1,49 €)
  assert.strictEqual(nach['HAEHNCHENBRUST'].menge, null);       // KI sagte 445 g bei 4,45 €
  assert.strictEqual(nach['HAEHNCHENBRUST'].menge_offen, true);
  assert.strictEqual(nach['INGWER BIO'].menge, 34);                // gewogen
  assert.strictEqual(nach['KICHERERBSEN'].menge, 265);          // Packungsgröße des sicheren Treffers
  for (const a of arts) {
    const preisZiffern = String(Math.round((a.einzelpreis ?? 0) * 100));
    assert.ok(a.menge === null || String(a.menge) !== preisZiffern, a.bon_text + ' hat eine Menge aus dem Preis');
  }
});

test('Zusammenfassung: gebuchte und „Menge offen“-Artikel getrennt, keine leeren Klammern', async () => {
  const arts = await uebernehmen();
  const mitTag = arts.map(a => ({ ...a, mhd: '2026-10-07', kaufdatum: '2026-09-30', product_id: 5, bon_summe: 22.45 }));
  const out = await laufen(code('01-ebon-import.json', 'Bons zusammenfassen'), { 'Alle Artikel': mitTag });
  const text = out[0].json.text;
  assert.match(text, /Menge offen – noch nicht gebucht/);
  assert.match(text, /HAEHNCHENBRUST/);
  assert.match(text, /Ingwer – 34 g/);
  assert.ok(!/\(\)/.test(text));
});

test('Rückfragen: offene Menge und Produktwahl werden als Zustand gemerkt, Text ohne „()“, Button „Anderes Produkt suchen“', async () => {
  const arts = (await uebernehmen()).map(a => ({ ...a, product_id: 5, mhd: '2026-10-07', kaufdatum: '2026-09-30', location_id: 3, bon_id: 'b1' }));
  const nodes = { 'Alle Artikel': arts, 'Profil laden': [{ chat_id: '42' }] };
  const s = (await laufen(code('01-ebon-import.json', 'Rückfragen sammeln'), nodes)).map(i => i.json.body);
  assert.deepStrictEqual(s.map(x => [x.bon_text, x.art]).sort(), [['BIO KEFIR', 'produkt'], ['HAEHNCHENBRUST', 'menge'], ['INGWER BIO', 'produkt']].sort());
  assert.ok(s.find(x => x.bon_text === 'BIO KEFIR').payload.unbucht);
  assert.strictEqual(s.find(x => x.bon_text === 'INGWER BIO').payload.unbucht, false);
  const q = (await laufen(code('01-ebon-import.json', 'Rückfragen bauen'), nodes)).map(i => i.json);
  const ing = q.find(x => x.text.includes('INGWER BIO'));
  assert.match(ing.text, /0,034 kg × 4,90 €\/kg = 0,17 €/);
  assert.ok(q.every(x => !/\(\)/.test(x.text)));
  assert.match(ing.suche, /^bon:3:s:5:34$/);
  const kefir = q.find(x => x.text.includes('KEFIR'));
  assert.match(kefir.text, /Noch nicht eingebucht/);
  assert.match(kefir.k1_data, /^bon:1:1:5:0$/);
  assert.match(kefir.k1_text, /REWE Bio Kefir Natur 500g/);
});

test('KI-Prompt: Menge nur bei Gewicht/Mengenangabe auf dem Bon', () => {
  const c = code('01-ebon-import.json', 'Bon vorbereiten');
  assert.match(c, /NUR wenn auf dem Bon ein Gewicht/);
  assert.match(c, /PREIS IST NIEMALS EINE MENGE/);
  assert.match(c, /menge null/);
});

test('Artikel aufbereiten: keine erfundene Menge', async () => {
  const bon = { message_id: 'b1', kaufdatum: '2026-09-30' };
  const antw = { choices: [{ message: { content: JSON.stringify({ kaufdatum: '2026-09-30', summe: 22.45, artikel: [
    { name: 'Hähnchenbrust', bon_text: 'HAEHNCHENBRUST', menge: null, einheit: null, packungen: 1, menge_geschaetzt: true, haltbarkeit_tage: 2 },
    { name: 'Ingwer', bon_text: 'INGWER', menge: 34, einheit: 'g', packungen: 1, menge_geschaetzt: false, haltbarkeit_tage: 14 }] }) } }] };
  const out = await laufen(code('01-ebon-import.json', 'Artikel aufbereiten'), { 'Bon vorbereiten': [bon] }, [antw]);
  assert.strictEqual(out[0].json.menge, null);
  assert.strictEqual(out[0].json.menge_geschaetzt, true);
  assert.strictEqual(out[1].json.menge, 34);
});
