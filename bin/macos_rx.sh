#!/bin/sh
#
# Receive Rattlegram messages acoustically on macOS.
#
# Records with sox (macOS has no arecord) and decodes with the bundled
# bin/linux-aarch64/decode in a linux/arm64 container -- the fork whose wire
# format the real Rattlegram phone app speaks.
#
# NB: this fork's decode takes its arguments as OUTPUT INPUT, the reverse of
# aicodix/modem HEAD.
#
# Capture is FIXED-WINDOW on purpose. Do not "improve" this with sox's
# level-triggered `silence` filter: it discards the first ~100ms of audio,
# which is exactly where the sync preamble lives, and nothing decodes.
# Verified -- silence-triggered capture fails where fixed-window succeeds.
#
# Because a transmission can straddle two windows, each window is also decoded
# joined to its predecessor.
#
# usage: bin/macos_rx.sh          listen until Ctrl-C
#        bin/macos_rx.sh once     capture one window and decode it
#
# env overrides:
#   WINDOW  seconds per capture window (default 8)
#   RATE    capture sample rate (default 48000)
#   IMAGE   container image (default debian:stable-slim)
#

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$HERE")

WINDOW=${WINDOW:-8}
RATE=${RATE:-48000}
IMAGE=${IMAGE:-debian:stable-slim}

NATIVE="$HERE/$(uname -s | tr A-Z a-z)-$(uname -m)/decode"

if [ ! -x "$NATIVE" ] && ! docker info >/dev/null 2>&1; then
	echo "no native decoder at $NATIVE and docker is not running." >&2
	echo "build one with: make -C native" >&2
	exit 1
fi

WORK=$(mktemp -d /tmp/rattlegram_rx.XXXXXX)
trap 'rm -rf "$WORK"; exit 0' EXIT INT TERM

try_decode() {
	# $1 = wav to decode, relative to $WORK
	rm -f "$WORK/out.bin"
	if [ -x "$NATIVE" ]; then
		# native: INPUT OUTPUT
		"$NATIVE" "$WORK/$1" "$WORK/out.bin" > "$WORK/log.txt" 2>&1 || return 1
	else
		# the fork binary takes them the other way round: OUTPUT INPUT
		docker run --rm --platform linux/arm64 \
			-v "$REPO":/w -v "$WORK":/out -w /w "$IMAGE" \
			./bin/linux-aarch64/decode /out/out.bin "/out/$1" \
			> "$WORK/log.txt" 2>&1 || return 1
	fi
	[ -s "$WORK/out.bin" ] || return 1
	CALL=$(grep -a "call sign" "$WORK/log.txt" | sed 's/.*call sign: *//')
	# Es/N0 is only reported by the fork binary; the app's decoder API
	# doesn't expose it, so fall back to bit flips.
	SNR=$(grep -a "Es/N0" "$WORK/log.txt" | sed 's/.*(dB): *//')
	FLIPS=$(grep -a "bit flips" "$WORK/log.txt" | sed 's/.*: *//')
	TEXT=$(tr -d '\000' < "$WORK/out.bin")
	if [ -n "$SNR" ]; then
		printf 'RX <%s> [Es/N0 %s] %s\n' "${CALL:-?}" "$SNR" "$TEXT"
	else
		printf 'RX <%s> [flips %s] %s\n' "${CALL:-?}" "${FLIPS:-?}" "$TEXT"
	fi
	return 0
}

echo "listening in ${WINDOW}s windows at ${RATE}Hz -- Ctrl-C to stop"

prev_ok=1	# 1 = previous window decoded nothing

while : ; do
	rm -f "$WORK/cur.wav"
	sox -d -c 1 -b 16 -r "$RATE" -t wav "$WORK/cur.wav" trim 0 "$WINDOW" 2>/dev/null

	if try_decode cur.wav ; then
		prev_ok=0
	else
		# Only join with the previous window if that one decoded nothing
		# either. If it succeeded, its audio is already accounted for and
		# joining would report the same transmission a second time.
		if [ "$prev_ok" = 1 ] && [ -f "$WORK/prev.wav" ]; then
			sox "$WORK/prev.wav" "$WORK/cur.wav" "$WORK/join.wav" 2>/dev/null
			if try_decode join.wav ; then
				prev_ok=0
			else
				echo "RX ... nothing decoded"
				prev_ok=1
			fi
		else
			echo "RX ... nothing decoded"
			prev_ok=1
		fi
	fi

	cp "$WORK/cur.wav" "$WORK/prev.wav" 2>/dev/null

	[ "$1" = "once" ] && break
done
