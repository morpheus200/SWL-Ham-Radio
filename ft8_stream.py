"""
===========================================================================
SWL FT8/FT4 Live-Logger & ADIF-Generator
===========================================================================
Änderungshistorie:
- v1.0: Basis-Parser für WSJT-X/JTDX UDP-Streams (FT8).
- v1.1: Locator-Memory hinzugefügt (Filterung von "RR73" als GridSquare).
- v1.2: QO-100 Satelliten-Support integriert (PROP_MODE und SAT_NAME Tags).
- v2.0: Dual-Port Engine (simultanes Lauschen auf FT8/2237 und FT4/2238).
- v2.1: eQSL & Wavelog Fix: <COMMENT> zu <QSLMSG> geändert, <RST_SENT> ergänzt.
- v3.0: Wavelog Master-DB Integration (know_call_signs.txt): Intelligentes 
        Limit auf maximal 2 geloggte QSOs pro Rufzeichen und Band.
- v3.1: QO-100 Club Fix: FT4 wird nun ADIF-konform als <MODE:4>MFSK 
        und <SUBMODE:3>FT4 exportiert.
===========================================================================
"""

import socket
import struct
import datetime
import re
import os
import select

def get_band(freq_mhz):
    try:
        freq = float(freq_mhz)
        if 1.8 <= freq <= 2.0: return "160m"
        elif 3.5 <= freq <= 3.8: return "80m"
        elif 7.0 <= freq <= 7.3: return "40m"
        elif 10.1 <= freq <= 10.15: return "30m"
        elif 14.0 <= freq <= 14.35: return "20m"
        elif 18.068 <= freq <= 18.168: return "17m"
        elif 21.0 <= freq <= 21.45: return "15m"
        elif 24.89 <= freq <= 24.99: return "12m"
        elif 28.0 <= freq <= 29.7: return "10m"
        elif 50.0 <= freq <= 54.0: return "6m"
        elif 10489.0 <= freq <= 10490.0: return "3cm"
        else: return ""
    except ValueError:
        return ""

def clean_callsign(call):
    if not call: return None
    call = call.replace('<', '').replace('>', '')
    invalid_calls = ['...', 'RR73;', 'RR73', '73', 'RRR', 'CQ', 'WSJT-X', 'JTDX']
    if call.upper() in invalid_calls or len(call) < 3: return None
    if not re.match(r'^[A-Z0-9/]+$', call, re.IGNORECASE): return None
    return call

def parse_ft8_message(message):
    parts = message.strip().split()
    if len(parts) < 3: return None, None
    last_word = parts[-1].upper().rstrip(';')
    if last_word not in ["73", "RR73", "RRR"]: return None, None
    receiver = clean_callsign(parts[0])
    sender = clean_callsign(parts[1])
    if sender and receiver: return sender, receiver
    return None, None

def parse_qt_string(payload, offset):
    if offset + 4 > len(payload): return "", offset
    length, = struct.unpack_from('>I', payload, offset)
    offset += 4
    if length == 0xffffffff or length == 0: return "", offset
    if offset + length > len(payload): return "", offset
    val = payload[offset:offset+length].decode('utf-8', 'ignore')
    return val, offset+length

def parse_wsjtx_packet(payload):
    if len(payload) < 12: return None
    magic, schema, msg_type = struct.unpack_from('>III', payload, 0)
    if magic != 0xadbccbda: return None
    offset = 12
    client_id, offset = parse_qt_string(payload, offset)
    
    if msg_type == 1: 
        if offset + 8 > len(payload): return None
        dial_freq, = struct.unpack_from('>Q', payload, offset)
        offset += 8
        mode, offset = parse_qt_string(payload, offset)
        return {'type': 'Status', 'freq': dial_freq, 'mode': mode}
    elif msg_type == 2: 
        if offset + 21 > len(payload): return None
        is_new, time_ms, snr, dt, df = struct.unpack_from('>bIidI', payload, offset)
        offset += 21
        mode, offset = parse_qt_string(payload, offset)
        message, offset = parse_qt_string(payload, offset)
        return {'type': 'Decode', 'snr': snr, 'mode': mode, 'message': message}
    return None

def format_adif_record(date, time, freq_mhz, mode, snr, callsign, target_callsign, remote_grid):
    band = get_band(freq_mhz)
    comment = f"WKD WD {target_callsign}"    
    my_call = "DL2570SWL" 
    my_grid = "JO30tg"
    
    adif_str = (
        f"<CALL:{len(callsign)}>{callsign} "
        f"<QSO_DATE:8>{date} "
        f"<TIME_ON:6>{time} "
        f"<FREQ:{len(str(freq_mhz))}>{freq_mhz} "
    )
    if band: adif_str += f"<BAND:{len(band)}>{band} "
        
    # FIX: ADIF-konforme FT4-Weiche für den QO-100 Dx Club
    if mode.upper() == "FT4":
        adif_str += "<MODE:4>MFSK <SUBMODE:3>FT4 "
    else:
        adif_str += f"<MODE:{len(mode)}>{mode} "
        
    adif_str += (
        f"<RST_RCVD:{len(str(snr))}>{snr} "
        f"<RST_SENT:{len(str(snr))}>{snr} "  
        f"<MY_GRIDSQUARE:{len(my_grid)}>{my_grid} "
    )
    
    if remote_grid and remote_grid != "RR73": 
        adif_str += f"<GRIDSQUARE:{len(remote_grid)}>{remote_grid} "
        
    if band == "3cm" or (10489.0 <= float(freq_mhz) <= 10490.0):
        adif_str += "<PROP_MODE:3>SAT <SAT_NAME:6>QO-100 "
        
    adif_str += (
        f"<QSLMSG:{len(comment)}>{comment} " 
        f"<STATION_CALLSIGN:{len(my_call)}>{my_call} "
        f"<EOR>\n"
    )
    return adif_str

