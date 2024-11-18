import socket
import threading
import pickle
import hashlib
import os

HOST = '10.38.2.108'
PORT = 6000
BUFFER_SIZE = 1024
STORAGE_DIR = "tracker_storage"
TORRENT_DIR = "torrents"
PEERLIST_DIR = "peers"

def generate_torrent_file(filename, file_size):
    piece_size = BUFFER_SIZE
    num_pieces = (file_size + piece_size - 1) // piece_size
    hashes = []

    with open(filename, "rb") as f:
        for _ in range(num_pieces):
            piece = f.read(piece_size)
            piece_hash = hashlib.sha1(piece).hexdigest()
            hashes.append(piece_hash)
    
    torrent_data = {
        "filename": os.path.basename(filename),
        "file_size": file_size,
        "piece_size": piece_size,
        "hashes": hashes,
    }

    os.makedirs(TORRENT_DIR, exist_ok=True)
    torrent_path = os.path.join(TORRENT_DIR, f"{os.path.basename(filename)}.torrent")

    with open(torrent_path, "wb") as torrent_file:
        pickle.dump(torrent_data, torrent_file)
    
    return torrent_path

def register_peer(filename, peer_address):
    os.makedirs(PEERLIST_DIR, exist_ok=True)
    peerlist_path = os.path.join(PEERLIST_DIR, f"{filename}.peers")

    if os.path.exists(peerlist_path):
        with open(peerlist_path, "rb") as peerlist_file:
            peer_list = pickle.load(peerlist_file)
    else:
        peer_list = []

    if peer_address not in peer_list:
        peer_list.append(peer_address)
    print(peer_list)
    with open(peerlist_path, "wb") as peerlist_file:
        pickle.dump(peer_list, peerlist_file)

def deregister_peer(peer_address):
    """Remove the given peer from all peer lists."""
    for filename in os.listdir(PEERLIST_DIR):
        peerlist_path = os.path.join(PEERLIST_DIR, filename)
        
        with open(peerlist_path, "rb") as peerlist_file:
            peer_list = pickle.load(peerlist_file)
        
        if peer_address in peer_list:
            peer_list.remove(peer_address)
            print(f"[-] Removed {peer_address} from peer list of {filename}")

        with open(peerlist_path, "wb") as peerlist_file:
            pickle.dump(peer_list, peerlist_file)

def start_tracker():
    os.makedirs(STORAGE_DIR, exist_ok=True)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, PORT))
    server_socket.listen(5)
    print(f"[*] Tracker server running at {HOST}:{PORT}")

    while True:
        client_socket, address = server_socket.accept()
        print(f"[+] Client {address} connected.")

        try:
            data = pickle.loads(client_socket.recv(4096))

            if data['command'] == 'upload':
                filename = data['filename']
                filesize = data['filesize']
                client_ip = data['client_ip']
                client_port = data['port']

                client_socket.send(b"Ready to receive file data")
                file_path = os.path.join(STORAGE_DIR, filename)

                with open(file_path, "wb") as f:
                    received_size = 0
                    while received_size < filesize:
                        chunk = client_socket.recv(BUFFER_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        received_size += len(chunk)

                print(f"[+] File '{filename}' uploaded and saved.")

                torrent_path = generate_torrent_file(file_path, filesize)
                register_peer(filename, (client_ip, client_port))
                client_socket.send(b"File upload completed")

            elif data['command'] == 'download':
                filename = data['filename']
                torrent_path = os.path.join(TORRENT_DIR, f"{filename}.torrent")
                peerlist_path = os.path.join(PEERLIST_DIR, f"{filename}.peers")

                if os.path.exists(torrent_path) and os.path.exists(peerlist_path):
                    with open(torrent_path, "rb") as torrent_file:
                        torrent_data = torrent_file.read()
                        client_socket.send(torrent_data)  

                    ack = client_socket.recv(1024)
                    if ack == b"Received Torrent":
                        with open(peerlist_path, "rb") as peerlist_file:
                            peerlist_data = peerlist_file.read()
                            client_socket.send(peerlist_data)  

                    print(f"[+] Sent torrent and peer list for '{filename}' to client.")
                else:
                    client_socket.send(b"File not found")
                    
            elif data['command'] == 'completed_download':
                filename = data['filename']
                client_ip = data['client_ip']
                client_port = data['client_port']
                print("po")
                register_peer(filename, (client_ip, client_port))
                client_socket.send(b"Successfully added to peer list")
                print(f"[Tracker] Registered client {client_ip}:{client_port} as peer for '{filename}'.")
            elif data['command'] == 'client_offline':
                client_ip = data['client_ip']
                client_port = data['client_port']
                deregister_peer((client_ip, client_port))
                client_socket.send(b"Offline notification received.")
                print(f"[+] Client {client_ip}:{client_port} went offline.")

        except Exception as e:
            print(f"[-] Error: {e}")
        
        client_socket.close()

if __name__ == "__main__":
    tracker_thread = threading.Thread(target=start_tracker)
    tracker_thread.start()