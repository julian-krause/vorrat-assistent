// Führt einen Code-Knoten aus einem Workflow aus: JSON auf stdin {datei, knoten, nodes, input, jetzt} -> JSON der Ausgabe-Items.
// Für den Prüfstand rewe-service/tests/test_ebon_pdfs.py (gleiche Knoten-Codes wie in n8n, n8n-artige Stubs).
const { code, laufen } = require('./harness.cjs');
let daten = '';
process.stdin.on('data', d => { daten += d; });
process.stdin.on('end', async () => {
  try {
    const a = JSON.parse(daten);
    const out = await laufen(code(a.datei, a.knoten), a.nodes || {}, a.input || [], a.jetzt);
    process.stdout.write(JSON.stringify(Array.isArray(out) ? out : [out]));
  } catch (e) {
    process.stderr.write(String(e && e.stack || e));
    process.exit(1);
  }
});
