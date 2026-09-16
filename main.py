from pathlib import Path

from shiju.app import AppConfig, ModelConfig, SamplingConfig, run
from shiju.tasks import HanpaiOptions, TaskRequest


def main() -> None:
    config = AppConfig(
        model=ModelConfig(
            model_name=r"C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B",
            quantization="4bit",
        ),
        task=TaskRequest(
            meter_type="汉俳",
            form_name="汉俳",
            theme="初秋离别",
            rhyme_dict_name="Xinyun",
            use_thinking=False,
            requirement="学姐毕业一年，探问工作情况如何，生活如何。极为**委婉**地表达思念和倾慕。",
            hanpai=HanpaiOptions(
                line_pattern="5-7-5",
                season="红叶",
                forbid_isolated_level=True,
                allow_aojiu=True,
                forbid_three_same_ending=True,
                rhyme_scheme="ABA",
            ),
        ),
        sampling=SamplingConfig(
            temperature=0.7,
            top_p=0.8,
            top_k=20,
            min_p=0.0,
        ),
        use_constraints=True,
        num_generations=3,
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
