# Bibliothek
import socket
import os
import psutil
import sys

#############################################################################################################################
# Hauptprogramm

def get_ip_adress():
    try:
        # Betriebssystemtyp abrufen
        os_hardware = os.name

        # Schnittstelle und Index basierend auf dem Betriebssystem auswählen
        if os_hardware == "nt":  # Für Windows
            interface = "WLAN"
            index = 1
        elif os_hardware == "posix":  # Für Linux/Mac
            interface = "en0"  # Ethernet oder Wi-Fi Schnittstelle
            index = 0

        # Alle verfügbaren Netzwerkschnittstellen und Adressen abrufen
        addresses = psutil.net_if_addrs()

        # Schnittstellen und deren Adressen prüfen
        for intface, addr_list in addresses.items():
            if intface == interface:  # Wenn die Schnittstelle übereinstimmt
                # Nach IPv4-Adresse suchen (index 0 für MacOS)
                ip_adress = addr_list[index][1]
                return ip_adress  # IP-Adresse zurückgeben
    except Exception as e:
        print(f"Fehler beim Abrufen der IP-Adresse: {e}")
        return None


def get_broadcast_ip():
    try:
        # Lokale IP-Adresse abrufen
        ip_address = get_ip_adress()
        if not ip_address:
            raise ValueError("IP-Adresse konnte nicht abgerufen werden.")

        # Standard-Subnetzmaske verwenden
        mask = socket.inet_ntoa(socket.inet_aton('255.255.255.0'))

        # IP-Adresse und Subnetzmaske in Integer-Werte umwandeln
        ip_parts = list(map(int, ip_address.split('.')))
        mask_parts = list(map(int, mask.split('.')))

        # Broadcast-Adresse berechnen
        broadcast_parts = [ip_parts[i] | (~mask_parts[i] & 255) for i in range(4)]
        broadcast_ip = '.'.join(map(str, broadcast_parts))

        return broadcast_ip
    except Exception as e:
        print(f"Fehler beim Berechnen der Broadcast-Adresse: {e}")
        return None

#############################################################################################################################
# Test
if __name__ == "__main__":
    # Standardausgabe in die Datei umleiten
    with open("Debug.txt", "w") as debug_file:
        sys.stdout = debug_file  # Umleitung der Standardausgabe
        try:
            print("=========================================")
            print("functions.py")
            print("Lokale IP-Adresse:", get_ip_adress())
            print("Broadcast-IP-Adresse:", get_broadcast_ip())
            print("=========================================")
        except Exception as e:
            print(f"Fehler während der Debug-Ausgabe: {e}")
        finally:
            sys.stdout = sys.__stdout__  # Standardausgabe zurücksetzen