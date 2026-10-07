'use strict';

const $ = (sel) => document.querySelector(sel);
const eur = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' });
const zahl = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 });
const WT = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];

const state = { monat: null, daten: null };

const STATUS_TEXT = {
  gemeldet: 'Gemeldet', offen: 'Offen', ueberfaellig: 'Überfällig', laufend: 'Läuft noch',
  korrektur: 'Korrektur offen', nicht_erfasst: 'Nicht erfasst', keine_daten: 'Keine Daten',
};
const QUELLE_TEXT = { enilive: 'Enilive', selbst: 'Dieses Tool' };
const fmtDatum = (iso) => (iso ? new Date(iso + 'T00:00:00').toLocaleDateString('de-DE') : '–');
const monatsname = (m) => new Date(m + '-01T00:00:00').toLocaleDateString('de-DE', { month: 'long', year: 'numeric' });

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
  ladeUebersicht();
}

async function ladeUebersicht() {
  try {
    const u = await api('GET', '/api/uebersicht');
    const rows = u.monate.slice().reverse().map((m) => `
      <tr data-monat="${m.monat}" class="${m.monat === state.monat ? 'aktiv' : ''}">
        <td><strong>${esc(monatsname(m.monat))}</strong></td>
        <td><span class="badge ${m.status}">${STATUS_TEXT[m.status]}</span>${m.abweichungen ? ` <span class="tag abweichung">${m.abweichungen} geändert</span>` : ''}</td>
        <td>${m.quelle ? esc(QUELLE_TEXT[m.quelle]) : '–'}</td>
        <td>${m.iut ? esc(m.iut) : '–'}</td>
        <td>${fmtDatum(m.gemeldet_am)}</td>
        <td>${m.status === 'gemeldet' || m.status === 'nicht_erfasst' || m.status === 'keine_daten' ? '' : fmtDatum(m.frist)}</td>
        <td class="num">${m.tage_mit_daten}/${m.tage_gesamt}</td>
        <td class="num">${m.tage_mit_daten ? fmtEur(m.brutto) : '–'}</td>
      </tr>`);
    $('#ue-tabelle tbody').innerHTML = rows.join('');
    const offen = u.monate.filter((m) => m.status === 'offen' || m.status === 'ueberfaellig' || m.status === 'korrektur');
    $('#ue-summary').textContent = offen.length
      ? `· ${offen.length} Monat(e) zu melden: ${offen.map((m) => monatsname(m.monat)).join(', ')}`
      : '· nichts offen';
  } catch (err) { zeigeFehler(err); }
}

