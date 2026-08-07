# RTSP IP Camera Input Guide

This guide documents how to run the Vision AI pipeline with an IP camera RTSP
stream. Do not write real camera passwords or full credentialed RTSP URLs in this
document, logs, commits, issues, or PR comments.

## Network requirement

The camera and the laptop running the pipeline must be connected to the same
internal network. If the laptop is connected to another Wi-Fi network, the RTSP
port may be unreachable even when the code is correct.

## Recommended stream for realtime AI

Use the camera's sub stream for realtime AI analysis on CPU environments.

Recommended sub stream settings:

- Codec: H.264
- Resolution: 720x576
- FPS: 15
- Bitrate mode: CBR
- Bitrate: 1024 Kbps
- I-frame interval: 15
- GOP: IP
- SVC: Off
- U-Code: Off

The main stream can be useful for a standalone OpenCV connectivity check, but
high-resolution main streams may overload CPU inference and cause broken display
or excessive latency.

## PowerShell environment variables

Set RTSP credentials only in the current shell session.

```powershell
$env:KIDCAFE_RTSP_USERNAME = "<RTSP_USERNAME>"

$secure = Read-Host "RTSP password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
  $env:KIDCAFE_RTSP_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
```

Do not create or commit a real `.env` file containing camera credentials.

## Run the Vision AI pipeline with the sub stream

Replace `<CAMERA_IP>` and `<RTSP_PORT>` with the local camera values shared
through the team’s secure channel.

```powershell
.\venv\Scripts\python.exe -m src.main `
  --source-type rtsp `
  --rtsp-host <CAMERA_IP> `
  --rtsp-port <RTSP_PORT> `
  --rtsp-stream sub `
  --rtsp-alias ipcam_sub `
  --zones "data/zones/sample.json" `
  --model yolo26n.pt `
  --infer-device cpu `
  --show
```

To send the latest frame to the React dashboard through FastAPI, omit `--show`
and enable live frame upload:

```powershell
.\venv\Scripts\python.exe -m src.main `
  --source-type rtsp `
  --rtsp-host <CAMERA_IP> `
  --rtsp-port <RTSP_PORT> `
  --rtsp-stream sub `
  --rtsp-alias ipcam_sub `
  --zones "data/zones/sample.json" `
  --model yolo26n.pt `
  --infer-device cpu `
  --api-url http://localhost:8000 `
  --live-frame-enabled
```

## Remove temporary credentials

```powershell
Remove-Item Env:\KIDCAFE_RTSP_USERNAME -ErrorAction SilentlyContinue
Remove-Item Env:\KIDCAFE_RTSP_PASSWORD -ErrorAction SilentlyContinue
Remove-Variable secure,bstr -ErrorAction SilentlyContinue
```

## Low-latency latest-frame behavior

`RTSPSource` receives camera frames on a background thread and keeps only the
latest frame. It does not build an unbounded frame queue.

If camera FPS is higher than AI processing FPS, older frames are overwritten and
`dropped_frames` increases. This is expected: it means the pipeline is preserving
realtime behavior by discarding stale frames instead of accumulating latency.

Temporary read failures are retried. The stream is marked as ended only after the
configured consecutive failure threshold is exceeded or no new frame arrives for
the stale timeout window. Full automatic reconnect is not part of the current
scope.

## Standalone connectivity check

Use `scripts/rtsp_camera_test.py` when you need to verify that OpenCV can receive
the RTSP stream independently of Detection, Tracking, Geofencing, and Event
processing. The script prompts for the password with `getpass()`, does not log
the full RTSP URL, and does not save camera frames automatically.
