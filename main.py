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
            meter_type="宋词",
            rhyme_dict_name="Xinyun",
            task_type="instruction",
            theme="婉约相思",
            form_name="浣溪沙",
            requirement="",
            use_thinking=False,
        ),
        sampling=SamplingConfig(
            temperature=0.6,
            top_p=0.95,
            top_k=20,
            min_p=0.0,
        ),
        use_constraints=True,
        num_generations=3,
        save_output=True,
        rhyme_dir=Path("Rhyme"),
        meter_source=Path("Songci_Meter"),
        output_dir=Path("output"),
    )
    run(config)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[启动失败] {exc}")
        raise
