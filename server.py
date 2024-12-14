# Bibliothek
import concurrent.futures # Zum Verwalten von Thread-Pools
import socket # Bereitstellung von Netzwerkkommunikationsschnittstellen
import threading # Ermöglicht Multithreading
import json # Um mit JSON-Daten zu arbeiten
import time # Arbeiten mit Zeitoperationen
import uuid # Zum Generieren eindeutiger Identifikatoren
import struct # Packen und Entpacken von Daten für die Netzwerkübertragung
from functions import get_ip_adress # Funktion zum Abrufen der lokalen IP-Adresse
from functions import get_broadcast_ip # Funktion zur Berechnung der Broadcast-Adresse

#############################################################################################################################
# Konstanten
BUFFER_SIZE = 1024 # Maximale Größe für eingehende Nachrichten
MULTICAST_BUFFER_SIZE = 10240  # Puffergröße für Multicast-Nachrichten
IP_ADDRESS = get_ip_adress() # Lokale IP-Adresse abrufen

BROADCAST_ADDRESS = get_broadcast_ip() # Berechnet die Broadcast-Adresse
BROADCAST_PORT_CLIENT = 50000  # Port für Client-Broadcast-Anfragen
BROADCAST_PORT_SERVER = 60000 # Port für Server-Broadcast-Kommunikation
TCP_CLIENT_PORT = 50510  # Port für eingehende TCP-Verbindungen

MULTICAST_PORT_CLIENT = 50550  # Port für ausgehende Multicast-Nachrichten
MULTICAST_GROUP_ADDRESS = '224.1.2.2'  # Multicast-Gruppenadresse
MULTICAST_TTL = 2 # Time-To-Live für Multicast-Pakete

LCR_PORT = 60600 # Port für Leaderwahl (LCR)
LEADER_DEATH_TIME = 20 # Zeit (in Sekunden), nach der ein Leader als tot gilt

HEARTBEAT_PORT_SERVER = 60570  # Port für Heartbeat-Nachrichten

#############################################################################################################################
# Hauptprogramm

