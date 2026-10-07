# Network Time Synchronization and Clock Drift Analyzer

A Python Computer Networks mini project for a third-year B.Tech IT demonstration.
It runs a real localhost TCP time server, simulates 3–5 independent logical clocks,
and compares Cristian's reference-clock synchronization with Berkeley's group-clock
synchronization in a Tkinter interface.

## Project overview

Computers can disagree about the time even when each clock appears to work. An
initial **offset** is the difference between two clocks at one instant. **Clock
drift** is the accumulation of error because a clock runs slightly fast or slow.
Network latency makes the timestamp received from another computer already old.

This application demonstrates all three effects. It changes simulated clocks only;
it does not change Windows time or need administrator privileges.

## Problem statement

How can computers agree on time when their clocks differ and timestamp messages
take an unknown amount of time to travel? How does a trusted time source differ
from a group that agrees on its own average time?

## Objectives

- Implement real TCP request-response communication using Python sockets.
- Observe initial offsets, continuing clock drift and directional network delays.
- Apply and compare Cristian's and Berkeley's algorithms.
- Measure corrections, residual error and group/reference accuracy.
- Explain the results using a live table, event log and before/after graph.

## Features

- Automatically started reference server at `127.0.0.1:5000`, configurable by CLI.
- Three to five clients with random offsets from −10 to +10 seconds.
- Independent drift rates from −250 to +250 parts per million (ppm).
- Independent request and response delays, each from 50 to 500 ms.
- Measured RTT that includes real waits and local socket overhead.
- Live clocks updated every 100 ms using Tkinter `after()`.
- Background workers keep the interface responsive during network operations.
- Cristian reference synchronization and Berkeley polling/averaging.
- Mean offset, signed minimum/maximum offset and absolute minimum/maximum drift.
- Target error and external reference error displayed separately.
- Matplotlib before/after bars and request/response/RTT comparison.
- Per-client measurement details, bounded event log, reset and clean shutdown.
- Understandable messages for missing clients, stopped server and port conflicts.

## System architecture

```text
                         Tkinter GUI (main thread)
                        controls / table / event log
                                     |
                         background experiment worker
                                     |
        +----------------------------+----------------------------+
        |                                                         |
  Cristian: clients request                         Berkeley: master polls
  trusted reference time                            client logical times
        |                                                         |
  Client 1 / 2 / 3 -- TCP --> Time server    Time master -- TCP --> Client listeners
        |                                                         |
  timestamp + RTT/2                                 average relative offsets
        |                                                         |
  correct client logical clocks                     correct clients AND master
        +----------------------------+----------------------------+
                                     |
                    analyzer: error against known simulation truth
                                     |
                         table + Matplotlib comparison
```

All participants run on one computer, but requests pass through actual TCP
sockets. Berkeley clients listen on OS-assigned local ports. The master's
`poll_client()` method initiates their requests. The GUI orchestrates the
simulation; it never blocks while waiting for network messages.

The trusted **reference clock** is anchored to wall time at startup and advanced
using a monotonic timer. The **Berkeley logical master** starts at reference time
but can move when the group is averaged. Both are visible in the server panel.
Cristian always uses the unchanged reference, including after a Berkeley run.

## Technologies used

| Technology | Purpose |
| --- | --- |
| Python 3.11+ | Application and algorithms |
| Tkinter / ttk | Desktop GUI |
| `socket` / `socketserver` | TCP communication and threaded listeners |
| `threading` / `queue` | Workers and safe delivery of GUI updates |
| `time` / `datetime` | Monotonic measurements and displayed clock times |
| `random` | Offsets, rate errors and delays |
| JSON | Structured, newline-delimited messages |
| Matplotlib | Embedded plots and image export |
| `unittest` | Network and GUI integration tests |

## Project structure

```text
Network-Time-Synchronization/
├── main.py                 # Tkinter UI, actions, worker queue and shutdown
├── server.py               # Reference clock, TCP service, framing and polling
├── client.py               # Logical clocks, drift, delays and client listeners
├── synchronization.py      # Cristian/Berkeley formulas and result records
├── analyzer.py             # Clock differences, absolute errors and statistics
├── visualization.py        # Matplotlib figure and Tk graph window
├── requirements.txt        # Only the third-party dependency: Matplotlib
├── README.md               # Setup, architecture, math, usage and limitations
├── PROJECT_DELIVERY.md     # Requested 20-part guide with complete source code
├── .gitignore              # Ignore local environments and bytecode
├── tests/
│   └── test_project.py     # Real-socket and withdrawn-GUI integration tests
└── screenshots/
    └── .gitkeep            # Preserve the screenshot directory in Git
```

