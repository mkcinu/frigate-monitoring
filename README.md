# frigate-monitoring

Subscribe to [Frigate NVR](https://frigate.video/) MQTT reviews and dispatch
them to configurable action handlers.

## Prerequisites

### Frigate MQTT setup

This project requires MQTT to be enabled in Frigate. Add the following to your Frigate `config.yml`:

```yaml
mqtt:
  enabled: true
  host: <your-mqtt-broker-host>
  port: 1883        # optional, default is 1883
  user: myuser      # optional
  password: secret  # optional
```

Without this, Frigate will not publish review events and this project will receive nothing.

## Usage

### Python API

```python
from frigate_monitoring.actions.print_action import PrintAction
from frigate_monitoring.filter import ReviewFilter
from frigate_monitoring.listener import FrigateListener

listener = FrigateListener()
listener.add_action(
    PrintAction(template="[{camera}] {label} ({score_pct})"),
    filter=ReviewFilter(alerts_only=True, review_types=["end"]),
)
listener.run()
```

`add_action` accepts an optional `filter` keyword argument — a `ReviewFilter` that
controls which reviews are forwarded to that action.  Omit it to receive everything.

### YAML configuration

Instead of writing Python, you can define everything in a YAML file:

```yaml
mqtt:
  host: 192.168.1.100
  port: 1883

frigate:
  host: 192.168.1.100
  port: 5000
  external_url: https://frigate.example.com

actions:
  - type: print
    template: "[{camera}] {severity}: {objects} ({score_pct})"
    filter:
      cameras: [front_door, back_door]
      alerts_only: true

  - type: webhook
    url: https://hooks.example.com/frigate
    method: POST
    body:
      text: "{label} detected on {camera} ({score_pct})"
      camera: "{camera}"
    headers:
      Authorization: "Bearer ${WEBHOOK_TOKEN}"
    filter:
      alerts_only: true
      review_types: [end]

  - type: pushover
    token: ${PUSHOVER_TOKEN}
    user_key: ${PUSHOVER_USER}
    options:
      sound: siren
      priority: 1
    filter:
      alerts_only: true
      review_types: [end]

# Record MQTT messages to a file for later replay
# record:
#   path: recordings/mqtt.jsonl
```

Environment variables in `${VAR}` syntax are expanded automatically.
See `config.example.yaml` for a fully annotated example.

Run with:

```bash
frigate-monitor --config config.yaml
```

### Built-in actions

| Class | YAML type | Description |
|-------|-----------|-------------|
| `PrintAction(template)` | `print` | Print a formatted line to stdout |
| `LogAction(template, level)` | `log` | Emit a Python log record |
| `CallbackAction(fn)` | _(Python only)_ | Call an arbitrary `fn(review)` function |
| `WebhookAction(url, method, body, headers)` | `webhook` | Send an HTTP request to any URL |
| `PushoverAction(token, user_key)` | `pushover` | Send Pushover push notifications |
| `RichAction()` | `rich` | Live-updating terminal table via [rich](https://github.com/Textualize/rich) |

### ReviewFilter

```python
ReviewFilter(
    alerts_only=True,           # skip detection-severity reviews
    cameras=["front_door"],     # restrict to these cameras
    objects=["person", "car"],  # at least one of these must be present
    zones=["driveway"],         # at least one of these zones must be active
    review_types=["end"],       # "new", "update", or "end"
)
```

All criteria are AND-ed together; omit any to match everything for that dimension.

In YAML, the same filter is written as:

```yaml
filter:
  alerts_only: true
  cameras: [front_door]
  objects: [person, car]
  zones: [driveway]
  review_types: [end]
```

## Configuration

There are two mutually exclusive ways to configure the connection to MQTT and Frigate:

### Option A: YAML config file (recommended)

When using `--config`, the YAML file is the **single source of truth**.
`.env` is not loaded. Secrets can reference environment variables with `${VAR}` syntax:

```yaml
mqtt:
  host: 192.168.1.11
  port: 1883
  user: myuser
  password: ${MQTT_PASSWORD}

frigate:
  host: 192.168.1.10
  port: 5000
  external_url: https://frigate.example.com
```

See `config.example.yaml` for a fully annotated example.

### Option B: `.env` file (Python API / no `--config`)

When running without `--config` (e.g. Python scripts, examples), configuration
is loaded from `.env` and environment variables:

```bash
cp .env.example .env
```

```ini
FRIGATE_MQTT_HOST=192.168.1.11
FRIGATE_MQTT_PORT=1883
FRIGATE_MQTT_USER=myuser
FRIGATE_MQTT_PASSWORD=secret
FRIGATE_MQTT_TOPIC=frigate/reviews

FRIGATE_HOST=192.168.1.10
FRIGATE_PORT=5000
```

Environment variables set in the shell take precedence over the `.env` file.

Python scripts must call `load_dotenv_config()` before creating a listener:

```python
from frigate_monitoring.config import load_dotenv_config

load_dotenv_config()
listener = FrigateListener()
```

### Environment variables reference

| Variable | Default | Description |
|----------|---------|-------------|
| `FRIGATE_MQTT_HOST` | `localhost` | MQTT broker hostname or IP |
| `FRIGATE_MQTT_PORT` | `1883` | MQTT broker TCP port |
| `FRIGATE_MQTT_USER` | _(none)_ | MQTT username (omit if broker has no auth) |
| `FRIGATE_MQTT_PASSWORD` | _(none)_ | MQTT password |
| `FRIGATE_MQTT_TOPIC` | `frigate/reviews` | Topic Frigate publishes reviews to |
| `FRIGATE_HOST` | `localhost` | Frigate HTTP API hostname or IP |
| `FRIGATE_PORT` | `5000` | Frigate HTTP API port |
| `FRIGATE_EXTERNAL_URL` | _(none)_ | Externally reachable Frigate URL (enables `external_*` template vars) |

## Running

```bash
# Activate the venv first (if not already active):
source .venv/bin/activate

# Built-in entry point (default config):
frigate-monitor

# With a YAML config file:
frigate-monitor --config config.yaml

# Replay a recorded MQTT session:
frigate-monitor --config config.yaml --replay recordings/mqtt.jsonl

# Replay with original timing:
frigate-monitor --replay recordings/mqtt.jsonl --realtime

# Verbose (debug) logging:
frigate-monitor -v

# Or via the module:
python -m frigate_monitoring

# Or run one of the YAML examples:
frigate-monitor --config examples/alert_only.yaml
frigate-monitor --config examples/pushover.yaml
frigate-monitor --config examples/webhook_ntfy.yaml
frigate-monitor --config examples/rich_display.yaml

# Or run one of the Python examples (uses .env):
python examples/debug_print.py
```

### Docker Compose

**1. Create your environment file:**

```bash
cp .env.example .env
# edit .env with your MQTT host, Frigate host, Pushover credentials, etc.
```

**2. Create your config file** in the repo root:

```bash
cp config.example.yaml config.yaml
# edit config.yaml with your actions, cameras, filters, etc.
```

`config.yaml` is git-ignored so your personal settings stay local.

**3. Start the container:**

```bash
docker compose up -d --build
```

`docker-compose.yml` mounts `./config.yaml` from the repo root into the
container and reads credentials from `.env`.

To force a clean rebuild (e.g. after pulling new changes):

```bash
docker compose build --no-cache && docker compose up -d
```

**Running directly with Docker:**

```bash
docker build -t frigate-monitoring .

docker run -d \
  --name frigate-monitoring \
  --restart unless-stopped \
  --env-file .env \
  -v "$(pwd)/config.yaml:/config/config.yaml:ro" \
  frigate-monitoring
```

**Overriding the config path:**

If you want to mount a config from a different location, create a
`docker-compose.override.yml` (git-ignored, auto-merged by Compose):

```yaml
services:
  frigate-monitoring:
    volumes:
      - /path/to/your/config.yaml:/config/config.yaml:ro
```

## Recording and replay

You can record live MQTT messages to a JSONL file and replay them later for
testing or debugging, without a live Frigate instance.

### Recording

Add a `record` section to your YAML config:

```yaml
record:
  path: recordings/mqtt.jsonl
```

Or in Python:

```python
from pathlib import Path
from frigate_monitoring.recorder import MqttRecorder

listener = FrigateListener()
listener.add_recorder(MqttRecorder(Path("recordings/mqtt.jsonl")))
listener.run()
```

### Replaying

```bash
frigate-monitor --config config.yaml --replay recordings/mqtt.jsonl
```

Or in Python:

```python
from pathlib import Path
from frigate_monitoring.recorder import replay

listener = FrigateListener()
listener.add_action(PrintAction())
replay(Path("recordings/mqtt.jsonl"), listener)
```

Recordings are also useful as test fixtures — the JSONL format is easy to
construct by hand or extract from real sessions.

## MQTT reconnection

The listener automatically reconnects with exponential backoff (1s to 120s)
when the MQTT broker becomes unreachable or the connection drops unexpectedly.
The backoff resets on successful reconnection.

## Development setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements-dev.txt   # runtime + all dev tools
pip install -e "."                    # install the package in editable mode
```

The editable install (`-e .`) registers the `src/` directory on `sys.path` via
a `.pth` file in site-packages, so `import frigate_monitoring` works without
any `PYTHONPATH` changes.  You only need to run this once; edits to the source
take effect immediately.

### Dependency files

| File | Contents |
|------|----------|
| `pyproject.toml` | Canonical runtime dependencies (`paho-mqtt`, `trio`, `httpx`, `pyyaml`, `rich`, …) |
| `requirements-dev.txt` | Dev tools — `black`, `isort`, `pylint`, `mypy`, `pdoc`, type stubs |

### 3. Verify the setup

```bash
python -m frigate_monitoring   # should connect (or fail clearly if .env is missing)
python checkpy                 # all quality tools should pass
```

## Docs

```bash
pdoc src/frigate_monitoring          # open live docs in the browser
pdoc src/frigate_monitoring --output-dir docs/  # generate static HTML docs
```

## Code quality

All tools are wrapped in a single script:

```bash
python checkpy          # check only — exits 1 on any failure
python checkpy --fix    # auto-fix formatting, then check
```

`checkpy` runs, in order: isort, black, pytest, mypy, pylint (src), pylint (tests).
All must pass for exit code 0.

Or run individual tools:
