"""Tap or wait for a view on the emulator by its text, content description or resource id."""
import re, subprocess, sys, time


def nodes():
	xml = subprocess.run(["adb", "exec-out", "uiautomator", "dump", "/dev/tty"], capture_output=True, text=True).stdout
	out = []
	for m in re.finditer(r"<node [^>]*>", xml):
		a = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group()))
		b = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", a.get("bounds", ""))
		if b:
			x1, y1, x2, y2 = map(int, b.groups()); a["xy"] = ((x1 + x2) // 2, (y1 + y2) // 2); out.append(a)
	return out


def find(kind, value, index=0):
	hits = [n for n in nodes() if (value.lower() in ((n.get("text") or "").lower(), (n.get("content-desc") or "").lower()) if kind == "text" else n.get("resource-id", "").endswith("/" + value))]
	return hits[index] if len(hits) > index else None


def main():
	cmd, kind, value = sys.argv[1], sys.argv[2], sys.argv[3]
	index = int(sys.argv[4]) if len(sys.argv) > 4 else 0
	for _ in range(12):
		if any("isn't responding" in (n.get("text") or "") for n in nodes()):  # slow emulator: a system app stalled
			w = find("text", "Wait")
			if w:
				subprocess.run(["adb", "shell", "input", "tap", str(w["xy"][0]), str(w["xy"][1])]); time.sleep(2)
		n = find(kind, value, index)
		if n:
			if cmd == "tap":
				subprocess.run(["adb", "shell", "input", "tap", str(n["xy"][0]), str(n["xy"][1])])
			print(cmd, kind, value, "ok", n["xy"], flush=True)
			return 0
		time.sleep(1)
	print(cmd, kind, value, "NOT FOUND; on screen:", sorted({n.get("text") or n.get("content-desc") for n in nodes()} - {"", None})[:40], flush=True)
	return 1


sys.exit(main())
