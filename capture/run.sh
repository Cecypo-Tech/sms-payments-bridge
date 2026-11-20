#!/usr/bin/env bash
# Screenshot job: drive the debug build through its screens on an emulator, against capture/mock_server.py.
# Fictional SMS only. Output: $OUT/*.png and *.mp4.
set -u
OUT=${OUT:-capture-out}; mkdir -p "$OUT"
UI="python3 capture/ui.py"
PKG=tech.cecypo.smsbridge
shot() { sleep "${2:-1.5}"; adb exec-out screencap -p > "$OUT/$1.png"; echo "shot $1 t=$(( $(date +%s) - ${T0:-0} ))"; }
rec_start() { adb shell "screenrecord --bit-rate 8000000 /sdcard/$1.mp4" & REC=$!; sleep 1.5; T0=$(date +%s); }
rec_stop() { adb shell pkill -INT screenrecord; wait $REC 2>/dev/null; sleep 2; adb pull "/sdcard/$1.mp4" "$OUT/$1.mp4" >/dev/null && echo "clip $1"; }
DB=/data/data/com.android.providers.telephony/databases/mmssms.db  # the unlocked-phone store; /data/user_de holds only pre-unlock messages
: > "$OUT/seed.sql"
sms() { # sender, body. A real SMS through the emulator's modem; also queued as a direct row in case the modem path drops it.
  echo "pdu $1: $(adb emu sms pdu "$(python3 capture/pdu.py "$1" "$2")" 2>&1 | tr '\n' ' ')"; sleep 2
  echo "insert into sms (address, date, date_sent, read, seen, type, sub_id, body) values ('$1', $(date +%s)000, $(date +%s)000, 1, 1, 1, SUBID, '$2');" >> "$OUT/seed.sql"
}
inbox() { adb shell "sqlite3 $DB 'select count(*) from sms where type=1'" | tr -d '\r'; }

python3 capture/mock_server.py app/src/debug/res/raw/capture_ca.pem "$CAPTURE_KEY" > "$OUT/mock.log" 2>&1 &
adb root; sleep 3; adb wait-for-device
adb shell settings put global http_proxy 10.0.2.2:8888
adb shell settings put secure show_ime_with_hard_keyboard 0
for pkg in $(adb shell ime list -a -s | tr -d '\r' | cut -d/ -f1 | sort -u); do adb shell pm disable-user --user 0 "$pkg" >/dev/null; done  # no soft keyboard: it covers the buttons and swallows typed characters
adb shell settings put system show_touches 1
adb shell settings put global captive_portal_mode 0  # the proxy answers no connectivity probe; without this the network never counts as usable and sync waits
adb shell settings put global sysui_demo_allowed 1
for c in "enter" "clock -e hhmm $(date +%H%M)" "battery -e level 100 -e plugged false" "network -e wifi show -e level 4 -e mobile show -e datatype none -e level 4" "notifications -e visible false"; do adb shell "am broadcast -a com.android.systemui.demo -e command $c" >/dev/null; done

TDB=/data/user_de/0/com.android.providers.telephony/databases/telephony.db
for i in $(seq 30); do  # Android 14+ shows an app only the SMS of the user's SIMs, so wait for the emulated SIM to register
  SUB=$(adb shell "sqlite3 $TDB 'select _id from siminfo limit 1'" 2>/dev/null | tr -d '\r')
  [ -n "$SUB" ] && break; sleep 4
