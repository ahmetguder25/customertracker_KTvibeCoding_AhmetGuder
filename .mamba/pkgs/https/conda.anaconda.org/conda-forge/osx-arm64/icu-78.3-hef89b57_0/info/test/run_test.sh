#!/bin/bash

set -e

genrb de.txt
echo "de.res" > list.txt
pkgdata -p mybundle list.txt


set -ex



test ! -f $PREFIX/lib/libicudata.a
test -f $PREFIX/lib/libicudata.78.3.dylib
test ! -f $PREFIX/lib/libicui18n.a
test -f $PREFIX/lib/libicui18n.78.3.dylib
test ! -f $PREFIX/lib/libicuio.a
test -f $PREFIX/lib/libicuio.78.3.dylib
test ! -f $PREFIX/lib/libicutest.a
test -f $PREFIX/lib/libicutest.78.3.dylib
test ! -f $PREFIX/lib/libicutu.a
test -f $PREFIX/lib/libicutu.78.3.dylib
test ! -f $PREFIX/lib/libicuuc.a
test -f $PREFIX/lib/libicuuc.78.3.dylib
genbrk --help
gencfu --help
gencnval --help
gendict --help
icuinfo --help
icu-config --help
makeconv gb-18030-2000.ucm
exit 0
