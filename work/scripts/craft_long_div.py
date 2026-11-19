import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oggtool import parse_pages
from craft_multiblock import make_page, crc_ogg, flac_block_header
GEN="/home/liiing/feedback/uid28350/work/gen"; CASES="/home/liiing/feedback/uid28350/work/cases"
ref=open(os.path.join(GEN,"long.oga"),"rb").read(); rp=parse_pages(ref)
serial=rp[0].serial; seq=0
p0=bytes(rp[0].raw); seq+=1
vc=struct.pack("<I",5)+b"hello"+struct.pack("<I",0)
p1=make_page(serial,seq,0,0,[flac_block_header(4,len(vc),False)+vc]); seq+=1
FULL=255*255; piece2=6000
payload=(FULL-4)+piece2
hdr=flac_block_header(100,payload,last=True)
p2=make_page(serial,seq,0,0,[hdr+b"\xAA"*(FULL-4)],continues=True); seq+=1
p3=make_page(serial,seq,1,0,[b"\xAA"*piece2]); seq+=1
audio=[]
for ap in rp[2:]:
    h=b"OggS"+bytes([0,ap.header_type])+struct.pack("<q",ap.granule)
    h+=struct.pack("<II",serial,seq)+struct.pack("<I",0)+bytes([len(ap.seg_table)])+bytes(ap.seg_table)
    pg=bytearray(h+bytes(ap.body)); struct.pack_into("<I",pg,22,crc_ogg(bytes(pg)))
    audio.append(bytes(pg)); seq+=1
clean=b"".join([p0,bytes(p1),bytes(p2),bytes(p3)]+audio)
open(os.path.join(CASES,"j_long_clean.oga"),"wb").write(clean)
pages=parse_pages(clean); pages[3].raw[pages[3].body_off+100]^=0xFF
open(os.path.join(CASES,"j_long_lastpage_crc.oga"),"wb").write(b"".join(bytes(p.raw) for p in pages))
# also corrupt first page of unknown block
pages=parse_pages(clean); pages[2].raw[pages[2].body_off+50000]^=0xFF
open(os.path.join(CASES,"j_long_firstpage_crc.oga"),"wb").write(b"".join(bytes(p.raw) for p in pages))
print("crafted long divergence cases", len(clean))
