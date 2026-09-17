from pathlib import Path

from shiju.app import AppConfig, ModelConfig, SamplingConfig, run
from shiju.tasks import TaskRequest


def main() -> None:
    config = AppConfig(
        model=ModelConfig(
            model_name=r"C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B",
            quantization="8bit",
        ),
        task=TaskRequest(
            meter_type="排律",
            form_name="七言排律",
            num_lines=16,
            theme="爱，美，诗，与永恒",
            rhyme_dict_name="Xinyun",
            use_thinking=False,
            requirement="""
            你需要创作一首七言排律，一共16句。
            你不应该直译下面的这首诗，也不应该单纯translate这些意象。而是应该自由的选择合适的中文诗词传统意象，信达雅的将十四行诗翻译为中文七言八韵十六句。
            注意，你可以不遵照原文，原样照搬，允许你自由发挥二次创作，但务必确保是这首诗的意译之作。至少保留相同的意蕴哲思与内涵。
            你需要先用一段文字梳理思路，明确创作的主题、意象、情感基调和诗歌结构，然后再进行创作。
            十四行诗如下：
            Shall I compare thee to a summer’s day?
            Thou art more lovely and more temperate:
            Rough winds do shake the darling buds of May,
            And summer’s lease hath all too short a date;
            Sometime too hot the eye of heaven shines,
            And often is his gold complexion dimm'd;
            And every fair from fair sometime declines,
            By chance or nature’s changing course untrimm'd;
            But thy eternal summer shall not fade,
            Nor lose possession of that fair thou ow’st;
            Nor shall death brag thou wander’st in his shade,
            When in eternal lines to time thou grow’st:
           So long as men can breathe or eyes can see,
           So long lives this, and this gives life to thee.
            """,
        ),
        sampling=SamplingConfig(
            temperature=0.7,
            top_p=0.8,
            top_k=20,
            min_p=0.0,
        ),
        use_constraints=True,
        num_generations=5,
        save_output=True,
        rhyme_dir=Path("Rhyme"),
        meter_source=Path("Songci_Meter"),
        output_dir=Path("output"),
        boundary_coherence_penalty=50.0,
    )
    run(config)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[启动失败] {exc}")
        raise
