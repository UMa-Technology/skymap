/* Stellarium Web Engine - Copyright (c) 2022 - Stellarium Labs SRL
 *
 * This program is licensed under the terms of the GNU AGPL v3, or
 * alternatively under a commercial licence.
 *
 * The terms of the AGPL v3 license can be found in the main directory of this
 * repository.
 */

#include "swe.h"

#include <dirent.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <time.h>

#ifndef PATH_MAX
#define PATH_MAX 1024
#endif

// Fix mkdir on MINGW
#ifdef WIN32
#   define mkdir(p, m) mkdir(p)
#endif


// The global system instance.
sys_callbacks_t sys_callbacks = {};

void sys_log(const char *msg)
{
    if (sys_callbacks.log) {
        sys_callbacks.log(sys_callbacks.user, msg);
    } else {
        printf("%s\n", msg);
        fflush(stdout);
    }
}

double sys_get_unix_time(void)
{
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec / 1000. / 1000.;
}

int sys_get_utc_offset(void)
{
#ifndef WIN32
    time_t t = time(NULL);
    struct tm lt = {0};
    localtime_r(&t, &lt);
    return lt.tm_gmtoff;
#else
    // Not implemented yet.
    return 0;
#endif
}

const char *sys_get_user_dir(void)
{
    if (sys_callbacks.get_user_dir) {
        return sys_callbacks.get_user_dir(sys_callbacks.user);
    } else {
        return ".";
    }
}

int sys_make_dir(const char *path)
{
    char tmp[PATH_MAX];
    char *p;
    strcpy(tmp, path);
    for (p = tmp + 1; *p; p++) {
        if (*p != '/') continue;
        *p = '\0';
        if ((mkdir(tmp, S_IRWXU) != 0) && (errno != EEXIST)) return -1;
        *p = '/';
    }
    return 0;
}

int sys_device_sensors(bool enable_accelero, bool enable_magneto,
                       double acc[3], double mag[3], int *rot,
                       double *calibration_level)
{
    if (!sys_callbacks.device_sensors) return -1;
    return sys_callbacks.device_sensors(
            sys_callbacks.user, enable_accelero, enable_magneto, acc, mag, rot,
            calibration_level);
}

int sys_get_position(double *lat, double *lon, double *alt, double *accuracy)
{
    if (!sys_callbacks.get_position) return -1;
    return sys_callbacks.get_position(
                        sys_callbacks.user, lat, lon, alt, accuracy);
}

// Cache of already-translated strings, keyed by the source string. sys_translate
// is called for every visible label every frame; without this each call would
// cross into JS (trampoline + two UTF8 decodes + two dictionary lookups) only
// to re-derive the same result. One table per domain, so the key is just `str`
// (no per-call combined-key building on the hot path). The cached values are
// owned by the translate callback (stable pointers), so we store but never free
// them here; the cache is cleared when the language changes (see sys_set_lang).
typedef struct trans_cache {
    UT_hash_handle  hh;
    const char      *value;
    char            key[];
} trans_cache_t;

enum { TRANS_DOMAIN_SKY, TRANS_DOMAIN_GUI, TRANS_DOMAIN_SKYCULTURE,
       TRANS_DOMAIN_COUNT };
static trans_cache_t *s_trans_cache[TRANS_DOMAIN_COUNT] = {NULL};

// "sky" is checked first: it is by far the most frequent domain (every star,
// DSO, planet and constellation label).
static trans_cache_t **trans_cache_head(const char *domain)
{
    if (strcmp(domain, "sky") == 0) return &s_trans_cache[TRANS_DOMAIN_SKY];
    if (strcmp(domain, "gui") == 0) return &s_trans_cache[TRANS_DOMAIN_GUI];
    return &s_trans_cache[TRANS_DOMAIN_SKYCULTURE];
}

static void trans_cache_clear(void)
{
    int i;
    trans_cache_t *e, *tmp;
    for (i = 0; i < TRANS_DOMAIN_COUNT; i++) {
        HASH_ITER(hh, s_trans_cache[i], e, tmp) {
            HASH_DEL(s_trans_cache[i], e);
            free(e);
        }
    }
}

const char *sys_translate(const char *domain, const char *str)
{
    trans_cache_t *e, **head;
    int n;
    assert(domain);
    assert(strcmp(domain, "gui") == 0 ||
           strcmp(domain, "sky") == 0 ||
           strcmp(domain, "skyculture") == 0);
    if (!sys_callbacks.translate) return str;

    head = trans_cache_head(domain);
    HASH_FIND_STR(*head, str, e);
    if (e) return e->value;

    n = strlen(str);
    e = calloc(1, sizeof(*e) + n + 1);
    if (!e) return sys_callbacks.translate(sys_callbacks.user, domain, str);
    memcpy(e->key, str, n + 1);
    e->value = sys_callbacks.translate(sys_callbacks.user, domain, str);
    HASH_ADD_STR(*head, key, e);
    return e->value;
}

// Active UI/sky language code (e.g. "en", "zh_cn"), set from JS via
// sys_set_lang. The web frontend has no get_lang callback, so this static
// buffer is the source of truth for sys_get_lang().
static char s_lang[16] = "en";

EMSCRIPTEN_KEEPALIVE
void sys_set_lang(const char *lang)
{
    // ccall(['string']) passes a temporary stack pointer; copy it, because
    // sys_get_lang() hands this string out and it is read every render frame.
    if (!lang || !lang[0]) return;
    snprintf(s_lang, sizeof(s_lang), "%s", lang);
    // The translation cache is keyed only by (domain, str); drop it so the new
    // language's strings are fetched fresh.
    trans_cache_clear();
}

const char *sys_get_lang()
{
    if (sys_callbacks.get_lang) return sys_callbacks.get_lang();
    return s_lang;
}

bool sys_lang_supports_spacing()
{
    // Computed live (no cache): the language can change at runtime via
    // sys_set_lang, and CJK labels must stop being letter-spaced immediately.
    const char *lang = sys_get_lang();
    return strncmp(lang, "ar", 2) != 0 &&
           strncmp(lang, "zh", 2) != 0 &&
           strncmp(lang, "ja", 2) != 0 &&
           strncmp(lang, "ko", 2) != 0;
}

char *sys_render_text(const char *txt, float size, int effects, int align,
                      int *w, int *h, int* xoffset, int* yoffset)
{
    assert(sys_callbacks.render_text);
    return sys_callbacks.render_text(sys_callbacks.user, txt, size, effects,
                                     align, w, h, xoffset, yoffset);
}

EMSCRIPTEN_KEEPALIVE
void sys_set_translate_function(
    const char *(*callback)(void *user, const char *domain, const char *str))
{
    sys_callbacks.translate = callback;
}
