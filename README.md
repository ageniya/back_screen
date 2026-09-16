# R1 Robot Back Screen

1024 × 600 touch-oriented local diagnostic screen. The project uses Vite for development and production builds, while retaining a dependency-light browser UI.

## Run

```bash
cd "/home/wangyulong/桌面/back_screen/robot-back-screen"
npm install
npm run dev
```

Open the address printed by Vite (normally `http://localhost:5173`). It will display stable offline example data until a local diagnostic service is configured.

To create deployment files:

```bash
npm run build
```

The generated `dist/` directory can be copied to the back-screen device's web server. See [the project architecture](docs/ARCHITECTURE.md) for the source layout.

## Connect to the real robot

The page does not prescribe a diagnostic-system architecture. It accepts an existing ROS2 bridge, SDK wrapper, or HTTP service through `window.ROBOT_DATA_ADAPTER`.

Before `index.html`'s main script, the deployment can inject an adapter:

```html
<script>
window.ROBOT_DATA_ADAPTER = {
  getSnapshot: () => existingRobotBridge.getSnapshot(),
  getWorkSummary: () => existingRobotBridge.getWorkSummary(),
  sendCommand: (path, body) => existingRobotBridge.sendCommand(path, body)
};
</script>
```

`getSnapshot()` is called at 1 Hz. It should provide health, pose/velocity, joint values, payload, battery, network and sensor fields. The top-left model can be supplied as `robotModel` or `identity.model`. `getWorkSummary()` supplies the current charge-cycle's 搬运记录、负载和续航消耗。

For a deployment that already exposes HTTP, the fallback is:

```html
<script>window.ROBOT_DIAGNOSTIC_API = 'http://127.0.0.1:8080/api/v1';</script>
```

| Screen action | API request |
| --- | --- |
| Refresh status | `GET /robot/snapshot` |
| One-key diagnosis | `POST /commands/diagnose` |
| Confirm recovered alarm | `POST /alarms/:id/acknowledge` |
| Clear recovered alarms | `POST /alarms/clear-recovered` |
| Soft stop | `POST /commands/soft-stop` |

`GET /robot/snapshot` is polled at 1 Hz. Command APIs must return a command receipt and must never treat an HTTP request alone as a successful safety action.