## How the application works

1. The GUI starts the reference server in a background listener thread.
2. Generate Clients creates logical clocks and TCP listeners for Berkeley polls.
3. Each clock advances with its initial offset and its own ppm rate error.
4. Analyze Drift samples all clocks at the same reference instant.
5. Synchronize runs the selected algorithm in a worker thread.
6. Real request/response exchanges include simulated directional waits.
7. The algorithm calculates an adjustment without consulting ground-truth error.
8. The analyzer compares the corrected time to its target and the reference.
9. Show Graph opens a frozen snapshot of that run. The main clocks keep ticking.

Select a client row to see its drift rate, TCP port, before time, sampled timestamp,
estimated one-way delay and absolute reference error.

## Algorithms and formulas

Let `R(t)` be the simulation's trusted reference time and `C_i(t)` a client clock.
All times and corrections below use seconds unless stated otherwise.

### Clock model

```text
Client time = Reference time + Current offset
Current offset = Base offset + Elapsed seconds × Drift ppm / 1,000,000
Observed offset = Client time − Reference time
```

An offset of `−5 s` means the clock is five seconds behind. A drift of `+100 ppm`
means the clock gains `0.0001 s` every second, or `0.1 s` in 1,000 seconds.
Applying a correction changes the base offset; it does not fix the rate error.
The Analyze Drift panel uses “absolute drift” to mean accumulated absolute clock
difference, while the row details identify the actual rate in ppm.

### Cristian's Algorithm

Cristian assumes a trusted reference time server.

1. A client connects to the reference server and records monotonic send time `T0`.
2. It waits for its simulated request journey, then sends `TIME_REQUEST`.
3. The server samples reference timestamp `Ts` before the response journey.
4. After the response delay and socket delivery, the client records `T1`.
5. It estimates the current reference time and applies the correction:

```text
RTT = T1 − T0
Estimated one-way delay = RTT / 2
Estimated reference time at receipt = Ts + RTT / 2
Correction = Estimated reference time − Client time at receipt
Corrected client time = Client time + Correction
Reference error = |Corrected client time − Reference time at receipt|
```

`T0` and `T1` use a monotonic timer, so clock corrections cannot distort the RTT.
TCP connection establishment is deliberately excluded from the measurement.
The client's local time and the reference used to evaluate its correction are
sampled at the same receipt epoch. Time continues to advance after that snapshot.

For request delay `d_request` and response delay `d_response`, ignoring overhead:

```text
Signed residual offset ≈ (d_request − d_response) / 2
```

Equal delays are well compensated even if large. **Asymmetry**, processing and
scheduling overhead cause error. The application never adds a fake error value or
forces the error to zero. Small natural residuals may round to zero in the table.

### Berkeley Algorithm

Berkeley aims at agreement among participating clocks. It does not assume that the
master has the correct external time.

1. The master connects to each client listener and sends `CLOCK_REQUEST`.
2. The client replies with its logical timestamp, sampled before the return delay.
3. The master estimates each client's time at poll receipt using `timestamp + RTT/2`.
4. It subtracts the master's logical time at that same epoch to estimate offset `o_i`.
5. It averages the available client offsets **including the master's offset 0**.
6. It adjusts the master by the mean and every responding client by `mean − o_i`.

```text
Estimated client time = Polled client timestamp + RTT / 2
Client offset o_i = Estimated client time − Master time at poll receipt
Average offset A = (0 + o_1 + o_2 + ... + o_n) / (n + 1)
Client correction_i = A − o_i
Master correction = A
Group target = Previous master time + A
Group error_i = |Corrected client time − Adjusted master time|
Reference error_i = |Corrected client time − Trusted reference time|
```

For ideal measurements and offsets `−5, +8, +3 s`, the average including the master
is `1.5 s`. The master moves forward by `1.5 s`; the clients receive corrections
`+6.5, −6.5, −1.5 s`. They agree at a group time `1.5 s` ahead of the external
reference. Their group errors can be small while their reference errors remain large.

