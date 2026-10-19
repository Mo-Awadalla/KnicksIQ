## Staged counts

| Stage | A_pin_r1 | A_pin_r2 | A_prod | B_pin_r1 | B_pin_r2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| questions | 110 | 110 | 110 | 110 | 110 |
| reached the model | 61 | 61 | 61 | 61 | 61 |
| writer response received | 61 | 61 | 61 | 61 | 61 |
| reviewer reached | 29 | 33 | 31 | 53 | 54 |
| reviewer accepted | 24 | 29 | 28 | 20 | 27 |
| met expectation | 33 | 38 | 37 | 29 | 35 |

## First failure by stage and message

| Run | Stage | Message | Count | Example question |
| --- | --- | --- | ---: | --- |
| A_pin_r1 | evidence preparation (capacity), after a valid writer answer | Complete explicitly cited sources exceed model input budget | 17 | exact_statistics-006 |
| A_pin_r1 | choice validation | Model response changes a required sealed claim choice | 13 | exact_statistics-001 |
| A_pin_r1 | choice validation | Model response selects a sealed claim more than once | 1 | comparisons-011 |
| A_pin_r2 | evidence preparation (capacity), after a valid writer answer | Complete explicitly cited sources exceed model input budget | 14 | exact_statistics-005 |
| A_pin_r2 | choice validation | Model response changes a required sealed claim choice | 12 | exact_statistics-001 |
| A_pin_r2 | choice validation | Model response selects a sealed claim more than once | 1 | comparisons-011 |
| A_pin_r2 | evidence preparation (capacity), after a valid writer answer | Complete selected-game claims exceed model input budget | 1 | turning_points-006 |
| A_prod | evidence preparation (capacity), after a valid writer answer | Complete explicitly cited sources exceed model input budget | 14 | exact_statistics-006 |
| A_prod | choice validation | Model response changes a required sealed claim choice | 13 | exact_statistics-001 |
| A_prod | choice validation | Model response selects a sealed claim more than once | 1 | comparisons-011 |
| A_prod | evidence preparation (capacity), after a valid writer answer | Complete selected-game claims exceed model input budget | 1 | turning_points-006 |
| B_pin_r1 | evidence preparation (capacity), after a valid writer answer | Complete explicitly cited sources exceed model input budget | 6 | comparisons-002 |
| B_pin_r1 | choice validation | Model response selects a sealed claim more than once | 1 | comparisons-011 |
| B_pin_r1 | evidence preparation (capacity), after a valid writer answer | Complete selected-game claims exceed model input budget | 1 | single_game_narrative-020 |
| B_pin_r2 | evidence preparation (capacity), after a valid writer answer | Complete explicitly cited sources exceed model input budget | 6 | comparisons-002 |
| B_pin_r2 | choice validation | Model response selects a sealed claim more than once | 1 | comparisons-011 |

## Review rejections

- A_pin_r1: 6 reviewer-rejected answers
- A_pin_r2: 4 reviewer-rejected answers
- A_prod: 4 reviewer-rejected answers
- B_pin_r1: 33 reviewer-rejected answers
- B_pin_r2: 27 reviewer-rejected answers

## Providers that served requests

- A_pin_r1: {'DeepInfra': 100}
- A_pin_r2: {'DeepInfra': 98}
- A_prod: {'DeepInfra': 81, 'Makora': 9, 'Together': 1, 'BaseTen': 3}
- B_pin_r1: {'DeepInfra': 182}
- B_pin_r2: {'DeepInfra': 189}

## Choices offered per required slot

| Claims in slot | Choices in slot | Slots seen |
| ---: | ---: | ---: |
| 1 | 1 | 176 |
| 1 | 5 | 361 |
