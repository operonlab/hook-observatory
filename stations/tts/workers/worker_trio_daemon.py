#!/usr/bin/env python3
"""worker_trio_daemon — tts-trio venv 內常駐，hosts cosyvoice / vibevoice.

注意：indextts 因 venv 不在 WSL（在 Windows lab/indextts/.venv/），由
worker_indextts_daemon 處理.

啟動：win-gpu WSL2 端 station main.py spawn 這個 daemon:
    /home/joneshong/.venvs/cosyvoice_vllm/bin/python3 \
        /mnt/c/Users/User/workshop-station/stations/tts/workers/worker_trio_daemon.py

少爺 2026-05-19 規格 - model_pool max=1（同時間最多 1 個 engine 在 GPU）.
切 engine 時自動 unload 舊的.

修正：cosyvoice 全走 inference_zero_shot (V2/V3 規格)，不再 cross_lingual
(少爺記憶: cross_lingual 會「外國人腔調」).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Find base_daemon (sibling)
sys.path.insert(0, str(Path(__file__).parent))
from base_daemon import WorkerDaemon

SYS_PROMPT = "You are a helpful assistant.<|endofprompt|>"


class WorkerTrioDaemon(WorkerDaemon):
    LAB_COSYVOICE = "/mnt/c/Users/User/workshop/lab/cosyvoice"
    LAB_INDEXTTS = "/mnt/c/Users/User/workshop/lab/indextts"
    HOME_VIBEVOICE = "/home/joneshong/VibeVoice"
    VIBEVOICE_MODEL = "/home/joneshong/vibevoice_models/VibeVoice-1.5B"

    def __init__(self):
        super().__init__()
        self.engine_obj = None
        self.vibevoice_processor = None

    def supported_engines(self) -> list[str]:
        return [
            "cosyvoice_v3_vllm",
            "cosyvoice_v3_native",
            "vibevoice",
        ]

    # ---- Load dispatch ----

    def _do_load(self, engine_name: str, **kwargs) -> None:
        if engine_name in ("cosyvoice_v3_vllm", "cosyvoice_v3_native"):
            self._load_cosyvoice(engine_name)
        elif engine_name == "vibevoice":
            self._load_vibevoice()
        else:
            raise RuntimeError(f"engine {engine_name} not supported by trio worker")

    def _load_cosyvoice(self, engine_name: str) -> None:
        os.chdir(self.LAB_COSYVOICE)
        if "." not in sys.path:
            sys.path.insert(0, ".")
        third_party = "third_party/Matcha-TTS"
        if third_party not in sys.path:
            sys.path.insert(0, third_party)
        from cosyvoice.cli.cosyvoice import CosyVoice3

        use_vllm = engine_name == "cosyvoice_v3_vllm"
        self.engine_obj = CosyVoice3(
            "pretrained_models/Fun-CosyVoice3-0.5B",
            load_trt=False,
            load_vllm=use_vllm,
            fp16=False,
        )

    def _load_indextts2(self, engine_name: str) -> None:
        os.chdir(self.LAB_INDEXTTS)
        ckpt_dir = "checkpoints" if engine_name == "indextts2_base" else "checkpoints_ja"
        from indextts.infer_v2 import IndexTTS2

        self.engine_obj = IndexTTS2(
            model_dir=ckpt_dir,
            cfg_path=f"{ckpt_dir}/config.yaml",
            device="cuda",
        )

    def _load_vibevoice(self) -> None:
        if self.HOME_VIBEVOICE not in sys.path:
            sys.path.insert(0, self.HOME_VIBEVOICE)
        from vibevoice.modular.modeling_vibevoice_inference import (
            VibeVoiceForConditionalGenerationInference,
        )
        from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor

        self.vibevoice_processor = VibeVoiceProcessor.from_pretrained(self.VIBEVOICE_MODEL)
        model = VibeVoiceForConditionalGenerationInference.from_pretrained(
            self.VIBEVOICE_MODEL, torch_dtype="bfloat16", device_map="cuda"
        )
        model.set_ddpm_inference_steps(num_steps=10)
        self.engine_obj = model

    # ---- Unload ----

    def _do_unload(self) -> None:
        if self.engine_obj is not None:
            del self.engine_obj
            self.engine_obj = None
        if self.vibevoice_processor is not None:
            del self.vibevoice_processor
            self.vibevoice_processor = None
        import gc

        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    # ---- Synth dispatch ----

    def _do_synth(
        self,
        text: str,
        lang: str,
        voice_id: str,
        ref_wav: str,
        ref_text: str,
        **kwargs,
    ):
        if self.current_engine_name in ("cosyvoice_v3_vllm", "cosyvoice_v3_native"):
            return self._synth_cosyvoice(text, lang, ref_wav, ref_text)
        elif self.current_engine_name == "vibevoice":
            return self._synth_vibevoice(text, lang, ref_wav, ref_text)
        raise RuntimeError(f"no synth method for {self.current_engine_name}")

    def _synth_cosyvoice(self, text: str, lang: str, ref_wav: str, ref_text: str):
        """少爺 V2/V3 規格：全走 inference_zero_shot，不再 cross_lingual.

        ref_text 用簡體輸入；text 也經繁簡轉換（zh）+ pykakasi (ja).
        """
        # 預處理
        if lang == "zh":
            text = self.to_simplified(text)
        elif lang == "ja":
            # CosyVoice ja 仍需片假名 + 空格
            text = self.to_katakana_spaced(text)
        if ref_text:
            ref_text = self.to_simplified(ref_text)

        import numpy as np
        import torch

        prompt_text_with_sys = SYS_PROMPT + (ref_text or "")
        gen = self.engine_obj.inference_zero_shot(text, prompt_text_with_sys, ref_wav, stream=False)
        chunks = [j["tts_speech"] for j in gen]
        if not chunks:
            raise RuntimeError("CosyVoice produced no output")
        wav_tensor = torch.cat(chunks, dim=-1)
        audio = wav_tensor.squeeze().cpu().numpy().astype(np.float32)
        return audio, int(self.engine_obj.sample_rate)

    def _synth_indextts2(self, text: str, lang: str, ref_wav: str):
        if lang == "zh":
            text = self.to_simplified(text)
        # IndexTTS-2 base 鎖在 zh/en，jmica 鎖在 ja（engine 守門已處理）
        import os as _os
        import tempfile

        import soundfile as sf

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp_wav = tf.name
        try:
            self.engine_obj.infer(spk_audio_prompt=ref_wav, text=text, output_path=tmp_wav)
            audio, sr = sf.read(tmp_wav, dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            return audio, int(sr)
        finally:
            try:
                _os.unlink(tmp_wav)
            except Exception:
                pass

    def _synth_vibevoice(self, text: str, lang: str, ref_wav: str, ref_text: str):
        if lang == "ja":
            raise ValueError("vibevoice 不支援日語")
        if lang == "zh":
            text = self.to_simplified(text)
        # VibeVoice processor 要求 podcast script 格式 "Speaker N: <text>"，
        # 單 speaker 也必須 wrap（否則 processor raise "No valid speaker lines"）。
        if "Speaker" not in text:
            text = f"Speaker 0: {text}"

        import numpy as np

        voice_samples = [ref_wav]
        inputs = self.vibevoice_processor(
            text=[text],
            voice_samples=[voice_samples],
            padding=True,
            return_tensors="pt",
            return_attention_mask=True,
        ).to("cuda")

        # VibeVoice official demo/inference_from_file.py 必要參數：
        # - cfg_scale: classifier-free guidance（預設 1.3），缺則無導向 → 模型自由生成 + hallucinate
        # - generation_config={'do_sample': False}: 關掉 sampling，否則隨機性導致內容錯字
        # 沒有這兩個 → 表現為「開頭錯字 + 後續長段 hallucination（10x 預期長度）」
        out = self.engine_obj.generate(
            **inputs,
            max_new_tokens=None,
            cfg_scale=1.3,
            tokenizer=self.vibevoice_processor.tokenizer,
            generation_config={"do_sample": False},
        )

        # Probe audio attribute (community fork differences)
        audio_obj = None
        for attr in ("speech_outputs", "audio", "audios", "outputs", "speech", "output_audios"):
            if hasattr(out, attr):
                cand = getattr(out, attr)
                if cand is not None:
                    audio_obj = cand[0] if isinstance(cand, (list, tuple)) else cand
                    break

        if audio_obj is None:
            # Last resort: check tuple-like return
            attrs_visible = [a for a in dir(out) if not a.startswith("_")][:15]
            raise RuntimeError(
                f"VibeVoice output has no known audio attr; visible: {attrs_visible}"
            )

        # `.float()` 把 bfloat16 → float32 (numpy 不支援 bfloat16 直轉)
        audio = audio_obj.detach().float().cpu().numpy().squeeze()
        if audio.ndim > 1:
            audio = audio.mean(axis=tuple(range(1, audio.ndim)))
        return audio.astype(np.float32), 24000


if __name__ == "__main__":
    sys.exit(WorkerTrioDaemon().main_loop())
