# `las-frontend`'s outbound HTTP/HTTPS client: libcurl, OpenSSL, and the shipped CA trust store

Firmware v1.8.2 root filesystem (`captures/firmware-1.8.2/rootfs-1.8.2/`, below `R/`),
cross-checked against the owner's own v1.5.0 filesystem (`captures/rootfs-1.5.0/`, `R15/`)
and the live-harvest binaries in `captures/arch-harvest/`.

Written 2026-09-10 entirely from files on local disk. **The instrument was not touched.**
No SSH, no OSC, no MIDI, no packet reached 192.168.1.x or 203.0.113.x. **No Moog binary was
executed** — every binary fact below comes from `strings`, `xxd`, `shasum`, `openssl x509`
on extracted DER, and
`llvm-objdump -d --triple=armv7-none-linux-gnueabihf`.

Every load-bearing claim is graded **[READ]** (quoted from a file, with path and
offset/line), **[INFERRED]** (reasoning, with the evidence named), or **[UNKNOWN]**.
Where a claim depends on knowledge that is *not* in these files — the numeric value of a
public `CURLOPT_*` constant, whether a CA has been distrusted by a browser root program —
it is marked **[EXTERNAL]** and separated from what the bytes say.

## Provenance

| file | v1.8.2 sha256 | v1.5.0 sha256 |
|---|---|---|
| `usr/bin/las-frontend` | `7b2ea057…d7d10bfe` | `42670ca0…025969c9` |
| `usr/lib/libcurl.so.4.4.0` | `dd48f407…1a746b6f` | **identical** |
| `usr/lib/libssl.so.1.0.0` | `52230e17…b79ed326` | **identical** |
| `usr/lib/libcrypto.so.1.0.0` | `fc58224b…6dd7b326` | `d8d0d4ad…831ebe82` |
| `etc/ssl/certs/ca-certificates.crt` | `5754013d…69f881d5` | **identical** |

`captures/arch-harvest/las-frontend`, pulled off the owner's live instrument, is
**byte-identical** to `R15/usr/bin/las-frontend` (`42670ca0…025969c9`, 145,070,812 bytes)
**[READ, `shasum -a256`]** — so the v1.5.0 tree really is this instrument's, and the
v1.5.0 column above describes hardware the owner has in the room.

---

## 0. Headline

**`las-frontend` contains a complete, TLS-verifying HTTP client and never calls it.**

The client is not Moog code. It is **JUCE 5.4.5's `WebInputStream`** — the stock
`juce_core/native/juce_curl_Network.cpp` implementation — linked against **libcurl 7.47.1
over OpenSSL 1.0.2f**, with the **full 179-root Mozilla CA bundle** on disk at
`/etc/ssl/certs`. Every one of the fifteen imported `curl_*` symbols is reached through a
single 60-byte function-pointer table, that table is built by exactly one function, and
that function is called from exactly one place: the constructor of `juce::WebInputStream`.

That constructor has three callers. Two are JUCE's own `URL` convenience wrappers, which
nothing calls. The third is `juce::ReportingThread::run()` — **JUCE's splash-screen
"app usage reporting" POST** — and the only site in the binary that constructs a
`ReportingThread` is itself referenced by nothing at all: no branch, no literal-pool word,
no vtable slot. The binary contains **zero `movt` instructions**, so no address in it can
be materialised except through a literal pool or a PC-relative branch, and both were
scanned exhaustively.

The practical consequences, in order of how much they matter to the owner:

1. **Nothing in the shipping UI process fetches anything over HTTP.** There is no update
   check, no telemetry, no licence call-home, no presetstore client. There is **no Moog
   hostname anywhere in the 145 MB binary** — the complete hostname inventory is W3C, Adobe
   XMP, DejaVu, ParaType, Serif, SIL, Thawte/Symantec (inside certificates) and
   `juce.com`.
2. **The one `juce.com` literal is not a fetch.** It is
   `URL("https://juce.com").launchInDefaultBrowser()` — JUCE's splash-screen click handler,
   which shells out to `xdg-open`/`firefox`/`chromium-browser`. It never touches libcurl.
3. **The capability is live if anything ever calls it.** libcurl is a real shared library on
   the device, correctly configured, with a working `CApath`. Anyone who can get code into
   this process — or who replaces the binary — inherits a working TLS client that trusts
   180 certificate authorities.
4. **That trust store is eleven years stale and has never been updated.**
   `ca-certificates.crt` is **byte-identical between v1.5.0 (May 2022) and v1.8.2
   (September 2025)**. The newest root in it was issued **2014-01-16**. **57 of the 179
   roots have already expired** as of today. Let's Encrypt's ISRG Root X1, Amazon Root CA 1
   and Google Trust Services' GTS Root R1 are **absent** — so if anything ever were pointed
   at a modern HTTPS endpoint, it would most likely fail certificate validation.
5. **The crypto is frozen at January 2016.** OpenSSL **1.0.2f** and libcurl **7.47.1** in
   *both* firmwares. `libssl.so.1.0.0` and `libcurl.so.4.4.0` are byte-identical across the
   three years; `libcrypto.so.1.0.0` differs **only in the embedded CI build path**. Max TLS
   version 1.2, no TLS 1.3.
6. **The Thawte/Symantec certificate chain in the binary is fully accounted for and is not
   Moog's.** It is the Authenticode signature on an embedded **ParaType** font — leaf
   subject `C=US/ST=California/L=Saratoga/O=Paratype, Inc.`, issuer
   `Thawte Code Signing CA - G2`, expired 2014-11-03. It has nothing to do with code signing
   of Moog firmware and nothing to do with the HTTP client's trust decisions.

---

## 1. Three corrections to the brief that commissioned this report

Recorded here rather than quietly worked around.

### 1.1 `las-frontend` imports **no OpenSSL symbols at all**

The brief describes the gap as "libcurl, OpenSSL, and the shipped CA trust store".
`DT_NEEDED` does list `libssl.so.1.0.0` and `libcrypto.so.1.0.0` **[READ,
`llvm-objdump -p R/usr/bin/las-frontend`]**, but the dynamic symbol table tells a
different story:

```
llvm-objdump -T R/usr/bin/las-frontend  →  607 entries
  curl_*                                    15
  SSL_* / X509_* / EVP_* / BIO_* / RAND_* /
  CRYPTO_* / ERR_* / OPENSSL_*               0
```

**[READ]** Zero. `las-frontend` never calls OpenSSL directly. Meanwhile
`libcurl.so.4.4.0` itself declares `NEEDED libssl.so.1.0.0`, `NEEDED libcrypto.so.1.0.0`,
`NEEDED libz.so.1` **[READ, `llvm-objdump -p R/usr/lib/libcurl.so.4.4.0`]** and imports 118
OpenSSL symbols.

**[INFERRED]** The two `DT_NEEDED` entries in `las-frontend` are **over-linking** — a
build that passed `-lcurl -lssl -lcrypto` on the link line where `-lcurl` alone would have
sufficed. Evidence: zero undefined OpenSSL symbols in the executable, and every OpenSSL
symbol libcurl needs is satisfied by libcurl's own `DT_NEEDED`. This matters because it
means **the TLS policy of this process is entirely libcurl's, not the application's** —
there is no application-level `SSL_CTX` callback, no pinning hook, nothing.

### 1.2 The curl multi interface is **not** wired into the JUCE event loop

