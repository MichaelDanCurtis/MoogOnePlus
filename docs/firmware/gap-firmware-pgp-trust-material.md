# Firmware PGP trust material — decoded

Gap: `usr/share/sec/` holds the root of the Moog One firmware trust chain, but no
prior report decoded the key material itself — `init-boot.md` only recorded that
the files exist (`ls -la`). This document decodes every key packet offline from
local disk: key IDs, fingerprints, algorithms, sizes, creation dates, subkey
structure, self-signatures, the S2K protection on the private half, and a
byte-level cross-version diff against `rootfs-1.5.0`.

Scope note: this is a pure-offline, read-only analysis. No instrument was
touched. No Moog ARM binary was executed — the one ARM binary in the chain
(`usr/bin/str`) was disassembled with `llvm-objdump` and its algorithm
re-implemented in Python to decode the steganographic payload, so nothing ran.

Secret-material note: decoding `/etc/bob.bmp` yields a *real PGP private key*.
This document deliberately records only its public identifiers (key IDs,
fingerprints, algorithm, S2K parameters) — the same facts already derivable from
the cleartext public keyring — and does **not** reproduce the secret key bytes.
The extracted private key was written only to a session scratchpad, never into
the repo.

---

## 1. Inventory of `usr/share/sec/` (firmware 1.8.2)

`[READ]` directory listing, `rootfs-1.8.2/usr/share/sec/`:

| file | size | what it is |
|---|---|---|
| `gpg.conf` | 9195 | GnuPG config (distro default; 2 active lines) |
| `mmspubk` | 837 | ASCII-armored **M**oog **M**usic **s**ign **pub**lic **k**ey (DSA) |
| `mmepubk` | 1690 | ASCII-armored **M**oog **M**usic **e**ncrypt **pub**lic **k**ey (RSA + subkey) |
| `pubring.gpg` | 1732 | binary keyring = both public keys above + trust packets |
| `secring.gpg` | **0** | empty (SHA-256 `e3b0c442…` = the canonical empty-file hash) `[READ]` |
| `trustdb.gpg` | 1200 | GnuPG trust database, v3, **empty hash table** |
| `random_seed` | 600 | GnuPG PRNG seed pool (high-entropy blob) |

The names map directly to roles. `mms*` = signing identity
`Moog Music <sign@moogmusic.com>`; `mme*` = encryption identity
`Moog Music <encrypt@moogmusic.com>`. `[READ]` user-ID packets, below.

`secring.gpg` being 0 bytes is significant: **no private key is stored in the
static keyring.** The private key needed on-device (the decryption key) is
side-loaded at upgrade time from a steganographic carrier — see §6.

---

## 2. Signing key — `Moog Music <sign@moogmusic.com>`

`[READ]` `gpg --list-packets mmspubk` and independent Python packet parse +
SHA-1 fingerprint recomputation (two methods agree):

```
algorithm        : DSA (pubkey algo 17)
key size         : 1024-bit  (p = 1024 bits, q = 160 bits)
key ID (long)    : 549C096FDD90D298
fingerprint      : 35A7 D475 D81E 6DEA 0F52  B448 549C 096F DD90 D298
created          : 946767989  = 2000-01-01 23:06:29 UTC
expires          : 0 (never)
user ID          : "Moog Music <sign@moogmusic.com>"
key flags        : 0x03  (certify + sign)
self-sig class   : 0x13 (positive certification), digest algo 2 = SHA-1
pref-sym-algos   : 9,8,7   (AES-256, AES-192, AES-128)
pref-zip-algos   : 2,1,0   (BZIP2, ZIP, uncompressed)
```

This is the key the device uses to **verify** firmware image signatures. Its
private half is, by design, not present on the device — it "is kept on the Moog
build server" `[READ]` `lasfwu:1079`.

`[INFERRED — strong]` **DSA-1024 with SHA-1 self-signatures is cryptographically
dated.** 1024-bit DSA sits at roughly an 80-bit security level (below the modern
112-bit floor), and SHA-1 is collision-broken. Evidence: the algo/size/digest
fields above. This does not by itself hand an attacker a forgery — forging a
firmware signature still requires the build-server private key or a discrete-log
break of the specific 1024-bit group — but it is the weakest link in the
integrity chain and the one most worth flagging.

---

## 3. Encryption key — `Moog Music <encrypt@moogmusic.com>`

