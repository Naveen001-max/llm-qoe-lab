# External Ubuntu Linux NetEm gateway

The production platform uses one network impairment implementation: an authenticated Linux host agent controlling `tc/netem` and IFB on a dedicated external Ubuntu gateway. The retired LLM HTTP proxy-container approach is not part of this repository.

## Required topology

```text
Participant / tester PC (isolated lab LAN)
              |
              v
      Gateway LAN interface
        Ubuntu Linux host
      Gateway WAN interface ---- API / React host
              |
              +---- IFB ingress redirection

API host ---- routed gateway ---- inference host(s)
```

The gateway must be in the actual participant-to-application traffic path. Configure split-horizon DNS so participants resolve the application hostname to the API host's private WAN-side address. The API host needs the static route to the participant LAN through the gateway. Verify both directions with route inspection and packet capture before applying impairment profiles.

## 1. Prepare the dedicated gateway

Install Ubuntu Server 24.04 on a dedicated machine with two physical NICs. Identify the LAN-facing and WAN-facing interface names. The installer modifies Netplan, forwarding, nftables/NAT and chrony, so use it only on a dedicated lab gateway after confirming the network plan and backing up existing configuration. It requires explicit environment values:

```bash
export LAN_IF=enp2s0
export WAN_IF=enp3s0
export LAN_CIDR=10.20.0.1/24
export LAN_GW_IP=10.20.0.1
export WAN_DHCP4=true
export API_HOST_IP=10.30.0.10
export INFERENCE_IPS=10.20.0.20
export NTP_ALLOW_CIDRS='10.20.0.0/24 10.30.0.0/24'
sudo --preserve-env=LAN_IF,WAN_IF,LAN_CIDR,LAN_GW_IP,WAN_DHCP4,API_HOST_IP,INFERENCE_IPS,NTP_ALLOW_CIDRS bash install_gateway.sh
```

Review the script and its confirmation prompt before proceeding. Do not copy the example IP plan without checking for subnet overlap.

## 2. Install the authenticated qdisc agent

Create an internal-CA-signed TLS certificate with `qoe-gateway.lab` as a DNS Subject Alternative Name. Generate one high-entropy token and configure the same value as `QOE_GATEWAY_TOKEN` on the gateway and `GATEWAY_TOKEN` in the API environment.

```bash
export WAN_IF=enp3s0
export QOE_GATEWAY_TOKEN='GENERATE_A_LONG_RANDOM_SECRET_LOCALLY'
export GATEWAY_TLS_CERT=/path/to/qoe-gateway.crt
export GATEWAY_TLS_KEY=/path/to/qoe-gateway.key
sudo --preserve-env=WAN_IF,QOE_GATEWAY_TOKEN,GATEWAY_TLS_CERT,GATEWAY_TLS_KEY bash install_agent.sh
```

The installer creates a systemd service on TCP/8090 with TLS. The gateway firewall must allow TCP/8090 only from the API host. Never expose this privileged controller to the public Internet, participant LAN, Wi-Fi or a shared campus network.

On the API host, configure:

```dotenv
GATEWAY_CONTROL_URL=https://qoe-gateway.lab:8090
GATEWAY_HOST_IP=10.30.0.1
GATEWAY_TOKEN=<same token as QOE_GATEWAY_TOKEN>
GATEWAY_CA_BUNDLE=/run/secrets/gateway-ca.crt
REQUIRE_GATEWAY=true
```

Place the CA certificate at `production/secrets/gateway-ca.crt` before starting the API container. Do not place the private key in the application repository.

## 3. Verify the route and qdisc agent

On the gateway:

```bash
systemctl status qoe-gateway-agent
sudo tc -s qdisc show dev "$WAN_IF"
sudo tc -s qdisc show dev ifb0
```

From the API host, verify that `https://qoe-gateway.lab:8090/health` is reachable and that the authenticated `/status` endpoint returns `wan_qdisc_stats`, `ifb_qdisc_stats` and structured `qdisc_counters`. The `/health` endpoint is a liveness check; `/status` requires the bearer token.

Run a controlled baseline request, then a non-zero delay/loss/bandwidth test. Confirm the qdisc profile with `tc qdisc show`, verify packets traverse the intended gateway interfaces with `tshark`/`tcpdump`, and compare before/after qdisc counters. Reset to baseline after every trial.

## Counter semantics

The agent obtains counters from `tc -s qdisc show`. It preserves each qdisc separately for WAN egress and IFB ingress: bytes, packets, drops, overlimits and requeues. The API stores a start snapshot after profile application and an end snapshot before baseline reset, then computes deltas joined to the request ID. Parent and child qdisc counters are not summed because hierarchical qdiscs may count the same packet at multiple levels.

These are interface-wide qdisc deltas during a serialized request lease, not per-flow attribution. A small amount of controller traffic may be included. They are packet/byte/drop counters, not a direct jitter measurement. Use packet capture and inter-arrival analysis for packet-level jitter.

## WSL2 boundary

WSL2 is acceptable for application development and isolated network-namespace tests. It is not the physical gateway and cannot be relied on to shape a Windows physical Ethernet NIC. Use a dedicated external Ubuntu gateway with the participant and API traffic routed through it for physical-link experiments.
