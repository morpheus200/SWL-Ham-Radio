"""
===========================================================================
Wavelog ADIF Cleaner & eQSL Upgrader
===========================================================================
Änderungshistorie:
- v1.0: Basis-Skript zum Ersetzen von COMMENT zu QSLMSG und RST-Fix.
- v2.0: Intelligenter Filter eingebaut: Max 3 QSOs pro Rufzeichen/Band.
        VIP-Logik: Bereits über eQSL bestätigte QSOs werden IMMER 
        behalten, um keinen Datenverlust in Wavelog zu riskieren.
- v2.1: FT4-Fix integriert (wandelt FT4 in MFSK/FT4 für QO-100 Club um).
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

    grouped_qsos = defaultdict(list)
    
    # Schritt 1: Alle QSOs einlesen und nach Rufzeichen+Band sortieren
    for record in records_raw:
        record = record.strip()
        if not record:
            continue
            
        call_match = re.search(r'<CALL:\d+>([^ <]+)', record, re.IGNORECASE)
        band_match = re.search(r'<BAND:\d+>([^ <]+)', record, re.IGNORECASE)
        
        if call_match and band_match:
            call = call_match.group(1).strip().upper()
            band = band_match.group(1).strip().upper()
            
            # VIP-Check: Ist das QSO bereits via eQSL bestätigt?
            # Wavelog nutzt meist <APP_EQSL_QSL_RCVD:1>Y oder <EQSL_QSL_RCVD:1>Y
            is_confirmed = False
            if re.search(r'<(?:APP_)?EQSL_QSL_RCVD:\d+>Y', record, re.IGNORECASE):
                is_confirmed = True
                
            grouped_qsos[f"{call}_{band}"].append({
                'raw': record,
                'is_confirmed': is_confirmed
            })

    # Schritt 2: Filtern und reparieren
    final_records = []
    
    for key, qsos in grouped_qsos.items():
        confirmed_qsos = [q for q in qsos if q['is_confirmed']]
        unconfirmed_qsos = [q for q in qsos if not q['is_confirmed']]
        
        # Alle bestätigten QSOs (VIPs) zwingend behalten
        kept_for_this_key = confirmed_qsos.copy()
        
        # Wenn weniger als 3 vorhanden sind, mit unbestätigten auffüllen
        needed = 3 - len(kept_for_this_key)
        if needed > 0:
            kept_for_this_key.extend(unconfirmed_qsos[:needed])
            
        # Die behaltenen QSOs nun reparieren (RST, QSLMSG, FT4)
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
                
            # 3. FT4 in MFSK + FT4-Submode umwandeln (falls noch alt)
            if re.search(r'<MODE:\d+>FT4', rec, re.IGNORECASE):
                rec = re.sub(r'<MODE:\d+>FT4', r'<MODE:4>MFSK <SUBMODE:3>FT4', rec, flags=re.IGNORECASE)
            
            final_records.append(rec + " <EOR>\n")

    # Schritt 3: Neue Datei schreiben
    with open(output_file, 'w', encoding='utf-8') as out:
        out.write(header)
        out.writelines(final_records)

    gelesene_eintraege = len(records_raw) - 1
    
    print("-" * 50)
    print("Zusammenfassung der ADIF-Bereinigung:")
    print(f"Ursprüngliche Einträge: {gelesene_eintraege}")
    print(f"Einträge nach Filter:   {len(final_records)}")
    print(f"Gelöschte Altlasten:    {gelesene_eintraege - len(final_records)}")
    print("-> VIP-Schutz für eQSL-Bestätigungen war AKTIV!")
    print("-> QSLMSG, RST_SENT & FT4 wurden vollautomatisch korrigiert.")
    print(f"Gespeichert in:         '{output_file}'")
    print("-" * 50)

if __name__ == "__main__":
    while True:
        print("\n" + "=" * 50)
        eingabe = input("Wavelog ADIF-Export reinziehen (oder 'exit'): ").strip()
        
        if eingabe.lower() in ['exit', 'quit', 'q', 'ende']:
            break
            
        eingabe_datei = eingabe.replace('"', '').replace("'", "")
        if not eingabe_datei:
            continue
            
        dateiname, dateiendung = os.path.splitext(eingabe_datei)
        ausgabe_datei = f"{dateiname}_cleaned{dateiendung}"
        
        clean_and_upgrade_adif(eingabe_datei, ausgabe_datei)