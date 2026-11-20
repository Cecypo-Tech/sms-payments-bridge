"""Stand-in ERPNext for the screenshot job: answers the three phone endpoints with fictional data.

Port 8443 speaks TLS as the server; port 8888 is an HTTP proxy whose CONNECT always lands on 8443,
so the emulator (global proxy 10.0.2.2:8888) can use a real-looking https URL with no DNS.
"""
import json, socket, ssl, sys, threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CERT, KEY = sys.argv[1], sys.argv[2]
TODAY = date.today()
DAILY = [(6, 1, 2), (9, 0, 3), (4, 2, 1), (11, 1, 4), (7, 0, 2), (0, 0, 1), (8, 1, 3), (12, 0, 2), (10, 2, 3), (6, 0, 1), (13, 1, 4), (9, 0, 2), (3, 0, 1), (5, 1, 2)]
D = lambda back, hm: f"{TODAY - timedelta(days=back)} {hm}:00"
# The same payments the ERPNext demo site holds, so the phone and the desk screens agree.
EVENTS = [("MPESA", "Matched", "SMSPAY-2026-00007", 29000.0, D(0, "12:06")), ("EQUITYBANK", "Matched", "SMSPAY-2026-00006", 275900.0, D(0, "11:39")),
	("MPESA", "Matched", "SMSPAY-2026-00005", 4500.0, D(0, "11:12")), ("KCB", "Unmatched", None, None, D(0, "10:35")),
	("MPESA", "Matched", "SMSPAY-2026-00004", 12750.0, D(0, "09:19")), ("EQUITYBANK", "Matched", "SMSPAY-2026-00003", 86400.0, D(1, "09:40")),
	("MPESA", "Matched", "SMSPAY-2026-00002", 21300.0, D(1, "06:50")), ("MPESA", "Matched", "SMSPAY-2026-00001", 8400.0, D(2, "08:50"))]


class H(BaseHTTPRequestHandler):
	def log_message(self, *a):
		print("mock", self.command, self.path.split("?")[0][-40:], flush=True)

	def _send(self, message):
		body = json.dumps({"message": message}).encode()
		self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

	def do_GET(self):
		if "get_config" in self.path:
			return self._send({"enabled": True, "device": "SMS-DEV-0001", "watched_senders": ["MPESA", "EQUITYBANK", "KCB"], "backfill_days": 3})
		self._send({
			"daily": [{"date": str(TODAY - timedelta(days=13 - i)), "matched": m, "unmatched": u, "ignored": g, "duplicate": 0, "error": 0} for i, (m, u, g) in enumerate(DAILY)],
			"unmatched_total": 1, "last_posted_at": EVENTS[0][4],
			"events": [{"time": t, "sender": s, "status": st, "entry": e, "amount": a} for s, st, e, a, t in EVENTS],
		})

	def do_POST(self):
		rows = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["messages"]
		self._send({"results": [{"phone_sms_id": r["phone_sms_id"], "status": "accepted", "error": None} for r in rows]})


def pipe(a, b):
	try:
		while (d := a.recv(65536)):
			b.sendall(d)
	except OSError:
		pass
	finally:
		for s in (a, b):
			try: s.shutdown(socket.SHUT_RDWR)
			except OSError: pass


def proxy():
	srv = socket.create_server(("0.0.0.0", 8888))
	while True:
		c, _ = srv.accept()
		head = b""
		while b"\r\n\r\n" not in head:
			head += c.recv(4096)
		print("proxy", head.split(b"\r\n")[0].decode(), flush=True)
		up = socket.create_connection(("127.0.0.1", 8443))
		c.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
		threading.Thread(target=pipe, args=(c, up), daemon=True).start()
		threading.Thread(target=pipe, args=(up, c), daemon=True).start()


threading.Thread(target=proxy, daemon=True).start()
httpd = ThreadingHTTPServer(("0.0.0.0", 8443), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); ctx.load_cert_chain(CERT, KEY)
httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
print("mock up", flush=True)
httpd.serve_forever()
