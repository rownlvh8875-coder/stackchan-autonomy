# K151 HTTPS live-connection cancellation and ephemeral token handling

Status: **OFF-DEVICE / COMPILE-ONLY**. No robot install, cloud calls or network
connections have been made during this stage.

Before an HTTPS call, `K151HttpChannel` now requires the actual dormant
`K151WifiTimePort::live_network_ready()` policy instead of unrelated booleans.
The Wi-Fi event callback immediately revokes admission on disconnection OR
DHCP IP renewal, before the event queue is processed. The owner task resumes
admission only after fresh accepted SNTP evidence; periodic IP renewal no
longer starts the same SNTP service a second time. The live check uses
atomically published time anchors, current wall time and a 15-minute
freshness bound. Ordinary SNTP is **not authenticated UTC evidence**.

The HTTPS transport's `LiveIoGate` rechecks actual network/time readiness,
owner paid consent, physical STOP and a 30-second deadline at each
socket-opening, send/receive chunk and final response boundary. Revocation
latches for the current request; subsequent network recovery **never**
permits the same request to continue or retry. A single ESP-IDF synchronous
I/O can still block for the configured timeout, so hard realtime
electrical STOP or immediate TCP cancellation is NOT proven.

`EphemeralApiKey` holds a noncopyable local byte array; the network port
copies a validated key into it while holding a mutex protecting RAM secret
clear. The caller uses the snapshot for one synchronous POST and wipes it
on return. This does not prevent other temporary heap copies created by the
ESP-IDF HTTP client or prove immunity from RAM/flash extraction. No key
persists in NVS. Power restart requires re-provisioning through a separately
approved local-owner process that **is not yet implemented**.

The firmware `app_main` still only links compile markers. Neither Wi-Fi,
SNTP, HTTPS nor the token holder are constructed or started on boot.
The source and host tests for this stage prove policy invariants, not
real K151 wireless connectivity or a charged OpenAI transaction.
