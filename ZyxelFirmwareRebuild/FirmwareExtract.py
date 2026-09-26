import re
import shutil
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR   = Path(__file__).parent.resolve()
FIRMWARE_DIR = SCRIPT_DIR / "Firmware"
WORK_DIR     = SCRIPT_DIR / "Work"
TAG_LEN      = 1024





def require(name):
    path = shutil.which(name)
    if not path:
        sys.exit(f"[!] Missing tool: {name}\n")
    return path



def find_bin_path():
    first_bin = next(FIRMWARE_DIR.glob("*.bin"), None)

    if first_bin:
        print(f"[+] Found: {first_bin}")
        return first_bin

    print("[-] No .bin files found")
    return None



def run_command(cmd, allow_fail):
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if res.returncode != 0 and not allow_fail:
        sys.exit(res.returncode)

    return res.returncode




def peel_volumes(body_path):
    tool = require("ubireader_extract_images")
    vols_out = WORK_DIR / "vols"

    if vols_out.exists():
        shutil.rmtree(vols_out) #delete old
    vols_out.mkdir(parents=True) #remake new

    run_command([tool, "-u", "ubifs", "-o", str(vols_out), str(body_path)], allow_fail=True)



    volumes = {}
    for p in vols_out.rglob("*_vol-*.ubifs"):
        name = p.stem.partition("_vol-")[2]
        flat = vols_out / f"{name}.ubifs"

        if p != flat:
            p.replace(flat)

        volumes[name] = flat


    # Prune the empty per-image subdirectory ubireader left behind.
    for sub in list(vols_out.iterdir()):
        if sub.is_dir():
            try:
                sub.rmdir()
            except OSError:
                pass

    if not volumes:
        sys.exit(f"[!] No UBI volumes produced Is {body_path.name} a Zyxel/Broadcom pureUBI image?")

    print(f"[+] Peeled {len(volumes)} volume(s):")
    for name, p in sorted(volumes.items(), key=lambda kv: kv[1].stat().st_size):
        print(f"      {name:<28} {p.stat().st_size:>12,} bytes")
    return volumes



def split_tag(bin_path):

    data = bin_path.read_bytes()


    if len(data) <= TAG_LEN:
        sys.exit(f"[!] {bin_path.name} too small ({len(data)} bytes) to contain a wfi_tag.")


    body = data[:-TAG_LEN]
    tag  = data[-TAG_LEN:]
    body_path = WORK_DIR / "body.bin"
    tag_path  = WORK_DIR / "tag.bin"

    body_path.write_bytes(body)
    tag_path.write_bytes(tag)

    print(f"[+] body.bin  ({len(body):>12,} bytes)")
    print(f"[+] tag.bin   ({len(tag):>12,} bytes)")
    return body_path




def extract_rootfs(volumes):
    if "rootfs_ubifs" not in volumes:
        sys.exit("[!] No rootfs_ubifs volume found")

    tool = require("ubireader_extract_files")
    rootfs_out = WORK_DIR / "rootfs"

    if rootfs_out.exists():
        shutil.rmtree(rootfs_out)
    rootfs_out.mkdir(parents=True)

    print("[?] The following command might take some time just let it run for a few minutes")

    run_command([tool, "-o", str(rootfs_out), str(volumes["rootfs_ubifs"])], allow_fail=False)


    candidates = set()
    for marker in ("sbin", "bin", "etc", "lib"):
        for hit in rootfs_out.rglob(marker):
            if hit.is_dir():
                candidates.add(hit.parent)
    if not candidates:
        sys.exit(f"[!] No recognizable rootfs tree under {rootfs_out}.")
    root = max(candidates, key=lambda p: sum(1 for _ in p.rglob("*") if _.is_file()))

    file_count = sum(1 for _ in root.rglob("*") if _.is_file())
    print(f"[+] Rootfs tree at {root.relative_to(WORK_DIR)}  ({file_count:,} files)")
    return root


def main():
    print(f"[*] ZyxelFirmware Extract stage")
    print(f"[*] Firmware dir: {FIRMWARE_DIR}")
    print(f"[*] Work dir: {WORK_DIR}\n\n")


    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR) # remove old dir
    WORK_DIR.mkdir(parents=True) # remake work dir

    bin_path  = find_bin_path()
    if not bin_path:
        sys.exit(1)



    body_path = split_tag(bin_path)
    volumes   = peel_volumes(body_path)
    rootfs    = extract_rootfs(volumes)


    print()
    print(f"[+] Extract complete.")
    print(f"      body   -> {body_path.relative_to(SCRIPT_DIR)}")
    print(f"      tag    -> {(WORK_DIR / 'tag.bin').relative_to(SCRIPT_DIR)}")
    print(f"      vols   -> {(WORK_DIR / 'vols').relative_to(SCRIPT_DIR)}/")
    print(f"      rootfs -> {rootfs.relative_to(SCRIPT_DIR)}/")



if __name__ == "__main__":
    main()
