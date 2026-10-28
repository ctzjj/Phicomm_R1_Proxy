import ctypes as ct

class SherpaOnnxFeatureConfig(ct.Structure):
    _fields_ = [
        ('sample_rate', ct.c_int32),
        ('feature_dim', ct.c_int32),
    ]

class SherpaOnnxOfflineTransducerModelConfig(ct.Structure):
    _fields_ = [
        ('encoder', ct.c_char_p),
        ('decoder', ct.c_char_p),
        ('joiner', ct.c_char_p),
    ]

class SherpaOnnxOfflineParaformerModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
    ]

class SherpaOnnxOfflineNemoEncDecCtcModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
    ]

class SherpaOnnxOfflineWhisperModelConfig(ct.Structure):
    _fields_ = [
        ('encoder', ct.c_char_p),
        ('decoder', ct.c_char_p),
        ('language', ct.c_char_p),
        ('task', ct.c_char_p),
        ('tail_paddings', ct.c_int32),
        ('enable_token_timestamps', ct.c_int32),
        ('enable_segment_timestamps', ct.c_int32),
    ]

class SherpaOnnxOfflineTdnnModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
    ]

class SherpaOnnxOfflineSenseVoiceModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
        ('language', ct.c_char_p),
        ('use_itn', ct.c_int32),
    ]

class SherpaOnnxOfflineMoonshineModelConfig(ct.Structure):
    _fields_ = [
        ('preprocessor', ct.c_char_p),
        ('encoder', ct.c_char_p),
        ('uncached_decoder', ct.c_char_p),
        ('cached_decoder', ct.c_char_p),
        ('merged_decoder', ct.c_char_p),
    ]

class SherpaOnnxOfflineFireRedAsrModelConfig(ct.Structure):
    _fields_ = [
        ('encoder', ct.c_char_p),
        ('decoder', ct.c_char_p),
    ]

class SherpaOnnxOfflineDolphinModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
    ]

class SherpaOnnxOfflineZipformerCtcModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
    ]

class SherpaOnnxOfflineCanaryModelConfig(ct.Structure):
    _fields_ = [
        ('encoder', ct.c_char_p),
        ('decoder', ct.c_char_p),
        ('src_lang', ct.c_char_p),
        ('tgt_lang', ct.c_char_p),
        ('use_pnc', ct.c_int32),
    ]

class SherpaOnnxOfflineWenetCtcModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
    ]

class SherpaOnnxOfflineOmnilingualAsrCtcModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
    ]

class SherpaOnnxOfflineMedAsrCtcModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
    ]

class SherpaOnnxOfflineFunASRNanoModelConfig(ct.Structure):
    _fields_ = [
        ('encoder_adaptor', ct.c_char_p),
        ('llm', ct.c_char_p),
        ('embedding', ct.c_char_p),
        ('tokenizer', ct.c_char_p),
        ('system_prompt', ct.c_char_p),
        ('user_prompt', ct.c_char_p),
        ('max_new_tokens', ct.c_int32),
        ('temperature', ct.c_float),
        ('top_p', ct.c_float),
        ('seed', ct.c_int32),
        ('language', ct.c_char_p),
        ('itn', ct.c_int32),
        ('hotwords', ct.c_char_p),
    ]

class SherpaOnnxOfflineFireRedAsrCtcModelConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
    ]

class SherpaOnnxOfflineQwen3ASRModelConfig(ct.Structure):
    _fields_ = [
        ('conv_frontend', ct.c_char_p),
        ('encoder', ct.c_char_p),
        ('decoder', ct.c_char_p),
        ('tokenizer', ct.c_char_p),
        ('max_total_len', ct.c_int32),
        ('max_new_tokens', ct.c_int32),
        ('temperature', ct.c_float),
        ('top_p', ct.c_float),
        ('seed', ct.c_int32),
        ('hotwords', ct.c_char_p),
    ]

class SherpaOnnxOfflineCohereTranscribeModelConfig(ct.Structure):
    _fields_ = [
        ('encoder', ct.c_char_p),
        ('decoder', ct.c_char_p),
        ('language', ct.c_char_p),
        ('use_punct', ct.c_int32),
        ('use_itn', ct.c_int32),
    ]

