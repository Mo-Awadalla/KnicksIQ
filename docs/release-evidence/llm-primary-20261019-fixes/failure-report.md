## Staged counts

| Stage | A_pin_r1 | A_pin_r2 | S_slotlocal_r1 | S_slotlocal_r2 | E_both_r1 | E_both_r2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| questions | 110 | 110 | 110 | 110 | 110 | 110 |
| reached the model | 61 | 61 | 61 | 61 | 61 | 61 |
| writer response received | 61 | 61 | 61 | 61 | 61 | 61 |
| reviewer reached | 29 | 33 | 46 | 44 | 55 | 55 |
| reviewer accepted | 24 | 29 | 42 | 41 | 47 | 47 |

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
| S_slotlocal_r1 | evidence preparation (capacity), after a valid writer answer | Complete explicitly cited sources exceed model input budget | 13 | exact_statistics-006 |
| S_slotlocal_r1 | other | TimeoutError with no message | 1 | exact_statistics-020 |
| S_slotlocal_r1 | choice validation | Model response changes a required sealed claim choice | 1 | single_game_narrative-011 |
| S_slotlocal_r1 | evidence preparation (capacity), after a valid writer answer | Complete selected-game claims exceed model input budget | 1 | turning_points-006 |
| S_slotlocal_r2 | evidence preparation (capacity), after a valid writer answer | Complete explicitly cited sources exceed model input budget | 15 | exact_statistics-005 |
| S_slotlocal_r2 | choice validation | Model response selects a sealed claim more than once | 1 | comparisons-011 |
| S_slotlocal_r2 | choice validation | Model response changes a required sealed claim choice | 1 | single_game_narrative-011 |
| E_both_r1 | evidence preparation (capacity), after a valid writer answer | Complete explicitly cited sources exceed model input budget | 2 | comparisons-002 |
| E_both_r1 | choice validation | Model response selects a sealed claim more than once | 1 | comparisons-011 |
| E_both_r1 | evidence preparation (capacity) | Complete explicitly cited sources exceed model input budget | 1 | comparisons-015 |
| E_both_r1 | choice validation | Model response changes a required sealed claim choice | 1 | single_game_narrative-011 |
| E_both_r2 | evidence preparation (capacity), after a valid writer answer | Complete explicitly cited sources exceed model input budget | 4 | comparisons-002 |
| E_both_r2 | other | TimeoutError with no message | 1 | comparisons-004 |
| E_both_r2 | choice validation | Model response selects a sealed claim more than once | 1 | comparisons-011 |
| E_both_r2 | choice validation | Model response changes a required sealed claim choice | 1 | single_game_narrative-011 |

## Review rejections

- A_pin_r1: 6 reviewer-rejected answers
- A_pin_r2: 4 reviewer-rejected answers
- S_slotlocal_r1: 3 reviewer-rejected answers
- S_slotlocal_r2: 3 reviewer-rejected answers
- E_both_r1: 9 reviewer-rejected answers
- E_both_r2: 7 reviewer-rejected answers

## Providers that served requests

- A_pin_r1: {'DeepInfra': 100}
- A_pin_r2: {'DeepInfra': 98}
- S_slotlocal_r1: {'DeepInfra': 110}
- S_slotlocal_r2: {'DeepInfra': 111}
- E_both_r1: {'DeepInfra': 124}
- E_both_r2: {'DeepInfra': 125}

## Choices offered per required slot

| Claims in slot | Choices in slot | Slots seen |
| ---: | ---: | ---: |
| 1 | 1 | 189 |
| 1 | 5 | 358 |
