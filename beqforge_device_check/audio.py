"""Explicit PortAudio routing with bounded buffers and discovery timeout."""

import json
import subprocess
import sys
import threading
import time

import numpy as np


def devices(timeout_s: float = 10) -> dict:
    # Native backend discovery can block on an unavailable host audio service. Keep
    # it in a disposable process, including in the frozen executable.
    command = (
        [sys.executable, "_audio-devices"]
        if getattr(sys, "frozen", False)
        else [sys.executable, "-m", "beqforge_device_check.cli", "_audio-devices"]
    )
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout_s, check=True
    )
    return json.loads(result.stdout)


def native_devices() -> dict:
    import sounddevice as sd

    return {
        "portaudio": list(sd.get_portaudio_version()),
        "host_apis": list(sd.query_hostapis()),
        "devices": list(sd.query_devices()),
    }


def resolve(selection: dict, inventory: dict, direction: str) -> int:
    key = "max_input_channels" if direction == "input" else "max_output_channels"
    matches = [
        index
        for index, device in enumerate(inventory["devices"])
        if device["name"] == selection["name"]
        and inventory["host_apis"][device["hostapi"]]["name"] == selection["host_api"]
        and device[key] >= selection["channels"]
    ]
    if len(matches) != 1:
        raise ValueError(f"{direction} device is missing or ambiguous; repeat setup")
    return matches[0]


class StreamCapture:
    def __init__(self, config: dict, inventory: dict):
        self.config = config
        self.input_index = resolve(config["input"], inventory, "input")
        self.output_index = resolve(config["output"], inventory, "output")

    def capture(self, stimulus: np.ndarray, rate: int) -> tuple[np.ndarray, dict]:
        import sounddevice as sd

        config = self.config
        inputs, outputs = config["input"]["channels"], config["output"]["channels"]
        in_channel, out_channel = (
            config["input"]["channel"],
            config["output"]["channel"],
        )
        if not 0 <= in_channel < inputs or not 0 <= out_channel < outputs:
            raise ValueError(
                "selected stream channel is outside the configured channels"
            )
        if len(stimulus) * 4 * (inputs + outputs) > config.get(
            "maximum_bytes", 512 * 1024**2
        ):
            raise ValueError("capture exceeds configured RAM buffer bound")
        sd.check_input_settings(
            device=self.input_index, channels=inputs, dtype="float32", samplerate=rate
        )
        sd.check_output_settings(
            device=self.output_index, channels=outputs, dtype="float32", samplerate=rate
        )
        playback = np.zeros((len(stimulus), outputs), dtype=np.float32)
        playback[:, out_channel] = stimulus
        recorded = np.zeros((len(stimulus), inputs), dtype=np.float32)
        # Preallocated status/timestamp storage: no FFT, control, file I/O or queue waits
        # in the callback. Completed capture storage happens on the caller's thread.
        blocksize = int(config.get("blocksize", 1024))
        capacity = len(stimulus) // max(blocksize, 1) + 1024
        timestamps = np.zeros((capacity, 3), dtype=float)
        statuses = np.zeros(capacity, dtype=np.int64)
        done = threading.Event()
        position = 0
        callbacks = 0

        def callback(indata, outdata, frames, timing, status):
            nonlocal position, callbacks
            outdata.fill(0)
            if callbacks >= capacity:
                raise sd.CallbackAbort
            timestamps[callbacks] = (
                timing.inputBufferAdcTime,
                timing.currentTime,
                timing.outputBufferDacTime,
            )
            statuses[callbacks] = int(status._flags)
            callbacks += 1
            count = min(frames, len(stimulus) - position)
            recorded[position : position + count] = indata[:count]
            outdata[:count] = playback[position : position + count]
            position += count
            if status:
                raise sd.CallbackAbort
            if position >= len(stimulus):
                raise sd.CallbackStop

        started = time.monotonic()
        with sd.Stream(
            device=(self.input_index, self.output_index),
            samplerate=rate,
            channels=(inputs, outputs),
            dtype="float32",
            blocksize=blocksize,
            latency=config.get("latency", "high"),
            callback=callback,
            finished_callback=done.set,
        ) as stream:
            if not done.wait(len(stimulus) / rate + 15):
                stream.abort()
                raise TimeoutError("audio capture timed out; stopped stream")
            actual = {"samplerate": stream.samplerate, "latency": list(stream.latency)}
        if position != len(stimulus) or np.any(statuses[:callbacks]):
            raise RuntimeError(
                f"audio capture stopped at {position}/{len(stimulus)} samples; statuses {statuses[:callbacks].tolist()}"
            )
        return recorded, {
            "actual": actual,
            "elapsed_s": time.monotonic() - started,
            "sample_count": position,
            "format": "float32",
            "callback_timestamps": timestamps[:callbacks].tolist(),
            "statuses": statuses[:callbacks].tolist(),
        }