function render() {
  const d = state.daten;
  const gesperrt = d.status === 'uebermittelt';
  const status = $('#status');
  const mg = d.meldung;
  status.className = `badge ${gesperrt ? 'gemeldet' : 'offen'}`;
  status.textContent = gesperrt ? `Gemeldet · ${QUELLE_TEXT[mg?.quelle] || 'gesperrt'}` : (mg ? 'Korrektur offen' : 'Offen');
  $('#frist').textContent = `Frist (IVA mensile): ${new Date(d.frist + 'T00:00:00').toLocaleDateString('de-DE')}`;

  const hinweise = [];
  if (d.einstellungen_fehler.length && !gesperrt) {
    hinweise.push(`<div class="hinweis bad">Stammdaten fehlen – bitte <a href="#" id="link-einst">Einstellungen</a> ausfüllen:<ul>${d.einstellungen_fehler.map((f) => `<li>${esc(f)}</li>`).join('')}</ul></div>`);
  }
  if (gesperrt && mg?.quelle === 'enilive') {
    hinweise.push(`<div class="hinweis ok">Dieser Monat wurde von Enilive am ${fmtDatum(mg.gemeldet_am)} gemeldet (IUT ${esc(mg.iut)}). Nicht erneut senden – die ADM lehnt bereits gemeldete Tage ab.</div>`);
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
    const wert = t.brutto == null ? '' : num(t.brutto).toFixed(2).replace('.', ',');
    const aus = t.brutto_quelle == null ? '' : num(t.brutto_quelle).toFixed(2).replace('.', ',');
    const lordo = gesperrt
      ? `<strong>${t.melden ? fmtEur(t.brutto) : '–'}</strong>`
      : `<input class="lordo" inputmode="decimal" autocomplete="off" placeholder="–" aria-label="Lordo ${t.datum}"
           data-orig="${wert}" data-quelle="${aus}" value="${wert}">`;
    const reset = gesperrt ? '' : `<button type="button" class="reset hidden" data-reset
           title="${aus ? 'Auf Wert der Tagesabrechnung zurücksetzen: ' + aus + ' €' : 'Eingabe entfernen (Tag nicht melden)'}">↺</button>`;
    return `<tr class="${cls}" data-datum="${t.datum}" data-imp="${t.imponibile ?? ''}" data-iva="${t.imposta ?? ''}">
      <td>${WT[wt]} ${datum.toLocaleDateString('de-DE')}</td>
      <td class="num">${lordo}</td>
      <td class="num imp"></td><td class="num iva"></td>
      <td class="quelle">${quelle}</td>
      <td>${reset}</td>
    </tr>`;
  });
  $('#tabelle tbody').innerHTML = rows.join('');
  document.querySelectorAll('#tabelle tbody tr').forEach(aktualisiereZeile);
  aktualisiereLeiste();

  $('#btn-xml').disabled = gesperrt;
  $('#btn-bestaetigen').disabled = gesperrt;
  $('#btn-extern').classList.toggle('hidden', gesperrt);
  $('#btn-entsperren').classList.toggle('hidden', !gesperrt);

  const neueste = d.dateien[0]?.id;
  $('#dateien').innerHTML = d.dateien.length ? d.dateien.map((f) => `
    <div class="datei">
      <div>
        <strong>${esc(f.dateiname)}</strong>
        <div class="meta">Erstellt ${fmtZeit(f.erstellt_am)} von ${esc(f.erstellt_von)} · Lordo ${fmtEur(f.summe_brutto)} · Imponibile ${fmtEur(f.summe_imponibile)} · IVA ${fmtEur(f.summe_imposta)}</div>
        ${f.hochgeladen_am
          ? `<div class="meta" style="color:var(--ok)">✓ Übermittelt · IUT <strong>${esc(f.ricevuta)}</strong> · ${fmtZeit(f.hochgeladen_am)} von ${esc(f.hochgeladen_von)}</div>`
          : '<div class="meta">Nicht übermittelt</div>'}
        ${renderSignatur(f)}
        ${renderAdm(f)}
      </div>
      <div class="btns">
        <a href="/api/datei/${f.id}"><button type="button">Download XML</button></a>
        ${f.signiert ? `<a href="/api/datei/${f.id}/signiert"><button type="button">Signierte Datei</button></a>` : ''}
        ${f.id === neueste && !f.hochgeladen_am ? `
          <button type="button" data-aktion="upload" data-id="${f.id}">Signierte Datei hochladen</button>
          ${f.signiert && (!f.adm_iut || f.adm_art === 'fehler') ? `<button type="button" class="primary" data-aktion="senden" data-id="${f.id}" ${state.adm?.fehler.length ? 'disabled' : ''}>${state.adm?.umgebung === 'reale' ? 'An ADM senden (ECHT)' : 'An ADM senden (Test)'}</button>` : ''}` : ''}
        ${f.adm_iut ? `<button type="button" data-aktion="status" data-id="${f.id}">Status abfragen</button>` : ''}
      </div>
    </div>`).join('') : '<p class="muted">Noch keine Datei für diesen Monat erstellt.</p>';
}

