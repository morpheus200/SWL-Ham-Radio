import re
import os

def erstelle_datenbank(adif_datei, db_datei="know_call_signs.txt"):
    if not os.path.exists(adif_datei):
        print(f"Fehler: Datei '{adif_datei}' nicht gefunden.")
        return

    print(f"Lese '{adif_datei}' ein und zähle Rufzeichen pro Band...")
    counts = {}
    
    with open(adif_datei, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # Trenne die ADIF-Datei in einzelne Datensätze
    records = content.split('<EOR>')
    for record in records:
        call_match = re.search(r'<CALL:\d+>([^ <]+)', record, re.IGNORECASE)
        band_match = re.search(r'<BAND:\d+>([^ <]+)', record, re.IGNORECASE)
        
        if call_match and band_match:
            call = call_match.group(1).strip().upper()
            band = band_match.group(1).strip().lower()
            
            # Schlüssel ist "CALL,band"
            key = f"{call},{band}"
            counts[key] = counts.get(key, 0) + 1

    # Schreibe die Datenbank-Datei
    with open(db_datei, 'w', encoding='utf-8') as f:
        for key, count in counts.items():
            f.write(f"{key},{count}\n")

    print(f"Erfolgreich! {len(counts)} einzigartige Kombinationen in '{db_datei}' gespeichert.")

if __name__ == "__main__":
    print("=" * 50)
    print("Wavelog Master-Export -> SWL Datenbank")
    print("=" * 50)
    eingabe = input("Bitte den Wavelog ADIF-Export hier reinziehen: ").strip()
    eingabe = eingabe.replace('"', '').replace("'", "")
    
    if eingabe:
        erstelle_datenbank(eingabe)