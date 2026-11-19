/* In-process fuzzer: for every mutation of the metadata region, confirm
   drflac_open_memory and drflac_open_memory_with_metadata agree on open
   status and on every decoded sample. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DR_FLAC_IMPLEMENTATION
#include "dr_flac_orig.h"

static void noop_meta(void* pUserData, drflac_metadata* pMetadata)
{
    (void)pUserData;
    (void)pMetadata;
}

static unsigned long fnv1a_update(unsigned long h, const unsigned char* p, size_t n)
{
    size_t i;
    for (i = 0; i < n; ++i) { h ^= p[i]; h *= 1099511628211UL; }
    return h;
}

typedef struct { int opened; unsigned long long frames; unsigned long hash; } result_t;

static result_t run(const unsigned char* data, size_t size, int withMeta)
{
    result_t r;
    drflac* pFlac;
    drflac_int32 buffer[4096];
    drflac_uint64 framesRead;
    unsigned long h;
    memset(&r, 0, sizeof(r));

    if (withMeta) pFlac = drflac_open_memory_with_metadata(data, size, noop_meta, NULL, NULL);
    else          pFlac = drflac_open_memory(data, size, NULL);
    if (!pFlac) return r;

    r.opened = 1;
    h = 1469598103934665603UL;
    do {
        framesRead = drflac_read_pcm_frames_s32(pFlac, 37, buffer);
        if (framesRead > 0) {
            r.frames += framesRead;
            h = fnv1a_update(h, (const unsigned char*)buffer,
                (size_t)(framesRead * pFlac->channels * sizeof(drflac_int32)));
        }
    } while (framesRead > 0);
    r.hash = h;
    drflac_close(pFlac);
    return r;
}

static int disagree(const result_t* a, const result_t* b)
{
    if (a->opened != b->opened) return 1;
    if (a->opened && (a->frames != b->frames || a->hash != b->hash)) return 1;
    return 0;
}

int main(int argc, char** argv)
{
    FILE* f; long sz; unsigned char* base; unsigned char* mut;
    long metaEnd, stride, i; int mismatches = 0, trials = 0;

    if (argc != 4) { fprintf(stderr, "usage: %s file metaEnd stride\n", argv[0]); return 2; }
    metaEnd = atol(argv[2]);
    stride = atol(argv[3]);

    f = fopen(argv[1], "rb");
    if (!f) { perror("fopen"); return 2; }
    fseek(f, 0, SEEK_END); sz = ftell(f); fseek(f, 0, SEEK_SET);
    if (metaEnd <= 0 || metaEnd > sz) metaEnd = sz;
    base = (unsigned char*)malloc((size_t)sz);
    mut  = (unsigned char*)malloc((size_t)sz);
    if (fread(base, 1, (size_t)sz, f) != (size_t)sz) { fprintf(stderr, "short read\n"); return 2; }
    fclose(f);

    /* Single-byte flips across the metadata region. */
    for (i = 0; i < metaEnd; i += stride) {
        result_t a, b;
        memcpy(mut, base, (size_t)sz);
        mut[i] ^= 0xFF;
        a = run(mut, (size_t)sz, 0);
        b = run(mut, (size_t)sz, 1);
        trials++;
        if (disagree(&a, &b)) {
            printf("MISMATCH flip@%ld plain(open=%d frames=%llu h=%016lx) meta(open=%d frames=%llu h=%016lx)\n",
                i, a.opened, a.frames, a.hash, b.opened, b.frames, b.hash);
            if (++mismatches >= 20) break;
        }
    }

    /* Truncations across the metadata region. */
    for (i = 0; i < metaEnd && mismatches < 20; i += stride) {
        result_t a, b;
        a = run(base, (size_t)i, 0);
        b = run(base, (size_t)i, 1);
        trials++;
        if (disagree(&a, &b)) {
            printf("MISMATCH trunc@%ld plain(open=%d frames=%llu h=%016lx) meta(open=%d frames=%llu h=%016lx)\n",
                i, a.opened, a.frames, a.hash, b.opened, b.frames, b.hash);
            if (++mismatches >= 20) break;
        }
    }

    printf("%s: %d trials, %d mismatches\n", argv[1], trials, mismatches);
    free(base); free(mut);
    return mismatches ? 1 : 0;
}
