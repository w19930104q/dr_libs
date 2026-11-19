/* Harness: compare drflac_open_memory vs drflac_open_memory_with_metadata
   on the same (possibly corrupted) input. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DR_FLAC_IMPLEMENTATION
#include "dr_flac_dbg.h"

static unsigned long g_metaCalls;

static void on_meta(void* pUserData, drflac_metadata* pMetadata)
{
    (void)pUserData; (void)pMetadata;
    g_metaCalls++;
}

static unsigned long fnv1a_update(unsigned long h, const unsigned char* p, size_t n)
{
    size_t i;
    for (i = 0; i < n; ++i) { h ^= p[i]; h *= 1099511628211UL; }
    return h;
}

typedef struct
{
    int opened;
    unsigned long long frames;
    unsigned long hash;
    int channels;
    int sampleRate;
    unsigned long long totalPCMFrameCount;
    unsigned long metaCalls;
} result_t;

static result_t run(const unsigned char* data, size_t size, int withMeta)
{
    result_t r;
    drflac* pFlac;

    memset(&r, 0, sizeof(r));
    g_metaCalls = 0;

    if (withMeta) {
        pFlac = drflac_open_memory_with_metadata(data, size, on_meta, NULL, NULL);
        r.metaCalls = g_metaCalls;
    } else {
        pFlac = drflac_open_memory(data, size, NULL);
    }

    if (pFlac == NULL) {
        return r;
    }

    r.opened = 1;
    r.channels = pFlac->channels;
    r.sampleRate = pFlac->sampleRate;
    r.totalPCMFrameCount = pFlac->totalPCMFrameCount;

    {
        /* Read in chunks so truncation mid-stream is exercised. */
        enum { CHUNK = 37 };
        drflac_int32 buffer[4096];
        drflac_uint64 framesRead;
        unsigned long h = 1469598103934665603UL;
        do {
            framesRead = drflac_read_pcm_frames_s32(pFlac, CHUNK, buffer);
            if (framesRead > 0) {
                r.frames += framesRead;
                h = fnv1a_update(h, (const unsigned char*)buffer,
                    (size_t)(framesRead * pFlac->channels * sizeof(drflac_int32)));
            }
        } while (framesRead > 0);
        r.hash = h;
    }

    drflac_close(pFlac);
    return r;
}

int main(int argc, char** argv)
{
    FILE* f;
    long sz;
    unsigned char* data;
    result_t a, b;

    if (argc != 2) { fprintf(stderr, "usage: %s file\n", argv[0]); return 2; }

    f = fopen(argv[1], "rb");
    if (!f) { perror("fopen"); return 2; }
    fseek(f, 0, SEEK_END); sz = ftell(f); fseek(f, 0, SEEK_SET);
    data = (unsigned char*)malloc((size_t)sz);
    if (fread(data, 1, (size_t)sz, f) != (size_t)sz) { fprintf(stderr, "short read\n"); return 2; }
    fclose(f);

    a = run(data, (size_t)sz, 0);
    b = run(data, (size_t)sz, 1);

    printf("file=%s size=%ld\n", argv[1], sz);
    printf("  plain : open=%d frames=%llu hash=%016lx ch=%d sr=%d total=%llu\n",
        a.opened, a.frames, a.hash, a.channels, a.sampleRate, a.totalPCMFrameCount);
    printf("  meta  : open=%d frames=%llu hash=%016lx ch=%d sr=%d total=%llu metacb=%lu\n",
        b.opened, b.frames, b.hash, b.channels, b.sampleRate, b.totalPCMFrameCount, b.metaCalls);

    if (a.opened != b.opened) {
        printf("  MISMATCH: open status differs\n");
    } else if (a.opened && (a.frames != b.frames || a.hash != b.hash)) {
        printf("  MISMATCH: decoded samples differ\n");
    } else {
        printf("  OK: consistent\n");
    }

    free(data);
    return 0;
}