The brief infers "integrated into its event loop via `curl_multi_fdset`". The disassembly
says otherwise. `R/usr/bin/las-frontend` at `.text:0x92b900–0x92bb60` **[READ]**:

```
92b948   blx  r3            ; symbols->curl_multi_timeout
92b98c   bl   __aeabi_idiv  ; ms → tv_sec        (divide by 1000)
92b99c   bl   __aeabi_idivmod ; ms → tv_usec
92ba30   blx  r12           ; symbols->curl_multi_fdset
92ba78   bl   0x18c40 <select@plt>
92babc   blx  r3            ; symbols->curl_multi_perform
92bb18   blx  r3            ; symbols->curl_multi_info_read
```

That is a **private, blocking `select()` loop** — JUCE's `WebInputStream::Pimpl::singleStep()`
— run on whatever thread calls `connect()`/`read()`. It shares no descriptor set with the
X11/message loop. The multi interface is used here for *timeout control*, not for
integration. **[INFERRED]** from the instruction sequence and from the absence of any
`fd_set` shared with the JUCE `MessageManager` fds.

### 1.3 "No URL literal for a Moog host was recoverable" — correct, and now explained

The brief left this as an open question ("either constructed at runtime or stored somewhere
not reachable by plain `strings`"). Neither is true. There is **no Moog endpoint anywhere,
in any form**, because **the HTTP client is never invoked**. The full derivation is §7.

---

## 2. What `las-frontend` links, exactly

**[READ]** `llvm-objdump -p R/usr/bin/las-frontend`, Dynamic Section:

```
NEEDED  libasound.so.2   libX11.so.6   libXinerama.so.1   libXext.so.6
        libfreetype.so.6 libcurl.so.4  libssl.so.1.0.0    libcrypto.so.1.0.0
        librt.so.1       libdl.so.2    libpthread.so.0    libchicken.so.8
        libstdc++.so.6   libm.so.6     libgcc_s.so.1      libc.so.6
```

Identical, in the same order, in `R15/usr/bin/las-frontend` **[READ]**. This confirms
`docs/arch/performance.md:672` exactly.

### 2.1 `las-frontend` is the only libcurl consumer in the rootfs

**[READ]** Every regular file under `R/{bin,sbin,usr/bin,usr/sbin,usr/lib,usr/libexec}`
with an ELF magic was checked for a `libcurl` `DT_NEEDED`:

```
usr/bin/las-frontend        ← the only hit
```

The wider OpenSSL consumer list, for context **[READ, same sweep]**:

```
usr/bin/Xorg            usr/bin/Xvfb           usr/bin/openssl
usr/bin/las-frontend    usr/sbin/wpa_supplicant  usr/sbin/wpa_passphrase
usr/lib/libssl.so.1.0.0 usr/lib/libcurl.so.4.4.0 usr/lib/dri/swrast_dri.so
```

`usr/bin/openssl` is the stock CLI, `OpenSSL 1.0.2f  28 Jan 2016` **[READ, `strings`]**.

### 2.2 The fifteen imported `curl_*` symbols

**[READ]** `llvm-objdump -T R/usr/bin/las-frontend | grep curl` — all fifteen are
`DF *UND*`, all resolved through `.rel.plt` (`R_ARM_JUMP_SLOT`, type 22). Verified twice:
once by parsing `.rel.plt` (549 entries at vaddr `0x16bf8`, size `0x1128`) against
`.dynsym`, and once by decoding each PLT stub's own `add r12,pc / add r12,r12 / ldr pc,[r12]!`
to recover the GOT slot it uses. **Both methods agree on all fifteen**:

| PLT stub | `.rel.plt` idx | GOT slot | symbol |
|---|---|---|---|
| `0x17d64` | 3 | `0x8a6d438` | `curl_multi_info_read` |
| `0x1831c` | 125 | `0x8a6d620` | `curl_slist_append` |
| `0x18334` | 127 | `0x8a6d628` | `curl_multi_add_handle` |
| `0x18814` | 231 | `0x8a6d7c8` | `curl_multi_perform` |
| `0x18a54` | 279 | `0x8a6d888` | `curl_multi_cleanup` |
| `0x18ab4` | 287 | `0x8a6d8a8` | `curl_easy_init` |
| `0x18d9c` | 349 | `0x8a6d9a0` | `curl_easy_cleanup` |
| `0x18dc0` | 352 | `0x8a6d9ac` | `curl_multi_timeout` |
| `0x18df0` | 356 | `0x8a6d9bc` | `curl_multi_remove_handle` |
| `0x1909c` | 413 | `0x8a6daa0` | `curl_easy_setopt` |
| `0x19354` | 471 | `0x8a6db88` | `curl_easy_getinfo` |
| `0x194e0` | 504 | `0x8a6dc0c` | `curl_slist_free_all` |
| `0x19648` | 534 | `0x8a6dc84` | `curl_multi_init` |
| `0x1969c` | 541 | `0x8a6dca0` | `curl_multi_fdset` |
| `0x196d8` | 546 | `0x8a6dcb4` | `curl_version_info` |

There is **no `dlsym`-by-name path to libcurl**. `dlopen`/`dlsym`/`dlclose`/`dlerror` are
imported **[READ]**, but the only library-name literals in `.rodata` are
`libXcursor.so.1`, `libXinerama.so`, `libXrandr.so`, `libXrandr.so.2`, `libXss.so.1`
**[READ, offsets 144,102,938 / 144,102,951 / 144,103,637 / 144,104,215 / 144,104,827]** —
JUCE's optional X11 extensions. The fifteen `curl_*` name strings in the file all sit at
offsets 18,412–18,676, i.e. **inside `.dynstr`** (vaddr `0x138cc`, size `0x2c29` → file
`0x38cc`–`0x64f5`) **[READ]**, so they are import-table entries, not literals a `dlsym` call
could use.

---

## 3. The libcurl build, read out of the binary

`R/usr/lib/libcurl.so.4.4.0`, 278,612 bytes, `SONAME libcurl.so.4`.

### 3.1 Version and identity — read from the static `curl_version_info_data`

The struct `curl_version_info()` returns lives at file offset `0x43b0c` (vaddr `0x53b0c`).
**[READ]**:

| field | value |
|---|---|
| `age` | `3` (`CURLVERSION_FOURTH`) |
| `version` | `"7.47.1"` (points to file `0x3f7d5`) |
| `version_num` | `0x00072f01` = 7.47.1 |
| `host` | `"arm-buildroot-linux-gnueabihf"` (file `0x3f7e5`) |
| `features` | `0x0008421d` |
| `ssl_version` | `NULL` (filled at runtime) |
| `libz_version` | `NULL` (filled at runtime) |
| `protocols` | → array at vaddr `0x52cd8` |

**[READ]** the protocol array, walked to its NULL terminator — **18 protocols**:

```
dict  file  ftp  ftps  gopher  http  https  imap  imaps
pop3  pop3s rtsp smb   smbs    smtp  smtps  telnet tftp
```

**[EXTERNAL + READ]** decoding `features = 0x0008421d` against curl's published feature
bits gives:

```
IPV6 | SSL | LIBZ | NTLM | LARGEFILE | TLSAUTH_SRP | UNIX_SOCKETS
```

Two absences matter:

* **`CURL_VERSION_ASYNCHDNS` (bit 7) is clear.** This libcurl uses the **blocking
  resolver**. Corroborated independently **[READ]**: it has no `NEEDED libpthread`, imports
  `getaddrinfo`, `alarm`, `sigaction` and `__sigsetjmp` but **not** `pthread_create`, and
  contains zero occurrences of `c-ares`/`ares_`. The strings `Resolving timed out after %ld
  milliseconds` and `Previous alarm fired off!` are present **[READ]** — the classic
  `SIGALRM`-based `Curl_resolv_timeout` path.
* **`CURL_VERSION_HTTP2` (bit 16) is clear** — HTTP/1.1 only.

### 3.2 TLS backend

**[READ]** `strings -t x R/usr/lib/libcurl.so.4.4.0`:

```
0x427cb  vtls/openssl.c
0x42ab5  OpenSSL
0x41e68  TLSv1.2      0x41e70  TLSv1.1      0x41e78  TLSv1.0
0x41ea8  SSL certificate problem: %s
0x3f428  CURLOPT_SSL_VERIFYHOST no longer supports 1 as value!
```

Plus 118 undefined OpenSSL symbols including `SSL_CTX_load_verify_locations`,
`SSL_CTX_set_verify`, `SSL_get_verify_result`, `X509_verify_cert_error_string`,
`SSL_CTX_set_alpn_protos`, `SSL_get0_alpn_selected`, and the whole OCSP-stapling set
(`OCSP_basic_verify`, `OCSP_check_validity`, `OCSP_response_status`) **[READ]**.

**Maximum TLS version is 1.2.** There is no `TLSv1.3` string and OpenSSL 1.0.2 cannot do
1.3 **[READ for the string absence; EXTERNAL for the OpenSSL 1.0.2 capability]**.

### 3.3 CA location — compiled in as a **path**, not a bundle

**[READ]** the *only* CA-related strings in the whole library:

```
0x3f3f5  /etc/ssl/certs
0x425a8    CAfile: %s
0x425b5    CApath: %s
```

There is **no** `/etc/ssl/certs/ca-certificates.crt` literal and no `CURL_CA_BUNDLE`
string. **[INFERRED]** libcurl was configured `--with-ca-path=/etc/ssl/certs` and
**without** `--with-ca-bundle`; the default `CURLOPT_CAPATH` is therefore `/etc/ssl/certs`
and the default `CURLOPT_CAINFO` is unset. Consequence: **OpenSSL resolves trust through the
180 hashed symlinks in that directory, not through `ca-certificates.crt`** — the bundle
file is present but, for this client, decorative.

Spot-checked six of the hash symlinks by recomputing the subject hash of the certificate
each points at **[READ, `openssl x509 -noout -hash`]** — `02265526.0`, `024dc131.0`,
`03179a64.0`, `034868d6.0`, `039c618a.0`, `062cdee6.0` — **all six match**. The `CApath` is
functional, not a broken leftover.

### 3.4 Proxy behaviour is inherited from the environment

**[READ]** libcurl contains `http_proxy`, `all_proxy`, `ALL_PROXY`, `no_proxy`, `NO_PROXY`
(offsets `0x3f556`–`0x3f588`) and the SOCKS scheme table `socks5h socks5 socks4a socks4
socks`. `las-frontend` never sets `CURLOPT_PROXY` (§6.2), so **libcurl's environment-variable
proxy discovery is active by default**.

**[READ]** No proxy variable is set anywhere in `R/etc` — a recursive grep for
`http_proxy|https_proxy|HTTP_PROXY|all_proxy|no_proxy|CURL_CA_BUNDLE|SSL_CERT_FILE|SSL_CERT_DIR`
over the whole `etc` tree returns nothing. `R/etc/profile` sets only `PATH`, `PS1`, `PAGER`,
`EDITOR`, `TERMINFO`. `R/etc/init.d/S43gui:21`, which launches the process, exports only
`TERMINFO` and `TERM` and passes `DISPLAY=:0` **[READ]**:

```
DISPLAY=:0 las-frontend  --usb-path=/media/thumbdrive --data-path=/var/las-frontend \
  --host-paneloutput=203.0.113.2 --host-performance=vc --host-oleds=203.0.113.2 \
  --affinity-mask=1 --host-systemclock=vc --cookie=1 --affinity-panel=1 \
  --startup-coordination --host-vc=vc &
```

**[READ]** The complete `--long-option` inventory recovered from the binary (66 options)
contains no URL, host-HTTP, proxy, CA or endpoint switch. The network-shaped ones are all
the XMOS/OSC transport pairs (`--host-*`/`--port-*`), which are the already-documented
control plane.

---

## 4. The OpenSSL build

`R/usr/lib/libcrypto.so.1.0.0` — **`OpenSSL 1.0.2f  28 Jan 2016`** **[READ, repeated at
offsets `0x117943`, `0x11796b`, `0x117993`, `0x1179bb`, `0x1179e4`, `0x117a10`, `0x117a8f`,
`0x11c4d0`, `0x11c4f8`]**.

**[READ]** offset `0x1385cc`: `platform: linux-armv4`
**[READ]** offset `0x1385e2`: `OPENSSLDIR: "/etc/ssl"`
**[READ]** offset `0x13859d`: `built on: reproducible build, date unspecified`
**[READ]** offset `0x1383c3`, the compiler line — which leaks Moog's CI layout:

```
compiler: /home/las-ci-builds/glrt-t3_/0/moog/hardware/moog-one/las-buildroot/
          output/host/usr/bin/arm-buildroot-linux-gnueabihf-gcc -I. -I.. -I../include
          -fPIC -DOPENSSL_PIC -DZLIB_SHARED -DZLIB -DOPENSSL_THREADS -D_REENTRANT
          -DDSO_DLFCN -DHAVE_DLFCN_H -D_LARGEFILE_SOURCE -D_LARGEFILE64_SOURCE
          -D_FILE_OFFSET_BITS=64 -Os -Wall -DOPENSSL_BN_ASM_MONT -DOPENSSL_BN_ASM_GF2m
          -DSHA1_ASM -DSHA256_ASM -DSHA512_ASM -DAES_ASM -DBSAES_ASM -DGHASH_ASM
```

### 4.1 The only change in three years is the build path

`libcrypto.so.1.0.0` differs between v1.5.0 and v1.8.2 by **twelve bytes of length**
(1,362,512 → 1,362,524) **[READ, `stat`]**, and `cmp -l` puts the first difference at byte
33. The cause is visible **[READ]** — the same string in v1.5.0 reads:

```
compiler: /home/las-ci-builds/6c53963c/0/moogmusic/las-buildroot/output/host/usr/bin/...
```

v1.5.0's CI path segment `6c53963c/0/moogmusic` became v1.8.2's
`glrt-t3_/0/moog/hardware/moog-one`. **[INFERRED]** Moog migrated GitLab runners between the
two releases; the OpenSSL *source* did not change at all — same version string, same flag
set, and `libssl.so.1.0.0` is byte-identical.

### 4.2 Exposure, stated plainly

**[EXTERNAL]** OpenSSL 1.0.2 reached end of life on 2019-12-31; 1.0.2f predates 1.0.2g,
which is where DROWN (CVE-2016-0800) was fixed, and every 1.0.2 CVE from March 2016 onward
is unpatched here. **[READ]** Nothing in either firmware carries a newer OpenSSL.

**[INFERRED, and the honest qualifier]** This is a *latent* exposure, not an active one,
for exactly the reason in §7: no process on this device initiates a TLS client connection
using it. `wpa_supplicant` links `libssl` too and would use it for WPA-Enterprise EAP-TLS —
**[UNKNOWN]** whether any WPA-Enterprise profile exists on this device; not investigated,
out of scope for this report.

---

## 5. The shipped CA trust store

`R/etc/ssl/certs/` — **361 directory entries: 360 symlinks and exactly one regular file**
**[READ, `find -type l | wc -l` and `find -type f`]**.

* 180 hash-style links (`^[0-9a-f]{8}\.[0-9]+$`) → the `.pem` names
* 180 `*.pem` links → `../../../usr/share/ca-certificates/<vendor>/<name>.crt`
* 1 regular file: `ca-certificates.crt`, 286,339 bytes, **180 `BEGIN CERTIFICATE` blocks**

**[READ]** `R/usr/share/ca-certificates/` holds `mozilla/` (179 `.crt` files) and
`spi-inc.org/` (1 file, `spi-cacert-2008.crt`). 179 + 1 = 180. Zero dangling links.

**[READ]** The store is **byte-identical between v1.5.0 and v1.8.2**: identical file
listing, identical `ca-certificates.crt` sha256 (`5754013d…`), and the recursive hash of
every file under `mozilla/` matches in both trees
(`45c5d6b2747113b10bf9fcdb01b1af06ec7420345d30b55bcc750174fc3bcc4d`).

### 5.1 Dating the snapshot

**[READ]** Every one of the 179 Mozilla roots was parsed with `openssl x509 -startdate`.
The eight newest by `notBefore`:

```
2013-08-01  DigiCert_Assured_ID_Root_G3, DigiCert_Global_Root_G2,
            DigiCert_Global_Root_G3, DigiCert_Trusted_Root_G4
2013-10-21  S-TRUST_Universal_Root_CA
2013-11-14  Staat_der_Nederlanden_Root_CA_-_G3
2014-01-16  IdenTrust_Public_Sector_Root_CA_1, IdenTrust_Commercial_Root_CA_1
```

**[READ]** Absent from the store: `ISRG_Root_X1`, `ISRG_Root_X2`, `Amazon_Root_CA_1`,
`GTS_Root_R1`. Present: `DST_Root_CA_X3`.

**[INFERRED]** The bundle is a Debian `ca-certificates` snapshot of roughly 2014–2015
vintage. Evidence: newest included root issued 2014-01-16; ISRG Root X1 (self-signed
2015-06-04) and Amazon Root CA 1 (2015-05-26) both absent. **[UNKNOWN]** the exact
`ca-certificates` package version — there is no `/etc/ca-certificates.conf` in the rootfs
and no package manifest.

### 5.2 Rot: 57 of 179 roots have already expired

**[READ]** Computed from `notAfter` of each shipped `.crt` against today, 2026-09-10.
**57 expired.** The tail end of the list, closest to now:

```
2021-09-30  DST_Root_CA_X3
2021-12-15  Cybertrust_Global_Root, GlobalSign_Root_CA_-_R2
2022-05-20  GeoTrust_Global_CA
2022-06-23  Visa_eCommerce_Root
2022-12-08  Staat_der_Nederlanden_EV_Root_CA
2022-12-13  WellsSecure_Public_Root_Certificate_Authority
2022-12-14  NetLock_Qualified_=Class_QA=_Root
2023-03-03  E-Tugra_Certification_Authority
2023-05-14  Hongkong_Post_Root_CA_1
2023-09-29  Security_Communication_Root_CA
2024-01-21  Trustis_FPS_Root_CA
2025-05-12  Baltimore_CyberTrust_Root
2025-08-18  Swisscom_Root_CA_1
2025-12-31  TC_TrustCenter_Class_2_CA_II / Class_3_CA_II / Universal_CA_I
2026-02-22  RSA_Security_2048_v3
```

**[READ]** Expiring within three years: `Entrust_Root_Certification_Authority`
(2026-11-27), `CNNIC_ROOT` (2027-04-16), `Certum_Root_CA` (2027-06-11), `Certigna`
(2027-06-29), `GlobalSign_Root_CA` (2028-01-28), and the whole 2028-08 VeriSign block.

### 5.3 Roots the rest of the industry stopped trusting

**[READ]** these files are present in `R/usr/share/ca-certificates/mozilla/`:

```
WoSign.crt                      WoSign_China.crt
StartCom_Certification_Authority{,_2,_G2}.crt
CNNIC_ROOT.crt                  PSCProcert.crt
Camerfirma_Chambers_of_Commerce_Root.crt   Camerfirma_Global_Chambersign_Root.crt
Chambers_of_Commerce_Root_-_2008.crt       Global_Chambersign_Root_-_2008.crt
E-Tugra_Certification_Authority.crt        Certinomis_-_Autorité_Racine.crt
thawte_Primary_Root_CA{,_-_G2,_-_G3}.crt
GeoTrust_{Global_CA,Global_CA_2,Primary_Certification_Authority,
          Primary_Certification_Authority_-_G2,-_G3,Universal_CA,Universal_CA_2}.crt
Verisign_/VeriSign_… (17 files)            Equifax_Secure_{CA,eBusiness_CA_1,Global_eBusiness_CA}.crt
SwissSign_{Gold,Platinum,Silver}_CA_-_G2.crt
```

**[EXTERNAL]** WoSign and StartCom were distrusted by Mozilla/Google in 2016–2017; CNNIC in
2015; the Symantec family (VeriSign / GeoTrust / thawte / RapidSSL) was fully distrusted by
Chrome and Firefox during 2018; Camerfirma in 2021; E-Tugra in 2023. **[INFERRED]** None of
those decisions ever reached this device, because the store has not been rebuilt since
before most of them happened.

**[INFERRED]** The practical risk is bounded by §7 — a trust store only matters to something
that validates a certificate, and nothing here does. It becomes load-bearing the moment
anyone adds an HTTPS client to this device (an aftermarket update checker, a sample
downloader) and relies on the system store rather than shipping its own.

---

## 6. The consumer: JUCE 5.4.5 `WebInputStream`, disassembled

`R/usr/bin/las-frontend` is a **JUCE v5.4.5** application **[READ, literal `JUCE v5.4.5`
at file offset 144,017,252]** with 866 `juce` RTTI type-name strings **[READ]**.

Section geometry, for anyone repeating this **[READ, `llvm-objdump --section-headers`]**:

```
.plt      0x000019d0 @ 0x00017d2c    .text    0x00a2bbd4 @ 0x00019700
.rodata   0x07f3c122 @ 0x00a452e0    .data    0x000026e0 @ 0x08a6dcf8
```

`.text` is 10.66 MB = **2,666,101 ARM words**. `.rodata` is 133 MB (fonts, images, presets).
The binary is stripped to `.dynsym`; there is no `.symtab`.

### 6.1 All fifteen curl entry points funnel through one 60-byte table

**This is the single most important structural fact in the report.**

**[READ]** A full decode of all 2,666,101 words of `.text`, computing the branch target of
every ARM `BL` (cond ≠ 0xF, bits 27:24 = 0b1011) and `BLX`-immediate (bits 31:25 = 0b1111101),
finds **zero direct branches to any of the fifteen curl PLT stubs**.

**[READ]** A byte scan of the whole 145 MB file for each stub address as a little-endian
32-bit word finds it in exactly two places: its own `.rel.plt`/`.dynsym` entry, and a
**contiguous, ordered 15-word table at `.text:0x92aca0`** (file offset `0x91aca0`):

```
0x92aca0  curl_easy_init            0x92acc0  curl_multi_init
0x92aca4  curl_easy_setopt          0x92acc4  curl_multi_perform
0x92aca8  curl_easy_cleanup         0x92acc8  curl_multi_remove_handle
0x92acac  curl_easy_getinfo         0x92accc  curl_multi_timeout
0x92acb0  curl_multi_add_handle     0x92acd0  curl_slist_append
0x92acb4  curl_multi_cleanup        0x92acd4  curl_slist_free_all
0x92acb8  curl_multi_fdset          0x92acd8  curl_version_info
0x92acbc  curl_multi_info_read
```

**[READ]** The function that fills it, at `.text:0x92ac0c`:

```
92ac0c  push {r4, lr}
92ac10  mov  r4, r0
92ac14  mov  r0, #60            ; sizeof == 15 pointers
92ac18  bl   0x18724 <_Znwj@plt>
92ac1c  ldr  r2, [pc, #0x7c]    ; = curl_easy_init@plt
92ac20  str  r0, [r4]
92ac24  str  r2, [r0]
        …fourteen more ldr/str pairs at +0x04 … +0x38…
92ac98  mov  r0, r4
92ac9c  pop  {r4, pc}
```

**[INFERRED]** This is JUCE's `CURLSymbols::create()` from
`juce_core/native/juce_curl_Network.cpp`, compiled **without** `JUCE_LOAD_CURL_SYMBOL_LAZILY`
— it stores the link-time PLT addresses directly rather than `dlopen`ing libcurl. Evidence:
the field count (15), the exact field order, the `new` of a 15-pointer struct, and the fact
that every subsequent libcurl call in the binary is `ldr r3,[pimpl,#0x34]; ldr r3,[r3,#off];
blx r3`.

**[READ]** `0x92ac0c` has **exactly one caller**: `0x924ca8`, inside the function at
`0x924c6c`.

**[READ]** No `movt` instruction exists anywhere in `.text` (`grep -c '\bmovt\b'` over the
full disassembly → **0**; `movw` → 5,068). **[INFERRED]** Therefore no 32-bit address in
this binary can be formed by a `movw`/`movt` pair, and the byte-level word scan above is
*complete* — every reference to any address is either a literal-pool word (scanned) or a
PC-relative branch (decoded).

### 6.2 `WebInputStream::Pimpl` construction — `.text:0x924c6c`

**[READ]**, annotated:

```
924c6c  ldr  r3, [pc, #0x1e8]   ; vtable 0x08967e18
924c70  push {r0,r1,r2,r4..r9,lr}
924c78  str  r3, [r0]
924c7c  mov  r0, #176           ; new WebInputStream::Pimpl (176 bytes)
924c88  bl   _Znwj@plt
924ca8  bl   0x92ac0c           ; pimpl+0x34 = CURLSymbols::create()
924cc0  cmp  r8, #0             ; r8 = the usePost argument
924cd0  mov  r3, #5
924cd4  str  r3, [r4, #0x4c]    ; numRedirectsToFollow = 5
924cd8  ldr  r3, [pc, #0x180]   ; → "POST" (0x089695c6)
924cdc  ldr  r1, [pc, #0x180]   ; → "GET"  (0x089695cb)
924ce0  strb r8, [r4, #0x50]    ; pimpl->isPost
924ce4  movne r1, r3            ; r1 = usePost ? "POST" : "GET"
924ce8  bl   0x909a70           ; String ctor → pimpl+84 (httpRequest)
924cf4  strd -1,-1, [r4, #88]   ; contentLength = -1
924d58  bl   pthread_mutex_lock@plt        ; JUCE getCurlLock()
924d64  blx  [symbols+0x20]     ; curl_multi_init()      → pimpl+0x38
924d94  blx  [symbols+0x00]     ; curl_easy_init()       → pimpl+0x3c
924db4  blx  [symbols+0x10]     ; curl_multi_add_handle(multi, easy)
```

The `POST`/`GET` string pointers are **[READ]** from the literal pool at `0x924e60` /
`0x924e64` → `.rodata` `0x089695c6` = `"POST"`, `0x089695cb` = `"GET"`.

### 6.3 `setOptions()` — `.text:0x93d0ec` — every option, in order

**[READ]** for each option number (the immediate in `r1`) and each value.
**[EXTERNAL]** for the mapping from number to the public `CURLOPT_*` name; these constants
have been ABI-stable across curl 7.x.

| addr | option | name | value |
|---|---|---|---|
| `0x93d11c` | — | `curl_version_info(3)` | `CURLVERSION_FOURTH` |
| `0x93d1c4` | `10002` | `CURLOPT_URL` | the URL, raw UTF-8 |
| `0x93d1e4` | `10001` | `CURLOPT_WRITEDATA` | `this` |
| `0x93d204` | `20011` | `CURLOPT_WRITEFUNCTION` | `0x0092c2a8` |
| `0x93d224` | `99` | `CURLOPT_NOSIGNAL` | `1` |
| `0x93d244` | `68` | `CURLOPT_MAXREDIRS` | `pimpl+0x4c` (= 5) |
| `0x93d264` | `10018` | `CURLOPT_USERAGENT` | `"curl/" + version` |
| `0x93d290` | `52` | `CURLOPT_FOLLOWLOCATION` | `numRedirects > 0 ? 1 : 0` |
| `0x93d2e0` | `10009` | `CURLOPT_READDATA` | `this` — POST only |
| `0x93d300` | `20012` | `CURLOPT_READFUNCTION` | `0x0092852c` — POST only |
| `0x93d320` | `47` | `CURLOPT_POST` | `1` — POST only |
| `0x93d344` | `30120` | `CURLOPT_POSTFIELDSIZE_LARGE` | `curl_off_t` from `pimpl+0x74` |
| `0x93d3a8` | `10036` | `CURLOPT_CUSTOMREQUEST` | only if verb ≠ `"POST"`/`"GET"` |
| `0x93d384` | `10029` | `CURLOPT_HEADERDATA` | `this` |
| `0x93d3cc` | `20079` | `CURLOPT_HEADERFUNCTION` | `0x00933d84` |
| `0x93d40c` | `78` | `CURLOPT_CONNECTTIMEOUT` | `(timeoutMs + 999) / 1000` seconds — only if `timeoutMs > 0` |
| `0x93d434` | `19` | `CURLOPT_LOW_SPEED_LIMIT` | `100` bytes/s |
| `0x93d454` | `20` | `CURLOPT_LOW_SPEED_TIME` | same seconds value |
| `0x93d578` | `10023` | `CURLOPT_HTTPHEADER` | slist built at `0x93d520` / `0x93d638` |

And on completion, `.text:0x93d688` / `0x93d6ac` **[READ]**, constants resolved from the
literal pool at `0x93d754` / `0x93d758`:

| addr | info | name |
|---|---|---|
| `0x93d688` | `0x200002` | `CURLINFO_RESPONSE_CODE` → `pimpl+0x80` |
| `0x93d6ac` | `0x30000f` | `CURLINFO_CONTENT_LENGTH_DOWNLOAD` → `__aeabi_d2lz` → `pimpl+0x58` |

**What is conspicuously never set** **[READ, negative — no `curl_easy_setopt` call in the
binary carries these immediates]**:

```
CURLOPT_SSL_VERIFYPEER (64)   CURLOPT_SSL_VERIFYHOST (81)
CURLOPT_CAINFO (10065)        CURLOPT_CAPATH (10097)
CURLOPT_PROXY (10004)         CURLOPT_SSLVERSION (32)
CURLOPT_TIMEOUT (13) / _MS (155)
```

**[INFERRED]** Certificate verification is therefore **on** (libcurl defaults
`VERIFYPEER=1`, `VERIFYHOST=2`), against the compiled-in `CApath` `/etc/ssl/certs` from
§3.3. Nobody disabled TLS verification here. Equally, nobody pinned anything, and nobody
overrode the trust store.

**[INFERRED]** Two behavioural consequences worth naming:
* `CURLOPT_NOSIGNAL=1` **plus** a blocking resolver (§3.1) means the `SIGALRM` DNS timeout
  is disabled and `CURLOPT_CONNECTTIMEOUT` does **not** bound name resolution. A request to
  an unresolvable host would block its thread for the system resolver's own timeout.
* There is no overall transfer timeout — only connect timeout plus a
  100 bytes/s low-speed floor.

### 6.4 The exact request this code would emit

**[READ]** `CURLOPT_USERAGENT` is built at `0x93d190`–`0x93d1a0`: a `juce::String` from the
`.rodata` literal `"curl/"` (vaddr `0x089696fb`) concatenated with `[r7+4]`, which is the
`version` field of the `curl_version_info_data` struct — **`"7.47.1"`** (§3.1).

```
User-Agent: curl/7.47.1
```

**[READ]** Extra headers are split on `"\r\n"` (literal at `0x0896e644`) into a
`StringArray` and appended one per `curl_slist_append`. **[READ]** No `Content-Type`,
`Accept`, `Accept-Encoding` or `Authorization` literal is set by this code — libcurl adds
only its own `Host:` and `Accept: */*` defaults.

That User-Agent string is the network fingerprint to look for. **If a Moog One ever appears
in a proxy or firewall log, it will present as `curl/7.47.1` over TLS 1.2, and per §7 that
should never happen.**

---

## 7. Reachability: the client is never called

This is the load-bearing negative, so here is the whole derivation.

### 7.1 Every path to libcurl passes through one constructor

From §6.1: fifteen curl PLT stubs, zero direct branches, one 15-pointer table, one builder
(`0x92ac0c`), one caller of that builder (`0x924ca8`, inside `0x924c6c`). **[READ]**

`0x924c6c` is `juce::WebInputStream::WebInputStream(const URL&, bool usePost)` **[INFERRED]**
— it installs vtable `0x08967e18`, `new`s a 176-byte pimpl, seeds `numRedirects = 5`, picks
`"POST"`/`"GET"` from its `bool` argument, and calls `curl_multi_init`/`curl_easy_init`/
`curl_multi_add_handle` in JUCE's documented order.

### 7.2 It has three callers, and all three are dead

**[READ]** `bl 0x924c6c` occurs at exactly three sites:

| call site | enclosing function | what it is |
|---|---|---|
| `0x925998` | `0x92594c` | `URL::createInputStream`-family wrapper |
| `0x9261dc` | `0x926174` | second `URL` wrapper (download/read-entire family) |
| `0xa13e8c` | `0xa13e70` | `juce::ReportingThread::run()` — `usePost = 1` |

**[READ]** A reverse-reachability walk over the full `.text` — following `bl`, `b`
tail-calls, **and** every literal-pool/`.rodata`/`.data` word that equals a function address
— closes after **nine functions**:

```
L0  0x924c6c   WebInputStream ctor
L1  0x92594c   (no callers)          L1  0x926174   (called only by L2 below)
L1  0xa13e70   ← vtable 0x8973d30
L2  0x926344 / 0x9264fc / 0x92662c   (no callers)
L2  0x9263c0   ← vtable 0x8967ddc
L3  0x92675c   (no callers)
```

Only two of the nine are reachable other than by a direct branch, and both are virtual:

* **`0x9263c0` sits in the vtable at `0x8967dd0`**, whose typeinfo `0x8968430` names
  **`N4juce14URLInputSourceE`** **[READ]**. So it is
  `juce::URLInputSource::createInputStream()`. **[READ]** The `URLInputSource` constructor
  is at `0x924a28` (it writes vtable `0x08967dd0`) and has **zero `b`/`bl` callers and zero
  word references**. Nothing ever constructs a `URLInputSource`.
* **`0xa13e70` sits in the vtable at `0x8973d28`**, whose typeinfo `0x08970440` names
  **`N4juce15ReportingThreadE`** **[READ]**. That is JUCE's splash-screen usage reporter.

### 7.3 The `ReportingThread` is never constructed

**[READ]** The `ReportingThread` vtable address-point `0x8973d28` is referenced from exactly
two literal pools, `0xa2140c` (destructor) and `0xa216bc` (constructor, at `0xa2143c`).

**[READ]** Literals resolved inside the constructor `0xa21388`–`0xa216cc`:

```
0xa216b8 → 0x0897d976  "JUCE app usage reporting"   (the juce::Thread name)
0xa216c0 → 0x0897d98f  "User-Agent: "
0xa216c4 → 0x08968b30  "="
0xa216c8 → 0x07ea76ba  "&"
```

— i.e. it builds `key=value&key=value` query parameters and a `User-Agent:` extra header,
and `run()` POSTs them (`usePost = 1` at `0xa13e8c`).

**[READ]** `curl_easy_setopt`'s `CURLOPT_USERAGENT` in §6.3 is separate from this
`"User-Agent: "` literal; the latter is an *extra header* string built by the reporter.

**[READ]** `bl 0xa2143c` occurs exactly once in the whole `.text`, at `0x9c9974`, inside the
function starting at `0x9c9944`:

```
9c9944  push {r0,r1,r4..r8,lr}
9c994c  mov  r0, #352            ; new ReportingThread (352 bytes)
9c995c  bl   _Znwj@plt
9c9974  bl   0xa2143c           ; ReportingThread ctor(url, …)
9c997c  str  r5, [r4, #0x8]
9c9998  b    0x919870           ; Thread::startThread()
```

**[READ]** `0x9c9944` has **zero `b`/`bl` callers and zero 32-bit word references anywhere in
the 145 MB file.**

**[INFERRED]** Therefore, with `movt` absent from the binary (§6.1), the usage-reporting
POST cannot be reached by any control-flow path. **The JUCE analytics call is dead code.**
This is consistent with a commercial JUCE licence, where `JUCE_REPORT_APP_USAGE` /
`JUCE_DISPLAY_SPLASH_SCREEN` are off and the linker retains the out-of-line copies.

### 7.4 `https://juce.com` is a browser launch, not a fetch

**[READ]** The literal `https://juce.com` lives at `.rodata` vaddr `0x0897d965` (file offset
144,103,781; the byte layout is
`_NET_WM_ICON\0https://juce.com\0JUCE app usage reporting\0User-Agent: \0`). It has
**exactly one** 32-bit reference in the file, the literal pool at `0x9c9940`, consumed by
the function at `0x9c98e8`:

```
9c98e8  str  lr,[sp,#-4]!
9c98f0  ldr  r1,[pc,#0x48]   ; "https://juce.com"
9c98f8  bl   0x909a70        ; String::String(const char*)
9c9904  bl   0x925e84        ; URL::URL(const String&)
9c9914  bl   0x925410        ; URL::launchInDefaultBrowser()
```

**[INFERRED]** `0x925410` is `launchInDefaultBrowser` and not an HTTP call: it is not in the
nine-function reachable set of §7.2, and the browser-name table sits immediately beside the
`URLInputSource` vtable in `.rodata` **[READ, `0x8967de4`–`0x8967e00`]**:

```
xdg-open   /etc/alternatives/x-www-browser   firefox   mozilla
google-chrome   chromium-browser   opera   konqueror
```

`0x9c98e8` is itself only referenced from a vtable slot at `0x8978c34` — the
`JUCESplashScreen` vtable **[READ, typeinfo `0x897c9ec` → `N4juce16JUCESplashScreenE`]** —
i.e. it is the splash screen's `mouseUp` handler.

### 7.5 No hostname of Moog's exists anywhere in the binary

**[READ]** Complete inventory of `http(s)://` literals in the 145 MB file (59 matches,
32 distinct):

```
w3.org (SVG/xlink/RDF/DTD)          ns.adobe.com (XMP)      www.adobe.com
dejavu.sourceforge.net              scripts.sil.org (OFL)   purl.org (Dublin Core)
www.paratype.com{,/help/designers,/eula}                    www.serif.com
ocsp.thawte.com  crl.thawte.com/{ThawteTimestampingCA,ThawtePCA,ThawteCSG2}.crl
cs-g2-crl.thawte.com  www.thawte.com/{repository,cps}
ts-{aia,crl,ocsp}.ws.symantec.com   th.symc{b,d}.com
https://juce.com
```

**[READ]** Complete inventory of bare hostname-shaped tokens (`*.com|net|org|io|co|dev|cloud`):
the same set. **Zero Moog hostnames. Zero update, licence, analytics or preset-store hosts.**

### 7.6 The same is true of v1.5.0

**[READ]** `R15/usr/bin/las-frontend` (`42670ca0…`) has: the identical 16-entry
`DT_NEEDED` list; 15 `curl_*` imports and 0 OpenSSL imports; **zero** `movt` instructions;
**zero** direct branches to any curl PLT stub across the whole of its `.text` (`0xa2b454`
bytes at `0x19700`); and
one contiguous 15-word `CURLSymbols` table, at `0x92a520`, in the same field order.

**[READ]** Its `WebInputStream` constructor is at `0x9244ec` with the same three callers at
the same relative offsets (`0x925218`, `0x925a5c`, `0xa1370c`). Its `ReportingThread`
launcher is at `0x9c91c4`, byte-for-byte the same prologue (`mov r0,#352` → `_Znwj`), and
has **zero `b`/`bl` callers and zero word references**. Its `https://juce.com` at
`0x8986b9d` has exactly one reference, the pool at `0x9c91c0`.

**[INFERRED]** The HTTP subsystem of `las-frontend` is unchanged in structure and in
reachability between May 2022 and September 2025.

---

## 8. The Thawte / Symantec chain, fully accounted for

The brief flagged this as unexplained. It is explained.

**[READ]** `las-frontend` contains three `DSIG` sfnt table tags, at file offsets
**134,498,844**, **135,289,642** and **136,338,204**, each surrounded by `ParaType` /
`PT`-font metadata (`ParaType` occurs at 134,503,527; 134,613,279; 136,342,716; 136,459,271;
and more).

**[READ]** Five DER certificates were extracted from the region 134,490,000–134,630,000 by
scanning for `30 82 xx xx 30 82 xx xx a0 03 02 01 02` and parsed with `openssl x509`:

| file offset | subject | issuer | validity |
|---|---|---|---|
| 134,562,296 | `C=US/O=Symantec Corporation/CN=Symantec Time Stamping Services CA - G2` | `C=ZA/…/O=Thawte/CN=Thawte Timestamping CA` | 2012-12-21 → **2020-12-30** |
| 134,563,306 | **`C=US/ST=California/L=Saratoga/O=Paratype, Inc./CN=Paratype, Inc.`** | `C=US/O=Thawte, Inc./CN=Thawte Code Signing CA - G2` | 2012-11-03 → **2014-11-03** |
| 134,564,350 | `CN=thawte Primary Root CA` (self-signed) | itself | 2006-11-17 → 2036-07-16 |
| 134,565,410 | `C=US/O=Thawte, Inc./CN=Thawte Code Signing CA - G2` | `CN=thawte Primary Root CA` | 2010-02-08 → **2020-02-07** |
| 134,566,594 | `C=US/O=Symantec Corporation/CN=Symantec Time Stamping Services Signer - G4` | `CN=Symantec Time Stamping Services CA - G2` | 2012-10-18 → **2020-12-29** |

**[INFERRED]** This is a complete **Authenticode code-signing chain plus RFC-3161
timestamp chain**, embedded inside the `DSIG` table of a ParaType font that JUCE compiled in
as a `BinaryData` resource. It is the *font vendor's* signature over the *font*.

Three things follow, and each is worth stating so nobody re-discovers this and gets excited:

1. **It is not Moog's.** No Moog entity appears in any of the five certificates.
2. **It is not related to firmware signing.** Nothing on this device validates an
   Authenticode signature; the format is a Windows convention that survived into the font
   file.
3. **It plays no part in the HTTP client's trust decisions.** libcurl's trust anchors come
   from `/etc/ssl/certs` (§3.3), which is a separate, on-disk store. `thawte Primary Root CA`
   happens to *also* be in that store — but as one of 179 roots, not because of this font.

The other cluster near offset 136,408,000 is the same chain again, in a second embedded
ParaType font **[READ, `Paratype` at 136,412,501 / 136,412,526]**.

---

## 9. What this means

For the owner:

* **The UI process does not phone home over HTTP.** The documented phone-home
  (`docs/firmware/network.md` §8, `lassvc.md`) is a *reverse SSH* from `las-dwm` behind a
  magic front-panel code. It is a different binary, a different protocol and a different
  trigger. This report changes nothing about it, and finds no second channel.
* **There is no HTTP-based update check.** Firmware update on this device is
  `lasfwu`/USB-thumbdrive, not network fetch. `lasfwu` does not link libcurl **[READ, §2.1
  sweep]**.
* **The stale CA store is not currently exploitable, because nothing uses it.** It becomes a
  real problem the moment anyone — Moog, or this project — adds an HTTPS client to the
  device. Anything added should ship its own pinned trust anchor rather than relying on
  `/etc/ssl/certs`.
* **`curl/7.47.1` is the string to watch for.** If a Moog One ever appears in a network log
  with that User-Agent, something is running in `las-frontend` that this report says should
  not be.

For anyone extending the instrument:

* **A working, TLS-verifying HTTP client already exists in-process** and costs nothing to
  reach if you can get code into `las-frontend` — but you cannot, without replacing Moog's
  signed binary. It is not a plugin surface.
* **libcurl is a shared library.** `libcurl.so.4` is on the device and usable by any new
  binary, with the caveats: HTTP/1.1 only, TLS 1.2 max, blocking DNS, and the 2014 trust
  store.

---

## 10. Unknowns, and what was not examined

* **[UNKNOWN]** The exact Debian `ca-certificates` package version. No manifest, no
  `/etc/ca-certificates.conf`.
* **[UNKNOWN]** Whether `JUCE_DISPLAY_SPLASH_SCREEN` / `JUCE_REPORT_APP_USAGE` were `0` in
  Moog's `AppConfig.h`, or whether the reporter is guarded some other way. What is proven is
  the *result*: the construction site is unreferenced. The cause is inference.
* **[UNKNOWN]** What URL the `ReportingThread` would have been given. It is a constructor
  argument supplied by the unreachable caller at `0x9c9944`, which itself receives it from a
  caller that does not exist. No URL literal for it survives in the binary.
* **[UNKNOWN]** Whether `wpa_supplicant`'s OpenSSL path is ever exercised (WPA-Enterprise).
  Out of scope.
* **Not examined:** `juce::NetworkServiceDiscovery::Advertiser` and `AvailableServiceList`
  RTTI are both present **[READ, name strings at file offsets 144,026,104 and 144,026,176]**
  with live vtable references at `0x896a570` and `0x896a710`. That is JUCE's **UDP broadcast**
  discovery — a different mechanism from this report's subject, and it deserves the same
  reachability treatment.
* **Not examined:** `libasound.so.2`. `las-frontend` imports 40 ALSA **sequencer** symbols
  (`snd_seq_open`, `snd_seq_create_simple_port`, `snd_seq_connect_to/from`,
  `snd_seq_event_input`, `snd_midi_event_encode/decode`, …) **[READ, `llvm-objdump -T`]**.
  That is JUCE's ALSA MIDI backend, linked into the UI process. Whether any of it is
  reachable — and how it squares with the established finding that no MIDI byte reaches
  Linux — is a separate question this report did not open. `libasound` has zero coverage in
  the existing 18 reports.
* **Not examined:** the `--enable-tests` / `--disable-tests` / `--test-fixture` options.
  `N4juce14UnitTestRunnerE` and `N4juce8UnitTestE` are both present **[READ]**, but no
  `UnitTest` subclass in the reachable set touches `URL`.

---

## 11. Conflicts with existing documentation

**No contradictions were found. Two refinements.**

### 11.1 `docs/arch/capability-survey.md:631` — confirmed and strengthened

The existing text reads:

> **`libcurl` and JUCE `WebInputStream` are linked into `las-frontend` and nothing uses
> them.** Zero Moog, telemetry, analytics or update hostnames in the binary; every
> `http(s)://` literal is certificate-authority, font or XML-namespace boilerplate [READ,
> negative]. Latent HTTP-client capability, no endpoint.

**Every part of that is correct.** This report upgrades it from a string-based negative to a
call-graph proof (§7) and adds the mechanism. Two phrasings could be tightened when that
file is next revised — *not* corrections, since neither changes the conclusion:

* "no endpoint" — there *is* one endpoint literal, `https://juce.com`, but it is consumed by
  `URL::launchInDefaultBrowser()`, not by the HTTP client (§7.4).
* "every `http(s)://` literal is certificate-authority, font or XML-namespace boilerplate" —
  true, and now specific: the certificate-authority ones are the **ParaType font's
  Authenticode DSIG**, not any CA store or signing infrastructure of Moog's (§8).

### 11.2 `docs/arch/performance.md:672` — confirmed exactly

The `DT_NEEDED` list quoted there matches byte-for-byte **[READ]**. One addition: the
`libssl.so.1.0.0` and `libcrypto.so.1.0.0` entries in that list are **over-linking** —
`las-frontend` imports zero OpenSSL symbols and reaches OpenSSL only transitively through
libcurl (§1.1). Anyone reasoning about the process's attack surface from that list should
know that.

### 11.3 Coverage before this report

**[READ]** across all of `docs/`: `libcurl` 2 occurrences, `curl` 3 (one of which is a shell
command in an unrelated plan file), `libssl` 1, `WebInputStream` 1, and **zero** for
`OpenSSL`, `User-Agent`, `juce.com`, `ca-certificates`, `thawte`, `symantec`, `ParaType`,
`CURLOPT`.

---

## 12. Validation plan — READ-ONLY commands for the human

**Do not run these as part of this report.** Every one is read-only, touches no Moog binary,
and writes nothing. They confirm the load-bearing claims against the *running* instrument
rather than against the extracted image.

Confirming the libraries and the trust store are what the image says:

```sh
sha256sum /usr/lib/libcurl.so.4.4.0 /usr/lib/libssl.so.1.0.0 \
          /usr/lib/libcrypto.so.1.0.0 /etc/ssl/certs/ca-certificates.crt
# expect dd48f407… / 52230e17… / d8d0d4ad… (v1.5.0) / 5754013d…

openssl version                     # expect: OpenSSL 1.0.2f  28 Jan 2016
ls /etc/ssl/certs | wc -l           # expect: 361
grep -c 'BEGIN CERTIFICATE' /etc/ssl/certs/ca-certificates.crt   # expect: 180
ls /usr/share/ca-certificates/mozilla | wc -l                    # expect: 179
```

Confirming the CA store is as stale as claimed:

```sh
openssl x509 -in /etc/ssl/certs/DST_Root_CA_X3.pem -noout -enddate
# expect: notAfter=Sep 30 14:01:15 2021 GMT   (an expired root, still trusted)
ls /usr/share/ca-certificates/mozilla | grep -i -e ISRG -e Amazon_Root -e GTS_Root
# expect: no output   (no modern roots present)
```

Confirming the process makes no outbound HTTP connection — the central claim of §7. Run
these while the instrument is idle at the main screen, and again after ten minutes of normal
play:

```sh
FE=$(pidof las-frontend)

# 1. every socket the UI process holds, with protocol and peer
ls -l /proc/$FE/fd | grep socket | wc -l
cat /proc/$FE/net/tcp /proc/$FE/net/tcp6
# expect: no ESTABLISHED entry with a remote port of 80 or 443 (0x0050 / 0x01BB)

# 2. is libcurl even mapped into the process?
grep -c libcurl /proc/$FE/maps        # expect: non-zero (it is linked)
grep -c libssl  /proc/$FE/maps        # expect: non-zero

# 3. system-wide: anything at all leaving on 80/443
ss -tanp 2>/dev/null | grep -E ':(80|443)\b'
# expect: no output

# 4. what the process actually has open (read-only listing)
lsof -p $FE -a -i 2>/dev/null
# expect: only the UDP/loopback OSC sockets already documented in network.md
```

A stronger, still read-only check — a short packet capture with **no** traffic generated by
the observer:

```sh
timeout 300 tcpdump -n -i any -c 200 \
  '(tcp port 80 or tcp port 443 or udp port 53) and not host 203.0.113.2' -w /tmp/fe-http.pcap
# expect: 0 packets captured, over five minutes of normal use
```

Confirming the environment the process was launched with (this is what decides proxy
behaviour, §3.4):

```sh
tr '\0' '\n' < /proc/$FE/environ | grep -iE 'proxy|SSL_CERT|CURL'
# expect: no output
```

If, contrary to §7, anything ever *is* observed, the fingerprint to match is
`User-Agent: curl/7.47.1` over TLS 1.2 (§6.4).
