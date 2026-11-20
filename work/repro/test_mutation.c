/* Mutation smoke test: corrupted files must not crash/hang/leak in either init mode. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define DRWAV_IMPLEMENTATION
#include "dr_wav.h"

typedef struct
{
    const drwav_uint8* data;
    size_t size;
    size_t pos;
    int pipe;
} stream_t;

static size_t on_read(void* u, void* b, size_t n)
{
    stream_t* s = (stream_t*)u;
    size_t a = s->size - s->pos;
    if (n > a) n = a;
    if (n) memcpy(b, s->data + s->pos, n);
    s->pos += n;
    return n;
}

static drwav_bool32 on_seek(void* u, int off, drwav_seek_origin o)
{
    stream_t* s = (stream_t*)u;
    if (s->pipe) {
        if (o != DRWAV_SEEK_CUR || off < 0) return DRWAV_FALSE;
    }
    int64_t t = o == DRWAV_SEEK_SET ? off : o == DRWAV_SEEK_CUR ? (int64_t)s->pos + off : (int64_t)s->size + off;
    if (t < 0 || (uint64_t)t > s->size) return DRWAV_FALSE;
    if (s->pipe && t < (int64_t)s->pos) return DRWAV_FALSE;
    s->pos = (size_t)t;
    return DRWAV_TRUE;
}

static unsigned char* load(const char* p, size_t* n)
{
    FILE* f = fopen(p, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long z = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char* d = (unsigned char*)malloc((size_t)z);
    if (fread(d, 1, (size_t)z, f) != (size_t)z) { free(d); fclose(f); return NULL; }
    fclose(f);
    *n = (size_t)z;
    return d;
}

static uint32_t rng_state = 0x12345678u;
static uint32_t xrnd(void)
{
    uint32_t x = rng_state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    rng_state = x;
    return x;
}

static void exercise(drwav_uint8* data, size_t size, int pipe)
{
    stream_t s = { data, size, 0, pipe };
    drwav w;
    drwav_bool32 ok = pipe
        ? drwav_init_ex(&w, on_read, on_seek, NULL, NULL, &s, NULL, DRWAV_SEQUENTIAL, NULL)
        : drwav_init(&w, on_read, on_seek, NULL, &s, NULL);
    if (ok) {
        float buf[512];
        int guard = 0;
        for (;;) {
            drwav_uint64 g = drwav_read_pcm_frames_f32(&w, 1 + (xrnd() % 31), buf);
            if (g == 0) break;
            if (++guard > 100000) break; /* hang protection */
        }
        drwav_uninit(&w);
    }
}

int main(int argc, char** argv)
{
    int i, m;
    if (argc < 2) { printf("usage: %s file ...\n", argv[0]); return 2; }

    for (i = 1; i < argc; ++i) {
        size_t size;
        unsigned char* base = load(argv[i], &size);
        if (!base) { printf("%s: missing\n", argv[i]); continue; }

        for (m = 0; m < 300; ++m) {
            unsigned char* buf = (unsigned char*)malloc(size);
            memcpy(buf, base, size);

            /* Apply 1-4 random mutations. */
            int nmut = 1 + (xrnd() % 4);
            int k;
            for (k = 0; k < nmut; ++k) {
                int kind = xrnd() % 3;
                if (size == 0) break;
                size_t pos = xrnd() % size;
                if (kind == 0) {
                    buf[pos] = (unsigned char)xrnd();                 /* flip/set byte */
                } else if (kind == 1 && size > 4) {
                    size_t len = 1 + (xrnd() % (size - pos > 8 ? 8 : size - pos));
                    memset(buf + pos, (int)(xrnd() & 0xFF), len);     /* spray */
                } else {
                    buf[pos] ^= (unsigned char)(1u << (xrnd() % 8));  /* bit flip */
                }
            }

            /* Also test random truncations. */
            size_t effSize = size;
            if ((xrnd() % 3) == 0 && size > 12) {
                effSize = 12 + (xrnd() % (size - 12));
            }

            exercise(buf, effSize, 1);  /* sequential, strict pipe */
            exercise(buf, effSize, 0);  /* random access */
            free(buf);
        }
        free(base);
        printf("%s: 300 mutations x2 modes OK\n", argv[i]);
    }
    printf("mutation smoke done\n");
    return 0;
}