This implementation uses **measured** offsets, so asymmetric delays affect Berkeley
as well. Polls are sequential; the small drift between polls is not extrapolated
away. Corrections are then applied locally at a common reference epoch. Additional
correction-message transport delay is intentionally not simulated. Only successful
polls enter the average; unreachable clients are excluded and reported as failures.

### Statistics and graph interpretation

```text
Average offset = sum(signed offsets) / number of clients
Minimum/maximum signed offset = min/max(offsets)
Minimum/maximum absolute drift = min/max(|offsets|)
Average synchronization error = sum(target errors) / successful clients
Maximum synchronization error = max(target errors)
Milliseconds = Seconds × 1,000
```

The table's **Target error** is reference error for Cristian and group/master error
for Berkeley. Results also show average external reference error. Failed clients
do not enter success-only error statistics; the success count makes this explicit.

The graph uses **signed reference offsets for both bars**, avoiding a misleading
comparison of signed offsets and absolute errors. Berkeley adds a horizontal
group-target line. The lower plot compares both simulated directions and measured
RTT. Graphs and measurement columns are snapshots, while Current time and Offset
remain live. Switching the algorithm selector does not relabel a previous report.

## Installation

Install Python 3.11 or later with Tcl/Tk support. The standard Windows installer
normally includes it. Open the project folder in VS Code and select its Python
interpreter. No Flask, Django, database or cloud account is required.

After uploading the project to your own repository, substitute its URL:

