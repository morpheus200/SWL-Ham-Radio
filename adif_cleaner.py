"""
===========================================================================
Wavelog ADIF Cleaner & eQSL Upgrader
===========================================================================
Änderungshistorie:
- v1.0: Basis-Skript zum Ersetzen von COMMENT zu QSLMSG und RST-Fix.
- v2.0: Intelligenter Filter eingebaut: Max 3 QSOs pro Rufzeichen/Band.
- v2.1: FT4-Fix integriert (MFSK/FT4).
- v2.2: Hardcore-Duplikat-Filter (Zeit-Duplikate gelöscht).
- v2.3: RR73-Geister-Locators entfernt.
- v2.4: QO-100 Satelliten-Fix (sichert PROP_MODE=SAT und ergänzt SAT_MODE).
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
    qo100_count = 0
    
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
            
            # 5. QO-100 Satelliten-Fix für eQSL
            is_qo100 = bool(re.search(r'<SAT_NAME:\d+>(QO-100|ESHAIL)', rec, re.IGNORECASE))
            if not is_qo100 and re.search(r'<BAND:\d+>(13cm|3cm)', rec, re.IGNORECASE):
                # Wenn das Band 13cm/3cm ist, machen wir es offiziell zum QO-100
                rec += " <SAT_NAME:6>QO-100"
                is_qo100 = True
                
            if is_qo100:
                qo100_count += 1
                if not re.search(r'<PROP_MODE:', rec, re.IGNORECASE):
                    rec += " <PROP_MODE:3>SAT"
                if not re.search(r'<SAT_MODE:', rec, re.IGNORECASE):
                    # Setzt ein leeres SAT_MODE Feld. 
                    # Falls eQSL hier z.B. ein "X" verlangt, ändere diese Zeile in: rec += " <SAT_MODE:1>X"
                    rec += " <SAT_MODE:0>"
            
            final_records.append(rec + " <EOR>\n")

    with open(output_file, 'w', encoding='utf-8') as out:
        out.write(header)
        out.writelines(final_records)

    print("-" * 50)
    print("Zusammenfassung der ADIF-Bereinigung (v2.4):")
    print(f"Einträge nach 3-QSO Limit:       {len(final_records)}")
    print(f"QO-100 QSOs repariert/bestätigt: {qo100_count}")
    print(f"Gespeichert in:                  '{output_file}'")
    print("-" * 50)

if __name__ == "__main__":
    while True:
        print("\n" + "=" * 50)
        eingabe = input("ADIF-Export reinziehen (oder 'exit'): ").strip()
        if eingabe.lower() in ['exit', 'quit', 'q', 'ende']:
            break
        eingabe_datei = eingabe.replace('"', '').replace("'", "")
        if not eingabe_datei:
            continue
        dateiname, dateiendung = os.path.splitext(eingabe_datei)
        ausgabe_datei = f"{dateiname}_cleaned{dateiendung}"
        clean_and_upgrade_adif(eingabe_datei, ausgabe_datei)