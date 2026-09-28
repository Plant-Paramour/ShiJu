import json, random, time
from pathlib import Path
import numpy as np
import torch
from shiju.contracts import GeneratePoemRequest, SamplingOptions
from shiju.generation.engine import GenerationEngine
from shiju.generation.model_runner import ModelRunner
from shiju.generation.result import ModelSettings

SEED = 20260928
REPEATS = 3
MODEL = r'C:\Users\26051\.cache\modelscope\hub\models\Qwen\Qwen3-4B'

def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

runner = ModelRunner(ModelSettings(model_name=MODEL, quantization='8bit'))
engine = GenerationEngine(runner, rhyme_dir='Rhyme', meter_source='Songci_Meter')
request = GeneratePoemRequest(
    meter_type='唐诗', form_name='七言绝句', theme='秋江晚景',
    rhyme_dict_name='Pinshui', requirement='意境清远，语言自然。',
    use_thinking=False, candidate_count=1,
    sampling=SamplingOptions(max_new_tokens=128, temperature=0.6, top_p=0.95, top_k=20),
)
groups = {}
for use_constraints in (True, False):
    label = 'with_constraints' if use_constraints else 'without_constraints'
    # Warmup also initializes the model and cached rhyme/vocab resources.
    seed_all(SEED)
    t0 = time.perf_counter()
    engine.generate_poem(request, use_constraints=use_constraints)
    warmup = time.perf_counter() - t0
    records = []
    for i in range(1, REPEATS + 1):
        seed_all(SEED)
        t0 = time.perf_counter()
        result = engine.generate_poem(request, use_constraints=use_constraints)
        elapsed = time.perf_counter() - t0
        candidate = result['candidates'][0]
        records.append({'run': i, 'seed': SEED, 'elapsed_seconds': elapsed, 'text': candidate['text'], 'raw_output': candidate['raw_output']})
        print(f'{label} run {i}: {elapsed:.3f}s')
    vals = [x['elapsed_seconds'] for x in records]
    groups[label] = {
        'use_constraints': use_constraints,
        'warmup_seconds': warmup,
        'mean_seconds': sum(vals) / len(vals),
        'min_seconds': min(vals),
        'max_seconds': max(vals),
        'std_seconds': float(np.std(vals, ddof=1)),
        'runs': records,
    }
summary={'model':MODEL,'quantization':'8bit','seed':SEED,'repeats':REPEATS,'request':request.to_dict(),'groups':groups}
out=Path('experiments/generation_timing'); out.mkdir(parents=True, exist_ok=True)
path=out / f'controlled_{time.strftime("%Y%m%d_%H%M%S")}.json'
path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'output':str(path),'summary':{name: {key: data[key] for key in ('warmup_seconds','mean_seconds','min_seconds','max_seconds','std_seconds')} for name, data in groups.items()}}, ensure_ascii=False))