`[READ]` `gpg --list-packets mmepubk` / independent parse. This is a primary key
plus one encryption subkey (standard GnuPG-v1 layout):

**Primary:**
```
algorithm        : RSA (pubkey algo 1)
key size         : 2048-bit,  e = 0x010001 (65537)
key ID (long)    : D7B0E9FC8D71B4E9
fingerprint      : 885E CD48 F4BD 6EA1 67C2  19E5 D7B0 E9FC 8D71 B4E9
created          : 946767770  = 2000-01-01 23:02:50 UTC
expires          : 0 (never)
user ID          : "Moog Music <encrypt@moogmusic.com>"
key flags        : 0x03  (certify + sign)
self-sig class   : 0x13, digest algo 2 = SHA-1
```

**Encryption subkey:**
```
algorithm        : RSA (pubkey algo 1)
key size         : 2048-bit,  e = 0x010001 (65537)
key ID (long)    : 6840F7E486E44AFD
fingerprint      : 4721 E682 3864 E5E2  80B9 F45C 6840 F7E4 86E4 4AFD
created          : 946767770  = 2000-01-01 23:02:50 UTC
binding-sig class: 0x18 (subkey binding), digest algo 2 = SHA-1
subkey flags     : 0x0C  (encrypt-communications + encrypt-storage)
```

Firmware images are **encrypted to subkey `6840F7E486E44AFD`**. The device
decrypts them with that subkey's *private* half (recovered from `bob.bmp`, §6).

---

## 4. `pubring.gpg` — the on-device keyring

`[READ]` `gpg --list-packets pubring.gpg`. The binary keyring is exactly the two
armored keys concatenated, each followed by a GnuPG trust packet:

```
off 0     public key   DSA 549C096FDD90D298   ("sign@")      + uid + self-sig
off 545   trust packet (sig flag=00, sigcache=03)
off 549   public key   RSA D7B0E9FC8D71B4E9   ("encrypt@")   + uid + self-sig
off 1162  trust packet
off 1166  public subkey RSA 6840F7E486E44AFD  + binding sig
off 1728  trust packet
```

`[READ]` Verified that the DSA public-key packet from `mmspubk` (bytes `0..420`)
and the RSA public-key packet from `mmepubk` (bytes `0..271`) appear **verbatim**
inside `pubring.gpg` — the armored files and the binary keyring carry identical
key material. So `mmspubk`/`mmepubk` are just the armored, single-key exports of
what `pubring.gpg` already contains.

---

## 5. `trustdb.gpg` and `gpg.conf` — mostly vestigial

`trustdb.gpg` `[READ]` (binary parse of the 40-byte records):
```
version 3, trust model 1 (PGP), marginals 3, completes 1, cert depth 5
created 946686339 = 2000-01-01 00:25:39 UTC
30 records total: 1 header + 29 hash-table records
ALL 29 hash-table records are entirely zero — no ownertrust is assigned
```
So the shipped trust database contains **no trust assignments at all.** It is an
empty template.

`gpg.conf` `[READ]` — of 237 lines, only two are active (non-comment):
```
keyserver hkp://keys.gnupg.net
no-tty
```
`keys.gnupg.net` has been defunct since ~2019; irrelevant for an offline,
local-keyring verify. `[INFERRED]` the trustdb and keyserver line are both inert
for the actual upgrade path because `lasfwu` does its own thing:

`[READ]` `lasfwu:352` — at upgrade time the script runs
`gpg --import --ignore-time-conflict /usr/share/sec/*` into a **fresh** `~/.gnupg`,
and `[READ]` `lasfwu:642,686` the decrypt/verify invocations pass
`--always-trust --ignore-time-conflict --ignore-valid-from`. The shipped
`trustdb.gpg` is therefore not the trust anchor at runtime; the imported public
keys plus `--always-trust` are. (`--always-trust` relaxes the web-of-trust
*validity* check only; it does **not** bypass the cryptographic signature check.)

---

## 6. The private decryption key ships on the device, in `/etc/bob.bmp`

This is the load-bearing finding. `init-boot.md` already noted that a private key
is steganographed in `bob.bmp` with passphrase `bob`; this section **decodes it**
and pins down exactly which key it is.

### 6.1 The extractor `usr/bin/str`

