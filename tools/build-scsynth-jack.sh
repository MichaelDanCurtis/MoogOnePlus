set -e
APT="apt-get -o Acquire::Check-Valid-Until=false -y --allow-unauthenticated"
echo "=== [1/4] jessie apt (glibc 2.19, archive key is expired -> trusted=yes) ==="
# All three suites. The base image's own packages come from updates/security, so
# with only `main` present apt cannot resolve even bzip2 and every install fails
# with "is not going to be installed".
cat > /etc/apt/sources.list <<EOF
deb [check-valid-until=no,trusted=yes] http://archive.debian.org/debian jessie main
deb [check-valid-until=no,trusted=yes] http://archive.debian.org/debian jessie-updates main
deb [check-valid-until=no,trusted=yes] http://archive.debian.org/debian-security jessie/updates main
EOF
$APT update 2>&1 | tail -1
# Staged, so one unresolvable package cannot abort the whole transaction.
$APT install gcc-4.8 g++-4.8 make 2>&1 | tail -2
$APT install cmake pkg-config 2>&1 | tail -2
$APT install libfftw3-dev 2>&1 | tail -2
$APT install libsndfile1-dev libjack-jackd2-dev libasound2-dev 2>&1 | tail -2
$APT install libx11-dev libxt-dev libudev-dev 2>&1 | tail -2
$APT install libboost-system-dev libboost-filesystem-dev libboost-thread-dev 2>&1 | tail -2
echo "gcc: $(gcc-4.8 --version|head -1)"
echo "cmake: $(cmake --version|head -1)"
echo "glibc: $(ldd --version|head -1)"

echo "=== [2/4] configure: scsynth only, AUDIOAPI=jack ==="
rm -rf /w/build && mkdir -p /w/build && cd /w/build
cmake /w/sc39 \
  -DCMAKE_BUILD_TYPE=Release -DAUDIOAPI=jack \
  -DCMAKE_C_COMPILER=gcc-4.8 -DCMAKE_CXX_COMPILER=g++-4.8 \
  -DSC_QT=OFF -DSC_IDE=OFF -DSC_ED=OFF -DSC_EL=OFF -DSC_VIM=OFF \
  -DSUPERNOVA=OFF -DNATIVE=OFF -DINSTALL_HELP=OFF \
  -DCMAKE_C_FLAGS="-march=armv7-a -mfpu=neon -mfloat-abi=hard" \
  -DCMAKE_CXX_FLAGS="-march=armv7-a -mfpu=neon -mfloat-abi=hard" 2>&1 | tail -30

echo "=== [3/4] build scsynth (this is the slow part) ==="
make scsynth -j2 2>&1 | tail -20

echo "=== [4/4] result ==="
BIN=$(find /w/build -name scsynth -type f | head -1)
ls -la "$BIN"
echo "--- highest GLIBC symbol required (device has 2.21) ---"
objdump -T "$BIN" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -4
echo "--- GLIBCXX required (device libstdc++ must supply this) ---"
objdump -T "$BIN" | grep -o 'GLIBCXX_[0-9.]*' | sort -uV | tail -2
echo "--- JACK driver compiled in? ---"
strings "$BIN" | grep -c 'SC_JackDriver' || echo 0
echo "--- NEEDED ---"
objdump -p "$BIN" | grep NEEDED
cp "$BIN" /w/scsynth-jack
