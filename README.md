# devenum - Serial & Audio Device Viewer

A Linux desktop tool for radio amateurs to inspect serial ports and audio
devices without needing to know the command line.

## Requirements

```
pip install pyserial sounddevice babel
# Optional system tools (degrade gracefully when absent):
sudo apt install setserial psmisc   # setserial + fuser
```

## Running

```bash
python serial_audio_gui.py          # English (default)
LANGUAGE=it python serial_audio_gui.py   # Italian
```


