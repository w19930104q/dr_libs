#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define DR_FLAC_IMPLEMENTATION
#include "dr_flac_orig.h"
static void noop_meta(void*u, drflac_metadata*m){(void)u;(void)m;}
static unsigned long fu(unsigned long h,const unsigned char*p,size_t n){size_t i;for(i=0;i<n;++i){h^=p[i];h*=1099511628211UL;}return h;}
typedef struct{int o;unsigned long long f;unsigned long h;}R;
static R run(const unsigned char*d,size_t n,int m){
 R r;drflac*p;drflac_int32 b[4096];drflac_uint64 g;unsigned long h;memset(&r,0,sizeof r);
 p=m?drflac_open_memory_with_metadata(d,n,noop_meta,0,0):drflac_open_memory(d,n,0);if(!p)return r;r.o=1;h=1469598103934665603UL;
 do{g=drflac_read_pcm_frames_s32(p,37,b);if(g){r.f+=g;h=fu(h,(const unsigned char*)b,(size_t)(g*p->channels*4));}}while(g);r.h=h;drflac_close(p);return r;}
int main(int c,char**v){FILE*f=fopen(v[1],"rb");fseek(f,0,2);long sz=ftell(f);fseek(f,0,0);unsigned char*d=malloc(sz);fread(d,1,sz,f);fclose(f);
 long off=atol(v[2]);d[off]^=0xFF;R a=run(d,sz,0),b=run(d,sz,1);
 printf("plain open=%d frames=%llu | meta open=%d frames=%llu | %s\n",a.o,a.f,b.o,b.f,(a.o!=b.o||(a.o&&(a.f!=b.f||a.h!=b.h)))?"MISMATCH":"OK");return 0;}
