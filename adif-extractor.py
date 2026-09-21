"""
===========================================================================
Wavelog ADIF Extractor (Retter für fehlende QSOs)
===========================================================================
Änderungshistorie:
- v1.1: Dateinamen-Sanierung (Sonderzeichen wie '/' in Rufzeichen 
        werden für den Dateinamen durch '_' ersetzt, z.B. EA4CTP_EA7.adi).
===========================================================================
"""

import re
import os

def load_adif_database(input_file):
    if not os.path.exists(input_file):
        print(f"Fehler: Die Datei '{input_file}' wurde nicht gefunden.")
        return None, None
        
    print(f"Lese Backup-Datei '{input_file}' in den Arbeitsspeicher. Bitte warten...")
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    header_split = content.split('<EOH>')
    if len(header_split) < 2:
        print("Fehler: Kein gültiger ADIF-Header gefunden.")
        return None, None
        
    header = header_split[0] + "<EOH>\n"
    records_raw = header_split[1].split('<EOR>')
    
    # Leere Einträge herausfiltern
    records_clean = [r.strip() for r in records_raw if r.strip()]
    print(f"Fertig! {len(records_clean)} QSOs geladen.")
    
    return header, records_clean

def extract_callsign(header, records_raw, callsign_to_find):
    callsign_to_find = callsign_to_find.strip().upper()
    extracted_records = []
    
    for record in records_raw:
        call_match = re.search(r'<CALL:\d+>([^ <]+)', record, re.IGNORECASE)
        if call_match:
            call = call_match.group(1).strip().upper()
            if call == callsign_to_find:
                extracted_records.append(record + " <EOR>\n")
                
    if extracted_records:
        # Hier ist der Fix: Wir ersetzen alle für Dateinamen verbotenen Zeichen durch Unterstriche
        safe_filename = re.sub(r'[\\/*?:"<>|]', '_', callsign_to_find)
        output_file = f"import_{safe_filename}.adi"
        
        with open(output_file, 'w', encoding='utf-8') as out:
            out.write(header)
            out.writelines(extracted_records)
        print(f"-> ERFOLG: {len(extracted_records)} QSOs für {callsign_to_find} gefunden und in '{output_file}' gespeichert.")
    else:
        print(f"-> FEHLER: Keine Verbindungen für das Rufzeichen {callsign_to_find} im Backup gefunden.")

if __name__ == "__main__":
    print("=" * 60)
    print("ADIF Rufzeichen-Extractor v1.1")
    print("=" * 60)
    
    while True:
        backup_eingabe = input("\nZiehe deine große Backup-ADIF hier rein (oder 'exit'): ").strip()
        if backup_eingabe.lower() in ['exit', 'quit', 'q']:
            break
            
        backup_datei = backup_eingabe.replace('"', '').replace("'", "")
        if not backup_datei:
            continue
            
        header, records = load_adif_database(backup_datei)
        
        if header and records:
            while True:
                such_call = input("\nWelches Rufzeichen fehlt in Wavelog? (oder 'zurück'): ").strip()
                if such_call.lower() in ['zurück', 'back', 'b', 'exit', 'quit', 'q', '']:
                    print("Gehe zurück zur Dateiauswahl...")
                    break
                
                extract_callsign(header, records, such_call)