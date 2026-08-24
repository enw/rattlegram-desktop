/*
Rattlegram CLI decoder for macOS (and anywhere else).

Wraps the Decoder<RATE> from the Rattlegram phone app's own sources
(aicodix/rattlegram, app/src/main/cpp/decoder.hh) in a command line tool that
reads a 16-bit PCM WAV, so the desktop app can receive without running the
prebuilt Linux binaries in a container.

Unlike the encoder, this is a streaming state machine: feed() accumulates up to
one extended symbol and returns true when process() should run; process()
reports SYNC when a frame header is locked and DONE when the payload is ready
for fetch().

The OFDM structure is defined in time (symbol_length = 1280*RATE/8000), so the
protocol is rate-agnostic: a transmission generated at 8kHz decodes fine from a
48kHz capture. The Decoder is instantiated for the WAV's own rate.

Argument order is INPUT OUTPUT -- note the prebuilt fork binaries take the
reverse, OUTPUT INPUT.
*/

#include <cassert>	// the app's headers assert() but rely on the NDK for this
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <algorithm>
#include <cmath>
#include <vector>

#include "decoder.hh"

namespace {

struct Wav {
	std::vector<int16_t> samples;	// interleaved
	int rate = 0;
	int channels = 0;
};

uint32_t rd32(const uint8_t *p) {
	return uint32_t(p[0]) | (uint32_t(p[1]) << 8) |
	       (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}

uint16_t rd16(const uint8_t *p) {
	return uint16_t(p[0]) | (uint16_t(p[1]) << 8);
}

// Minimal RIFF/WAVE reader: 16-bit PCM only, chunks walked so non-canonical
// files (extra LIST/fact chunks, which sox and ffmpeg both emit) still work.
bool read_wav(const char *path, Wav &out) {
	std::vector<uint8_t> raw;
	std::FILE *f = std::strcmp(path, "-") ? std::fopen(path, "rb") : stdin;
	if (!f) {
		std::fprintf(stderr, "cannot open %s\n", path);
		return false;
	}
	uint8_t chunk[65536];
	std::size_t n;
	while ((n = std::fread(chunk, 1, sizeof chunk, f)) > 0)
		raw.insert(raw.end(), chunk, chunk + n);
	if (f != stdin)
		std::fclose(f);

	if (raw.size() < 12 || std::memcmp(raw.data(), "RIFF", 4) ||
	    std::memcmp(raw.data() + 8, "WAVE", 4)) {
		std::fprintf(stderr, "%s is not a RIFF/WAVE file\n", path);
		return false;
	}

	int bits = 0;
	std::size_t pos = 12;
	while (pos + 8 <= raw.size()) {
		const uint8_t *id = raw.data() + pos;
		uint32_t size = rd32(raw.data() + pos + 4);
		std::size_t body = pos + 8;
		if (!std::memcmp(id, "fmt ", 4) && body + 16 <= raw.size()) {
			out.channels = rd16(raw.data() + body + 2);
			out.rate = int(rd32(raw.data() + body + 4));
			bits = rd16(raw.data() + body + 14);
		} else if (!std::memcmp(id, "data", 4)) {
			std::size_t avail = std::min<std::size_t>(size, raw.size() - body);
			out.samples.resize(avail / 2);
			std::memcpy(out.samples.data(), raw.data() + body, out.samples.size() * 2);
		}
		pos = body + size + (size & 1);	// chunks are word aligned
	}

	if (bits != 16) {
		std::fprintf(stderr, "only 16-bit PCM supported (got %d-bit)\n", bits);
		return false;
	}
	if (out.samples.empty()) {
		std::fprintf(stderr, "no audio data in %s\n", path);
		return false;
	}
	return true;
}

template<int RATE>
int run(const Wav &wav, const char *out_path) {
	static const int symbol_length = (1280 * RATE) / 8000;
	static const int extended_length = symbol_length + symbol_length / 8;

	// channel_select: 0 is mono, 1 takes the left of an interleaved pair.
	int channel_select = wav.channels == 1 ? 0 : 1;
	int frames = int(wav.samples.size()) / wav.channels;

	Decoder<RATE> *decoder = new Decoder<RATE>();
	uint8_t payload[170];
	bool got = false;

	// process() advances one symbol per extended_length block, so a frame needs
	// symbol_count+1 blocks after sync to complete. A file that ends right
	// after the last payload symbol -- which is exactly what the encoders
	// produce -- would otherwise sync and then never reach DONE. Feed silence
	// past the end so the state machine can finish.
	std::vector<int16_t> tail(std::size_t(extended_length) * wav.channels, 0);
	const int flush_blocks = 8;
	int total = frames + flush_blocks * extended_length;

	for (int off = 0; off < total; ) {
		int n = std::min(extended_length, total - off);
		const int16_t *src;
		if (off < frames) {
			n = std::min(n, frames - off);
			src = wav.samples.data() + std::size_t(off) * wav.channels;
		} else {
			src = tail.data();
		}
		if (decoder->feed(src, n, channel_select)) {
			int status = decoder->process();
			switch (status) {
			case STATUS_SYNC: {
				float cfo = 0;
				int32_t mode = 0;
				uint8_t call[10] = {0};
				decoder->staged(&cfo, &mode, call);
				std::fprintf(stderr, "call sign:    %s\n", (char *)call);
				std::fprintf(stderr, "oper mode:    %d\n", mode);
				std::fprintf(stderr, "carrier cfo:  %.1f Hz\n", cfo);
				break;
			}
			case STATUS_DONE: {
				int flips = decoder->fetch(payload);
				if (flips < 0) {
					std::fprintf(stderr, "unsupported operation mode\n");
					break;
				}
				std::fprintf(stderr, "bit flips:    %d\n", flips);
				got = true;
				break;
			}
			case STATUS_NOPE:
				std::fprintf(stderr, "preamble found but undecodable\n");
				break;
			case STATUS_PING:
				std::fprintf(stderr, "ping\n");
				break;
			case STATUS_FAIL:
				std::fprintf(stderr, "preamble decoding failed\n");
				break;
			default:
				break;
			}
		}
		off += n;
		if (got) break;
	}
	delete decoder;

	if (!got) {
		std::fprintf(stderr, "no frame decoded\n");
		return 1;
	}

	// Payload is NUL-padded to 170 bytes; write only up to the terminator so
	// callers don't have to strip zeros.
	std::size_t len = 0;
	while (len < sizeof payload && payload[len])
		++len;

	std::FILE *o = std::strcmp(out_path, "-") ? std::fopen(out_path, "wb") : stdout;
	if (!o) {
		std::fprintf(stderr, "cannot open %s for writing\n", out_path);
		return 1;
	}
	std::fwrite(payload, 1, len, o);
	if (o != stdout)
		std::fclose(o);
	return 0;
}

} // namespace

int main(int argc, char **argv) {
	if (argc < 3) {
		std::fprintf(stderr,
			"usage: %s INPUT OUTPUT\n"
			"\n"
			"  INPUT   16-bit PCM WAV to decode, or - for stdin\n"
			"  OUTPUT  file to write the payload to, or - for stdout\n"
			"\n"
			"NB: the prebuilt fork binaries take OUTPUT INPUT, the reverse.\n",
			argv[0]);
		return 2;
	}

	Wav wav;
	if (!read_wav(argv[1], wav))
		return 1;

	switch (wav.rate) {
	case 8000:
		return run<8000>(wav, argv[2]);
	case 16000:
		return run<16000>(wav, argv[2]);
	case 32000:
		return run<32000>(wav, argv[2]);
	case 44100:
		return run<44100>(wav, argv[2]);
	case 48000:
		return run<48000>(wav, argv[2]);
	default:
		std::fprintf(stderr, "unsupported sample rate %d\n", wav.rate);
		return 1;
	}
}
