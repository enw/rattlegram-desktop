/*
Rattlegram CLI encoder for macOS (and anywhere else).

Wraps the Encoder<RATE> from the Rattlegram phone app's own sources
(aicodix/rattlegram, app/src/main/cpp/encoder.hh) in a command line tool that
writes a mono 16-bit PCM WAV, so the desktop app can transmit without running
the prebuilt Linux binaries in a container.

This is the app's protocol, NOT aicodix/modem HEAD -- those are mutually
incompatible and the phone cannot decode modem HEAD output. See CLAUDE.md.
*/

#include <cassert>	// the app's headers assert() but rely on the NDK for this
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <algorithm>
#include <cmath>
#include <string>
#include <vector>

#include "encoder.hh"

namespace {

// Minimal mono 16-bit PCM WAV writer. Header is patched on close once the
// sample count is known.
class WavWriter {
	std::FILE *f = nullptr;
	uint32_t frames = 0;
	int rate;

	void u32(uint32_t v) { std::fwrite(&v, 4, 1, f); }
	void u16(uint16_t v) { std::fwrite(&v, 2, 1, f); }

public:
	explicit WavWriter(const char *path, int rate) : rate(rate) {
		f = std::fopen(path, "wb");
		if (!f)
			return;
		std::fwrite("RIFF", 1, 4, f);
		u32(0);				// patched
		std::fwrite("WAVEfmt ", 1, 8, f);
		u32(16);			// fmt chunk size
		u16(1);				// PCM
		u16(1);				// mono
		u32(rate);
		u32(rate * 2);			// byte rate
		u16(2);				// block align
		u16(16);			// bits
		std::fwrite("data", 1, 4, f);
		u32(0);				// patched
	}

	bool ok() const { return f != nullptr; }

	void write(const int16_t *s, int n) {
		std::fwrite(s, 2, n, f);
		frames += n;
	}

	void silence(int n) {
		std::vector<int16_t> z(n, 0);
		write(z.data(), n);
	}

	~WavWriter() {
		if (!f)
			return;
		uint32_t data = frames * 2;
		std::fseek(f, 4, SEEK_SET);
		u32(36 + data);
		std::fseek(f, 40, SEEK_SET);
		u32(data);
		std::fclose(f);
	}
};

template<int RATE>
int run(const char *path, int offset, const char *callsign,
	int noise, bool fancy, const char *message) {

	static const int symbol_length = (1280 * RATE) / 8000;
	static const int extended_length = symbol_length + symbol_length / 8;

	// configure() scans payload for NUL and supports up to 128 bytes;
	// the encoder's internal message buffer is 1360/8 bytes.
	uint8_t payload[1360 / 8] = {0};
	std::size_t len = std::strlen(message);
	if (len > 128) {
		std::fprintf(stderr, "message too long (%zu > 128 bytes)\n", len);
		return 1;
	}
	std::memcpy(payload, message, len);

	int8_t call[10] = {0};
	std::size_t clen = std::strlen(callsign);
	if (clen > 9) {
		std::fprintf(stderr, "call sign too long (%zu > 9 chars)\n", clen);
		return 1;
	}
	std::memcpy(call, callsign, clen);

	WavWriter wav(path, RATE);
	if (!wav.ok()) {
		std::fprintf(stderr, "cannot open %s for writing\n", path);
		return 1;
	}

	Encoder<RATE> *encoder = new Encoder<RATE>();
	encoder->configure(payload, call, offset, noise, fancy);

	std::vector<int16_t> buf(extended_length);
	std::vector<int16_t> samples;
	while (encoder->produce(buf.data(), 0))
		samples.insert(samples.end(), buf.begin(), buf.end());
	delete encoder;

	if (samples.empty()) {
		std::fprintf(stderr, "encoder produced no samples\n");
		return 1;
	}

	// Normalise to just under full scale. The PAPR-reduction stage in the
	// app's encoder leaves peaks near half scale, which is ~6dB down; played
	// acoustically that was the difference between decoding and not decoding
	// at all. The prebuilt fork binaries emit near full scale too.
	int peak = 1;
	for (int16_t s : samples)
		peak = std::max(peak, std::abs(int(s)));
	double gain = 32440.0 / peak;
	for (int16_t &s : samples) {
		double v = s * gain;
		s = int16_t(std::clamp(v, -32768.0, 32767.0));
	}

	// A little silence either side gives the receiver room to settle.
	wav.silence(RATE / 10);
	wav.write(samples.data(), int(samples.size()));
	wav.silence(RATE / 10);

	return 0;
}

} // namespace

int main(int argc, char **argv) {
	if (argc < 8) {
		std::fprintf(stderr,
			"usage: %s OUTPUT RATE OFFSET CALLSIGN NOISE_SYMBOLS FANCY MESSAGE\n"
			"\n"
			"  OUTPUT         mono 16-bit PCM WAV to write\n"
			"  RATE           8000 | 16000 | 32000 | 44100 | 48000\n"
			"  OFFSET         carrier frequency in Hz (app default 1300)\n"
			"  CALLSIGN       up to 9 base-37 characters\n"
			"  NOISE_SYMBOLS  leading noise symbols (app default 4)\n"
			"  FANCY          1 to append the fancy header symbols, else 0\n"
			"  MESSAGE        up to 128 bytes\n",
			argv[0]);
		return 2;
	}

	const char *path = argv[1];
	int rate = std::atoi(argv[2]);
	int offset = std::atoi(argv[3]);
	const char *callsign = argv[4];
	int noise = std::atoi(argv[5]);
	bool fancy = std::atoi(argv[6]) != 0;
	const char *message = argv[7];

	switch (rate) {
	case 8000:
		return run<8000>(path, offset, callsign, noise, fancy, message);
	case 16000:
		return run<16000>(path, offset, callsign, noise, fancy, message);
	case 32000:
		return run<32000>(path, offset, callsign, noise, fancy, message);
	case 44100:
		return run<44100>(path, offset, callsign, noise, fancy, message);
	case 48000:
		return run<48000>(path, offset, callsign, noise, fancy, message);
	default:
		std::fprintf(stderr, "unsupported sample rate %d\n", rate);
		return 1;
	}
}
