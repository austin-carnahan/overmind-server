"""OpenAI CLIP's byte-pair tokenizer in the standard library only, for the
text-prompted models' adapters (EfficientSAM3's MobileCLIP-S0, OWLv2's CLIP
text tower) -- the guest has no regex/ftfy/tokenizers. Same merges file
(assets/bpe_simple_vocab_16e6.txt.gz, OpenAI CLIP, MIT), vocabulary, cleaning
("lower": whitespace collapsed, lowercased, HTML entities unescaped twice) and
special tokens (<start_of_text> 49406, <end_of_text> 49407, padding 0) as
open_clip's / EfficientSAM3's SimpleTokenizer.

Two documented differences, both outside ordinary prompts: ftfy.fix_text
(mojibake repair) is not applied, and the pre-tokenizer's Unicode classes are
approximated with the stdlib's (\\p{L}+ as [^\\W\\d_]+, \\p{N} as \\d), which
differ only for letter-like marks and non-decimal numerals (e.g. "½", "Ⅻ").
Checked token for token against both originals (models' tests)."""
import gzip
import html
import os
import re
from functools import lru_cache

BPE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "bpe_simple_vocab_16e6.txt.gz")


@lru_cache()
def bytes_to_unicode():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(2 ** 8):
        if b not in bs:
            bs.append(b)
            cs.append(2 ** 8 + n)
            n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


def get_pairs(word):
    return {(a, b) for a, b in zip(word[:-1], word[1:])}


class ClipTokenizer:
    def __init__(self, bpe_path: str = BPE_PATH):
        self.byte_encoder = bytes_to_unicode()
        merges = gzip.open(bpe_path).read().decode("utf-8").split("\n")[1:49152 - 256 - 2 + 1]
        merges = [tuple(m.split()) for m in merges]
        vocab = list(self.byte_encoder.values())
        vocab = vocab + [v + "</w>" for v in vocab] + ["".join(m) for m in merges] + ["<start_of_text>", "<end_of_text>"]
        self.encoder = {v: i for i, v in enumerate(vocab)}
        self.bpe_ranks = {m: i for i, m in enumerate(merges)}
        self.cache = {}
        self.sot, self.eot = self.encoder["<start_of_text>"], self.encoder["<end_of_text>"]
        self.pat = re.compile(r"""<start_of_text>|<end_of_text>|'s|'t|'re|'ve|'m|'ll|'d|[^\W\d_]+|\d|(?:[^\s\w]|_)+""", re.IGNORECASE)

    def bpe(self, token):
        if token in self.cache:
            return self.cache[token]
        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        pairs = get_pairs(word)
        if not pairs:
            return token + "</w>"
        while True:
            bigram = min(pairs, key=lambda p: self.bpe_ranks.get(p, float("inf")))
            if bigram not in self.bpe_ranks:
                break
            first, second = bigram
            new, i = [], 0
            while i < len(word):
                try:
                    j = word.index(first, i)
                except ValueError:
                    new.extend(word[i:])
                    break
                new.extend(word[i:j])
                i = j
                if word[i] == first and i < len(word) - 1 and word[i + 1] == second:
                    new.append(first + second)
                    i += 2
                else:
                    new.append(word[i])
                    i += 1
            word = tuple(new)
            if len(word) == 1:
                break
            pairs = get_pairs(word)
        out = " ".join(word)
        self.cache[token] = out
        return out

    @staticmethod
    def clean(text):
        text = html.unescape(html.unescape(text)).strip()
        return re.sub(r"\s+", " ", text).strip().lower()

    def encode(self, text):
        ids = []
        for token in self.pat.findall(self.clean(text)):
            token = "".join(self.byte_encoder[b] for b in token.encode("utf-8"))
            ids.extend(self.encoder[t] for t in self.bpe(token).split(" "))
        return ids

    def __call__(self, texts, context_length):
        """-> list of int lists, each [sot, ..., eot] zero-padded (truncated with eot last)."""
        out = []
        for text in texts:
            toks = [self.sot] + self.encode(text) + [self.eot]
            if len(toks) > context_length:
                toks = toks[:context_length]
                toks[-1] = self.eot
            out.append(toks + [0] * (context_length - len(toks)))
        return out