class Server:
    def __init__(self):
        """
        Initialisiert den Server und setzt Standardwerte.
        """
        self.shutdown_event = threading.Event() # Ereignis, um den Server herunterzufahren
        self.threads = [] # Liste der aktiven Threads
        self.server_uuid = None # UUID des Servers
        self.list_of_known_servers = [] # Liste der bekannten Server
        self.client_list = [] # Liste der verbundenen Clients
        self.lcr_ongoing = False # Status, ob eine Leaderwahl läuft
        self.is_leader = False # Gibt an, ob dieser Server der Leader ist
        self.last_message_from_leader_ts = time.time() # Zeit der letzten Leadernachricht
        self.direct_neighbour = '' # UUID des direkten Nachbarn im Ring
        self.ip_direct_neighbour = '' # IP-Adresse des direkten Nachbarn
        self.leader = '' # UUID des aktuellen Leaders
        self.ip_leader = '' # IP-Adresse des aktuellen Leaders
        self.lock = threading.Lock() # Lock für Thread-sicheren Zugriff
        self.participant = False # Gibt an, ob dieser Server an einer Leaderwahl teilnimmt

    def start_server(self):
        """
        Startet den Server und initialisiert Threads für verschiedene Aufgaben.
        """
        self.server_uuid = str(uuid.uuid4()) # UUID des Servers generieren

        # Threads starten
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            methods = [
                self.handle_broadcast_server_requests, # Bearbeitung von Broadcast-Anfragen anderer Server
                self.lcr, # Leaderwahl durchführen
                self.handle_leader_heartbeat, # Verarbeiten von Heartbeat-Nachrichten
                self.detection_of_missing_or_dead_leader, # Erkennen eines fehlenden Leaders
                self.handle_broadcast_client_requests, # Bearbeitung von Broadcast-Anfragen von Clients
                self.handle_send_message_request # Bearbeitung von Client-Nachrichten
            ]

            for method in methods:
                self.threads.append(executor.submit(self.run_with_exception_handling, method))

            print('Server started')

            try:
                # Hauptthread aktiv halten, bis ein Shutdown ausgelöst wird
                while not self.shutdown_event.is_set():
                    self.shutdown_event.wait(1)
            except KeyboardInterrupt:
                print("Server shutdown initiated.")
                self.shutdown_event.set()
                for thread in self.threads:
                    thread.cancel()
            finally:
                executor.shutdown(wait=True)

    def run_with_exception_handling(self, target):
        """
        Führt die Zielmethode mit Fehlerbehandlung aus.
        """
        try:
            target()
        except Exception as e:
            print(f"Error in thread {target.__name__}: {e}")

  # Client-Kommunikation
    def handle_broadcast_client_requests(self):
        """
        Verarbeitet Broadcast-Anfragen von Clients, z. B. zur Erkennung von Servern.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener_socket:
                listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener_socket.bind(('', BROADCAST_PORT_CLIENT)) # Port binden
                listener_socket.settimeout(1) # Timeout setzen

                while not self.shutdown_event.is_set(): # Empfangene Nachricht dekodieren
                    if self.is_leader: # Nur der Leader antwortet auf Broadcasts
                        try:
                            data, client_ip = listener_socket.recvfrom(BUFFER_SIZE)
                            

                            json_message = json.loads(data)
                            print(f"Server discovery request by {json_message['client_uuid']}")

                            current_client = {}
                            current_client['client_uuid'] = json_message['client_uuid']
                            current_client['client_ip'] = json_message['client_ip']
                            current_client['select_client_uuid'] = ''

                            # Prüfen, ob der Client neu ist
                            new_client = True
                            for client in self.client_list:
                                if client['client_uuid'] == current_client['client_uuid']:
                                    new_client = False

                            # Antwort an den Client senden
                            if new_client:
                                self.client_list.append(current_client)

                            response_message = f'hello from server {self.server_uuid}'.encode()
                            listener_socket.sendto(response_message, client_ip)
                            print("Sent server hello to client: " + current_client["client_uuid"])
                        except socket.timeout:
                            continue
                        except Exception as e:
                            print(f"Error handling broadcast client request: {e}")
        except Exception as e:
            print(f"Failed to open Socket for handling client Broadcast requests: {e}")

    def handle_send_message_request(self):
        """
        Bearbeitet eingehende TCP-Nachrichten von Clients und führt entsprechende Aktionen aus.
        """
        while not self.shutdown_event.is_set():
            if self.is_leader: # Nur der Leader bearbeitet diese Anfragen
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
                    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    server_socket.bind((IP_ADDRESS, TCP_CLIENT_PORT)) # Server-Socket binden
                    server_socket.listen() # Eingehende Verbindungen abhören

                    client_socket, addr = server_socket.accept() # Verbindung akzeptieren
                    with client_socket:
                        try:
                            data = client_socket.recv(BUFFER_SIZE) # Nachricht empfangen
                            client_response_msg = ''
                            if data:
                                json_data = json.loads(data.decode('UTF-8')) # Nachricht dekodieren
                                print(f"Received message {json_data}")

                                # Nachricht basierend auf Funktion verarbeiten
                                if json_data['function'] == 'get_clients':
                                    client_response_msg = self.get_clients(json_data['client_uuid'])
                                elif json_data['function'] == 'select_client':
                                    if json_data['select_client_uuid'] != '':
                                        client_response_msg = self.select_client(json_data['client_uuid'], json_data['select_client_uuid'])
                                    else:
                                        client_response_msg = 'The selected client is not available'
                                elif json_data['function'] == 'send_message':
                                    if json_data['msg']:
                                        client_response_msg = self.send_message(json_data['client_uuid'], json_data['msg'])
                                    else:
                                        client_response_msg = "No message received to submit"
                                else:
                                    client_response_msg = "Received invalid data object"

                                # Antwort an den Client senden
                                client_socket.sendall(client_response_msg.encode('UTF-8', errors='replace'))
                        finally:
                            client_socket.close() # Socket schließen

    def get_clients(self, client_uuid):
        """
        Gibt eine Liste aller verbundenen Clients (außer dem aktuellen) zurück.
        """
        clients = ''
        counter = 1
        for client in self.client_list:
            if client['client_uuid'] != client_uuid:
                client_str = f"{counter} - {client['client_uuid']}\n"
                clients = clients + client_str
                counter += 1
 
        if clients == '':
            return "No other clients connected"
        else:
            return clients
        
    def select_client(self, client_uuid, select_client_uuid):
        """
        Markiert einen bestimmten Client als ausgewählten Chat-Partner.
        """
        for client in self.client_list:
            if client['client_uuid'] == client_uuid:
                client['select_client_uuid'] = select_client_uuid
                break

        return "Client selected"

    def send_message(self, client_uuid, message):
        """
        Sendet eine Nachricht an einen zuvor ausgewählten Client.
        """
        is_client_selected = False
        select_client_uuid = ''
        for client in self.client_list:
            if client['client_uuid'] == client_uuid:
                if client['select_client_uuid'] != '':
                    is_client_selected = True
                    select_client_uuid = client['select_client_uuid']
                    break

        if is_client_selected:
            self.forward_message_select_client(select_client_uuid, message, client_uuid)
            return f'Message to {select_client_uuid} sent'

        return "First select a client to chat with"

    def forward_message_select_client(self, receiver, msg, sender):
        """
        Leitet eine Nachricht über Multicast an den ausgewählten Client weiter.
        """
        client_multicast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        client_multicast_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
        send_message = f'{sender}: {msg}'.encode('UTF-8')

        try:
            for client in self.client_list:
                if client['client_uuid'] == receiver:
                    client_multicast_socket.sendto(send_message, (client['client_ip'], MULTICAST_PORT_CLIENT))
        except Exception as e:
            print(f"Error sending message to chat participants: {e}")
        finally:
            client_multicast_socket.close()

 #  Server-Verbindung
    def send_broadcast_to_search_for_servers(self):
        """
        Sendet eine Broadcast-Nachricht, um andere Server im Netzwerk zu suchen.
        """
        print('Sending server discovery message via broadcast')
        with self.lock:
            server = {}
            server['server_uuid'] = self.server_uuid
            server['server_ip'] = IP_ADDRESS
            self.list_of_known_servers.clear()
            self.list_of_known_servers.append(server)

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as broadcast_server_discovery_socket:
                broadcast_server_discovery_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                json_message = json.dumps({"server_uuid": str(self.server_uuid), "server_ip": str(IP_ADDRESS)})
                broadcast_server_discovery_socket.sendto(json_message.encode('utf-8'), (BROADCAST_ADDRESS, BROADCAST_PORT_SERVER))

                broadcast_server_discovery_socket.settimeout(3)
                while True:
                    try:
                        response, addr = broadcast_server_discovery_socket.recvfrom(BUFFER_SIZE)
                        response_message = json.loads(response)
                        print('Received server discovery answer from ' + response_message['server_uuid'])

                        check_server_not_in_list = True
                        for known_server in self.list_of_known_servers:
                            if response_message['server_uuid'] == known_server['server_uuid']:
                                check_server_not_in_list = False

                        if check_server_not_in_list:
                            server = {}
                            server['server_uuid'] = response_message['server_uuid']
                            server['server_ip'] = response_message['server_ip']
                            self.list_of_known_servers.append(server)

                    except socket.timeout:
                        print('No more responses, ending wait')
                        break
                    except Exception as e:
                        print(f'Error receiving response: {e}')
                        break
        except Exception as e:
            print(f'Failed to send broadcast message: {e}')

    def handle_broadcast_server_requests(self):
        """
        Bearbeitet eingehende Broadcast-Anfragen von anderen Servern.
        """
        print('Starting to listen for broadcast server requests')

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener_socket:
                listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener_socket.bind(('', BROADCAST_PORT_SERVER)) # Port für eingehende Broadcasts binden
                listener_socket.settimeout(1)

                while not self.shutdown_event.is_set():
                    try:
                        msg, addr = listener_socket.recvfrom(BUFFER_SIZE)
                        json_message = json.loads(msg) # Empfangene Nachricht dekodieren
                        print('Received server discovery message via broadcast')

                        check_server_not_in_list = True
                        for known_server in self.list_of_known_servers:
                            if json_message['server_uuid'] == known_server['server_uuid']:
                                check_server_not_in_list = False

                        if check_server_not_in_list:
                            server = {}
                            server['server_uuid'] = json_message['server_uuid']
                            server['server_ip'] = json_message['server_ip']
                            self.list_of_known_servers.append(server)

                        response_message= json.dumps({"server_uuid": str(self.server_uuid), "server_ip": str(IP_ADDRESS)}).encode() 
                        listener_socket.sendto(response_message, addr)
                        print('Sent server hello to ' + json_message['server_uuid'])

                    except socket.timeout:
                        continue
                    except socket.error as e:
                        print(f'Socket error: {e}')
                    except Exception as e:
                        print(f'Unexpected error: {e}')

        except socket.error as e:
            print(f'Failed to set up listener socket: {e}')

  # Leaderwahl
    def detection_of_missing_or_dead_leader(self):
        """
        Erkennung eines fehlenden oder toten Leaders und Einleitung der Leaderwahl.
        """
        print('Starting detection of missing or dead leader')
        while not self.shutdown_event.is_set():
            time.sleep(3) # Alle 3 Sekunden prüfen
            if not self.is_leader and not self.lcr_ongoing:
                if (time.time() - self.last_message_from_leader_ts) >= LEADER_DEATH_TIME:
                    print('No active leader detected')
                    self.start_lcr()

    def form_ring(self):
        """
        Bildet einen logischen Ring mit bekannten Servern basierend auf deren UUIDs.
        """
        print('Forming ring with list of known servers')
        try:
            uuid_list = []
            for server in self.list_of_known_servers:
                uuid_list.append(uuid.UUID(server['server_uuid']))

            uuid_list.sort() # Sortiere die UUIDs, um einen Ring zu bilden

            uuid_ring = []
            for server in uuid_list:
                uuid_ring.append(str(server))
            
            print(f'Ring formed: {uuid_ring}')
            return uuid_ring
        except socket.error as e:
            print(f'Failed to form ring: {e}')
            return []
        
    def get_direct_neighbour(self):
        """
        Findet den direkten Nachbarn im logischen Ring basierend auf der UUID.
        """
        print('Preparing to get direct neighbour')
        self.direct_neighbour = ''
        try:
            ring = self.form_ring() # Logischen Ring der Server basierend auf ihren UUIDs bilden

            if self.server_uuid in ring:
                index = ring.index(self.server_uuid) # Finde die Position der eigenen UUID im Ring
                direct_neighbour = ring[(index + 1) % len(ring)] # Finde die nächste UUID im Ring (zyklisch)

                # Wenn ein Nachbar gefunden wurde, der nicht der Server selbst ist
                if direct_neighbour and direct_neighbour != self.server_uuid:
                    self.direct_neighbour = direct_neighbour # Speichere die UUID des direkten Nachbarn
                    
                    # Finde die IP-Adresse des direkten Nachbarn
                    for server in self.list_of_known_servers:
                        if server['server_uuid'] == self.direct_neighbour:
                            self.ip_direct_neighbour = server['server_ip']

                    print(f'Direct neighbour: {self.direct_neighbour}')
            else:
                print(f'Ring is not complete!') # Warnung, falls der Ring unvollständig ist
        except Exception as e:
            print(f'Failed to get direct neighbour: {e}') # Fehler beim Abrufen des Nachbarn

    def start_lcr(self):
        """
        Startet den Leaderwahlprozess (LCR-Algorithmus).
        """
        print('Starting leader election')
        retry = 3 # Anzahl der Versuche, den direkten Nachbarn zu finden
        while retry > 0:
            self.send_broadcast_to_search_for_servers() # Senden einer Broadcast-Nachricht, um Server zu entdecken
            time.sleep(8) # Warte auf Antworten
            self.get_direct_neighbour() # Finde den direkten Nachbarn
            if not self.direct_neighbour == '':
                break # Beende die Schleife, wenn ein Nachbar gefunden wurde
            retry -= 1

        # Wenn ein Nachbar gefunden wurde, starte die Wahl
        if not self.direct_neighbour == '':
            lcr_start_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                # Sende eine Nachricht zur Einleitung der Leaderwahl an den Nachbarn
                election_message = {"mid": self.server_uuid, "isLeader": False}
                message = json.dumps(election_message).encode()
                lcr_start_socket.sendto(message, (self.ip_direct_neighbour, LCR_PORT))
                with self.lock:
                    self.lcr_ongoing = True # Markiere, dass eine Leaderwahl läuft
                    self.is_leader = False
                    self.participant = False
                print(f'LCR start message sent to {self.direct_neighbour}')
            except socket.error as e:
                print('Socket error occurred in start_lcr', e)
            finally:
                lcr_start_socket.close()
        else:
            # Wenn keine Nachbarn gefunden wurden, wird der Server selbst Leader
            print('Assuming to be the only active server - assigning as leader')
            with self.lock:
                self.is_leader = True
                self.participant = False
                self.lcr_ongoing = False

    def lcr(self):
        """
        Führt den LCR-Algorithmus durch, um den Leader im Netzwerk zu bestimmen.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as lcr_listener_socket:
            lcr_listener_socket.bind((IP_ADDRESS, LCR_PORT)) # Binde den Socket an den LCR-Port
            while not self.shutdown_event.is_set():
                data, address = lcr_listener_socket.recvfrom(BUFFER_SIZE) # Empfange Wahl-Nachricht
                with self.lock:
                    election_message = json.loads(data.decode()) # Dekodiere die Nachricht

                    if election_message['isLeader']:
                      # Wenn die Nachricht einen Leader bestätigt
                        leader_uuid = election_message['mid']
                        if leader_uuid != self.server_uuid:
                            print(f'{self.server_uuid}: Leader was elected! {election_message["mid"]}')
                            lcr_listener_socket.sendto(json.dumps(election_message).encode(),
                                                       (self.ip_direct_neighbour, LCR_PORT)) # Nachricht weiterleiten
                            self.leader = leader_uuid

                            # Speichere die IP-Adresse des Leaders
                            for server in self.list_of_known_servers:
                                if server['server_uuid'] == self.leader:
                                    self.ip_leader = server['server_ip']

                            self.is_leader = False # Markiere sich selbst nicht als Leader
                        self.participant = False
                        self.lcr_ongoing = False

                    elif uuid.UUID(election_message['mid']) < uuid.UUID(self.server_uuid) and not self.participant:
                        # Wenn die eigene UUID größer ist, sende eine neue Nachricht
                        new_election_message = {"mid": self.server_uuid, "isLeader": False}
                        self.participant = True
                        lcr_listener_socket.sendto(json.dumps(new_election_message).encode(),
                                                   (self.ip_direct_neighbour, LCR_PORT))

                    elif uuid.UUID(election_message['mid']) > uuid.UUID(self.server_uuid):
                        # Leite Nachricht weiter, wenn sie von einer größeren UUID stammt
                        self.participant = False
                        lcr_listener_socket.sendto(json.dumps(election_message).encode(),
                                                   (self.ip_direct_neighbour, LCR_PORT))
                    elif election_message['mid'] == self.server_uuid:
                        # Wenn die eigene UUID die größte ist, wird man selbst Leader
                        new_election_message = {"mid": self.server_uuid, "isLeader": True}
                        lcr_listener_socket.sendto(json.dumps(new_election_message).encode(),
                                                   (self.ip_direct_neighbour, LCR_PORT))
                        self.leader = self.server_uuid
                        self.ip_leader = IP_ADDRESS
                        self.is_leader = True
                        self.participant = False
                        self.lcr_ongoing = False
                        print(f'Current node won leader election! {self.server_uuid} (sent message to {self.direct_neighbour} )')
                    else:
                        print(f'Unexpected event occurred in LCR {election_message}')

    def handle_leader_heartbeat(self):
        """
        Verarbeitet Heartbeat-Nachrichten vom Leader und aktualisiert Client-Daten.
        """
        # Erstelle einen UDP-Socket für den Empfang von Heartbeat-Nachrichten
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as heartbeat_server_socket:
            heartbeat_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            heartbeat_server_socket.bind(('', HEARTBEAT_PORT_SERVER)) # Binde den Socket an den Heartbeat-Port

            # Binde den Socket an den Heartbeat-Port
            group = socket.inet_aton(MULTICAST_GROUP_ADDRESS)
            mreq = struct.pack('4sL', group, socket.INADDR_ANY)
            heartbeat_server_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            heartbeat_server_socket.settimeout(2) # Timeout für das Warten auf Nachrichten

            try:
              # Empfange Heartbeat-Nachricht vom Leader
                while not self.shutdown_event.is_set(): # Solange kein Shutdown ausgelöst wird
                    if self.is_leader:
                        self.send_leader_heartbeat() # Sende Heartbeat, wenn dieser Server der Leader ist
                        continue
                    try:
                        # Empfange Heartbeat-Nachricht vom Leader
                        data, addr = heartbeat_server_socket.recvfrom(MULTICAST_BUFFER_SIZE)
                        data = json.loads(data.decode()) # Dekodiere die Nachricht
                        self.client_list = data['client_data'] # Aktualisiere die Client-Daten
                        print('Received heartbeat from leader server and updated client data send by leader server')

                        # Falls die IP des Leaders nicht bekannt ist, speichere sie
                        if not self.ip_leader:
                            self.leader = data['server_uuid']
                            self.ip_leader = addr[0]
                        # Aktualisiere den Zeitstempel der letzten Heartbeat-Nachricht
                        with self.lock:
                            self.last_message_from_leader_ts = time.time()
                    except socket.timeout:
                        continue # Timeout, erneut auf Nachricht warten
                    except socket.error as e:
                        print('Socket error occurred while receiving heartbeat: {e}')
                    except Exception as e:
                        print(f'Unexpected error occurred: {e}')
            finally:
                print('Shutting down heartbeat listener')

    def send_leader_heartbeat(self):
        """
        Sendet Heartbeat-Nachrichten vom Leader an die Multicast-Gruppe.
        """
        # Erstelle einen UDP-Socket für das Senden der Heartbeat-Nachricht
        heartbeat_client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        heartbeat_client_socket.settimeout(1) # Setze Timeout für den Socket
        try:
            print('Sending heartbeat and client data')
            # Erstelle die Payload für die Heartbeat-Nachricht
            payload = {}
            payload['server_uuid'] = self.server_uuid # UUID des Leaders
            payload['client_data'] = self.client_list # Aktuelle Client-Daten
            print(payload) # Debug-Ausgabe der Nachricht
            message = json.dumps(payload).encode() # Kodierung der Nachricht
            heartbeat_client_socket.sendto(message, (MULTICAST_GROUP_ADDRESS, HEARTBEAT_PORT_SERVER))

            time.sleep(2) # Kurze Pause, bevor der nächste Heartbeat gesendet wird
        except socket.error as e:
            print(f"Socket error: {e}") # Fehler beim Senden
        except Exception as e:
            print(f"Error: {e}") # Allgemeiner Fehler
        finally:
            heartbeat_client_socket.close() # Schließe den Socket