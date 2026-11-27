#!/usr/bin/env python3
"""Derive packet inter-arrival variation from the metadata CSV produced by tshark."""
import argparse, csv, statistics, json
from collections import defaultdict
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("capture_csv",type=Path)
    p.add_argument("--out",type=Path,default=Path("packet-interarrival.json"))
    a=p.parse_args()
    flows=defaultdict(list)
    with a.capture_csv.open(newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ts=float(row["frame.time_epoch"])
                key=(row.get("ip.src",""),row.get("ip.dst",""),row.get("tcp.srcport",""),row.get("tcp.dstport",""))
                flows[key].append((ts,int(row.get("tcp.len") or 0),row.get("tcp.analysis.retransmission","")))
            except (ValueError,KeyError): continue
    result=[]
    for key,items in flows.items():
        items.sort()
        gaps=[(items[i][0]-items[i-1][0])*1000 for i in range(1,len(items))]
        result.append({"flow":{"src":key[0],"dst":key[1],"src_port":key[2],"dst_port":key[3]},
          "packets":len(items),"payload_packets":sum(1 for x in items if x[1]>0),
          "mean_interarrival_ms":statistics.mean(gaps) if gaps else None,
          "std_interarrival_ms":statistics.pstdev(gaps) if len(gaps)>1 else None,
          "p50_interarrival_ms":statistics.median(gaps) if gaps else None,
          "p95_interarrival_ms":sorted(gaps)[int(.95*(len(gaps)-1))] if gaps else None,
          "retransmission_marked_packets":sum(1 for x in items if x[2])})
    output={"metric":"TCP packet inter-arrival variation (not RTP/RFC3550 jitter)",
            "capture":str(a.capture_csv),"flows":result,
            "caveat":"Capture point, offload settings, clock resolution and packet aggregation affect values. Do not call this one-way delay jitter without synchronized capture points and a defined packet matching method."}
    a.out.write_text(json.dumps(output,indent=2),encoding="utf-8")
    print(f"Wrote {a.out}")
if __name__=="__main__": main()
