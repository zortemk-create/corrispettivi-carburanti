'use strict';

const $ = (sel) => document.querySelector(sel);
const eur = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' });
const zahl = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 });
const WT = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];

const state = { monat: null, daten: null, tagEdit: null };

// ---------- Hilfsfunktionen ----------

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (_) { return null; }
}

function toast(text) {
  const t = $('#toast');
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove('show'), 3500);
}

function benutzer() {
  const name = $('#benutzer').value.trim();
  if (!name) {
    $('#benutzer').focus();
    throw new Error('Bitte oben rechts deinen Namen eintragen.');
  }
  return name;
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.error || `Fehler ${res.status}`);
    err.details = data.details || [];
    throw err;
  }
  return data;
}

function zeigeFehler(err) {
  const details = (err.details || []).length ? '<ul>' + err.details.map((d) => `<li>${esc(d)}</li>`).join('') + '</ul>' : '';
  $('#hinweise').insertAdjacentHTML('afterbegin', `<div class="hinweis bad">${esc(err.message)}${details}</div>`);
  toast(err.message);
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

const num = (s) => (s == null ? null : Number(s));
const fmtEur = (s) => (s == null ? '–' : eur.format(num(s)));
const fmtZeit = (iso) => (iso ? new Date(iso).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }) : '');

