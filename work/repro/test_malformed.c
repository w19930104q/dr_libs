/* Failure-path robustness: malformed files must fail cleanly with no leak/crash under ASan. */
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
} stream_t;

static size_t on_read(void* pUserData, void* pBufferOut, size_t bytesToRead)
{
    stream_t* s = (stream_t*)pUserData;
    size_t avail = s->size - s->pos;
    if (bytesToRead > avail) {
        bytesToRead = avail;
    }
    if (bytesToRead > 0) {
        memcpy(pBufferOut, s->data + s->pos, bytesToRead);
    }
    s->pos += bytesToRead;
    return bytesToRead;
}

/* Strict pipe: only forward SEEK_CUR. */
static drwav_bool32 on_seek(void* pUserData, int offset, drwav_seek_origin origin)
{
    stream_t* s = (stream_t*)pUserData;
    if (origin != DRWAV_SEEK_CUR || offset < 0) {
        return DRWAV_FALSE;
    }
    if ((uint64_t)s->pos + offset > s->size) {
        return DRWAV_FALSE;
    }
    s->pos += offset;
    return DRWAV_TRUE;
}

static unsigned char* load_file(const char* path, size_t* pSize)
{
    FILE* f = fopen(path, "rb");
    if (f == NULL) {
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char* p = (unsigned char*)malloc((size_t)n);
    if (fread(p, 1, (size_t)n, f) != (size_t)n) {
        free(p);
        fclose(f);
        return NULL;
    }
    fclose(f);
    *pSize = (size_t)n;
    return p;
}

int main(int argc, char** argv)
{
    int i;
    const char* files[] = {
        "mal_ssndfirst_truncated.aifc",
        "mal_ssndfirst_nocomm.aifc",
        "mal_ssnd_huge.aifc",
        "mal_ssnd_badoffset.aifc",
        "mal_ssnd_cut_early.aifc",
        "mal_ssnd_odd_padding.aifc",
        "mal_ssnd_empty.aifc",
    };

    if (argc < 2) {
        printf("usage: %s <data-dir>\n", argv[0]);
        return 2;
    }

    for (i = 0; i < (int)(sizeof(files) / sizeof(files[0])); ++i) {
        char path[1024];
        size_t size;
        unsigned char* data;
        stream_t s;
        drwav wav;
        drwav_bool32 ok;

        snprintf(path, sizeof(path), "%s/%s", argv[1], files[i]);
        data = load_file(path, &size);
        if (data == NULL) {
            printf("%s: missing\n", files[i]);
            continue;
        }

        s.data = data;
        s.size = size;
        s.pos = 0;
        ok = drwav_init_ex(&wav, on_read, on_seek, NULL, NULL, &s, NULL, DRWAV_SEQUENTIAL, NULL);
        if (ok) {
            /* If it somehow opens, drain it to exercise the replay path, then close. */
            float buf[256];
            while (drwav_read_pcm_frames_f32(&wav, 16, buf) > 0) {
            }
            drwav_uninit(&wav);
            printf("%s: opened and drained cleanly\n", files[i]);
        } else {
            printf("%s: rejected cleanly\n", files[i]);
        }
        free(data);
    }

    printf("robustness done\n");
    return 0;
}
