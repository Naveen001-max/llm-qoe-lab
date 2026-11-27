#!/usr/bin/env bash
set -euo pipefail
: "${PCAP:?Set PCAP to a pcap/pcapng file}"
OUT="${OUT:-${PCAP%.*}.metadata.csv}"
tshark -r "$PCAP" -Y tcp -T fields -E header=y -E separator=, -E quote=d \
  -e frame.time_epoch -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport \
  -e tcp.len -e tcp.analysis.retransmission > "$OUT"
echo "Wrote metadata-only CSV: $OUT"
