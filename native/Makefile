# Build native Rattlegram CLI tools for this host.
#
# The modem itself comes from the phone app's own sources, which are fetched on
# first build. That is deliberately the app's protocol -- do NOT substitute
# aicodix/modem, which is a different and incompatible OFDM structure.
#
#   make            build into ../bin/<os>-<arch>/
#   make clean      remove binaries
#   make distclean  also remove the fetched sources
#
# Override RATTLEGRAM_SRC to build against an existing checkout.

RATTLEGRAM_SRC ?= $(CURDIR)/.rattlegram-src
CPP = $(RATTLEGRAM_SRC)/app/src/main/cpp

ARCH := $(shell uname -s | tr A-Z a-z)-$(shell uname -m)
OUT = ../bin/$(ARCH)

# No -ffast-math: this is DSP code and the gain is nil (measured).
CXXFLAGS += -std=c++17 -O3 -fno-exceptions -fno-rtti -I$(CPP)

.PHONY: all clean distclean

all: $(OUT)/encode

$(RATTLEGRAM_SRC):
	git clone --depth 1 https://github.com/aicodix/rattlegram.git $@

$(OUT)/encode: encode.cc | $(RATTLEGRAM_SRC)
	mkdir -p $(OUT)
	$(CXX) $(CXXFLAGS) $< -o $@
	@echo "built $@"

clean:
	rm -f $(OUT)/encode

distclean: clean
	rm -rf $(RATTLEGRAM_SRC)
