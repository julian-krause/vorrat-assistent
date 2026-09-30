const test = require('node:test');
const assert = require('node:assert');
const { code, laufen, workflow } = require('./harness.cjs');

const u = { aktion: 'chat', param: '', chat_id: '42', text: '500 g Kefir', callback_id: '' };

test('Vor-Router: Antwort auf offene Rückfrage geht nicht an den Agenten', async () => {
  const js = code('03-telegram-bot.json', 'Aktion festlegen');
  const nodes = { 'Update auswerten': [u] };
  // Menge -> Aktion „rueckfrage“
  let out = (await laufen(js, nodes, [{ treffer: true, aktion: 'menge_buchen', menge: 500, payload: {} }]))[0].json;
  assert.strictEqual(out.aktion, 'rueckfrage');
  // Produktwahl per Text -> wie ein Klick auf den Button (bon:<zeile>:<rewe>:<grocy>:<gebucht>), unbuchte Zeile = 0
  out = (await laufen(js, nodes, [{ treffer: true, aktion: 'produkt_waehlen', bon_zeile_id: 9, rewe_product_id: '3002', payload: { product_id: 7, unbucht: true, gebucht: 445 } }]))[0].json;
  assert.deepStrictEqual([out.aktion, out.param], ['bon_antwort', '9:3002:7:0']);
  // kein Treffer / Dienst nicht erreichbar -> unverändert an den Agenten
  for (const antw of [{ treffer: false }, { statusCode: 500 }, undefined]) {
    out = (await laufen(js, nodes, antw ? [antw] : [u]))[0].json;
    assert.strictEqual(out.aktion, 'chat');
  }
});

test('Menge ersetzt die gebuchte Menge statt sie zu addieren', async () => {
  const nodes = { 'Aktion festlegen': [{ chat_id: '42', rueckfrage: { bon_text: 'BIO KEFIR', menge: 500, einheit: 'g', payload: { product_id: 7, gebucht: 445 } } }] };
  // Bestand 700 g, davon 445 g aus diesem Bon -> 255 g Rest + 500 g = 755 g
  const out = (await laufen(code('03-telegram-bot.json', 'Bestand ersetzen vorbereiten'), nodes, [{ stock_amount: 700 }]))[0].json;
  assert.strictEqual(out.neuer_bestand, 755);
  assert.match(out.text, /Menge auf 500 g gesetzt \(statt 445\)/);
});

test('Bon-Antwort: Packungsgröße greift nach der Rückfrage (Nachbuchen bzw. Korrektur), kein direktes kcal-Setzen', async () => {
  const js = code('03-telegram-bot.json', 'Bon-Korrektur vorbereiten');
  const produkt = { rewe_product_id: '3002', name: 'REWE Bio Kefir Natur 500g', brand: 'REWE Bio', price: 1.19, kcal_100: 55, size_value: 500, size_unit: 'g' };
  const base = (extra) => ({ 'Aktion festlegen': [{ chat_id: '42', param: '1:3002:7:445' }], 'Bon-Antwort speichern': [{ ok: true, bon_text: 'BIO KEFIR', produkt, ...extra }] });
  const grocy = { quantity_unit_stock: { name: 'Gramm' }, stock_amount: 700 };
  // bereits mit falscher Menge (445 g aus dem Preis) gebucht -> auf Packungsgröße korrigieren, Rest bleibt
  let out = (await laufen(js, base({ menge_info: { menge: 500, einheit: 'g', quelle: 'packung_bestaetigt', offen: false } }), [grocy]))[0].json;
  assert.strictEqual(out.neue_menge, 755);
  assert.ok(!('kcal_einheit' in out));
  // noch nicht gebucht (param …:0) -> Nachbuchen
  const b0 = base({ menge_info: { menge: 500, einheit: 'g', quelle: 'packung_bestaetigt', offen: false }, nachbuchen: { menge: 500, einheit: 'g', payload: { mhd: '2026-10-07' } } });
  b0['Aktion festlegen'] = [{ chat_id: '42', param: '1:3002:7:0' }];
  out = (await laufen(js, b0, [grocy]))[0].json;
  assert.strictEqual(out.neue_menge, null);
  assert.strictEqual(out.nachbuchen.menge, 500);
  assert.match(out.text, /eingebucht: 500 g/);
  // Packungsgröße unbekannt -> Rückfrage nach der Menge
  out = (await laufen(js, base({ menge_info: { offen: true }, menge_nachfragen: true }), [grocy]))[0].json;
  assert.match(out.text, /Wie viel war es/);
});

