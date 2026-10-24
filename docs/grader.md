# grader.md

Shape census over DEV labels only (never test), by `classify_shape`. 74 dev labels, 129 sub-answers.

| shape | count | examples |
|---|---|---|
| decimal_1dp | 7 | '0.0', '0.0' |
| decimal_2dp | 61 | '0.01', '-0.04' |
| decimal_3dp | 11 | '0.252', '0.828' |
| decimal_4dp | 7 | '0.4058', '0.0000' |
| integer | 23 | '0', '2081990' |
| list_like | 4 | '314, 577', '0.00, 1.00, 0.0629' |
| string | 13 | 'not normally distributed', 'none' |
| yes_no | 3 | 'False', 'Yes' |

Format-only check across all 257 labels (461 sub-answers, dev + test): **0** failed to classify into a known shape (must be 0). Counts only -- no label content from the test split is read anywhere above this line.
