/* Harness over the drflac_read/seek/tell callback API (including relaxed
   variants) rather than the memory API. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DR_FLAC_IMPLEMENTATION
#include "dr_flac.h"

typedef struct { const unsigned char* data; size_t size; size_t pos; } mem_t;

static size_t on_read(void* p, void* buf, size_t n)
{
    mem_t* m = (mem_t*)p;
    size_t avail = (m->pos < m->size) ? (m->size - m->pos) : 0;
    size_t take = n < avail ? n : avail;
    memcpy(buf, m->data + m->pos, take);
    m->pos += take;
    return take;
}
static drflac_bool32 on_seek(void* p, int off, drflac_seek_origin origin)
{
    mem_t* m = (mem_t*)p;
    if (origin == DRFLAC_SEEK_SET) m->pos = (size_t)off;
    else m->pos += (size_t)off;
    return m->pos <= m->size;
}
static drflac_bool32 on_tell(void* p, drflac_int64* pos)
{
    mem_t* m = (mem_t*)p;
    *pos = (drflac_int64)m->pos;
    return DRFLAC_TRUE;
}

static unsigned long fu(unsigned long h, const unsigned char* p, size_t n)
{ size_t i; for (i=0;i<n;++i){h^=p[i];h*=1099511628211UL;} return h; }

typedef struct { int opened; unsigned long long frames; unsigned long hash; } result_t;

static result_t run(const unsigned char* data, size_t size, int mode)
{
    result_t r; mem_t m; drflac* pFlac = NULL; drflac_int32 b[4096];
    drflac_uint64 g; unsigned long h;
    memset(&r, 0, sizeof(r));
    m.data = data; m.size = size; m.pos = 0;

    switch (mode) {
        case 0: pFlac = drflac_open(on_read, on_seek, on_tell, &m, NULL); break;
        case 1: pFlac = drflac_open_with_metadata(on_read, on_seek, on_tell, NULL, &m, NULL); break;
        case 2: pFlac = drflac_open_relaxed(on_read, on_seek, on_tell, drflac_container_ogg, &m, NULL); break;
        case 3: pFlac = drflac_open_with_metadata_relaxed(on_read, on_seek, on_tell, NULL, drflac_container_ogg, &m, NULL); break;
    }
    if (!pFlac) return r;
    r.opened = 1; h = 1469598103934665603UL;
    do {
        g = drflac_read_pcm_frames_s32(pFlac, 37, b);
        if (g) { r.frames += g; h = fu(h, (const unsigned char*)b, (size_t)(g * pFlac->channels * 4)); }
    } while (g);
    r.hash = h;
    drflac_close(pFlac);
    return r;
}

int main(int argc, char** argv)
{
    FILE* f; long sz; unsigned char* data; int mode, bad = 0;
    if (argc != 2) return 2;
    f = fopen(argv[1], "rb"); fseek(f,0,SEEK_END); sz = ftell(f); fseek(f,0,SEEK_SET);
    data = malloc((size_t)sz); fread(data,1,(size_t)sz,f); fclose(f);

    for (mode = 0; mode < 4; ++mode) {
        result_t r = run(data, (size_t)sz, mode);
        printf("  mode%d: open=%d frames=%llu hash=%016lx\n", mode, r.opened, r.frames, r.hash);
    }
    /* strict vs with-metadata (modes 0,1) must agree; relaxed pair (2,3) must agree */
    {
        result_t a = run(data, (size_t)sz, 0), b = run(data, (size_t)sz, 1);
        if (a.opened != b.opened || (a.opened && (a.frames != b.frames || a.hash != b.hash))) {
            printf("  MISMATCH strict pair\n"); bad = 1;
        }
        result_t c = run(data, (size_t)sz, 2), d = run(data, (size_t)sz, 3);
        if (c.opened != d.opened || (c.opened && (c.frames != d.frames || c.hash != d.hash))) {
            printf("  MISMATCH relaxed pair\n"); bad = 1;
        }
    }
    printf("  %s\n", bad ? "DIVERGENCE" : "OK: consistent");
    free(data);
    return bad;
}
