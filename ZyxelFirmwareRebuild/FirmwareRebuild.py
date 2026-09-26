#!/usr/bin/env python3
"""FirmwareRebuild.py - Zyxel firmware rebuilder"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR   = Path(__file__).parent.resolve()
WORK_DIR     = SCRIPT_DIR / "Work"
REBUILD_DIR  = SCRIPT_DIR / "Rebuild"


# AX7501-B0 target NAND geometry (Macronix MX30LF4G28AD).
UBI_PEB_SIZE       = 262144    # 256 KiB erase block
UBI_PAGE_SIZE      = 4096      # 4 KiB page (min I/O)
UBI_SUBPAGE_SIZE   = 4096
UBI_LEB_SIZE       = UBI_PEB_SIZE - 2 * UBI_PAGE_SIZE   # 253952
UBIFS_MAX_LEB      = 400
UBIFS_JOURNAL_SIZE = 4 * 1024 * 1024
UBIFS_COMPRESSION  = "zlib"


# Volume layout, vol_ids and types verified against the stock ABPC.8 image
# with `ubireader_display_info`. rootfs_ubifs is left DYNAMIC (stock ships
# it static) so kernel mounts it R/W and preinit's mounts/mknods succeed.
STOCK_VOL_TABLE = {
    "rootfs_ubifs":        {"vol_id": 0,  "vol_type": "dynamic"},
    "METADATA":            {"vol_id": 1,  "vol_type": "dynamic"},
    "METADATACOPY":        {"vol_id": 2,  "vol_type": "dynamic"},
    "filestruct_full.bin": {"vol_id": 10, "vol_type": "static"},
}


# Device nodes baked into the rebuilt UBIFS via mkfs.ubifs -D. Preinit
# assumes /dev is writable and mknod's console/tty*/etc.; on a static
# rootfs those calls fail. Baking the essentials here lets boot proceed.
DEVICE_TABLE = """
/dev            d    755  0   0   -     -     -     -     -
/dev/console    c    600  0   0   5     1     -     -     -
/dev/null       c    666  0   0   1     3     -     -     -
/dev/zero       c    666  0   0   1     5     -     -     -
/dev/full       c    666  0   0   1     7     -     -     -
/dev/random     c    666  0   0   1     8     -     -     -
/dev/urandom    c    666  0   0   1     9     -     -     -
/dev/tty        c    666  0   0   5     0     -     -     -
/dev/tty        c    666  0   0   4     0     0     6     1
/dev/ttyS       c    660  0   0   4     64    0     4     1
/dev/ptmx       c    666  0   0   5     2     -     -     -
/dev/mem        c    600  0   0   1     1     -     -     -
/dev/kmem       c    600  0   0   1     2     -     -     -
/dev/pts        d    755  0   0   -     -     -     -     -
/dev/shm        d    755  0   0   -     -     -     -     -
/proc           d    555  0   0   -     -     -     -     -
/sys            d    555  0   0   -     -     -     -     -
/tmp            d    1777 0   0   -     -     -     -     -
/var            d    755  0   0   -     -     -     -     -
""".strip()




def require(name):
    path = shutil.which(name)
    if not path:
        sys.exit(f"[!] Missing tool: {name}\n")
    return path




def run_command(cmd, allow_fail=False):
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if res.returncode != 0 and not allow_fail:
        sys.exit(res.returncode)

    return res.returncode




def find_rootfs_root():
    rootfs_dir = WORK_DIR / "rootfs"

    if not rootfs_dir.is_dir():
        sys.exit(f"[-] {rootfs_dir} not found. Run FirmwareExtract.py first.")

    candidates = set()
    for marker in ("sbin", "bin", "etc"):
        for hit in rootfs_dir.rglob(marker):
            if hit.is_dir():
                candidates.add(hit.parent)

    if not candidates:
        sys.exit(f"[-] No rootfs tree under {rootfs_dir}")

    return max(candidates, key=lambda p: sum(1 for _ in p.rglob("*") if _.is_file()))




def fix_permissions(rootfs):
    # ubireader strips exec + setuid bits when extracting.

    exec_dirs = ("bin", "sbin", "usr/bin", "usr/sbin", "usr/libexec", "libexec")
    for sub in exec_dirs:
        d = rootfs / sub
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and not f.is_symlink():
                f.chmod(0o755)

    lib_dirs = ("lib", "usr/lib", "lib64", "usr/lib64")
    for sub in lib_dirs:
        d = rootfs / sub
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and not f.is_symlink() and ".so" in f.name:
                f.chmod(0o755)

    # Init/rc scripts.
    for sub in ("etc/init.d", "etc/rc.d", "etc/rc.local.d"):
        d = rootfs / sub
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and not f.is_symlink():
                f.chmod(0o755)

    for rel in ("etc/preinit", "etc/rcS", "etc/rc.common"):
        f = rootfs / rel
        if f.exists() and f.is_file():
            f.chmod(0o755)

    # Any file with a shebang line.
    for f in rootfs.rglob("*"):
        if not f.is_file() or f.is_symlink():
            continue
        try:
            with open(f, "rb") as h:
                if h.read(2) == b"#!":
                    f.chmod(0o755)
        except OSError:
            pass

    bb = rootfs / "bin" / "busybox"
    if bb.exists() and bb.is_file():
        bb.chmod(0o4755)

    print("[+] Permissions restored")




def apply_file_caps(rootfs):
    # Broadcom kernel drops caps on exec unless the target binary has a
    # security.capability xattr. Blanket-cap every executable in the
    # vendor bin dirs so daemons don't get EPERM on mount/mknod/etc.

    setcap = require("setcap")

    targets = []
    for sub in ("bin", "sbin", "usr/bin", "usr/sbin"):
        d = rootfs / sub
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.is_file() and not f.is_symlink() and (f.stat().st_mode & 0o111):
                targets.append(str(f))

    if not targets:
        return

    print(f"[*] setcap all=eip on {len(targets)} binaries (may prompt for password)")

    payload = b"\0".join(s.encode() for s in targets) + b"\0"
    proc = subprocess.Popen(
        ["sudo", "xargs", "-0", "-n", "1", setcap, "all=eip"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    proc.communicate(input=payload)

    # setcap strips setuid; put it back on busybox.
    bb = rootfs / "bin" / "busybox"
    if bb.exists():
        subprocess.run(["sudo", "chmod", "4755", str(bb)], stdout=subprocess.DEVNULL)

    print(f"[+] Applied caps + re-set busybox setuid")




def bridge_libraries(rootfs):
    # Dynamic linker strips LD_LIBRARY_PATH for capability-enabled binaries.
    # /lib is in the loader's compiled-in trusted path, /usr/lib is not on
    # this vendor's glibc build. Symlink so daemons find libshared.so /
    # libcurl.so.4 / libzcfg_*.so at load time.

    usr_lib = rootfs / "usr" / "lib"
    lib     = rootfs / "lib"

    if not (usr_lib.is_dir() and lib.is_dir()):
        return

    linked = 0
    for so in sorted(usr_lib.iterdir()):
        if ".so" not in so.name:
            continue
        if not (so.is_file() or so.is_symlink()):
            continue
        target = lib / so.name
        if target.exists() or target.is_symlink():
            continue
        target.symlink_to(f"../usr/lib/{so.name}")
        linked += 1

    print(f"[+] Bridged {linked} libraries /usr/lib -> /lib")




def chown_root(rootfs):
    # Files extracted by ubireader are owned by the WSL user (UID 1000).
    # On the router that's not root, so setuid transitions target UID 1000
    # instead of UID 0. chown fixes that.

    print("[*] chown -R root:root (may prompt for password)")
    subprocess.run(["sudo", "chown", "-R", "root:root", str(rootfs)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # chown strips setuid; re-apply on busybox.
    bb = rootfs / "bin" / "busybox"
    if bb.exists():
        subprocess.run(["sudo", "chmod", "4755", str(bb)], stdout=subprocess.DEVNULL)

    print("[+] Ownership set")




def build_ubifs(rootfs):
    tool     = require("mkfs.ubifs")
    out      = REBUILD_DIR / "rootfs.ubifs"
    devtable = REBUILD_DIR / "devtable.txt"

    devtable.write_text(DEVICE_TABLE)

    print("[*] mkfs.ubifs -> rootfs.ubifs")

    cmd = [
        "sudo", tool,
        "-m", str(UBI_PAGE_SIZE),
        "-e", str(UBI_LEB_SIZE),
        "-c", str(UBIFS_MAX_LEB),
        "-j", str(UBIFS_JOURNAL_SIZE),
        "-x", UBIFS_COMPRESSION,
        "-D", str(devtable),
        "-r", str(rootfs),
        "-o", str(out),
    ]
    run_command(cmd)

    # Hand the output back to the caller so post-build steps can touch it.
    subprocess.run(["sudo", "chown", f"{os.getuid()}:{os.getgid()}", str(out)],
                   stdout=subprocess.DEVNULL)

    print(f"[+] rootfs.ubifs  ({out.stat().st_size:>12,} bytes)")
    return out




def build_ubinize_ini(rootfs_ubifs):
    vols_dir = WORK_DIR / "vols"
    ini      = REBUILD_DIR / "ubinize.ini"
    lines    = []

    for name, meta in STOCK_VOL_TABLE.items():
        if name == "rootfs_ubifs":
            img = rootfs_ubifs
        else:
            img = vols_dir / f"{name}.ubifs"
            if not img.is_file():
                sys.exit(f"[-] Missing volume: {img}")

        lines.append(f"[{name}]")
        lines.append("mode=ubi")
        lines.append(f"image={img.resolve()}")
        lines.append(f"vol_id={meta['vol_id']}")
        lines.append(f"vol_type={meta['vol_type']}")
        lines.append(f"vol_name={name}")
        lines.append(f"vol_size={img.stat().st_size}")
        lines.append("")

    ini.write_text("\n".join(lines))
    print(f"[+] ubinize.ini   ({len(STOCK_VOL_TABLE)} volumes)")
    return ini




def ubinize(ini):
    tool = require("ubinize")
    out  = REBUILD_DIR / "body.bin"

    print("[*] ubinize -> body.bin")

    cmd = [
        tool,
        "-m", str(UBI_PAGE_SIZE),
        "-s", str(UBI_SUBPAGE_SIZE),
        "-p", str(UBI_PEB_SIZE),
        "-o", str(out),
        str(ini),
    ]
    run_command(cmd)

    print(f"[+] body.bin      ({out.stat().st_size:>12,} bytes)")
    return out




def main():
    print("[*] ZyxelFirmware Rebuild stage")
    print(f"[*] Work dir:    {WORK_DIR}")
    print(f"[*] Rebuild dir: {REBUILD_DIR}\n\n")

    if REBUILD_DIR.exists():
        shutil.rmtree(REBUILD_DIR)
    REBUILD_DIR.mkdir(parents=True)

    rootfs = find_rootfs_root()
    print(f"[*] Rootfs tree: {rootfs.relative_to(WORK_DIR)}\n")

    fix_permissions(rootfs)
    apply_file_caps(rootfs)
    bridge_libraries(rootfs)
    chown_root(rootfs)

    print()
    rootfs_ubifs = build_ubifs(rootfs)
    ini          = build_ubinize_ini(rootfs_ubifs)
    body         = ubinize(ini)

    print()
    print(f"[+] Rebuild complete.")
    print(f"      body -> {body.relative_to(SCRIPT_DIR)}")
    print(f"[?] Now run FirmwarePatch.py to apply the tag.")



if __name__ == "__main__":
    main()
