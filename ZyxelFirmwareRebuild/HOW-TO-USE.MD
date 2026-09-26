**How To Use ZyxelUnlocker** : by (username)

First of all you will need WSL
https://learn.microsoft.com/en-us/windows/wsl/install
you can learn how to install it here

i personally had debian already installed so i used that



Then you just need to open it in the path where you have all 3 .py files


---


## What each file does

Full write-up is in `Research.pdf` if you want the deep dive. Short version:

- **`FirmwareExtract.py`**  takes the first `.bin` in `Firmware/`, splits
  off the last 1024 bytes (Zyxel wfi_tag) into `Work/tag.bin`, saves the
  UBI body as `Work/body.bin`, then peels each UBI volume out as a raw
  payload into `Work/vols/*.ubifs`, and walks the `rootfs_ubifs` volume
  into a full file tree at `Work/rootfs/`. Path-traversal warnings from
  ubireader are filtered out because Broadcom's rootfs has symlinks
  pointing outside the tree (into `/rom`, `/proc`, `/var`) that ubireader
  safely drops.

- **`FirmwareRebuild.py`**  takes `Work/rootfs/` and repacks it into a
  fresh UBI body at the AX7501-B0's true NAND geometry (4 KiB page,
  256 KiB PEB). Before repacking it fixes what ubireader stripped: exec
  bits on binaries and init scripts, file capabilities on vendor daemons,
  symlinks from `/usr/lib` into `/lib` so the dynamic linker still finds
  the vendor `.so` files after caps strip `LD_LIBRARY_PATH`, and
  chown-to-root so setuid transitions land on UID 0. `mkfs.ubifs` bakes a
  device table into the rebuilt UBIFS (`/dev/console`, `/dev/null`, ttys,
  etc.) so preinit doesn't fault on `mknod` at boot. `ubinize` wraps four
  volumes back into a single body, keeping the vol_ids/types/names
  identical to stock (`rootfs_ubifs`, `filestruct_full.bin`, `METADATA`,
  `METADATACOPY`) so CFE's `ubi_find_file` still locates `vmlinux.lz` on
  the next boot. Output: `Rebuild/body.bin`.

- **`FirmwarePatch.py`**  rewrites the wfi_tag: sets `wfiFlashType` to
  NAND256 (what the on-device loader checks against the detected block
  size), recomputes the Broadcom CRC32 over the new body, then folds the
  entire tag into the 16-bit Zyxel checksum at offset `0x3FE` (has to be
  the last write since every earlier field feeds into it). Concatenates
  the patched tag onto the body and emits `Rebuild/unlocked.bin` — the
  flash-ready image.


## Layout

```
ZyxelFirmwareRebuild/
  Firmware/                <-- drop stock .bin here
  Work/                    <-- auto-populated by Extract
    body.bin
    tag.bin
    vols/*.ubifs
    rootfs/...
  Rebuild/                 <-- auto-populated by Rebuild + Patch
    rootfs.ubifs
    devtable.txt
    ubinize.ini
    body.bin
    unlocked.bin           <-- flash this
  FirmwareExtract.py
  FirmwareRebuild.py
  FirmwarePatch.py
  HOW-TO-USE.md
  Research.pdf
```


## Steps

Inside WSL, from the folder that contains all three `.py` files:

```bash
sudo apt install -y mtd-utils libcap2-bin python3-pip
pip3 install ubi_reader

python3 FirmwareExtract.py     # Firmware/*.bin   ->  Work/
python3 FirmwareRebuild.py     # Work/rootfs/     ->  Rebuild/body.bin
python3 FirmwarePatch.py       # Rebuild/body.bin ->  Rebuild/unlocked.bin
```

`FirmwareRebuild.py` will prompt for your sudo password (setcap on the
vendor binaries and chown to root both need root).


## Flashing

Copy `Rebuild/unlocked.bin` somewhere your Windows TFTP server (I used
tftpd64) is serving from. Set your PC's Ethernet NIC to a static
`192.168.1.33` (that's the host IP CFE reads from NVRAM), then interrupt
CFE by mashing a key during boot and run:

```
CFE> ATUR 192.168.1.33:unlocked.bin
CFE> ATGO
```

OR use ftp with direct connection (run the followintg)
```
ftp 192.168.1.1
(when prompted for password enter sticker admin password)
bin
cd fw
put pathtoyourpayload.bin fw.bin
```
If you have access to ftp i would recommend this


## Why any of this is necessary

Full derivation in `Research.pdf`. Short version: the stock ABPC.8 image
ships with 2 KiB page / 128 KiB PEB UBI geometry, but the AX7501-B0's
Macronix NAND is 4 KiB page / 256 KiB PEB. The kernel's UBI attach
hard-rejects the mismatch (`bad VID header offset 2048, expected 4096`)
and panics before mounting the rootfs. Fixing it means rebuilding the
UBIFS itself (LEB size is baked into the filesystem at mkfs time),
re-wrapping it in a new UBI container at the correct geometry, and
re-signing the tag the on-device validator checks three separate
stages, one script each.