function renderSignatur(f) {
  const s = f.signatur;
  if (!s) return '';
  if (!s.ok) {
    return `<div class="meta" style="color:var(--bad)">✗ Signierte Datei abgelehnt (${fmtZeit(f.signiert_am)}):<ul>${s.fehler.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
  }
  const u = s.unterzeichner;
  return `<div class="meta" style="color:var(--ok)">✓ Signatur geprüft${u ? ` · ${esc(u.name)}${u.codice_fiscale ? ' (' + esc(u.codice_fiscale) + ')' : ''} · Zertifikat bis ${fmtDatum(u.gueltig_bis.slice(0, 10))}` : ''}</div>`;
}

function renderAdm(f) {
  if (!f.adm_iut && !f.adm_codice) return '';
  const farbe = { ok: 'var(--ok)', fehler: 'var(--bad)', laeuft: 'var(--warn)' }[f.adm_art] || 'var(--muted)';
  const e = f.adm_esito || {};
  const liste = (titel, xs) => (xs && xs.length ? `<div>${titel}:<ul>${xs.map((x) => `<li>${esc(x.codice)} – ${esc(x.descrizione)}</li>`).join('')}</ul></div>` : '');
  return `<div class="meta" style="color:${farbe}">ADM ${f.adm_umgebung === 'reale' ? '(Echtbetrieb)' : '(Testumgebung)'} · IUT ${esc(f.adm_iut || '–')} · ${esc(f.adm_codice)} ${esc(f.adm_text || '')}
    · gesendet ${fmtZeit(f.adm_gesendet_am)}${f.adm_geprueft_am ? ' · geprüft ' + fmtZeit(f.adm_geprueft_am) : ''}
    ${liste('Fehler', e.errori)}${liste('Hinweise', e.segnalazioni)}</div>`;
}

async function ladeAdm() {
  try {
    state.adm = await api('GET', '/api/adm');
    const a = state.adm;
    const umg = a.umgebung === 'reale' ? '<strong>ECHTBETRIEB</strong>' : 'Testumgebung (prova)';
    $('#adm-info').innerHTML = a.fehler.length
      ? `ADM-Web-Service nicht eingerichtet: ${a.fehler.map(esc).join(' ')}`
      : `ADM-Web-Service: ${umg} · Zertifikat ${esc(a.zertifikat.name)} gültig bis ${fmtDatum(a.zertifikat.gueltig_bis.slice(0, 10))}`;
  } catch (err) { state.adm = null; }
}

async function dateiAktion(e) {
  const b = e.target.closest('button[data-aktion]');
  if (!b) return;
  const id = Number(b.dataset.id);
  try {
    const name = benutzer();
    if (b.dataset.aktion === 'upload') {
      state.uploadDatei = id;
      $('#signiert-input').value = '';
      $('#signiert-input').click();
      return;
    }
    if (b.dataset.aktion === 'senden') {
      const echt = state.adm?.umgebung === 'reale';
      if (echt && !confirm('ECHTE Meldung an die ADM senden? Gemeldete Tage können danach nur per Annullamento geändert werden.')) return;
      b.disabled = true;
      const r = await api('POST', `/api/datei/${id}/senden`, { benutzer: name, bestaetigt: echt });
      toast(`Gesendet · IUT ${r.iut} · ${r.codice} ${r.text}`);
    }
    if (b.dataset.aktion === 'status') {
      b.disabled = true;
      const r = await api('POST', `/api/datei/${id}/status`, { benutzer: name });
      toast(`Status ${r.codice}: ${r.text}`);
    }
    laden();
  } catch (err) { b.disabled = false; zeigeFehler(err); }
}

async function signierteDateiHochladen() {
  const datei = $('#signiert-input').files[0];
  if (!datei) return;
  const form = new FormData();
  form.append('datei', datei);
  form.append('benutzer', $('#benutzer').value.trim());
  try {
    const res = await fetch(`/api/datei/${state.uploadDatei}/signiert`, { method: 'POST', body: form });
    const r = await res.json();
    if (!res.ok) throw Object.assign(new Error(r.error || `Fehler ${res.status}`), { details: r.details || [] });
    toast(r.ok ? 'Signatur geprüft – bereit zum Senden.' : 'Signierte Datei abgelehnt – Details bei der Datei.');
    laden();
  } catch (err) { zeigeFehler(err); }
}

const AKTIONEN = {
  korrektur: 'Tag korrigiert', korrektur_entfernt: 'Korrektur entfernt', xml_erstellt: 'XML erstellt',
  upload_bestaetigt: 'Übermittlung bestätigt', signiert_hochgeladen: 'Signierte Datei hochgeladen',
  adm_gesendet: 'An ADM gesendet', adm_senden_fehler: 'Senden an ADM fehlgeschlagen', adm_status: 'ADM-Status abgefragt', extern_gemeldet: 'Von Enilive gemeldet markiert', korrektur_geoeffnet: 'Korrektur geöffnet', einstellungen: 'Einstellungen',
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
  if (p.aktion === 'extern_gemeldet') return `IUT ${d.iut} · gemeldet am ${d.datum}`;
  if (p.aktion === 'signiert_hochgeladen') return `${d.datei} · ${d.ok ? 'gültig' : 'abgelehnt'}`;
  if (p.aktion === 'adm_gesendet') return `${d.umgebung} · IUT ${d.iut} · ${d.codice} ${d.text}`;
  if (p.aktion === 'adm_senden_fehler') return `${d.umgebung} · ${d.fehler}`;
  if (p.aktion === 'adm_status') return `IUT ${d.iut} · ${d.codice} ${d.text}`;
  if (p.aktion === 'korrektur_geoeffnet') return `– ${d.grund}`;
  return '';
}

// ---------- Dialoge ----------

// ---------- Lordo bearbeiten ----------

// Eingabe -> { leer } | { wert: '1234.56' } | { fehler }
function parseBetrag(text) {
  let t = String(text ?? '').replace(/[€\s]/g, '');
  if (t === '') return { leer: true };
  if (t.includes(',')) t = t.replace(/\./g, '').replace(',', '.');
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return { fehler: true };
  const n = Number(t);
  if (!(n >= 0 && n <= 9999999.99)) return { fehler: true };
  return { wert: n.toFixed(2) };
}

function gleicherWert(a, b) {
  return (a.leer && b.leer) || (a.wert !== undefined && a.wert === b.wert);
}

function vorschau(wert) {
  const iva = Number(state.daten.iva_satz);
  const cents = Math.round(Number(wert) * 100);
  const imp = Math.round((cents * 100) / (100 + iva));
  return [(imp / 100).toFixed(2), ((cents - imp) / 100).toFixed(2)];
}

function aktualisiereZeile(tr) {
  const inp = tr.querySelector('input.lordo');
  const imp = tr.querySelector('.imp');
  const iva = tr.querySelector('.iva');
  const setze = (zelle, roh, kopierbar) => {
    const leer = roh === '' || roh == null;
    zelle.textContent = leer ? '–' : fmtEur(roh);
    zelle.classList.toggle('kopie', kopierbar && !leer);
    zelle.classList.toggle('vorschau', !kopierbar && !leer);
    if (kopierbar && !leer) { zelle.dataset.kopie = roh; zelle.title = 'Klicken zum Kopieren'; }
    else { delete zelle.dataset.kopie; zelle.title = !kopierbar && !leer ? 'Vorschau – erst nach dem Speichern kopierbar' : ''; }
  };
  if (!inp) { setze(imp, tr.dataset.imp, true); setze(iva, tr.dataset.iva, true); return; }
  const neu = parseBetrag(inp.value);
  const orig = parseBetrag(inp.dataset.orig);
  const quelle = parseBetrag(inp.dataset.quelle);
  const geaendert = !neu.fehler && !gleicherWert(neu, orig);
  tr.classList.toggle('geaendert', geaendert);
  inp.classList.toggle('ungueltig', !!neu.fehler);
  tr.querySelector('[data-reset]').classList.toggle('hidden', !neu.fehler && gleicherWert(neu, quelle));
  if (neu.fehler) { setze(imp, '', false); setze(iva, '', false); }
  else if (!geaendert) { setze(imp, tr.dataset.imp, true); setze(iva, tr.dataset.iva, true); }
  else if (neu.leer) { setze(imp, '', false); setze(iva, '', false); }
  else { const [i, v] = vorschau(neu.wert); setze(imp, i, false); setze(iva, v, false); }
}

function offeneAenderungen() {
  return [...document.querySelectorAll('#tabelle tbody tr')].filter((tr) => {
    const inp = tr.querySelector('input.lordo');
    if (!inp) return false;
    const neu = parseBetrag(inp.value);
    return neu.fehler || !gleicherWert(neu, parseBetrag(inp.dataset.orig));
  });
}

function aktualisiereLeiste() {
  const n = offeneAenderungen().length;
  $('#lordo-leiste').classList.toggle('hidden', n === 0);
  $('#lordo-anzahl').textContent = n === 1 ? '1 ungespeicherte Änderung' : `${n} ungespeicherte Änderungen`;
}

async function speichereLordo() {
  const zeilen = offeneAenderungen();
  if (zeilen.some((tr) => parseBetrag(tr.querySelector('input.lordo').value).fehler)) {
    toast('Bitte ungültige Beträge (rot markiert) korrigieren, z.B. 1234,56.');
    return;
  }
  try {
    const r = await api('PUT', `/api/monat/${state.monat}/lordo`, {
      benutzer: benutzer(),
      notiz: $('#lordo-notiz').value,
      aenderungen: zeilen.map((tr) => ({ datum: tr.dataset.datum, brutto: parseBetrag(tr.querySelector('input.lordo').value).wert ?? '' })),
    });
    $('#lordo-notiz').value = '';
    toast(`${r.gespeichert} Änderung(en) gespeichert.`);
    laden();
  } catch (err) { zeigeFehler(err); toast([err.message, ...(err.details || [])].join(' ')); }
}

function verwerfeLordo() {
  document.querySelectorAll('#tabelle input.lordo').forEach((inp) => { inp.value = inp.dataset.orig; });
  document.querySelectorAll('#tabelle tbody tr').forEach(aktualisiereZeile);
  aktualisiereLeiste();
}

function ungespeichertOk() {
  return offeneAenderungen().length === 0 || confirm('Es gibt ungespeicherte Änderungen. Wirklich wechseln und verwerfen?');
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

function oeffneExtern() {
  $('#ex-iut').value = '';
  $('#ex-datum').value = '';
  $('#dlg-extern').showModal();
}

async function speichereExtern(e) {
  e.preventDefault();
  try {
    await api('POST', `/api/monat/${state.monat}/extern`, { benutzer: benutzer(), iut: $('#ex-iut').value, datum: $('#ex-datum').value });
    $('#dlg-extern').close();
    toast('Als von Enilive gemeldet markiert – Monat gesperrt.');
    laden();
  } catch (err) { toast(err.message); }
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
    toast(`${r.dateiname} erstellt und gegen das ADM-Schema geprüft.`);
    const a = document.createElement('a');
    a.href = `/api/datei/${r.id}`;
    a.click();
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
$('#prev').onclick = () => ungespeichertOk() && monatVerschieben(-1);
$('#next').onclick = () => ungespeichertOk() && monatVerschieben(1);
$('#monat').onchange = (e) => {
  if (!e.target.value) return;
  if (!ungespeichertOk()) { e.target.value = state.monat; return; }
  setMonat(e.target.value);
};
$('#tabelle tbody').addEventListener('input', (e) => {
  if (!e.target.classList.contains('lordo')) return;
  aktualisiereZeile(e.target.closest('tr'));
  aktualisiereLeiste();
});
$('#tabelle tbody').addEventListener('keydown', (e) => {
  if (!e.target.classList.contains('lordo')) return;
  if (e.key === 'Enter') {
    e.preventDefault();
    const felder = [...document.querySelectorAll('#tabelle input.lordo')];
    const next = felder[felder.indexOf(e.target) + 1];
    if (next) { next.focus(); next.select(); }
  } else if (e.key === 'Escape') {
    e.target.value = e.target.dataset.orig;
    aktualisiereZeile(e.target.closest('tr'));
    aktualisiereLeiste();
  }
});
$('#tabelle tbody').addEventListener('focusin', (e) => { if (e.target.classList.contains('lordo')) e.target.select(); });
$('#tabelle tbody').addEventListener('click', (e) => {
  const r = e.target.closest('[data-reset]');
  if (r) {
    const tr = r.closest('tr');
    const inp = tr.querySelector('input.lordo');
    inp.value = inp.dataset.quelle;
    aktualisiereZeile(tr);
    aktualisiereLeiste();
    return;
  }
  const k = e.target.closest('td[data-kopie]');
  if (k) kopiere(k.dataset.kopie);
});
$('#lordo-speichern').onclick = speichereLordo;
$('#lordo-verwerfen').onclick = verwerfeLordo;
window.addEventListener('beforeunload', (e) => { if (offeneAenderungen().length) { e.preventDefault(); e.returnValue = ''; } });
$('#btn-einstellungen').onclick = oeffneEinstellungen;
$('#btn-xml').onclick = erstelleXml;
$('#btn-entsperren').onclick = entsperren;
$('#btn-bestaetigen').onclick = () => { try { benutzer(); oeffneUpload(); } catch (err) { toast(err.message); } };
$('#btn-extern').onclick = () => { try { benutzer(); oeffneExtern(); } catch (err) { toast(err.message); } };
$('#ex-save').onclick = speichereExtern;
$('#ue-tabelle tbody').onclick = (e) => {
  const tr = e.target.closest('tr[data-monat]');
  if (tr && ungespeichertOk()) { setMonat(tr.dataset.monat); window.scrollTo({ top: $('.monthbar').offsetTop - 12, behavior: 'smooth' }); }
};
$('#dateien').onclick = dateiAktion;
$('#signiert-input').onchange = signierteDateiHochladen;
$('#btn-drucken').onclick = () => window.print();
$('#dezimal').value = store('dezimal') || ',';
$('#dezimal').onchange = (e) => store('dezimal', e.target.value);
$('#e-save').onclick = speichereEinstellungen;
$('#up-save').onclick = bestaetigeUpload;

// Standard: Vormonat (der Monat, der als Nächstes zu melden ist)
const jetzt = new Date();
const vm = new Date(jetzt.getFullYear(), jetzt.getMonth() - 1, 1);
ladeAdm().finally(() => setMonat(`${vm.getFullYear()}-${String(vm.getMonth() + 1).padStart(2, '0')}`));
