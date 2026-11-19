#define _POSIX_C_SOURCE 199309L
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#define DR_FLAC_IMPLEMENTATION
#include "dr_flac_orig.h"
static void nm(void*u,drflac_metadata*m){(void)u;(void)m;}
int main(int c,char**v){
 FILE*f=fopen(v[1],"rb");fseek(f,0,2);long sz=ftell(f);fseek(f,0,0);
 unsigned char*d=malloc(sz);fread(d,1,sz,f);fclose(f);
 int iters=atoi(v[2]),i,meta=atoi(v[3]);
 struct timespec a,b; clock_gettime(CLOCK_MONOTONIC,&a);
 drflac_int32 buf[8192];
 for(i=0;i<iters;i++){
   drflac*p=meta?drflac_open_memory_with_metadata(d,sz,nm,0,0):drflac_open_memory(d,sz,0);
   if(!p)return 3; drflac_uint64 g; do{g=drflac_read_pcm_frames_s32(p,4096,buf);}while(g); drflac_close(p);
 }
 clock_gettime(CLOCK_MONOTONIC,&b);
 double ms=(b.tv_sec-a.tv_sec)*1e3+(b.tv_nsec-a.tv_nsec)/1e6;
 printf("%s meta=%d: %.1f ms total, %.3f ms/iter\n",v[1],meta,ms,ms/iters);
 return 0;}
