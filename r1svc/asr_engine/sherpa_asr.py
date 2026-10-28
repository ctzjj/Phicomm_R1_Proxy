import ctypes as ct
import os
import threading
from pathlib import Path

import numpy as np

_ROOT = str(Path(__file__).resolve().parents[2])
_MODEL_DIR_NAME = "sherpa-onnx-v1.13.8-cuda-12.x-cudnn-9.x-onnxruntime1.28.2-win-x64-cuda"
MODEL_DIR = os.path.join(_ROOT, "asr-slu", "models", "sensevoice")
_BIN = os.path.join(_ROOT, "asr-slu", "pkg", _MODEL_DIR_NAME, "bin")
_LIB = os.path.join(_ROOT, "asr-slu", "pkg", _MODEL_DIR_NAME, "lib")


def _ensure_dll_env():
    for d in (_LIB, _BIN):
        if os.path.isdir(d):
            os.add_dll_directory(d)


_ensure_dll_env()

ct.CDLL(os.path.join(_BIN, "onnxruntime.dll"))
try:
    ct.CDLL(os.path.join(_BIN, "onnxruntime_providers_shared.dll"))
except OSError:
    pass
try:
    ct.CDLL(os.path.join(_LIB, "cargs.dll"))
except OSError:
    pass
ct.CDLL(os.path.join(_LIB, "sherpa-onnx-cxx-api.dll"))
_api = ct.CDLL(os.path.join(_LIB, "sherpa-onnx-c-api.dll"))

from r1svc.asr_engine.sherpa_structs import SherpaOnnxOfflineRecognizerConfig

_api.SherpaOnnxCreateOfflineRecognizer.restype = ct.c_void_p
_api.SherpaOnnxCreateOfflineRecognizer.argtypes = [ct.c_void_p]
_api.SherpaOnnxCreateOfflineStream.restype = ct.c_void_p
_api.SherpaOnnxCreateOfflineStream.argtypes = [ct.c_void_p]
_api.SherpaOnnxAcceptWaveformOffline.restype = None
_api.SherpaOnnxAcceptWaveformOffline.argtypes = [ct.c_void_p, ct.c_int32, ct.c_void_p, ct.c_int32]
_api.SherpaOnnxDecodeOfflineStream.restype = None
_api.SherpaOnnxDecodeOfflineStream.argtypes = [ct.c_void_p, ct.c_void_p]
_api.SherpaOnnxGetOfflineStreamResult.restype = ct.c_void_p
_api.SherpaOnnxGetOfflineStreamResult.argtypes = [ct.c_void_p]
_api.SherpaOnnxDestroyOfflineRecognizerResult.restype = None
_api.SherpaOnnxDestroyOfflineRecognizerResult.argtypes = [ct.c_void_p]
_api.SherpaOnnxDestroyOfflineStream.restype = None
_api.SherpaOnnxDestroyOfflineStream.argtypes = [ct.c_void_p]
_api.SherpaOnnxDestroyOfflineRecognizer.restype = None
_api.SherpaOnnxDestroyOfflineRecognizer.argtypes = [ct.c_void_p]

from r1svc.asr_engine.sherpa_structs import SherpaOnnxOfflineRecognizerResult


class SherpaASR:
    def __init__(self, model_path, tokens_path, sample_rate=16000,
                 num_threads=1, engine="sensevoice"):
        cfg = SherpaOnnxOfflineRecognizerConfig()
        cfg.feat_config.sample_rate = sample_rate
        cfg.feat_config.feature_dim = 80
        if engine == "sensevoice":
            cfg.model_config.sense_voice.model = model_path.encode("utf8")
            cfg.model_config.sense_voice.language = b"zh"
            cfg.model_config.sense_voice.use_itn = 0
        else:  # paraformer
            cfg.model_config.paraformer.model = model_path.encode("utf8")
            cfg.model_config.model_type = b"paraformer"
        cfg.model_config.tokens = tokens_path.encode("utf8")
        cfg.model_config.num_threads = num_threads
        cfg.model_config.provider = b"cpu"
        self.recognizer = _api.SherpaOnnxCreateOfflineRecognizer(ct.byref(cfg))
        if not self.recognizer:
            raise RuntimeError("failed to create recognizer")

    def transcribe(self, samples: np.ndarray, sample_rate: int = 16000) -> str:
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        stream = _api.SherpaOnnxCreateOfflineStream(self.recognizer)
        buf = samples.ctypes.data_as(ct.c_void_p)
        _api.SherpaOnnxAcceptWaveformOffline(stream, sample_rate, buf, len(samples))
        _api.SherpaOnnxDecodeOfflineStream(self.recognizer, stream)
        res = _api.SherpaOnnxGetOfflineStreamResult(stream)
        result = ct.cast(res, ct.POINTER(SherpaOnnxOfflineRecognizerResult)).contents
        text = result.text.decode("utf8") if result.text else ""
        _api.SherpaOnnxDestroyOfflineRecognizerResult(res)
        _api.SherpaOnnxDestroyOfflineStream(stream)
        return text

    def __del__(self):
        if getattr(self, "recognizer", None):
            _api.SherpaOnnxDestroyOfflineRecognizer(self.recognizer)


# ----------------- r1svc engine interface -----------------
ASR_LOCK = threading.Lock()

_asr = None
_asr_device = ""
_ready = False


def get_asr():
    return _asr


def asr_ready() -> bool:
    return _ready


def asr_label() -> str:
    return _asr_device


def asr_lock():
    return ASR_LOCK


def transcribe(samples: np.ndarray) -> str:
    """Module-level transcribe on the current engine (nlu.py calls this)."""
    if _asr is None:
        raise RuntimeError("asr not loaded")
    return _asr.transcribe(samples)


def load_asr() -> bool:
    """加载 SenseVoice(CPU),进程内仅一次。Return ready"""
    global _asr, _ready, _asr_device
    if _ready:
        return True
    try:
        n_thr = max(1, int((os.cpu_count() or 4) * 0.8))  # 按核数 ~80% 分配
        a = SherpaASR(os.path.join(MODEL_DIR, "model.int8.onnx"),
                      os.path.join(MODEL_DIR, "tokens.txt"),
                      num_threads=n_thr)
        _asr = a
        _asr_device = f"sensevoice cpu x{n_thr}"
        _ready = True
        try:
            transcribe(np.zeros(16000, dtype="float32"))
        except Exception:
            pass
        return True
    except Exception as e:
        _ready = False
        try:
            from r1svc import state as _state
            _state.STATE.log(f"[asr] load failed: {e}")
        except Exception:
            pass
        return False
