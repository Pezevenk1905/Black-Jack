# Bibliothek
import sys # Ermöglicht den Zugriff auf systembezogene Parameter und Funktionen
import threading # Bietet Unterstützung für Multithreading, um parallele Aufgaben auszuführen
from client import Client # Importiert die Klasse 'Client' aus der Datei 'client.py'

#############################################################################################################################
# Hauptprogramm
if __name__ == "__main__":
    client = Client() # Erstellt eine Instanz der Client-Klasse
    client.start_client() # Startet den Client, der in der 'Client'-Klasse definiert ist