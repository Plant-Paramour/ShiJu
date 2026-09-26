import json
import re
from pathlib import Path

from transformers import AutoTokenizer


MODEL_DIR = Path(r"C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B")
OUT_DIR = Path(__file__).resolve().parents[1] / "exports" / "qwen3-4b-vocab"
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def main():
    tokenizer = AutoTokenizer.from_pretrained(
        MODEL_DIR, local_files_only=True, use_fast=True
    )
    vocab = tokenizer.get_vocab()
    rows = []
    for token, token_id in sorted(vocab.items(), key=lambda item: item[1]):
        decoded = tokenizer.decode(
            [token_id], skip_special_tokens=False, clean_up_tokenization_spaces=False
        )
        rows.append(
            {
                "id": token_id,
                "token": token,
                "decoded": decoded,
                "has_cjk": bool(CJK_RE.search(decoded)),
                "decoded_is_cjk": bool(decoded) and all(
                    CJK_RE.match(char) for char in decoded
                ),
            }
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "vocab.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def write_tsv(path, selected):
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            handle.write("id\ttoken\tdecoded\n")
            for row in selected:
                handle.write(
                    f"{row['id']}\t{row['token']}\t{row['decoded']}\n"
                )

    write_tsv(OUT_DIR / "chinese-containing.tsv", [r for r in rows if r["has_cjk"]])
    write_tsv(
        OUT_DIR / "chinese-only-decoded.tsv",
        [r for r in rows if r["decoded_is_cjk"]],
    )
    write_tsv(OUT_DIR / "vocab.tsv", rows)

    summary = {
        "model_dir": str(MODEL_DIR),
        "vocab_size": len(rows),
        "chinese_containing": sum(r["has_cjk"] for r in rows),
        "chinese_only_decoded": sum(r["decoded_is_cjk"] for r in rows),
        "rule": "CJK Unicode ranges U+3400-U+4DBF, U+4E00-U+9FFF, U+F900-U+FAFF",
        "files": [
            "vocab.jsonl",
            "vocab.tsv",
            "chinese-containing.tsv",
            "chinese-only-decoded.tsv",
        ],
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
