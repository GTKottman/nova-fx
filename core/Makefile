# Nova FX core. Built on the machine that runs it, so -march=native is safe.
CC ?= gcc
CFLAGS ?= -O3 -march=native -ffast-math -fno-math-errno -fopenmp -fPIC -fvisibility=hidden -Wall -Wextra -Wno-unused-parameter
OUT ?= ../addon/nova_fx/lib/libnovacore.so

$(OUT): nova_core.c
	mkdir -p $(dir $(OUT))
	$(CC) $(CFLAGS) -shared -o $@ $< -lm
	cp nova_core.c $(dir $(OUT))nova_core.c

clean:
	rm -f $(OUT)

# Installable extension zip: ships the C source, the add-on compiles it on first use.
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' ../addon/nova_fx/blender_manifest.toml)
package:
	rm -rf ../dist/stage && mkdir -p ../dist/stage
	cp -r ../addon/nova_fx ../dist/stage/nova_fx
	rm -rf ../dist/stage/nova_fx/__pycache__ ../dist/stage/nova_fx/lib/libnovacore.so
	cp nova_core.c ../dist/stage/nova_fx/lib/nova_core.c
	cd ../dist/stage && zip -qr ../nova_fx-$(VERSION).zip nova_fx
	rm -rf ../dist/stage
	@echo "../dist/nova_fx-$(VERSION).zip"

.PHONY: clean package
