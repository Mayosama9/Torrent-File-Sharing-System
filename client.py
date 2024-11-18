import socket
import threading
import pickle
import hashlib
import os
import atexit

# [guid]::NewGuid()
UUID='6e7e0db6-fcd5-4f60-b781-ea2dc4dc67e0'
TRACKER_HOST = '10.38.2.108'
TRACKER_PORT = 6000
BUFFER_SIZE = 1024
CLIENT_PORT = 7001
DOWNLOADS_DIR = "downloads"

def notify_tracker_offline():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tracker_socket:
            tracker_socket.connect((TRACKER_HOST, TRACKER_PORT))
            offline_message = {
                "command": "client_offline",
                "client_ip": socket.gethostbyname(socket.gethostname()),
                "client_port": CLIENT_PORT
            }
            print(offline_message)
            tracker_socket.send(pickle.dumps(offline_message))
            print("[*] Notified tracker that client is going offline.")
    except Exception as e:
        print(f"[-] Failed to notify tracker: {e}")


def notify_tracker_of_download(filename):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tracker_socket:
            tracker_socket.connect((TRACKER_HOST, TRACKER_PORT))
            notification_data = {
                "command": "completed_download",
                "filename": filename,
                "client_ip": socket.gethostbyname(socket.gethostname()),
                "client_port": CLIENT_PORT
            }
            tracker_socket.send(pickle.dumps(notification_data))
            response = tracker_socket.recv(1024).decode()
            print(f"[Tracker] {response}")
    except Exception as e:
        print(f"[-] Error notifying tracker: {e}")

def upload_file(filename):
    file_path = os.path.join(DOWNLOADS_DIR, filename)
    file_size = os.path.getsize(file_path)
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tracker_socket:
        tracker_socket.connect((TRACKER_HOST, TRACKER_PORT))
        data = {
            "command": "upload",
            "filename": filename,
            "filesize": file_size,
            "client_ip": socket.gethostbyname(socket.gethostname()),
            "port": CLIENT_PORT
        }
        tracker_socket.send(pickle.dumps(data))

        if tracker_socket.recv(1024) == b"Ready to receive file data":
            with open(file_path, "rb") as f:
                while (chunk := f.read(BUFFER_SIZE)):
                    tracker_socket.send(chunk)

            print(tracker_socket.recv(1024).decode())  



def receive_all(sock, size):
    data = b""
    while len(data) < size:
        packet = sock.recv(size - len(data))
        if not packet:
            break
        data += packet
    return data


downloaded_pieces = {}
download_lock = threading.Lock()  

def download_piece(piece_num, piece_hash, peer_list, filename, file_path):
    piece_downloaded = False
    start_peer_index = piece_num % len(peer_list)  
    
    for i in range(len(peer_list)):
        peer_index = (start_peer_index + i) % len(peer_list)
        peer = peer_list[peer_index]

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as peer_socket:
                peer_socket.connect(peer)
                request = {"command": "download_piece", "filename": filename, "piece_num": piece_num}
                peer_socket.send(pickle.dumps(request))

                piece_data = receive_all(peer_socket, BUFFER_SIZE)
                
                if hashlib.sha1(piece_data).hexdigest() == piece_hash:
                    with download_lock:
                        if piece_num not in downloaded_pieces:  
                            with open(file_path, "r+b") as f:
                                f.seek(piece_num * BUFFER_SIZE)
                                f.write(piece_data)
                            downloaded_pieces[piece_num] = True
                            print(f"[+] Downloaded and verified piece {piece_num} from {peer}.")
                            piece_downloaded = True
                            break
                else:
                    print(f"[-] Piece {piece_num} from {peer} failed verification.")
        except Exception as e:
            print(f"[-] Failed to download piece {piece_num} from {peer}: {e}")
    
    if not piece_downloaded:
        print(f"[!] Could not download piece {piece_num} from any peer.")
    return piece_downloaded

def download_file(filename):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tracker_socket:
        tracker_socket.connect((TRACKER_HOST, TRACKER_PORT))
        request_data = {"command": "download", "filename": filename}
        tracker_socket.send(pickle.dumps(request_data))

        torrent_data = tracker_socket.recv(4096)
        if not torrent_data or torrent_data == b"File not found":
            print("[-] File not found on tracker.")
            return

        tracker_socket.send(b"Received Torrent")
        peerlist_data = tracker_socket.recv(4096)

        torrent_info = pickle.loads(torrent_data)
        peer_list = pickle.loads(peerlist_data)

        file_path = os.path.join(DOWNLOADS_DIR, filename)
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        
        with open(file_path, "wb") as f:
            f.truncate(torrent_info["file_size"])

        global downloaded_pieces
        downloaded_pieces = {}

        threads = []
        for piece_num, piece_hash in enumerate(torrent_info["hashes"]):
            thread = threading.Thread(target=download_piece, args=(piece_num, piece_hash, peer_list, filename, file_path))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        if len(downloaded_pieces) == len(torrent_info["hashes"]):
            print(f"[+] File '{filename}' downloaded and verified successfully.")
            notify_tracker_of_download(filename)
        else:
            print("[-] Download incomplete: some pieces could not be downloaded.")


def handle_peer_request(peer_socket):
    try:
        request_data = pickle.loads(peer_socket.recv(1024))
        if request_data["command"] == "download_piece":
            filename = request_data["filename"]
            piece_num = request_data["piece_num"]
            file_path = os.path.join(DOWNLOADS_DIR, filename)

            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    f.seek(piece_num * BUFFER_SIZE)
                    piece_data = f.read(BUFFER_SIZE)
                    peer_socket.send(piece_data)
                print(f"[+] Sent piece {piece_num} of '{filename}' to peer.")
            else:
                peer_socket.send(b"File or piece not available")
    except Exception as e:
        print(f"[-] Error handling peer request: {e}")
    finally:
        peer_socket.close()

def start_peer_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('0.0.0.0', CLIENT_PORT))
    server_socket.listen(5)
    print(f"[+] Peer server running on port {CLIENT_PORT}.")

    while True:
        peer_socket, address = server_socket.accept()
        print(f"[+] Connection from peer {address}.")
        threading.Thread(target=handle_peer_request, args=(peer_socket,)).start()

def main():
    peer_server_thread = threading.Thread(target=start_peer_server, daemon=True)
    peer_server_thread.start()

    while True:
        action = input("Enter 'upload' to upload a file or 'download' to download a file: ").strip().lower()
        
        if action == 'upload':
            filename = input("Enter the filename: ").strip()
            upload_file(filename)
        elif action == 'download':
            filename = input("Enter the filename: ").strip()
            download_file(filename)
        elif action == 'exit':
            break

if __name__ == "__main__":
    main()

atexit.register(notify_tracker_offline)
