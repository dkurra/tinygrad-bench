# tinygrad-bench results

| config | n | mean score | resolved | apply-fail | mean steps | easy | medium | hard |
|---|---|---|---|---|---|---|---|---|
| A_thinking_high | 8 | 0.356 | 2 (25%) | 0 | 32.625 | 0.500 | 0.281 | 0.000 |
| openrouter_deepseek_deepseek-v4-flash | 100 | 0.242 | 24 (24%) | 0 | 36.270 | 0.423 | 0.038 | 0.067 |
| openrouter_minimax_minimax-m2.5 | 29 | 0.103 | 3 (10%) | 0 | 39.207 | 0.231 | 0.000 | 0.000 |
| openrouter_qwen_qwen3-coder-30b-a3b-instruct | 100 | 0.037 | 3 (3%) | 3 | 29.330 | 0.051 | 0.030 | 0.000 |
| openrouter_z-ai_glm-5.2 | 100 | 0.351 | 34 (34%) | 0 | 32.910 | 0.558 | 0.101 | 0.182 |

## A_thinking_high
- exit statuses: {'LimitsExceeded': 3, 'Submitted': 5}
- by module: mixin: 0.000 (n=3), core: 0.922 (n=2), uop: 0.000 (n=1), codegen: 0.000 (n=1), schedule: 1.000 (n=1)
- cost: n/a

## openrouter_deepseek_deepseek-v4-flash
- exit statuses: {'LimitsExceeded': 73, 'Submitted': 27}
- by module: mixin: 0.261 (n=23), core: 0.368 (n=17), codegen: 0.000 (n=15), uop: 0.500 (n=10), schedule: 0.111 (n=9), engine: 0.125 (n=8), viz: 0.333 (n=6), nn: 0.250 (n=4), runtime: 0.000 (n=3), llm: 0.000 (n=2), renderer: 0.500 (n=2), apps: 1.000 (n=1)
- cost: n/a

## openrouter_minimax_minimax-m2.5
- exit statuses: {'LimitsExceeded': 25, 'Submitted': 4}
- by module: core: 0.200 (n=5), mixin: 0.200 (n=5), codegen: 0.000 (n=3), engine: 0.000 (n=3), uop: 0.000 (n=2), schedule: 0.000 (n=2), viz: 0.000 (n=2), nn: 0.000 (n=2), renderer: 0.000 (n=2), runtime: 0.000 (n=1), llm: 0.000 (n=1), apps: 1.000 (n=1)
- cost: n/a

## openrouter_qwen_qwen3-coder-30b-a3b-instruct
- exit statuses: {'LimitsExceeded': 61, 'Submitted': 10, 'RepeatedFormatError': 29}
- by module: mixin: 0.000 (n=23), core: 0.157 (n=17), codegen: 0.067 (n=15), uop: 0.000 (n=10), schedule: 0.000 (n=9), engine: 0.000 (n=8), viz: 0.000 (n=6), nn: 0.000 (n=4), runtime: 0.000 (n=3), llm: 0.000 (n=2), renderer: 0.000 (n=2), apps: 0.000 (n=1)
- cost: n/a

## openrouter_z-ai_glm-5.2
- exit statuses: {'LimitsExceeded': 53, 'Submitted': 47}
- by module: mixin: 0.317 (n=23), core: 0.438 (n=17), codegen: 0.067 (n=15), uop: 0.733 (n=10), schedule: 0.222 (n=9), engine: 0.375 (n=8), viz: 0.500 (n=6), nn: 0.500 (n=4), runtime: 0.000 (n=3), llm: 0.000 (n=2), renderer: 0.500 (n=2), apps: 1.000 (n=1)
- cost: n/a