`[READ]` `file` + `strings`: `usr/bin/str` is a 4056-byte ARM ELF. Its usage
string is `usage: %s <in file> <n last bits> > <out file>` and it rejects any
`n` except `1, 2, or 4` `[READ]` (`error: number of last bits can only be 1, 2
or 4`). So the `4` in `str /etc/bob.bmp 4` is **not a byte offset** — it is the
number of least-significant bits per carrier byte. This is LSB steganography, not
a header skip.

`[READ]` disassembly (`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`):
- `fseek(f, 54, SEEK_SET)` — skip the 54-byte BMP header, start at pixel data
  (`bits offset 54` `[READ]` in the BMP header).
- extract 7 output bytes → ASCII decimal **size** string; `fprintf(stderr,
  "msg size: %d bytes", size)`.
- `malloc(size)`, extract `size` payload bytes, `fputc` each to stdout.
- inner reconstruction loop at `0x10784`: for `n=4`, each output byte is built
  from two consecutive carrier bytes as
  `out = ((B0 & 0x0F) << 4) | (B1 & 0x0F)` — first carrier byte supplies the
  high nibble, second the low nibble, both from the carrier's low 4 bits.

### 6.2 Decoded payload

`[READ]` Re-implementing that exact algorithm in Python against
`rootfs-1.8.2/etc/bob.bmp` (no ARM execution):
- size header decoded to the ASCII string `"3581"` → **3581-byte** payload.
- payload begins `-----BEGIN PGP PRIVATE KEY BLOCK-----` / `Version: GnuPG v1`
  and ends `-----END PGP PRIVATE KEY BLOCK-----`. The base64 body's opening
  matches `mmepubk` byte-for-byte at the key-material prefix.

`[READ]` Parsing the decoded private key's packet headers (structure only; secret
MPIs never printed):
```
SECRET KEY    v4 RSA-2048  created 946767770   →  matches D7B0E9FC8D71B4E9
  user ID     "Moog Music <encrypt@moogmusic.com>"
SECRET SUBKEY v4 RSA-2048  created 946767770   →  matches 6840F7E486E44AFD
  S2K protection (both): usage 254, cipher AES-128 (sym-algo 7),
      S2K type 3 (iterated+salted), hash SHA-1, salt cbc7e2bacf48cdd9,
      coded count 96 = 65536 iteration-bytes
```

So `bob.bmp` carries the **private half of the encryption key**
(`D7B0E9FC8D71B4E9` + subkey `6840F7E486E44AFD`). The S2K passphrase is the
literal string `bob`, hardcoded in the decrypt call `[READ]` `lasfwu:642`
(`gpg … --passphrase bob --decrypt`).

### 6.3 Consequence

`[INFERRED — strong, and consistent with the prior "decrypt yes" conclusion]`
Firmware-image **encryption provides no confidentiality against anyone who holds
a rootfs image**: the decryption private key (`bob.bmp`) *and* its passphrase
(`bob`) both ship on the device. The iteration count (65536, low) and AES-128 S2K
are moot because the passphrase is known.

`[INFERRED — strong]` **Integrity is a separate, stronger story.** The signing
private key (`sign@`, DSA) is *not* on the device (`secring.gpg` is empty; no
PGP PRIVATE KEY block anywhere references `sign@` — only the public keyring
does `[READ]`). An attacker with the rootfs can therefore *read* a firmware image
but cannot produce one that passes the signature check in §5 without the
build-server key (or a DSA-1024/SHA-1 break). The practical conclusion
"decrypt yes, re-sign no" holds; the DSA-1024+SHA-1 weakness in §2 is the
theoretical caveat on "no."

---

## 7. Cross-version diff (1.5.0 vs 1.8.2) — no key rotation

`[READ]` SHA-256 of every file, `rootfs-1.5.0/usr/share/sec/*` vs
`rootfs-1.8.2/usr/share/sec/*`:

| file | 1.5.0 vs 1.8.2 |
|---|---|
| `gpg.conf` | **identical** (`c828f093…`) |
| `mmepubk` | **identical** (`3dbb1b36…`) |
| `mmspubk` | **identical** (`1c315587…`) |
| `pubring.gpg` | **identical** (`674079c0…`) |
| `random_seed` | **identical** (`e8fe399f…`) |
| `secring.gpg` | **identical** (both 0 bytes, `e3b0c442…`) |
| `trustdb.gpg` | **identical** (`7a96d6c2…`) |

