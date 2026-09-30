// Führt Code-Knoten aus den n8n-Workflow-JSONs mit n8n-artigen Stubs aus ($, $input, DateTime).
// luxon: lokal per `npm i luxon` oder LUXON_PATH (z.B. /usr/local/lib/node_modules/n8n/node_modules/luxon im n8n-Container).
const fs = require('fs');
const path = require('path');
let luxon;
try { luxon = require(process.env.LUXON_PATH || 'luxon'); } catch (e) { throw new Error('luxon nicht gefunden (LUXON_PATH setzen): ' + e.message); }
const { DateTime, Settings } = luxon;

function workflow(datei) {
  return JSON.parse(fs.readFileSync(path.join(__dirname, '..', datei), 'utf8'))[0];
}
function code(datei, knoten) {
  const n = workflow(datei).nodes.find(x => x.name === knoten);
  if (!n) throw new Error('Knoten fehlt: ' + knoten);
  return n.parameters.jsCode;
}
// nodes: { Knotenname: [json, ...] }; input: Items des Vorgängerknotens
async function laufen(js, nodes, input = [], jetzt = '2026-09-30T13:00:00+02:00') {
  const ms = new Date(jetzt).getTime();
  Settings.now = () => ms;
  Settings.defaultZone = 'Europe/Berlin';
  const items = n => (nodes[n] || []).map(x => (x && x.__item) ? { json: x.json, binary: x.binary } : { json: x });
  const dollar = name => {
    if (!(name in nodes)) throw new Error('Knoten nicht ausgeführt: ' + name);
    const l = items(name);
    return { first: () => l[0], all: () => l, item: l[0], itemMatching: i => l[i] };
  };
  // Eingabe-Elemente: reines JSON oder { __item: true, json, binary } (z.B. Mail mit PDF-Anhang)
  const inp = input.map(x => (x && x.__item) ? { json: x.json, binary: x.binary } : { json: x });
  const $input = { all: () => inp, first: () => inp[0], item: inp[0] };
  const f = new Function('$', '$input', '$json', 'DateTime', '$now', 'return (async () => {' + js + '\n})();');
  return await f(dollar, $input, inp[0] && inp[0].json, DateTime, DateTime.now());
}
module.exports = { code, laufen, workflow, DateTime };
