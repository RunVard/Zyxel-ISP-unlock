# Zyxel AX7501-B0 Firmware Unpacker, Patcher & Repacker

A set of python scripts and all the reasearch going with it to : Unpack official firmware images for **ZYxel** Adjust the bootloader compatibility and repack images that you will be able to flash to your router.


**⚠️ TESTING WAS DONE ON A ZYXEL AX7501-B0 I do not know if this will work on other models OR even on differently configured versions of this exact router**

---


## ⚠️ Legal & Safety Notice

* **No Proprietary Binaries Included:** This repository contains **only open-source Python scripts and documentation**. It does not distribute Zyxel firmware, proprietary drivers, or copyrighted blobs. Users must obtain their own base firmware files directly from official sources.
* **Device Ownership & ISP Agreements:** You should only perform this procedure on hardware that you legally own. If your router is leased, rented, or on loan from an ISP, modifying its firmware may violate your terms of service or result in equipment non-return fees.
* **Risk of Bricking:** Modifying flash images and bootloader headers carries inherent hardware risk. Always ensure you have a way to recover (such as serial/UART access) before flashing custom or repacked partitions. Proceed entirely at your own risk.


---


## What This Toolset Does

1. **Extract & Decompile:** Unpacks the outer firmware container and extracts the internal `UBIFS` rootfs partitions.
2. **Bootloader & Model Identification Patching:** Modifies the specific header/model identification bytes (e.g., vendor/model magic bytes) so the onboard CFE/U-Boot bootloader validates and accepts generic or custom images.
3. **Recompression & Alignment:** Repacks the file system into standard block-aligned images (supporting 256 KB PEB / 4096 KB boundaries required by the flash controller).


---


## Prerequisites & Dependencies
- WSL or a linux VM or a linux machine (the tools used in this scenario where used on WSL)
- Either a USB->UART board or a rasberry pi + the cables to go in between (Not necesarry depending on how locked down your device is) (testing in this case was made with a rasberry pi 3 since the device did not give acces to ssh/ftp services directly)
- one or multiple ethernet cables
- Python 3.xx
