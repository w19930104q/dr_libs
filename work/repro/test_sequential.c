/* Reproducer/verification harness: sequential vs random-access AIFF decoding. */
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
    int forwardOnly;   /* Reject backwards seeks, but allow SEEK_SET forward. */
    int strictPipe;    /* Like a real pipe: SEEK_SET/SEEK_END always fail; only forward SEEK_CUR works. */
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

static drwav_bool32 on_seek(void* pUserData, int offset, drwav_seek_origin origin)
{
    stream_t* s = (stream_t*)pUserData;
    int64_t target;

    if (s->strictPipe) {
        /* Real pipe: only SEEK_CUR with a non-negative offset is possible. */
        if (origin != DRWAV_SEEK_CUR || offset < 0) {
            return DRWAV_FALSE;
        }
        target = (int64_t)s->pos + offset;
    } else if (origin == DRWAV_SEEK_SET) {
        target = (int64_t)offset;
    } else if (origin == DRWAV_SEEK_CUR) {
        target = (int64_t)s->pos + offset;
    } else {
        if (s->forwardOnly) {
            return DRWAV_FALSE; /* A pipe cannot seek relative to the end. */
        }
        target = (int64_t)s->size + offset;
    }

    if (s->forwardOnly && !s->strictPipe) {
        /* Sequential stream: backwards seeks and SEEK_SET to an earlier position are impossible. */
        if (target < (int64_t)s->pos) {
            return DRWAV_FALSE;
        }
    }

    if (target < 0 || (uint64_t)target > s->size) {
        return DRWAV_FALSE;
    }

    s->pos = (size_t)target;
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

typedef enum
{
    API_F32,
    API_S32,
    API_S16,
    API_RAW
} api_t;

typedef struct
{
    drwav_uint64 frames;
    drwav_uint64 totalPCMFrameCount;
    size_t bytes;
    size_t bytesPerSample;
    unsigned char* data;
} decode_result_t;

static int decode_one(const char* path, int sequential, int strictPipe, api_t api, decode_result_t* out)
{
    size_t fileSize = 0;
    unsigned char* fileData = load_file(path, &fileSize);
    stream_t stream;
    drwav wav;
    drwav_bool32 ok;
    drwav_uint32 bytesPerFrame;
    size_t cap;

    if (fileData == NULL) {
        printf("    cannot open file\n");
        return -1;
    }

    stream.data = fileData;
    stream.size = fileSize;
    stream.pos = 0;
    stream.forwardOnly = sequential;
    stream.strictPipe = strictPipe;

    if (sequential) {
        ok = drwav_init_ex(&wav, on_read, on_seek, NULL, NULL, &stream, NULL, DRWAV_SEQUENTIAL, NULL);
    } else {
        ok = drwav_init(&wav, on_read, on_seek, NULL, &stream, NULL);
    }

    if (!ok) {
        free(fileData);
        return 1; /* "open failed" */
    }

    bytesPerFrame = drwav_get_bytes_per_pcm_frame(&wav);
    out->bytesPerSample = (api == API_F32) ? sizeof(float) : (api == API_S32) ? sizeof(drwav_int32) : (api == API_S16) ? sizeof(drwav_int16) : (bytesPerFrame / wav.channels);
    cap = (size_t)(wav.totalPCMFrameCount * wav.channels * out->bytesPerSample);
    out->data = (unsigned char*)malloc(cap > 0 ? cap : 1);
    out->frames = 0;
    out->totalPCMFrameCount = wav.totalPCMFrameCount;

    /* Read in small batches to make sure nothing relies on whole-file reads. */
    for (;;) {
        drwav_uint64 want = 7;
        drwav_uint64 got = 0;
        size_t elemSize;
        void* dst;

        if (out->frames >= wav.totalPCMFrameCount) {
            break;
        }
        if (want > wav.totalPCMFrameCount - out->frames) {
            want = wav.totalPCMFrameCount - out->frames;
        }

        elemSize = out->bytesPerSample;
        dst = out->data + (size_t)out->frames * wav.channels * elemSize;

        switch (api) {
            case API_F32: got = drwav_read_pcm_frames_f32(&wav, want, (float*)dst); break;
            case API_S32: got = drwav_read_pcm_frames_s32(&wav, want, (drwav_int32*)dst); break;
            case API_S16: got = drwav_read_pcm_frames_s16(&wav, want, (drwav_int16*)dst); break;
            case API_RAW: got = drwav_read_pcm_frames(&wav, want, dst); break;
        }

        if (got == 0) {
            break;
        }
        out->frames += got;
    }

    out->bytes = (size_t)out->frames * wav.channels * out->bytesPerSample;

    drwav_uninit(&wav);
    free(fileData);
    return 0;
}

static void free_result(decode_result_t* r)
{
    free(r->data);
    r->data = NULL;
}

static int run_case(const char* dir, const char* name, int expectSeqOpenFail)
{
    char path[1024];
    const api_t apis[] = { API_F32, API_S32, API_S16, API_RAW };
    const char* api_names[] = { "f32", "s32", "s16", "raw" };
    int failures = 0;
    int i;
    int strict;

    snprintf(path, sizeof(path), "%s/%s", dir, name);
    printf("== %s\n", name);

    for (strict = 0; strict <= 1; ++strict) {
        for (i = 0; i < 4; ++i) {
            decode_result_t ra = {0}, seq = {0};
            int rra, rseq;

            rra  = decode_one(path, 0, 0, apis[i], &ra);
            rseq = decode_one(path, 1, strict, apis[i], &seq);

            if (rra == 1) {
                printf("  [%s/%s] SKIP (random-access open failed too)\n", strict ? "pipe" : "fwd ", api_names[i]);
                continue;
            }
            if (rra != 0) {
                printf("  [%s/%s] ERROR random-access harness failure\n", strict ? "pipe" : "fwd ", api_names[i]);
                failures++;
                continue;
            }

            if (rseq == 1) {
                if (expectSeqOpenFail) {
                    printf("  [%s/%s] OK  (sequential open rejected as expected)\n", strict ? "pipe" : "fwd ", api_names[i]);
                } else {
                    printf("  [%s/%s] FAIL sequential open failed\n", strict ? "pipe" : "fwd ", api_names[i]);
                    failures++;
                }
                free_result(&ra);
                continue;
            }
            if (rseq != 0) {
                printf("  [%s/%s] FAIL sequential harness error\n", strict ? "pipe" : "fwd ", api_names[i]);
                failures++;
                free_result(&ra);
                continue;
            }

            if (seq.frames != ra.frames || seq.totalPCMFrameCount != ra.totalPCMFrameCount) {
                printf("  [%s/%s] FAIL frame count: seq=%llu (total=%llu) ra=%llu (total=%llu)\n", strict ? "pipe" : "fwd ", api_names[i],
                    (unsigned long long)seq.frames, (unsigned long long)seq.totalPCMFrameCount,
                    (unsigned long long)ra.frames, (unsigned long long)ra.totalPCMFrameCount);
                failures++;
            } else if (seq.bytes != ra.bytes || memcmp(seq.data, ra.data, ra.bytes) != 0) {
                printf("  [%s/%s] FAIL sample mismatch over %llu frames\n", strict ? "pipe" : "fwd ", api_names[i], (unsigned long long)ra.frames);
                failures++;
            } else {
                printf("  [%s/%s] PASS %llu frames, identical output\n", strict ? "pipe" : "fwd ", api_names[i], (unsigned long long)ra.frames);
            }

            free_result(&ra);
            free_result(&seq);
        }
    }

    return failures;
}

int main(int argc, char** argv)
{
    const char* dir;
    int totalFailures = 0;
    size_t i;

    struct { const char* name; int expectSeqOpenFail; } cases[] = {
        { "aiff_pcm16be_st.aiff",       0 },
        { "aiff_pcm8s_mono.aiff",       0 },
        { "aiff_pcm24be_st.aiff",       0 },
        { "aifc_sowt16_st.aifc",        0 },
        { "aifc_sowt24_mono.aifc",      0 },
        { "aifc_fl32_st.aifc",          0 },
        { "aifc_fl64_mono.aifc",        0 },
        { "aiff_pcm16be_offset.aiff",   0 },
        { "aifc_fl32_offset.aifc",      0 },
        { "aifc_sowt16_ssndfirst.aifc", 0 },
        { "aifc_fl32_ssndfirst.aifc",   0 },
        { "aiff_pcm16be_ssndfirst_offset.aiff", 0 },
        { "aifc_sowt24_ssndfirst.aifc", 0 },
        { "aifc_fl64_ssndfirst.aifc",   0 },
        { "aiff_pcm8s_ssndfirst.aiff",  0 },
        { "aifc_fl32_ssndfirst_extra.aifc", 0 },
        { "wav_pcm16le_st.wav",         0 },
    };

    if (argc < 2) {
        printf("usage: %s <data-dir>\n", argv[0]);
        return 2;
    }
    dir = argv[1];

    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        totalFailures += run_case(dir, cases[i].name, cases[i].expectSeqOpenFail);
    }

    printf("\n%s\n", totalFailures == 0 ? "ALL PASS" : "FAILURES PRESENT");
    return totalFailures == 0 ? 0 : 1;
}
