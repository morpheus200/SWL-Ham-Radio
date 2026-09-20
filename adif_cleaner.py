"""
===========================================================================
Wavelog ADIF Cleaner & eQSL Upgrader
===========================================================================
Änderungshistorie:
- v1.0: Basis-Skript zum Ersetzen von COMMENT zu QSLMSG und RST-Fix.
- v2.0: Intelligenter Filter eingebaut: Max 3 QSOs pro Rufzeichen/Band.
        VIP-Logik für eQSL-Bestätigungen (verhindert Datenverlust).
- v2.1: FT4-Fix integriert (wandelt FT4 in MFSK/FT4 für QO-100 Club um).
- v2.2: Hardcore-Duplikat-Filter: Löscht exakte Zeitstempel-Kopien vor der 
        3-QSO-Limitierung, um Wavelog-Import-Fehler ("Doppelte QSOs") 
        zu verhindern. Bevorzugt dabei immer eQSL-bestätigte Einträge.
- v2.3: Sibirien-Fix: Entfernt fälschlicherweise als GridSquare geloggte 
        "RR73"-Texte aus alten Beständen restlos.
===========================================================================
"""

import re
import os
from collections import defaultdict

def clean_and_upgrade_adif(input_file, output_file):
    if not os.path.exists(input_file):
        print(f"Fehler: Die Datei '{input_file}' wurde nicht gefunden.")
        return

    print("Lese und analysiere ADIF-Datei. Bitte warten...")
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    header_split = content.split('<EOH>')
    if len(header_split) < 2:
        print("Fehler: Kein gültiger ADIF-Header gefunden.")
        return
        
    header = header_split[0] + "<EOH>\n"
    records_raw = header_split[1].split('<EOR>')

    unique_by_time = {}
    
    # Schritt 1: Exakte Zeit-Duplikate filtern (Wavelog-Schutz)
    for record in records_raw:
        record = record.strip()
        if not record:
            continue
            
        call_match = re.search(r'<CALL:\d+>([^ <]+)', record, re.IGNORECASE)
        band_match = re.search(r'<BAND:\d+>([^ <]+)', record, re.IGNORECASE)
        date_match = re.search(r'<QSO_DATE:\d+>([^ <]+)', record, re.IGNORECASE)
        time_match = re.search(r'<TIME_ON:\d+>([^ <]+)', record, re.IGNORECASE)
        
        if call_match and band_match and date_match and time_match:
            call = call_match.group(1).strip().upper()
            band = band_match.group(1).strip().upper()
            date = date_match.group(1).strip()
            time = time_match.group(1).strip()
            
            is_confirmed = bool(re.search(r'<(?:APP_)?EQSL_QSL_RCVD:\d+>Y', record, re.IGNORECASE))
            exact_key = f"{call}_{band}_{date}_{time}"
            
            # VIP-Check: Bestätigte überschreiben unbestätigte Duplikate
            if exact_key not in unique_by_time or (is_confirmed and not unique_by_time[exact_key]['is_confirmed']):
                unique_by_time[exact_key] = {
                    'raw': record,
                    'is_confirmed': is_confirmed,
                    'call_band': f"{call}_{band}"
                }

    # Schritt 2: Auf max 3 pro Rufzeichen/Band reduzieren
    grouped_qsos = defaultdict(list)
    for data in unique_by_time.values():
        grouped_qsos[data['call_band']].append(data)

    final_records = []
    
    for key, qsos in grouped_qsos.items():
        confirmed_qsos = [q for q in qsos if q['is_confirmed']]
        unconfirmed_qsos = [q for q in qsos if not q['is_confirmed']]
        
        kept_for_this_key = confirmed_qsos.copy()
        
        needed = 3 - len(kept_for_this_key)
        if needed > 0:
            kept_for_this_key.extend(unconfirmed_qsos[:needed])
            
        # Schritt 3: Felder reparieren
        for qso in kept_for_this_key:
            rec = qso['raw']
            
            # 1. COMMENT in QSLMSG umwandeln
            rec = re.sub(r'<COMMENT:(\d+)>', r'<QSLMSG:\1>', rec, flags=re.IGNORECASE)
            
            # 2. Fehlendes RST_SENT ergänzen
            rst_rcvd_match = re.search(r'<RST_RCVD:(\d+)>([^ <]+)', rec, re.IGNORECASE)
            if rst_rcvd_match and not re.search(r'<RST_SENT:', rec, re.IGNORECASE):
                length = rst_rcvd_match.group(1)
                val = rst_rcvd_match.group(2)
                rec = rec.replace(f"<RST_RCVD:{length}>{val}", f"<RST_RCVD:{length}>{val} <RST_SENT:{length}>{val}")
                
            # 3. FT4 in MFSK + FT4-Submode umwandeln
            if re.search(r'<MODE:\d+>FT4', rec, re.IGNORECASE):
                rec = re.sub(r'<MODE:\d+>FT4', r'<MODE:4>MFSK <SUBMODE:3>FT4', rec, flags=re.IGNORECASE)

            # 4. RR73-GridSquare Fehler restlos entfernen
            rec = re.sub(r'<GRIDSQUARE:\d+>RR73\s*', '', rec, flags=re.IGNORECASE)
            
            final_records.append(rec + " <EOR>\n")

    with open(output_file, 'w', encoding='utf-8') as out:
        out.write(header)
        out.writelines(final_records)

    gelesene_eintraege = len(records_raw) - 1
    
    print("-" * 50)
    print("Zusammenfassung der ADIF-Bereinigung (v2.3):")
    print(f"Ursprüngliche Einträge:          {gelesene_eintraege}")
    print(f"Ohne exakte Zeit-Duplikate:      {len(unique_by_time)}")
    print(f"Einträge nach 3-QSO Limit:       {len(final_records)}")
    print("-> RR73-Geister-Locators wurden erfolgreich gelöscht!")
    print(f"Gespeichert in:                  '{output_file}'")
    print("-" * 50)

if __name__ == "__main__":
    while True:
        print("\n" + "=" * 50)
        eingabe = input("Originalen Wavelog ADIF-Export reinziehen (oder 'exit'): ").strip()
        if eingabe.lower() in ['exit', 'quit', 'q', 'ende']:
            break
        eingabe_datei = eingabe.replace('"', '').replace("'", "")
        if not eingabe_datei:
            continue
        dateiname, dateiendung = os.path.splitext(eingabe_datei)
        ausgabe_datei = f"{dateiname}_cleaned{dateiendung}"
        clean_and_upgrade_adif(eingabe_datei, ausgabe_datei)