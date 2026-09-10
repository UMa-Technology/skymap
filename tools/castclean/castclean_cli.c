/* castclean_cli — test harness for the castclean module.
 * Reads a binary PPM (P6, 8-bit), cleans it, writes a binary PPM.
 *
 *   castclean_cli [-confirmed] [-cell N] [-no-lum] in.ppm out.ppm
 */
#include "castclean.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int read_token(FILE *f, char *buf, int cap)
{
    int c, i = 0;
    do {
        c = fgetc(f);
        if (c == '#') { while (c != '\n' && c != EOF) c = fgetc(f); }
    } while (c == ' ' || c == '\t' || c == '\n' || c == '\r');
    while (c != EOF && c != ' ' && c != '\t' && c != '\n' && c != '\r') {
        if (i < cap - 1) buf[i++] = (char)c;
        c = fgetc(f);
    }
    buf[i] = 0;
    return i > 0 ? 0 : -1;
}

static uint8_t *read_ppm(const char *path, int *w, int *h)
{
    char tok[64];
    FILE *f = fopen(path, "rb");
    uint8_t *pix = NULL;
    int maxv;
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return NULL; }
    if (read_token(f, tok, sizeof(tok)) || strcmp(tok, "P6")) goto fail;
    if (read_token(f, tok, sizeof(tok))) goto fail;
    *w = atoi(tok);
    if (read_token(f, tok, sizeof(tok))) goto fail;
    *h = atoi(tok);
    if (read_token(f, tok, sizeof(tok))) goto fail;
    maxv = atoi(tok);
    if (*w <= 0 || *h <= 0 || maxv != 255) goto fail;
    pix = (uint8_t *)malloc((size_t)*w * *h * 3);
    if (!pix || fread(pix, 3, (size_t)*w * *h, f) != (size_t)*w * *h) {
        free(pix); pix = NULL;
    }
fail:
    fclose(f);
    if (!pix) fprintf(stderr, "bad PPM %s\n", path);
    return pix;
}

static int write_ppm(const char *path, const uint8_t *pix, int w, int h)
{
    FILE *f = fopen(path, "wb");
    if (!f) { fprintf(stderr, "cannot write %s\n", path); return -1; }
    fprintf(f, "P6\n%d %d\n255\n", w, h);
    fwrite(pix, 3, (size_t)w * h, f);
    fclose(f);
    return 0;
}

int main(int argc, char **argv)
{
    castclean_params p;
    castclean_report rep;
    const char *in = NULL, *out = NULL;
    uint8_t *pix;
    int w, h, i;

    castclean_params_init(&p);
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-confirmed")) p.confirmed = 1;
        else if (!strcmp(argv[i], "-no-blue")) p.fix_blue = 0;
        else if (!strcmp(argv[i], "-no-lum")) p.fix_luminance = 0;
        else if (!strcmp(argv[i], "-cell") && i + 1 < argc) p.cell = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-cast-thresh") && i + 1 < argc)
            p.cast_thresh = (float)atof(argv[++i]);
        else if (!in) in = argv[i];
        else if (!out) out = argv[i];
        else { fprintf(stderr, "unexpected arg %s\n", argv[i]); return 2; }
    }
    if (!in || !out) {
        fprintf(stderr,
                "usage: castclean_cli [-confirmed] [-cell N] [-no-lum] in.ppm out.ppm\n");
        return 2;
    }
    pix = read_ppm(in, &w, &h);
    if (!pix) return 1;
    if (castclean_rgb8(pix, w, h, w * 3, &p, &rep) != 0) {
        fprintf(stderr, "castclean failed\n");
        free(pix);
        return 1;
    }
    printf("%s: %s  dead=%.1f%%  mask=%.1f%%  max|du|=%.1f max|dv|=%.1f  "
           "mean|d|=%.3f\n",
           in, rep.changed ? "CHANGED" : "untouched",
           rep.dead_frac * 100, rep.mask_frac * 100,
           rep.max_du, rep.max_dv, rep.mean_abs_delta);
    i = write_ppm(out, pix, w, h);
    free(pix);
    return i ? 1 : 0;
}