test('Kein Werkzeug und kein Knoten setzt das Grocy-kcal-Feld direkt (nur der Abgleich aus vorrat_naehrwerte)', () => {
  for (const [datei, erlaubt] of [['03-telegram-bot.json', ['grocy_produkt_anlegen']], ['01-ebon-import.json', ['Grocy-Produkt anlegen']]]) {
    for (const n of workflow(datei).nodes) {
      const s = JSON.stringify(n.parameters);
      if (/calories/.test(s) && !erlaubt.includes(n.name)) assert.fail(datei + ': ' + n.name + ' setzt calories');
    }
  }
  const anlegen = workflow('03-telegram-bot.json').nodes.find(n => n.name === 'grocy_produkt_anlegen').parameters.jsonBody;
  assert.match(anlegen, /calories: 0/);
  const neu = workflow('01-ebon-import.json').nodes.find(n => n.name === 'Grocy-Produkt anlegen').parameters.jsonBody;
  assert.match(neu, /calories: \$json\.kcal_pro_einheit/);   // 0 beim Anlegen, danach setzt „Nährwerte ermitteln“ den Wert aus der Ansicht
});

test('Agent kennt bestand_korrigieren, buchungen_letzte und plan_erstellen mit den neuen Parametern', () => {
  const w = workflow('03-telegram-bot.json');
  const namen = w.nodes.map(n => n.name);
  for (const t of ['bestand_korrigieren', 'buchungen_letzte']) {
    assert.ok(namen.includes(t)); assert.ok(w.connections[t].ai_tool[0].some(c => c.node === 'Vorrats-Assistent'));
  }
  const plan = w.nodes.find(n => n.name === 'plan_erstellen').parameters.workflowInputs.value;
  for (const k of ['kcal_ziel', 'mahlzeiten', 'restlicher_tag', 'ausschluesse']) assert.ok(k in plan, k);
  const sm = w.nodes.find(n => n.name === 'Vorrats-Assistent').parameters.options.systemMessage;
  assert.match(sm, /bestand_korrigieren/); assert.match(sm, /NIE mehrere rezept_vorschlagen-Aufrufe/); assert.match(sm, /AUSDRÜCKLICH sagt, dass etwas weggeworfen/);
  const inv = w.nodes.find(n => n.name === 'bestand_korrigieren').parameters.url;
  assert.match(inv, /\/inventory$/);
});

test('Verzehr-Sync ignoriert Inventurkorrekturen und Weggeworfenes', async () => {
  const log = (id, typ, extra = {}) => ({ id, product_id: 7, amount: 100, transaction_type: typ, undone: 0, spoiled: 0, row_created_timestamp: '2026-09-30 10:00:00', ...extra });
  const nodes = {
    'Grocy-Produkte laden': [{ id: 7, name: 'Kefir', qu_id_stock: 4, calories: 0.55 }], 'Grocy-Einheiten laden': [{ id: 4, name: 'Gramm' }],
    'Nährwerte laden': [{ grocy_product_id: 7, einheit: 'g', kcal_100: 55, protein_100: 3, fett_100: 2, kh_100: 4, naehrwert_quelle: 'rewe', naehrwert_rang: 2 }],
    'Grocy-Verbrauch laden': [log(1, 'consume'), log(2, 'inventory-correction'), log(3, 'consume', { spoiled: 1 }), log(4, 'consume', { undone: 1 })] };
  const out = (await laufen(code('08-verzehr-erfassen.json', 'Verzehr aufbereiten'), nodes))[0].json;
  assert.deepStrictEqual(out.neu.map(x => x.log_id), [1]);
  assert.deepStrictEqual(out.rueck, [4]);
  const url = workflow('08-verzehr-erfassen.json').nodes.find(n => n.name === 'Grocy-Verbrauch laden').parameters.url;
  assert.match(url, /transaction_type%3Dconsume/);          // Inventur (inventory-correction) wird schon in der Abfrage nicht geladen
});