`[READ]` `/etc/bob.bmp` is **also byte-identical** across the two versions
(`67ceca27…`).

So between 1.5.0 (the owner's instrument, timestamped Nov 2021) and 1.8.2, **the
signing key, the encryption key/subkey, and the private-key carrier did not
rotate.** Same trust anchors, same decryption key, same passphrase across the
span. `[INFERRED]` key rotation is not part of Moog's update discipline for these
versions — a compromise of `bob.bmp`/`bob` would not be healed by a later update
in this range.

---

## 8. The trust chain, end to end (as decoded)

`[READ]` `lasfwu` + man-page text (`lasfwu:1079-1127`), combined with §2–§6:

1. Moog build server **signs** the image (and MANIFEST) with the DSA private key
   for `sign@moogmusic.com` (`549C096FDD90D298`). Private half never ships.
2. Build server **encrypts** the image to RSA encryption subkey
   `6840F7E486E44AFD` (`encrypt@moogmusic.com`).
3. On device, `lasfwu` imports the public keyring `/usr/share/sec/*`
   (`:352`), extracts the RSA **private** key from `/etc/bob.bmp` via
   `str … 4` (`:49`, `:637`), and imports it.
4. `lasfwu` **decrypts** the image with `--passphrase bob` (`:642`).
5. `lasfwu` **verifies** the decrypted image's detached signature against the
   public DSA key (`:686`), unconditionally, before writing the partition. A bad
   signature rejects the package (`:723`).
6. `lasfwu` then **deletes** the imported secret key (`erasekey`, `:65`, `:729`)
   and wipes the transient `~/.gnupg`.

Crypto primitives in play: RSA-2048/AES for confidentiality (key on device →
confidentiality defeated); DSA-1024 + SHA-1 for authenticity (key off device →
authenticity intact in practice, dated in theory).

---

## Conflicts with existing docs

- **No conflict, and a direct extension of `init-boot.md`.** `init-boot.md` §
  (lines ~1284-1290) records the key *files* via `ls -la`, the 0-byte
  `secring.gpg`, the `bob.bmp` steganography, passphrase `bob`, and the
  "decrypt yes / re-sign no" conclusion. This document supplies the key
  cryptographic details that were missing (IDs, fingerprints, algorithms, sizes,
  dates, subkey structure, private-key S2K) and the cross-version diff. Every
  overlapping claim agrees.
- `[READ]` No existing doc under `docs/` cites any of these key IDs or
  fingerprints (grep for `549C096F`, `D7B0E9FC`, `6840F7E4`, `885ECD48`,
  `35A7D475`, `4721E682`, `dsa1024`, `rsa2048` returns nothing) — so the decoded
  identifiers here are not contradicted anywhere.
- The `--accept-unsigned` "documented-but-unimplemented" note in `init-boot.md`
  is about `lasfwu`'s option parser, outside this gap's scope; not re-examined
  here.

---

## Validation plan (READ-ONLY; no instrument, no binary execution)

All already performed offline on local disk and reproducible by a human:

1. `gpg --no-options --batch --no-default-keyring --list-packets <rootfs>/usr/share/sec/mmspubk`
   (and `mmepubk`, `pubring.gpg`) — confirms algos, key IDs, dates, flags.
2. Import into a throwaway `GNUPGHOME` and `gpg --fingerprint --with-subkey-fingerprint`
   — confirms the three fingerprints in §2–§3.
3. SHA-256 every `usr/share/sec/*` and `etc/bob.bmp` in both rootfs trees and
   compare — confirms §7 (no rotation).
4. `llvm-objdump -d --triple=armv7-none-linux-gnueabihf <rootfs>/usr/bin/str`
   — confirms the LSB-4 algorithm (`fseek 54`, 7-byte size header, nibble
   assembly) without running it.
5. Re-implement that algorithm in Python against `etc/bob.bmp` and parse the
   resulting PGP private-key packet *headers only* — confirms the carrier holds
   `encrypt@moogmusic.com`'s RSA-2048 secret key/subkey with S2K AES-128 /
   iterated+salted / SHA-1 / salt `cbc7e2bacf48cdd9`.

A human wishing to *fully* confirm the private key decrypts real images can, off
the instrument, feed the extracted key to `gpg --passphrase bob` against a
captured `.ext4.gpg` image. That step reproduces Moog's own decrypt and needs no
device access; it is out of scope here and was not performed.
