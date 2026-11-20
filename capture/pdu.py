"""SMS-DELIVER PDU with an alphanumeric sender (e.g. MPESA), for `adb emu sms pdu <hex>`.

The emulator's `sms send` only takes numeric senders; banks and M-Pesa use names. Basic GSM 7-bit text only, 160 characters at most.
"""
import sys, time


def pack7(text):
	bits = "".join(format(ord(c), "07b")[::-1] for c in text)  # LSB first
	bits += "0" * (-len(bits) % 8)
	return bytes(int(bits[i:i + 8][::-1], 2) for i in range(0, len(bits), 8))


def swap(two_digits):
	return two_digits[1] + two_digits[0]


def pdu(sender, body):
	assert len(body) <= 160 and all(32 <= ord(c) < 127 and c not in "$@_[]{}\\^~|`" for c in sender + body), "basic GSM text, 160 chars at most"
	addr = pack7(sender)
	t = time.localtime()
	stamp = "".join(swap(f"{v:02d}") for v in (t.tm_year % 100, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)) + "00"
	return ("00" + "04" + f"{(len(sender) * 7 + 3) // 4:02X}" + "D0" + addr.hex().upper() + "00" + "00" + stamp + f"{len(body):02X}" + pack7(body).hex().upper())


if __name__ == "__main__":
	assert pack7("hellohello").hex().upper() == "E8329BFD4697D9EC37"
	print(pdu(sys.argv[1], sys.argv[2]))
