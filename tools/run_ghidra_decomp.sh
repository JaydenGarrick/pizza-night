#!/bin/sh
# Headless Ghidra: import the PE-wrapped Xbox executable, auto-analyse, and export decompiled C for the NAL animation code.
# Output: intermediate/xbox/decomp_nal.c   (takes several minutes; needs Java 21 — /opt/homebrew/opt/openjdk@21)
cd "$(dirname "$0")/.." || exit 1
export JAVA_HOME=/opt/homebrew/opt/openjdk@25
export PATH="$JAVA_HOME/bin:$PATH"
GH=/opt/homebrew/opt/ghidra/libexec
rm -rf intermediate/tools/ghproj && mkdir -p intermediate/tools/ghproj
"$GH/support/analyzeHeadless" intermediate/tools/ghproj sm2 \
  -import intermediate/xbox/default_xbe.exe \
  -scriptPath tools/ghidra_scripts \
  -postScript ExportDecomp.java intermediate/xbox/decomp_nal.c 0x32b000-0x337000 0x2dd000-0x2e6000 0x33c000-0x33d000 0x1cf000-0x1d2000 \
  2>&1 | tee intermediate/xbox/ghidra_headless.log | grep -E "INFO  (Analysis|REPORT)|decompiled|wrote|ERROR|Exception" 
echo "done -> intermediate/xbox/decomp_nal.c"
