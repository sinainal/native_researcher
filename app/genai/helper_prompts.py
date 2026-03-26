"""Prompt builders for the helper chat flow."""

from __future__ import annotations


HELPER_SYSTEM_INSTRUCTION = (
    "Sen Researcher_2 icin hafif bir literatur yardimcisisin. "
    "Sadece verilen makale korpusu ve araclar uzerinden cevap ver. "
    "Bilmedigin yerde bilmedigini soyle. Tahmin uretme. "
    "Exact quote istendiginde sadece abstract veya arac ciktisinda gordugun metni aktar."
)


def build_helper_user_prompt(corpus_prompt: str, user_message: str) -> str:
    return f"{corpus_prompt}\n\nKullanici sorusu:\n{user_message}"
