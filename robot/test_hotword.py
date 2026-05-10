import sounddevice as sd
from openwakeword.model import Model

SAMPLE_RATE = 16000
CHUNK_SIZE = 1280  # 80ms — required frame size for openwakeword

model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
print("Listening for 'hey jarvis'... Ctrl+C to stop")


def callback(indata, frames, time_info, status):
    score = model.predict(indata[:, 0]).get("hey_jarvis", 0)
    if score > 0.5:
        print(f"  >>> detected (score={score:.2f})")


with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                    blocksize=CHUNK_SIZE, callback=callback):
    while True:
        sd.sleep(100)
