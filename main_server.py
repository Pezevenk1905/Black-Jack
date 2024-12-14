# Bibliothek
import sys # Ermöglicht den Zugriff auf systembezogene Parameter und Funktionen
import threading # Bietet Unterstützung für Multithreading, um parallele Aufgaben auszuführen
from server import Server # Importiert die Klasse 'Server' aus der Datei 'server.py'

#############################################################################################################################
# Hauptprogramm
if __name__ == "__main__":
    server = Server() # Erstellt eine Instanz der Server-Klasse
    server.start_server() # Startet den Server, der in der 'Server'-Klasse definiert ist