done
echo "sim: state=$(adb shell getprop gsm.sim.state | tr -d '\r') sub=${SUB:-none} sms app=$(adb shell settings get secure sms_default_application | tr -d '\r') sdk=$(adb shell getprop ro.build.version.sdk | tr -d '\r')"
SUB=${SUB:-1}
sleep 10  # let the launcher settle after boot
sms MPESA "UKE9B4H55C Confirmed. You have received Ksh12,750.00 from MAMA PENDO HARDWARE 0711000333 on $(date +%-d/%-m/%y) at 9:19 AM New M-PESA balance is Ksh14,810.00."
sms 0722000444 "Hi, are you open on Sunday?"
sms Safaricom "Dear customer, enjoy 2GB for only Ksh99 valid for 24 hours. Dial *544#."
sms KCB "KES 18,200.00 received from NYALI CONSTRUCTION CO via RTGS. Ref FT26319XK2PD. Available balance KES 412,655.40."
sms MPESA "UKF2M7X88A Confirmed. You have received Ksh4,500.00 from PETER KAMAU 0733000222 on $(date +%-d/%-m/%y) at 11:12 AM New M-PESA balance is Ksh19,310.00."
sms EQUITYBANK "You have received 275900.00 KES from RIFT VALLEY CONTRACTORS LIMITED 0********1511 to your Equity account 0********9198. Ref. A9B1287073F47 on $(date +"%d %b %Y") at 11:39 EAT"
sleep 3
sed -i "s/SUBID/$SUB/" "$OUT/seed.sql"
adb shell cmd statusbar collapse; adb shell input keyevent 3; sleep 2

adb install -r app/build/outputs/apk/debug/app-debug.apk
rec_start 1-setup
adb shell monkey -p $PKG -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
$UI wait text "Connect"; shot 01-setup-empty
$UI tap id url; adb shell input text "https://erp.acme-hardware.example"; sleep 0.6
$UI tap id apiKey; adb shell input text "4f1c9a7be2d05c3"; sleep 0.6
$UI tap id apiSecret; adb shell input text "9b3e6d1f0a8c2e7"; sleep 0.6
$UI tap id deviceName; adb shell input keyevent 123; adb shell "input keyevent $(printf '67 %.0s' $(seq 60))"; adb shell input text "Office%sphone"; sleep 0.8
shot 02-setup-filled
$UI tap text "Connect"; $UI wait text "I agree"; shot 03-disclosure 2
$UI tap text "I agree"; $UI wait text "Continue"; shot 04-checklist 2
$UI tap text "Allow SMS access"; sleep 2; shot 05-sms-permission; $UI tap text "Allow"; sleep 2
$UI tap text "Allow background activity"; sleep 2; shot 06-battery; $UI tap text "Allow"; sleep 2
$UI wait text "Recent messages" || { shot 08-stuck; rec_stop 1-setup; exit 0; }; shot 08-home 4
sms MPESA "UKF4T9Q21N Confirmed. You have received Ksh29,000.00 from GRACE WAMBUI 0722000111 on $(date +%-d/%-m/%y) at 12:06 PM New M-PESA balance is Ksh48,310.00."
sed -i "s/SUBID/$SUB/" "$OUT/seed.sql"
# The provider creates its store on first use, so seed now that the app has read SMS once.
echo "inbox after modem: $(inbox)"
if [ "$(inbox)" = "0" ] || [ -z "$(inbox)" ]; then adb push "$OUT/seed.sql" /data/local/tmp/seed.sql >/dev/null; adb shell "sqlite3 $DB < /data/local/tmp/seed.sql"; fi
echo "inbox after direct rows: $(inbox)"; adb shell "sqlite3 $DB 'select address, sub_id from sms'" | tee "$OUT/inbox.txt"
shot 08b-sms-arrives 2
sleep 5; adb shell cmd statusbar collapse
adb shell input swipe 540 1700 540 900 400; shot 09-home-events 2
rec_stop 1-setup

adb shell input swipe 540 900 540 1700 400; sleep 1
rec_start 2-samples
$UI tap text "More options"; shot 10-menu 1.5
$UI tap text "Send samples"; $UI wait id sendSamples; shot 11-picker 2
$UI tap text KCB; sleep 0.8; $UI tap text EQUITYBANK; shot 12-picker-ticked 1
$UI tap id sendSamples; shot 13-confirm 1.5
$UI tap text "Send"; $UI wait text "OK"; shot 14-sent 1
$UI tap text "OK"; sleep 2; adb shell input keyevent 4; $UI wait text "Recent messages"; sleep 2
$UI tap text "More options"; sleep 1; $UI tap text "Resend recent messages"; shot 15-resend 1.5
adb shell input keyevent 4; sleep 1
rec_stop 2-samples
ls -la "$OUT"
