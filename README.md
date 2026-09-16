# R1 Robot Back Screen

1024 × 600 touch-oriented local diagnostic screen. This is a standalone static page and does not require npm.

## Run

```bash
cd "/home/wangyulong/桌面/back_screen/robot-back-screen"
python3 -m http.server 8081
```

Open `http://127.0.0.1:8081`. It will display stable offline example data until a local diagnostic service is configured.

## Connect to the robot's diagnostic service

Before `index.html`'s main script, set the local service address:

```html
<script>window.ROBOT_DIAGNOSTIC_API = 'http://127.0.0.1:8080/api/v1';</script>
```

The service, rather than the screen, is responsible for PLC/BMS/sensor protocols, authentication, permission checks, and command acknowledgements.

| Screen action | API request |
| --- | --- |
| Refresh status | `GET /robot/snapshot` |
| One-key diagnosis | `POST /commands/diagnose` |
| Confirm recovered alarm | `POST /alarms/:id/acknowledge` |
| Clear recovered alarms | `POST /alarms/clear-recovered` |
| Soft stop | `POST /commands/soft-stop` |

`GET /robot/snapshot` is polled at 1 Hz and should return `health`, `motion`, `battery`, `uptime`, and `sensors` fields. Command APIs must return a command receipt and must never treat an HTTP request alone as a successful safety action.
