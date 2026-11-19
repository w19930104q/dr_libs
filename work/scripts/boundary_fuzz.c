/* Variant of fuzzer restricted to an offset window [lo,hi), stride 1. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define DR_FLAC_IMPLEMENTATION
#include "dr_flac.h"
static void noop_meta(void*u, drflac_metadata*m){(void)u;(void)m;}
static unsigned long fu(unsigned long h,const unsigned char*p,size_t n){size_t i;for(i=0;i<n;++i){h^=p[i];h*=1099511628211UL;}return h;}
typedef struct{int o;unsigned long long f;unsigned long h;}R;
static R run(const unsigned char*d,size_t n,int m){
    R r;drflac*p;drflac_int32 b[4096];drflac_uint64 g;unsigned long h;memset(&r,0,sizeof r);
    p=m?drflac_open_memory_with_metadata(d,n,noop_meta,0,0):drflac_open_memory(d,n,0);
    if(!p)return r;r.o=1;h=1469598103934665603UL;
    do{g=drflac_read_pcm_frames_s32(p,37,b);if(g){r.f+=g;h=fu(h,(const unsigned char*)b,(size_t)(g*p->channels*4));}}while(g);
    r.h=h;drflac_close(p);return r;
}
static int dis(R*a,R*b){if(a->o!=b->o)return 1;if(a->o&&(a->f!=b->f||a->h!=b->h))return 1;return 0;}
int main(int c,char**v){
    if(c!=4)return 2; long lo=atol(v[2]),hi=atol(v[3]);
    FILE*f=fopen(v[1],"rb");fseek(f,0,SEEK_END);long sz=ftell(f);fseek(f,0,SEEK_SET);
    unsigned char*base=malloc(sz),*mut=malloc(sz);fread(base,1,sz,f);fclose(f);
    if(hi>sz)hi=sz;int bad=0,trials=0;long i;
    for(i=lo;i<hi;i++){memcpy(mut,base,sz);mut[i]^=0xFF;R a=run(mut,sz,0),b=run(mut,sz,1);trials++;
        if(dis(&a,&b)){printf("MISMATCH flip@%ld\n",i);if(++bad>=10)break;}}
    for(i=lo;i<hi&&bad<10;i++){R a=run(base,(size_t)i,0),b=run(base,(size_t)i,1);trials++;
        if(dis(&a,&b)){printf("MISMATCH trunc@%ld\n",i);if(++bad>=10)break;}}
    printf("window[%ld,%ld): %d trials %d mismatches\n",lo,hi,trials,bad);
    return bad?1:0;
}