function monatVerschieben(delta) {
  const [y, m] = state.monat.split('-').map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  setMonat(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
}

function setMonat(m) {
  state.monat = m;
  $('#monat').value = m;
  laden();
}

// ---------- Rendern ----------

async function laden() {
  $('#hinweise').innerHTML = '';
  try {
    state.daten = await api('GET', `/api/monat/${state.monat}`);
  } catch (err) {
    zeigeFehler(err);
    return;
  }
  render();
  ladeProtokoll();
}

function render() {
  const d = state.daten;
  const gesperrt = d.status === 'uebermittelt';
  const status = $('#status');
  status.className = `badge ${d.status}`;
  status.textContent = gesperrt ? 'Übermittelt · gesperrt' : 'Offen';
  $('#frist').textContent = `Frist (IVA mensile): ${new Date(d.frist + 'T00:00:00').toLocaleDateString('de-DE')}`;

  const hinweise = [];
  if (d.einstellungen_fehler.length) {
    hinweise.push(`<div class="hinweis bad">Stammdaten fehlen – bitte <a href="#" id="link-einst">Einstellungen</a> ausfüllen:<ul>${d.einstellungen_fehler.map((f) => `<li>${esc(f)}</li>`).join('')}</ul></div>`);
  }
  const heute = new Date().toISOString().slice(0, 10);
  const fehlend = d.tage.filter((t) => !t.melden && t.datum <= heute);
  const geaendert = d.tage.filter((t) => t.abweichung);
  if (geaendert.length) {
    hinweise.push(`<div class="hinweis bad">${geaendert.length} Tag(e) weichen von der letzten Übermittlung ab. Im ADM-Portal unter
      <em>Annullamento corrispettivi</em> je Tag die angegebene IUT, Häkchen <em>Corrispettivi</em> und die Data di riferimento eintragen,
      dann diese Tage neu senden und die neue IUT hier bestätigen:
      <ul>${geaendert.map((t) => `<li>${new Date(t.datum + 'T00:00:00').toLocaleDateString('de-DE')} – IUT ${esc(t.gemeldet?.iut || '?')}</li>`).join('')}</ul></div>`);
  }
  $('#hinweise').innerHTML = hinweise.join('');
  const link = $('#link-einst');
  if (link) link.onclick = (e) => { e.preventDefault(); oeffneEinstellungen(); };

  $('#k-brutto').textContent = fmtEur(d.summe.brutto);
  $('#k-imponibile').textContent = fmtEur(d.summe.imponibile);
  $('#k-imposta').textContent = fmtEur(d.summe.imposta);
  $('#k-fehlend').textContent = fehlend.length;

  const rows = d.tage.map((t) => {
    const datum = new Date(t.datum + 'T00:00:00');
    const wt = datum.getDay();
    const cls = [wt === 0 || wt === 6 ? 'wochenende' : '', t.korrektur ? 'korrigiert' : '',
      !t.melden ? 'ausgelassen' : '', t.abweichung ? 'abweichung' : ''].join(' ');
    let quelle = '<span class="tag">Tagesabrechnung</span>';
    if (t.korrektur) quelle = `<span class="tag manuell" title="${esc(t.korrektur.notiz)} – ${esc(t.korrektur.von)}, ${fmtZeit(t.korrektur.am)}">manuell · ${esc(t.korrektur.von)}</span>`;
    else if (!t.melden) quelle = '<span class="tag">kein Eintrag · wird nicht gemeldet</span>';
    if (t.abweichung) quelle += ` <span class="tag abweichung" title="Gemeldet: ${esc(t.gemeldet ? t.gemeldet.imponibile + ' / ' + t.gemeldet.imposta : '–')}">geändert seit Meldung</span>`;
    return `<tr class="${cls}">
      <td>${WT[wt]} ${datum.toLocaleDateString('de-DE')}</td>
      <td class="num">${t.liter == null ? '–' : zahl.format(num(t.liter))}</td>
      <td class="num">${fmtEur(t.brutto_quelle)}</td>
      <td class="num"><strong>${fmtEur(t.brutto)}</strong></td>
      ${t.melden ? `<td class="num kopie" data-kopie="${t.imponibile}" title="Klicken zum Kopieren">${fmtEur(t.imponibile)}</td>
      <td class="num kopie" data-kopie="${t.imposta}" title="Klicken zum Kopieren">${fmtEur(t.imposta)}</td>` : '<td class="num">–</td><td class="num">–</td>'}
      <td>${quelle}</td>
      <td>${gesperrt ? '' : `<button data-tag="${t.datum}">Ändern</button>`}</td>
    </tr>`;
  });
  $('#tabelle tbody').innerHTML = rows.join('');
  $('#tabelle tbody').onclick = (e) => {
    const b = e.target.closest('button[data-tag]');
    if (b) return oeffneTag(b.dataset.tag);
    const k = e.target.closest('td[data-kopie]');
    if (k) kopiere(k.dataset.kopie);
  };

  $('#btn-xml').disabled = gesperrt;
  $('#btn-bestaetigen').disabled = gesperrt;
  $('#btn-entsperren').classList.toggle('hidden', !gesperrt);

  $('#dateien').innerHTML = d.dateien.length ? d.dateien.map((f) => `
    <div class="datei">
      <div>
        <strong>${esc(f.dateiname)}</strong>
        <div class="meta">Erstellt ${fmtZeit(f.erstellt_am)} von ${esc(f.erstellt_von)} · Lordo ${fmtEur(f.summe_brutto)} · Imponibile ${fmtEur(f.summe_imponibile)} · IVA ${fmtEur(f.summe_imposta)}</div>
        ${f.hochgeladen_am
          ? `<div class="meta" style="color:var(--ok)">✓ Übermittelt · IUT <strong>${esc(f.ricevuta)}</strong> · bestätigt ${fmtZeit(f.hochgeladen_am)} von ${esc(f.hochgeladen_von)}</div>`
          : '<div class="meta">Nur Archiv-Datei, nicht als übermittelt bestätigt</div>'}
      </div>
      <div class="btns">
        <a href="/api/datei/${f.id}"><button type="button">Download XML</button></a>
      </div>
    </div>`).join('') : '<p class="muted">Noch keine Datei für diesen Monat erstellt.</p>';
}

const AKTIONEN = {
  korrektur: 'Tag korrigiert', korrektur_entfernt: 'Korrektur entfernt', xml_erstellt: 'XML erstellt',
  upload_bestaetigt: 'Übermittlung bestätigt', korrektur_geoeffnet: 'Korrektur geöffnet', einstellungen: 'Einstellungen',
};

async function ladeProtokoll() {
  try {
    const eintraege = await api('GET', `/api/protokoll?monat=${state.monat}`);
    $('#protokoll').innerHTML = eintraege.length
      ? '<div class="log">' + eintraege.map((p) => `<div><span>${fmtZeit(p.zeit)}</span><strong>${esc(p.benutzer)}</strong><span>${esc(AKTIONEN[p.aktion] || p.aktion)} ${esc(beschreibe(p))}</span></div>`).join('') + '</div>'
      : '<p class="muted">Keine Einträge.</p>';
  } catch (err) { zeigeFehler(err); }
}

function beschreibe(p) {
  const d = p.details || {};
  if (p.aktion === 'korrektur') return `${d.tag}: ${d.alt ?? 'Tagesabrechnung'} → ${d.neu}${d.notiz ? ' (' + d.notiz + ')' : ''}`;
  if (p.aktion === 'korrektur_entfernt') return `${d.tag}`;
  if (p.aktion === 'xml_erstellt') return `${d.datei}`;
  if (p.aktion === 'upload_bestaetigt') return `IUT ${d.ricevuta} · Imponibile ${d.imponibile} · Imposta ${d.imposta}`;
  if (p.aktion === 'korrektur_geoeffnet') return `– ${d.grund}`;
  return '';
}

// ---------- Dialoge ----------

function oeffneTag(datum) {
  const t = state.daten.tage.find((x) => x.datum === datum);
  state.tagEdit = t;
  $('#tag-titel').textContent = `Tag ${new Date(datum + 'T00:00:00').toLocaleDateString('de-DE')} korrigieren`;
  $('#tag-quelle').textContent = t.brutto_quelle == null
    ? 'Kein Eintrag in der Tagesabrechnung.'
    : `Tagesabrechnung: ${fmtEur(t.brutto_quelle)} (${zahl.format(num(t.liter))} Liter)`;
  $('#tag-brutto').value = t.brutto == null ? '' : num(t.brutto).toFixed(2).replace('.', ',');
  $('#tag-notiz').value = t.korrektur?.notiz || '';
  $('#tag-reset').classList.toggle('hidden', !t.korrektur);
  $('#dlg-tag').showModal();
}

async function speichereTag(e) {
  e.preventDefault();
  try {
    await api('PUT', `/api/tag/${state.tagEdit.datum}`, {
      benutzer: benutzer(), brutto: $('#tag-brutto').value, notiz: $('#tag-notiz').value,
    });
    $('#dlg-tag').close();
    toast('Gespeichert.');
    laden();
  } catch (err) { toast(err.message); }
}

async function resetTag() {
  try {
    await api('DELETE', `/api/tag/${state.tagEdit.datum}`, { benutzer: benutzer() });
    $('#dlg-tag').close();
    toast('Wert aus der Tagesabrechnung wiederhergestellt.');
    laden();
  } catch (err) { toast(err.message); }
}

async function oeffneEinstellungen() {
  try {
    const e = await api('GET', '/api/einstellungen');
    $('#e-piva-gestore').value = e.piva_gestore;
    $('#e-codice-ditta').value = e.codice_ditta;
    $('#e-piva-marchio').value = e.piva_marchio;
    $('#e-iva').value = e.iva_satz;
    $('#dlg-einst').showModal();
  } catch (err) { zeigeFehler(err); }
}

async function speichereEinstellungen(e) {
  e.preventDefault();
  try {
    await api('PUT', '/api/einstellungen', {
      benutzer: benutzer(),
      piva_gestore: $('#e-piva-gestore').value,
      codice_ditta: $('#e-codice-ditta').value,
      piva_marchio: $('#e-piva-marchio').value,
      iva_satz: $('#e-iva').value,
    });
    $('#dlg-einst').close();
    toast('Einstellungen gespeichert.');
    laden();
  } catch (err) { toast([err.message, ...(err.details || [])].join(' ')); }
}

function oeffneUpload() {
  $('#up-iut').value = '';
  $('#dlg-upload').showModal();
}

async function kopiere(wert) {
  const text = $('#dezimal').value === ',' ? wert.replace('.', ',') : wert;
  try {
    await navigator.clipboard.writeText(text);
    toast(`Kopiert: ${text}`);
  } catch (_) {
    toast(`Kopieren nicht möglich – Wert: ${text}`);
  }
}

async function bestaetigeUpload(e) {
  e.preventDefault();
  try {
    await api('POST', `/api/monat/${state.monat}/bestaetigen`, { benutzer: benutzer(), iut: $('#up-iut').value });
    $('#dlg-upload').close();
    toast('Übermittlung bestätigt – Monat gesperrt.');
    laden();
  } catch (err) { toast(err.message); }
}

async function erstelleXml() {
  try {
    const r = await api('POST', `/api/monat/${state.monat}/xml`, { benutzer: benutzer() });
    toast(`${r.dateiname} erstellt und gegen das ADM-Schema geprüft (Archiv).`);
    laden();
  } catch (err) { zeigeFehler(err); }
}

async function entsperren() {
  try {
    const name = benutzer();
    const grund = prompt('Grund für die Korrektur des bereits übermittelten Monats:');
    if (!grund) return;
    await api('POST', `/api/monat/${state.monat}/entsperren`, { benutzer: name, grund });
    toast('Monat zur Korrektur geöffnet.');
    laden();
  } catch (err) { toast(err.message); }
}

// ---------- Start ----------

$('#benutzer').value = store('benutzer') || '';
$('#benutzer').addEventListener('change', (e) => store('benutzer', e.target.value.trim()));
$('#prev').onclick = () => monatVerschieben(-1);
$('#next').onclick = () => monatVerschieben(1);
$('#monat').onchange = (e) => e.target.value && setMonat(e.target.value);
$('#btn-einstellungen').onclick = oeffneEinstellungen;
$('#btn-xml').onclick = erstelleXml;
$('#btn-entsperren').onclick = entsperren;
$('#btn-bestaetigen').onclick = () => { try { benutzer(); oeffneUpload(); } catch (err) { toast(err.message); } };
$('#btn-drucken').onclick = () => window.print();
$('#dezimal').value = store('dezimal') || ',';
$('#dezimal').onchange = (e) => store('dezimal', e.target.value);
$('#tag-save').onclick = speichereTag;
$('#tag-reset').onclick = resetTag;
$('#e-save').onclick = speichereEinstellungen;
$('#up-save').onclick = bestaetigeUpload;

// Standard: Vormonat (der Monat, der als Nächstes zu melden ist)
const jetzt = new Date();
const vm = new Date(jetzt.getFullYear(), jetzt.getMonth() - 1, 1);
setMonat(`${vm.getFullYear()}-${String(vm.getMonth() + 1).padStart(2, '0')}`);
