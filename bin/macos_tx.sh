#!/bin/sh
#
# Transmit a Rattlegram message acoustically on macOS.
#
# Uses the bundled bin/linux-aarch64/encode -- the fork whose wire format the
# real Rattlegram phone app speaks. There is no macOS build of that fork (its
# source is not public), so it runs in a linux/arm64 container and the audio is
# played on the host with afplay.
#
# NOTE: do NOT use aicodix/modem HEAD for this. It is a different, incompatible
# OFDM structure (guard = symbol/40, variable modulation) and the phone app will
# hear the tones but decode nothing.
#
# usage: bin/macos_tx.sh "MESSAGE"
#
# env overrides:
#   CALLSIGN  (default ZL3TUX)
#   CFO       carrier offset in Hz (default 1300 -- the app default)
#   NOISE     noise symbols (default 4)
#   MAPPING   constellation mapping (default 4)
#   RATE      sample rate (default 48000)
#   VOLUME    afplay volume, 0.0-1.0+ (default 0.8)
#   IMAGE     container image (default debian:stable-slim)
#

set -e

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$HERE")

MESSAGE=$1
if [ -z "$MESSAGE" ]; then
	echo "usage: $0 \"MESSAGE\"" >&2
	exit 2
fi

CALLSIGN=${CALLSIGN:-ZL3TUX}
CFO=${CFO:-1300}
NOISE=${NOISE:-4}
MAPPING=${MAPPING:-4}
FANCY=${FANCY:-0}
VOLUME=${VOLUME:-0.8}
IMAGE=${IMAGE:-debian:stable-slim}
BITS=16
CHANNEL=0

NATIVE="$HERE/$(uname -s | tr A-Z a-z)-$(uname -m)/encode"

# 8 kHz is the best rate for the native encoder: signal quality tracks the
# encoder's PAPR-reduction parameter, (32000 + RATE/2)/RATE, which is 4 at
# 8 kHz but only 1 at 48 kHz. Measured Es/N0 on a clean file: 23dB at 8 kHz,
# 15dB at 16 kHz, 9dB at 44.1/48 kHz, and 32 kHz does not decode at all.
# The prebuilt fork binaries don't apply that stage, so they are fine at 48 kHz.
if [ -x "$NATIVE" ]; then
	RATE=${RATE:-8000}
else
	RATE=${RATE:-48000}
fi

WORK=$(mktemp -d /tmp/rattlegram_tx.XXXXXX)
trap 'rm -rf "$WORK"' EXIT INT TERM

if [ -x "$NATIVE" ]; then
	"$NATIVE" "$WORK/msg.wav" "$RATE" "$CFO" "$CALLSIGN" \
		"$NOISE" "$FANCY" "$MESSAGE"
	VIA=native
else
	if ! docker info >/dev/null 2>&1; then
		echo "no native encoder at $NATIVE and docker is not running." >&2
		echo "build one with: make -C native" >&2
		exit 1
	fi
	docker run --rm --platform linux/arm64 \
		-v "$REPO":/w -v "$WORK":/out -w /w "$IMAGE" \
		./bin/linux-aarch64/encode "$MESSAGE" "$CALLSIGN" \
			"$NOISE" "$CFO" "$RATE" "$BITS" "$CHANNEL" "$MAPPING" /out/msg.wav
	VIA=container
fi

echo "TX <$CALLSIGN> @${CFO}Hz ${RATE}Hz noise=$NOISE ($VIA): $MESSAGE"
afplay -v "$VOLUME" "$WORK/msg.wav"
echo "TX done"