class SherpaOnnxOfflineModelConfig(ct.Structure):
    _fields_ = [
        ('transducer', SherpaOnnxOfflineTransducerModelConfig),
        ('paraformer', SherpaOnnxOfflineParaformerModelConfig),
        ('nemo_ctc', SherpaOnnxOfflineNemoEncDecCtcModelConfig),
        ('whisper', SherpaOnnxOfflineWhisperModelConfig),
        ('tdnn', SherpaOnnxOfflineTdnnModelConfig),
        ('tokens', ct.c_char_p),
        ('num_threads', ct.c_int32),
        ('debug', ct.c_int32),
        ('provider', ct.c_char_p),
        ('model_type', ct.c_char_p),
        ('modeling_unit', ct.c_char_p),
        ('bpe_vocab', ct.c_char_p),
        ('telespeech_ctc', ct.c_char_p),
        ('sense_voice', SherpaOnnxOfflineSenseVoiceModelConfig),
        ('moonshine', SherpaOnnxOfflineMoonshineModelConfig),
        ('fire_red_asr', SherpaOnnxOfflineFireRedAsrModelConfig),
        ('dolphin', SherpaOnnxOfflineDolphinModelConfig),
        ('zipformer_ctc', SherpaOnnxOfflineZipformerCtcModelConfig),
        ('canary', SherpaOnnxOfflineCanaryModelConfig),
        ('wenet_ctc', SherpaOnnxOfflineWenetCtcModelConfig),
        ('omnilingual', SherpaOnnxOfflineOmnilingualAsrCtcModelConfig),
        ('medasr', SherpaOnnxOfflineMedAsrCtcModelConfig),
        ('funasr_nano', SherpaOnnxOfflineFunASRNanoModelConfig),
        ('fire_red_asr_ctc', SherpaOnnxOfflineFireRedAsrCtcModelConfig),
        ('qwen3_asr', SherpaOnnxOfflineQwen3ASRModelConfig),
        ('cohere_transcribe', SherpaOnnxOfflineCohereTranscribeModelConfig),
    ]

class SherpaOnnxOfflineLMConfig(ct.Structure):
    _fields_ = [
        ('model', ct.c_char_p),
        ('scale', ct.c_float),
    ]

class SherpaOnnxHomophoneReplacerConfig(ct.Structure):
    _fields_ = [
        ('dict_dir', ct.c_char_p),
        ('lexicon', ct.c_char_p),
        ('rule_fsts', ct.c_char_p),
    ]

class SherpaOnnxOfflineRecognizerConfig(ct.Structure):
    _fields_ = [
        ('feat_config', SherpaOnnxFeatureConfig),
        ('model_config', SherpaOnnxOfflineModelConfig),
        ('lm_config', SherpaOnnxOfflineLMConfig),
        ('decoding_method', ct.c_char_p),
        ('max_active_paths', ct.c_int32),
        ('hotwords_file', ct.c_char_p),
        ('hotwords_score', ct.c_float),
        ('rule_fsts', ct.c_char_p),
        ('rule_fars', ct.c_char_p),
        ('blank_penalty', ct.c_float),
        ('hr', SherpaOnnxHomophoneReplacerConfig),
    ]


class SherpaOnnxOfflineRecognizerResult(ct.Structure):
    _fields_ = [
        ("text", ct.c_char_p),
        ("timestamps", ct.POINTER(ct.c_float)),
        ("count", ctypes_int32 := ct.c_int32),
        ("tokens", ct.c_char_p),
        ("tokens_arr", ct.c_void_p),
        ("json", ct.c_char_p),
        ("lang", ct.c_char_p),
        ("emotion", ct.c_char_p),
        ("event", ct.c_char_p),
        ("durations", ct.POINTER(ct.c_float)),
        ("ys_log_probs", ct.POINTER(ct.c_float)),
        ("segment_timestamps", ct.POINTER(ct.c_float)),
        ("segment_durations", ct.POINTER(ct.c_float)),
        ("segment_texts", ct.c_char_p),
        ("segment_texts_arr", ct.c_void_p),
        ("segment_count", ct.c_int32),
    ]
