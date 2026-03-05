#!/usr/bin/env python3
import socket
import threading
import paramiko
import sqlite3
import datetime
import smtplib
from email.mime.text import MIMEText

# ---------------------------
# CONFIG
# ---------------------------
HOST = "0.0.0.0"
PORT = 2223

DB_FILE = "honeypot.db"

EMAIL_FROM = "arkoaugustin26@gmail.com"
EMAIL_TO = "01876164154@sms.robi.com.bd"
EMAIL_PASS = "wylcjnmqhlysgiby"

# ---------------------------
# DATABASE SETUP
# ---------------------------
def db_init():
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS auth_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            ip TEXT,
            username TEXT,
            password TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            ip TEXT,
            command TEXT
        )
    """)
    con.commit()
    con.close()

def log_auth(ip, user, passwd):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    ts = datetime.datetime.utcnow().isoformat()+"Z"
    cur.execute("INSERT INTO auth_attempts (timestamp, ip, username, password) VALUES (?, ?, ?, ?)",
                (ts, ip, user, passwd))
    con.commit()
    con.close()

def log_cmd(ip, cmd):
    con = sqlite3.connect(DB_FILE)
    cur = con.cursor()
    ts = datetime.datetime.utcnow().isoformat()+"Z"
    cur.execute("INSERT INTO commands (timestamp, ip, command) VALUES (?, ?, ?)",
                (ts, ip, cmd))
    con.commit()
    con.close()

# ---------------------------
# EMAIL ALERT
# ---------------------------
def send_alert(ip, username, password):
    try:
        msg = MIMEText(f"[HONEYPOT]\nIP: {ip}\nUSER: {username}\nPASS: {password}")
        msg["Subject"] = f"Honeypot Login Attempt from {ip}"
        msg["From"] = EMAIL_FROM
        msg["To"] = EMAIL_TO

        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        server.quit()
        print("[+] Alert email sent")
    except Exception as e:
        print("[!] Email error:", e)

# ---------------------------
# FAKE SHELL
# ---------------------------
def fake_output(cmd):
    if cmd in ["ls", "dir"]:
        return "fake_file.txt\nhoneypot.log\nsystem.conf"
    if cmd.startswith("cat"):
        return "This is a honeypot. All your actions are logged."
    if cmd == "whoami":
        return "root"
    if cmd == "pwd":
        return "/root"
    if cmd == "uname -a":
        return "Linux honeypot 5.15.0 FakeKernel"
    if cmd == "":
        return ""
    return f"bash: {cmd}: command not found"

# ---------------------------
# PARAMIKO SERVER
# ---------------------------
HOST_KEY = paramiko.RSAKey.generate(2048)

class HoneyPotServer(paramiko.ServerInterface):
    def __init__(self, client_ip):
        self.client_ip = client_ip
        self.event = threading.Event()
        self.username = None
        self.password = None

    def check_auth_password(self, username, password):
        self.username = username
        self.password = password
        print(f"[AUTH] {self.client_ip} → {username}:{password}")

        # log & alert
        log_auth(self.client_ip, username, password)
        send_alert(self.client_ip, username, password)

        # Pretend login is successful
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_shell_request(self, channel):
        self.event.set()
        return True

    def check_channel_pty_request(self, *args, **kwargs):
        return True

# ---------------------------
# CONNECTION HANDLER
# ---------------------------
def handle_client(client, addr):
    ip = addr[0]
    print(f"[+] Connection from {ip}")

    try:
        transport = paramiko.Transport(client)
        transport.add_server_key(HOST_KEY)

        server = HoneyPotServer(ip)
        transport.start_server(server=server)

        chan = transport.accept(20)
        if chan is None:
            print("[!] No channel, closing")
            return

        server.event.wait(10)

        chan.send("Welcome to BAUST SSH Shell 22.04 LTS\n")
        chan.send("root@honeypot:~# ")

        buffer = ""
        while True:
            data = chan.recv(1024)
            if not data:
                break

            buffer += data.decode()
            if "\n" in buffer:
                cmd = buffer.strip()
                buffer = ""

                print(f"[CMD] {ip}: {cmd}")
                log_cmd(ip, cmd)

                if cmd == "exit":
                    chan.send("logout\n")
                    break

                chan.send(fake_output(cmd) + "\n")
                chan.send("root@honeypot:~# ")

    except Exception as e:
        print("[!] Error:", e)
    finally:
        try:
            client.close()
        except:
            pass
        print(f"[-] Disconnected: {ip}")

# ---------------------------
# MAIN SERVER LOOP
# ---------------------------
def main():
    db_init()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, PORT))
    sock.listen(100)
    print(f"[+] Honeypot listening on {HOST}:{PORT}")

    while True:
        client, addr = sock.accept()
        threading.Thread(target=handle_client, args=(client, addr)).start()

if __name__ == "__main__":
    main()