```powershell
git clone <repository-url>
cd Network-Time-Synchronization
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Using the interpreter path directly avoids PowerShell activation-policy issues.
If using an already activated environment, these are equivalent:

```powershell
pip install -r requirements.txt
python main.py
```

Only Matplotlib is installed through pip. Tkinter, sockets, JSON and threading
are Python standard-library modules, not requirements entries.

## How to run

For this delivered workspace:

```powershell
cd C:\Users\Home\Desktop\CN\Network-Time-Synchronization
python -m pip install -r requirements.txt
python main.py
```

If port 5000 is occupied, stop the other demo or use another port:

```powershell
python main.py --port 5001
```

The GUI owns its server; do not also start `server.py` on the same port. Running
`python server.py` separately is useful only for an independent socket demonstration.
Close the GUI with the normal window close button. It waits for any current request
and releases every listener, including client ports.

## Professor demonstration workflow

1. Launch the application and identify the running reference server and local port.
2. Generate three clients. Point out their different offsets and request/response delays.
3. Select a client to explain its ppm rate error and TCP listener.
4. Click Analyze Drift. Explain signed offset versus absolute accumulated error.
5. Select Cristian's Algorithm, then Synchronize. Watch the log while clocks continue.
6. Explain the measured RTT, half-RTT estimate, corrections and residual errors.
7. Select a row for the sampled server timestamp and original client time.
8. Open Show Graph and compare before/after offsets and directional delays.
9. Close the graph, Reset, and Generate Clients again.
10. Select Berkeley Algorithm and Synchronize.
11. Show the mean offset and the master's adjustment, then the group-target graph line.
12. Compare small group error with potentially larger external reference error.
13. Click Simulate New Delay and rerun to demonstrate uncertainty from asymmetry.
14. Close the application and rerun it to show that the server port is released.

Reset clears clients, listeners, results, statistics, graph windows and the logical
master offset. It leaves the reference server available. Generate Clients also starts
a fresh group. Simulate New Delay preserves current clock values but clears previous
measurements so the displayed delays and result snapshots cannot be confused.

## Example output

The following is an **illustrative calculation**, ignoring OS overhead and ppm drift;
the GUI uses random inputs and measures real elapsed time.

| Client | Before offset | Request / response | RTT | Cristian correction | After offset | Absolute error |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Client 1 | −5.000 s | 50 / 250 ms | 300 ms | +4.900 s | −0.100 s | 0.100 s |
| Client 2 | +8.000 s | 120 / 80 ms | 200 ms | −7.980 s | +0.020 s | 0.020 s |
| Client 3 | +3.000 s | 60 / 100 ms | 160 ms | −3.020 s | −0.020 s | 0.020 s |

Average reference error is approximately `0.0467 s`; maximum is `0.1000 s`.

For the same initial offsets in a **fresh Berkeley run with symmetric delays**:

```text
Participating clocks: 3 clients + 1 master
Average offset: (-5 + 8 + 3 + 0) / 4 = +1.500 s
Master correction: +1.500 s
Client corrections: +6.500 s, -6.500 s, -1.500 s
Group offset from external reference: +1.500 s
Group error: near zero, subject to measured network and scheduling effects
External reference error: approximately 1.500 s
```

## Testing

```powershell
python -m unittest discover -s tests -v
python -m compileall -q .
```

Seven tests cover actual socket framing, asymmetric Cristian residuals, Berkeley's
master adjustment, repeat synchronization, reference/group distinction, partial
failures, drift math, port conflicts and server recovery. The GUI lifecycle test
creates a withdrawn Tk root and exercises generation, analysis, both algorithms,
graph creation, invalid input, reset, regeneration and closing during a request.
It verifies that the server port can be bound again after shutdown.

The GUI test requires a desktop/Tk environment; a graph window may briefly appear.
For a server without a display, run only the network tests:

```powershell
python -m unittest discover -s tests -p test_project.py -k NetworkTests -v
```

The delivered project was tested on Windows with Python 3.14.5, Tk 8.6 and
Matplotlib 3.11.0. It targets Python 3.11+, but every supported interpreter version
has not been tested. Timing assertions allow a small scheduling tolerance; a heavily
loaded machine may need a rerun after the load is reduced.

## Error handling and troubleshooting

| Situation | Expected action or behavior |
| --- | --- |
| Port already in use | A message explains how to choose `--port 5001` |
| Server stopped | Start Server before synchronizing |
| No clients | Generate Clients first; an informational dialog explains this |
| Invalid count | Only 3, 4 and 5 are accepted |
| No successful results | Show Graph asks you to synchronize first |
| Connection failure | Report failed/partial status with per-client details |
| Matplotlib missing | Install `requirements.txt`; normal startup still works |
| Tkinter missing | Modify/reinstall Python with Tcl/Tk support |
| Clocks diverge after synchronization | Expected: corrections do not remove oscillator rate error |
| Large Berkeley reference error | Expected: group agreement does not ensure external accuracy |

## Computer Networks concepts used

Client-server architecture; TCP sockets and ports; request-response communication;
TCP byte-stream framing; directional latency and RTT; time servers; distributed
logical clocks; offset versus drift; reference synchronization; group consensus on
time; asymmetric-delay uncertainty; multithreaded network services.

Messages use one JSON object plus a newline per connection. The receiver loops
until it sees the delimiter because TCP does not preserve application message
boundaries. Size limits and socket timeouts prevent malformed or incomplete input
from waiting indefinitely. Listeners bind only to localhost for this demo.

## Screenshots

Save your own screenshots in `screenshots/`:

- `before-sync.png`: three clients and drift analysis.
- `cristian-results.png`: reference corrections and errors.
- `berkeley-results.png`: adjusted master, mean offset and target errors.
- `comparison.png`: before/after graph saved with the Matplotlib toolbar.

These filenames are suggestions, not claims that GUI screenshots are bundled.
The directory contains `.gitkeep` so it is preserved in Git.

## Limitations

- This is a simulator with actual localhost sockets, not a full NTP implementation.
- All clocks share one host's timing source; physical oscillators are modeled with ppm.
- The reference is a stable local baseline, not independently verified UTC.
- Delays are deliberate waits, not measurements of a real remote network path.
- Processing overhead is included in RTT; equal-path-delay assumptions are approximate.
- Berkeley polls sequentially, uses no outlier rejection and applies corrections locally.
- Clocks are stepped, not gradually slewed; drift continues after synchronization.
- No clock election, authenticated time, packet-loss model or persistent history.
- Mean offsets near zero can make Berkeley's output look close to Cristian by chance.

## Future enhancements

Real NTP time sources and protocol; multiple physical computers; IPv4/IPv6
configuration; periodic synchronization; jitter analysis; packet-loss simulation;
outlier rejection; correction delivery over TCP; synchronization history; CSV export;
optional database logs; a separate web dashboard.

## Academic relevance

This project links socket programming with distributed-systems time uncertainty.
Students can inspect every formula, modify offset/drift/delay ranges, compare
reference accuracy with group agreement, and demonstrate the impact of network
asymmetry without external services or specialized hardware.

Suggested explanation: “Different computers have different local clocks. Network
latency makes clock synchronization difficult. Cristian's Algorithm estimates
reference time using RTT, while Berkeley's Algorithm synchronizes a group of clocks
using an average correction.”
