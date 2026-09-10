CC ?= cc
CFLAGS ?= -std=c99 -O2 -Wall -Wextra
LDLIBS = -lm

all: castclean_cli

castclean_cli: castclean_cli.c castclean.c castclean.h
	$(CC) $(CFLAGS) -o $@ castclean_cli.c castclean.c $(LDLIBS)

clean:
	rm -f castclean_cli

.PHONY: all clean
