import socket
import struct
import datetime
import re
import os
import select

def get_band(freq_mhz):
    """Ermittelt das Band anhand der Frequenz in MHz."""
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
    if not call:
        return None
    call = call.replace('<', '').replace('>', '')
    invalid_calls = ['...', 'RR73;', 'RR73', '73', 'RRR', 'CQ', 'WSJT-X', 'JTDX']
    if call.upper() in invalid_calls or len(call) < 3:
        return None
    if not re.match(r'^[A-Z0-9/]+$', call, re.IGNORECASE):
        return None
    return call

def parse_ft8_message(message):
    """Filtert NUR abgeschlossene QSOs aus dem Live-Stream."""
    parts = message.strip().split()
    if len(parts) < 3:
        return None, None
        
    last_word = parts[-1].upper().rstrip(';')
    if last_word not in ["73", "RR73", "RRR"]:
        return None, None
        
    receiver = clean_callsign(parts[0])
    sender = clean_callsign(parts[1])
    
    if sender and receiver:
        return sender, receiver
    return None, None

def parse_qt_string(payload, offset):
    """Extrahiert einen Qt-formatierten String aus dem Binär-Paket."""
    if offset + 4 > len(payload): return "", offset
    length, = struct.unpack_from('>I', payload, offset)
    offset += 4
    if length == 0xffffffff or length == 0: return "", offset
    if offset + length > len(payload): return "", offset
    val = payload[offset:offset+length].decode('utf-8', 'ignore')
    return val, offset+length

def parse_wsjtx_packet(payload):
    """Zerlegt das WSJT-X UDP-Paket manuell über das struct-Modul."""
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
    
    if band:
        adif_str += f"<BAND:{len(band)}>{band} "
        
    adif_str += (
        f"<MODE:{len(mode)}>{mode} "
        f"<RST_RCVD:{len(str(snr))}>{snr} "
        f"<RST_SENT:{len(str(snr))}>{snr} "
        f"<MY_GRIDSQUARE:{len(my_grid)}>{my_grid} "
    )
    
    if remote_grid:
        adif_str += f"<GRIDSQUARE:{len(remote_grid)}>{remote_grid} "
        
    if band == "3cm" or (10489.0 <= float(freq_mhz) <= 10490.0):
        adif_str += "<PROP_MODE:3>SAT <SAT_NAME:6>QO-100 "
        
    adif_str += (
        f"<COMMENT:{len(comment)}>{comment} "
        f"<STATION_CALLSIGN:{len(my_call)}>{my_call} "
        f"<EOR>\n"
    )
    return adif_str

def start_swl_server(output_file="swl_live_export.adi"):
    ip = '127.0.0.1'
    port1 = 2237 # FT8
    port2 = 2238 # FT4
    treffer = 0
    seen_grids = {} 
    
    # Sockets vorbereiten
    sock1 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock1.bind((ip, port1))
    
    sock2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock2.bind((ip, port2))
    
    sockets = [sock1, sock2]
    
    # Status-Gedächtnis pro Socket, damit FT8 und FT4 sich nicht überschreiben
    current_status = {
        sock1: {'freq': 10489.552, 'mode': 'FT8', 'name': f"Port {port1}"},
        sock2: {'freq': 10489.552, 'mode': 'FT4', 'name': f"Port {port2}"}
    }
    
    print("=" * 60)
    print(f"Starte Dual-Port Live SWL-Logger auf UDP {ip}")
    print(f"Lausche auf Port {port1} (FT8) und Port {port2} (FT4)...")
    print(f"Schreibe zweiseitige QSOs inkl. Locatoren in '{output_file}'")
    print("Abbruch mit STRG+C")
    print("=" * 60)
    
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
                
                if not pkt:
                    continue
                    
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
                                if len(seen_grids) > 5000:
                                    seen_grids.clear()

                    sender, receiver = parse_ft8_message(pkt['message'])
                    
                    if sender:
                        now = datetime.datetime.utcnow()
                        date_str = now.strftime("%Y%m%d")
                        time_str = now.strftime("%H%M%S")
                        
                        sender_grid = seen_grids.get(sender, "")
                        receiver_grid = seen_grids.get(receiver, "")
                        
                        freq = current_status[s]['freq']
                        mode = current_status[s]['mode']
                        
                        record_sender = format_adif_record(
                            date_str, time_str, freq, mode, 
                            pkt['snr'], sender, receiver, sender_grid
                        )
                        record_receiver = format_adif_record(
                            date_str, time_str, freq, mode, 
                            pkt['snr'], receiver, sender, receiver_grid
                        )
                        
                        with open(output_file, 'a', encoding='utf-8') as f:
                            f.write(record_sender)
                            f.write(record_receiver)
                        
                        treffer += 1
                        print(f"[{time_str} | {mode}] LOG (2x): {sender} ({sender_grid if sender_grid else '?'}) <-> {receiver} ({receiver_grid if receiver_grid else '?'}) (Gesamt: {treffer})")
                        
        except KeyboardInterrupt:
            print("\nLive-Logger beendet. Bis zum nächsten Mal!")
            break
        except Exception:
            continue

if __name__ == "__main__":
    start_swl_server()