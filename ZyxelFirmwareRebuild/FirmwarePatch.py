#!/usr/bin/env python3
"""FirmwarePatch.py - Rewrites the Zyxel wfi_tag so the loader accepts the rebuilt body"""

import struct
import sys
import zlib
from pathlib import Path


SCRIPT_DIR  = Path(__file__).parent.resolve()
WORK_DIR    = SCRIPT_DIR / "Work"
REBUILD_DIR = SCRIPT_DIR / "Rebuild"


# wfi_tag offsets and constants.
TAG_LEN            = 1024
OFF_WFI_CRC        = 0x000     # u32, Broadcom CRC32 over the body
OFF_WFI_FLASH_TYPE = 0x00C     # u32, NAND size enum (3=NAND128, 4=NAND256, ...)
OFF_ZYXEL_CK       = 0x3FE     # u16, Zyxel-appended fold-16 checksum

WFI_FLASH_NAND256  = 4         # AX7501-B0 target




def zyxel_checksum(buf):
    # Sum-of-bytes into a 32-bit accumulator, then fold to 16 bits.
    s = 0
    for b in buf:
        s = (s + b) & 0xFFFFFFFF
    return (s + (s >> 16)) & 0xFFFF




def bcm_crc32(buf):
    # Standard poly 0xEDB88320, init 0xFFFFFFFF, refin/refout, NO final XOR.
    return (zlib.crc32(buf) ^ 0xFFFFFFFF) & 0xFFFFFFFF




def patch_tag(tag_bytes, body_bytes):
    tag = bytearray(tag_bytes)

    # Order matters: flashType and CRC first, zyxelChecksum last (it folds
    # the rest of the tag including the two writes above).
    struct.pack_into("<I", tag, OFF_WFI_FLASH_TYPE, WFI_FLASH_NAND256)
    struct.pack_into("<I", tag, OFF_WFI_CRC,        bcm_crc32(body_bytes))
    struct.pack_into("<H", tag, OFF_ZYXEL_CK,
                     zyxel_checksum(bytes(tag[:OFF_ZYXEL_CK])))

    return bytes(tag)




def main():
    tag_in   = WORK_DIR / "tag.bin"
    body_in  = REBUILD_DIR / "body.bin"
    unlocked = REBUILD_DIR / "unlocked.bin"

    if not tag_in.is_file():
        sys.exit(f"[-] {tag_in} not found. Run FirmwareExtract.py first.")
    if not body_in.is_file():
        sys.exit(f"[-] {body_in} not found. Run FirmwareRebuild.py first.")


    print("[*] ZyxelFirmware Patch stage")
    print(f"[*] tag:  {tag_in.relative_to(SCRIPT_DIR)}")
    print(f"[*] body: {body_in.relative_to(SCRIPT_DIR)}\n")


    tag  = tag_in.read_bytes()
    body = body_in.read_bytes()

    print("[*] Recomputing wfi_tag fields")
    print("      flashType     -> NAND256 (4)")
    print(f"      wfiCrc        -> 0x{bcm_crc32(body):08x}")
    new_tag = patch_tag(tag, body)
    print(f"      zyxelChecksum -> 0x{struct.unpack_from('<H', new_tag, OFF_ZYXEL_CK)[0]:04x}")


    unlocked.write_bytes(body + new_tag)
    total = len(body) + len(new_tag)

    print()
    print(f"[+] unlocked.bin  ({total:>12,} bytes / {total / 1024 / 1024:.2f} MiB)")
    print(f"[?] You can now flash to your router using either CFE> shell or trough FTP")




if __name__ == "__main__":
    main()