def load_database(filename="know_call_signs.txt"):
    """Liest die Master-Datenbank ein."""
    counts = {}
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) == 3:
                    call, band, count = parts
                    counts[f"{call},{band}"] = int(count)
    return counts

def save_database(counts, filename="know_call_signs.txt"):
    """Speichert die aktualisierte Datenbank ab."""
    with open(filename, 'w', encoding='utf-8') as f:
        for key, count in counts.items():
            f.write(f"{key},{count}\n")

def start_swl_server(output_file="swl_live_export.adi"):
    ip = '127.0.0.1'
    port1 = 2237
    port2 = 2238
    db_file = "know_call_signs.txt"
    
    sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock1.bind((ip, port1))
    sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock2.bind((ip, port2))
    sockets = [sock1, sock2]
    
    current_status = {
        sock1: {'freq': 10489.552, 'mode': 'FT8'},
        sock2: {'freq': 10489.552, 'mode': 'FT4'}
    }
    
    seen_grids = {}
    
    # Master-Datenbank laden
    qso_counts = load_database(db_file)
    bekannte_kombis = len(qso_counts)
    
    print("=" * 70)
    print(f"Starte Dual-Port Live SWL-Logger (Ports {port1} & {port2})")
    print(f"Limit: Max 2 QSOs pro Rufzeichen & Band.")
    print(f"Datenbank geladen: {bekannte_kombis} bekannte Stationen aus '{db_file}'.")
    print("=" * 70)
    
    if not os.path.exists(output_file):
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("ADIF Export vom Dual-Port Live FT8/FT4 SWL Parser\n")
            f.write("<PROGRAMID:18>PythonFT8LiveSWL\n")
            f.write("<EOH>\n\n")

    while True:
        try:
            readable, _, _ = select.select(sockets, [], [])
            for s in readable:
                data, addr = s.recvfrom(2048)
                pkt = parse_wsjtx_packet(data)
                
                if not pkt: continue
                    
                if pkt['type'] == 'Status':
                    if pkt['freq'] > 0:
                        current_status[s]['freq'] = pkt['freq'] / 1000000.0
                    if pkt['mode']:
                        current_status[s]['mode'] = pkt['mode'].strip()
                        
                elif pkt['type'] == 'Decode':
                    msg_parts = pkt['message'].strip().split()
                    
                    if len(msg_parts) >= 2:
                        potential_grid = msg_parts[-1].upper()
                        if re.match(r'^[A-R][A-R][0-9][0-9]$', potential_grid) and potential_grid != "RR73":
                            sender_cand = clean_callsign(msg_parts[-2])
                            if sender_cand:
                                seen_grids[sender_cand] = potential_grid
                                if len(seen_grids) > 5000: seen_grids.clear()

                    sender, receiver = parse_ft8_message(pkt['message'])
                    
                    if sender:
                        freq = current_status[s]['freq']
                        mode = current_status[s]['mode']
                        band = get_band(freq)
                        
                        sender_key = f"{sender},{band}"
                        receiver_key = f"{receiver},{band}"
                        
                        # Prüfen, ob das Limit (< 2) laut Wavelog-Datenbank erreicht ist
                        log_sender = qso_counts.get(sender_key, 0) < 2
                        log_receiver = qso_counts.get(receiver_key, 0) < 2
                        
                        if log_sender or log_receiver:
                            now = datetime.datetime.utcnow()
                            date_str = now.strftime("%Y%m%d")
                            time_str = now.strftime("%H%M%S")
                            
                            sender_grid = seen_grids.get(sender, "")
                            receiver_grid = seen_grids.get(receiver, "")
                            
                            with open(output_file, 'a', encoding='utf-8') as f:
                                if log_sender:
                                    f.write(format_adif_record(date_str, time_str, freq, mode, pkt['snr'], sender, receiver, sender_grid))
                                    qso_counts[sender_key] = qso_counts.get(sender_key, 0) + 1
                                    
                                if log_receiver:
                                    f.write(format_adif_record(date_str, time_str, freq, mode, pkt['snr'], receiver, sender, receiver_grid))
                                    qso_counts[receiver_key] = qso_counts.get(receiver_key, 0) + 1
                            
                            # Update die Datenbank-Datei in Echtzeit
                            save_database(qso_counts, db_file)
                            
                            if log_sender and log_receiver:
                                print(f"[{time_str} | {band}] LOG: {sender} <-> {receiver}")
                            elif log_sender:
                                print(f"[{time_str} | {band}] LOG: {sender} (Ignoriere {receiver}, Limit erreicht)")
                            elif log_receiver:
                                print(f"[{time_str} | {band}] LOG: {receiver} (Ignoriere {sender}, Limit erreicht)")
                        
        except KeyboardInterrupt:
            print("\nLive-Logger beendet.")
            break
        except Exception:
            continue

if __name__ == "__main__":
    start_swl_server()