from pathlib import Path

import scipy.io.wavfile as wavf
import torch
from .utils import get_hparams_from_file, load_checkpoint
from torch import no_grad, LongTensor

from .commons import intersperse
from .models import SynthesizerTrn
from .text import text_to_sequence

import datetime

device = "cuda:0" if torch.cuda.is_available() else "cpu"

language_marks = {
    "JP": "[JA]",
    "ZH": "[ZH]",
    "EN": "[EN]",
    "Mix": ""
}


def get_text(text, hps, is_symbol):
    text_norm = text_to_sequence(text, hps.symbols, [] if is_symbol else hps.data.text_cleaners)
    if hps.data.add_blank:
        text_norm = intersperse(text_norm, 0)
    text_norm = LongTensor(text_norm)
    return text_norm


def generate(text, noise_scale=.667, noise_scale_w=.6, length=.8, language="Mix"):
    """
    :param text: Text to generate
    :param noise_scale: THE EMOTION
    :param noise_scale_w: phoneme scale
    :param length: overall talk speed
    :param language: The language, can be ["Mix", "JP", "CH", "EN"]
    """

    output_dir = Path("D:/LurieAI/voice")
    output_dir.mkdir(parents=True, exist_ok=True)

    hps = get_hparams_from_file("D:/LurieAI/vits-fast-fine-tuning-model/finetune_speaker.json")
    net_g = SynthesizerTrn(
        len(hps.symbols),
        hps.data.filter_length // 2 + 1,
        hps.train.segment_size // hps.data.hop_length,
        n_speakers=hps.data.n_speakers,
        **hps.model).to(device)
    _ = net_g.eval()
    _ = load_checkpoint("D:/LurieAI/vits-fast-fine-tuning-model/G_latest.pth", net_g, None)

    speaker_ids = hps.speakers

    if language is not None:
        text = language_marks[language] + text + language_marks[language]
        speaker_id = speaker_ids["Lurie1.4"]
        stn_tst = get_text(text, hps, False)
        with no_grad():
            x_tst = stn_tst.unsqueeze(0).to(device)
            x_tst_lengths = LongTensor([stn_tst.size(0)]).to(device)
            sid = LongTensor([speaker_id]).to(device)
            audio = net_g.infer(x_tst, x_tst_lengths, sid=sid, noise_scale=noise_scale, noise_scale_w=noise_scale_w,
                                length_scale=1.0 / length)[0][0, 0].data.cpu().float().numpy()
        del stn_tst, x_tst, x_tst_lengths, sid

        # 获取当前日期时间
        current_datetime = datetime.datetime.now()
        # 将日期时间对象转换为字符串
        datetime_str = current_datetime.strftime("%Y-%m-%d-%H-%M-%S")

        wavf.write(str(output_dir) + f"\{datetime_str}.wav", hps.data.sampling_rate, audio)

    return f"{datetime_str}.wav"


if __name__ == "__main__":
    generate("測試，第三次", language="ZH")