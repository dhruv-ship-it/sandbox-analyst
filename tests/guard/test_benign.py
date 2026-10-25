"""Benign snippets typical of CSV analysis must all pass the checker."""

import pytest

from sandbox_analyst.guard import check

BENIGN_CASES: list[tuple[str, str]] = [
    (
        "groupby_agg",
        "import pandas as pd\n"
        "df = pd.DataFrame({'g': ['a', 'b', 'a'], 'v': [1, 2, 3]})\n"
        "df.groupby('g')['v'].agg(['sum', 'mean'])\n",
    ),
    (
        "merge",
        "import pandas as pd\n"
        "a = pd.DataFrame({'id': [1, 2]})\n"
        "b = pd.DataFrame({'id': [1, 2], 'x': [3, 4]})\n"
        "a.merge(b, on='id', how='left')\n",
    ),
    (
        "describe",
        "import pandas as pd\ndf = pd.DataFrame({'a': [1, 2, 3]})\nprint(df.describe())\n",
    ),
    (
        "corr",
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': [1, 2, 3], 'b': [3, 2, 1]})\n"
        "print(df.corr())\n",
    ),
    (
        "value_counts",
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': ['x', 'y', 'x']})\n"
        "print(df['a'].value_counts())\n",
    ),
    (
        "datetime_parsing",
        "import pandas as pd\n"
        "df = pd.DataFrame({'d': ['2024-01-01', '2024-02-01']})\n"
        "df['d'] = pd.to_datetime(df['d'])\n",
    ),
    (
        "regex_on_strings",
        "import re\n"
        "import pandas as pd\n"
        "df = pd.DataFrame({'s': ['abc123', 'def456']})\n"
        "df['num'] = df['s'].apply(lambda x: re.search(r'\\d+', x).group())\n",
    ),
    (
        "str_contains",
        "import pandas as pd\n"
        "df = pd.DataFrame({'s': ['foo', 'bar']})\n"
        "df[df['s'].str.contains('fo')]\n",
    ),
    (
        "scipy_ttest",
        "from scipy import stats\nstats.ttest_ind([1, 2, 3], [2, 3, 4])\n",
    ),
    (
        "scipy_pearsonr",
        "from scipy.stats import pearsonr\npearsonr([1, 2, 3], [3, 2, 1])\n",
    ),
    (
        "sklearn_linear_regression",
        "from sklearn.linear_model import LinearRegression\n"
        "model = LinearRegression()\n"
        "model.fit([[1], [2], [3]], [1, 2, 3])\n"
        "model.predict([[4]])\n",
    ),
    (
        "statsmodels_ols",
        "import statsmodels.api as sm\n"
        "import numpy as np\n"
        "x = sm.add_constant(np.array([1, 2, 3]))\n"
        "model = sm.OLS([1, 2, 3], x).fit()\n"
        "print(model.summary())\n",
    ),
    (
        "seaborn_plot",
        "import seaborn as sns\n"
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': [1, 2, 3], 'b': [3, 2, 1]})\n"
        "sns.scatterplot(data=df, x='a', y='b')\n",
    ),
    (
        "df_query",
        "import pandas as pd\ndf = pd.DataFrame({'a': [1, 2, 3]})\ndf.query('a > 1')\n",
    ),
    (
        "json_dumps_results",
        "import json\nresult = {'mean': 1.5, 'count': 3}\nprint(json.dumps(result))\n",
    ),
    (
        "numpy_mean_std",
        "import numpy as np\narr = np.array([1, 2, 3, 4])\nprint(arr.mean(), arr.std())\n",
    ),
    (
        "pivot_table",
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': ['x', 'y'], 'b': [1, 2], 'v': [10, 20]})\n"
        "df.pivot_table(index='a', columns='b', values='v')\n",
    ),
    (
        "sort_values",
        "import pandas as pd\ndf = pd.DataFrame({'a': [3, 1, 2]})\ndf.sort_values('a')\n",
    ),
    (
        "fillna",
        "import pandas as pd\n"
        "import numpy as np\n"
        "df = pd.DataFrame({'a': [1, np.nan, 3]})\n"
        "df['a'].fillna(0)\n",
    ),
    (
        "dropna",
        "import pandas as pd\n"
        "import numpy as np\n"
        "df = pd.DataFrame({'a': [1, np.nan, 3]})\n"
        "df.dropna()\n",
    ),
    (
        "astype",
        "import pandas as pd\ndf = pd.DataFrame({'a': ['1', '2', '3']})\ndf['a'].astype(int)\n",
    ),
    (
        "apply_lambda",
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': [1, 2, 3]})\n"
        "df['a'].apply(lambda x: x * 2)\n",
    ),
    (
        "fstring_formatting",
        "mean = 3.14159\nprint(f'mean is {mean:.2f}')\n",
    ),
    (
        "savefig_into_work_out",
        "import matplotlib.pyplot as plt\nplt.plot([1, 2, 3])\nplt.savefig('/work/out/plot.png')\n",
    ),
    (
        "to_csv_no_path_returns_string",
        "import pandas as pd\ndf = pd.DataFrame({'a': [1, 2]})\ncsv_text = df.to_csv()\n",
    ),
    (
        "to_csv_relative_path_in_work",
        "import pandas as pd\ndf = pd.DataFrame({'a': [1, 2]})\ndf.to_csv('out/result.csv')\n",
    ),
    (
        "collections_counter",
        "from collections import Counter\nCounter(['a', 'b', 'a']).most_common()\n",
    ),
    (
        "itertools_combinations",
        "import itertools\nlist(itertools.combinations([1, 2, 3], 2))\n",
    ),
    (
        "math_and_statistics",
        "import math\nimport statistics\nprint(math.sqrt(16), statistics.mean([1, 2, 3]))\n",
    ),
    (
        "open_read_default_mode",
        "with open('/work/data/input.csv') as f:\n    contents = f.read()\n",
    ),
    (
        "open_read_explicit_r_mode",
        "with open('/work/data/input.csv', 'r') as f:\n    contents = f.read()\n",
    ),
    (
        "groupby_size_reset_index",
        "import pandas as pd\n"
        "df = pd.DataFrame({'g': ['a', 'b', 'a']})\n"
        "df.groupby('g').size().reset_index(name='count')\n",
    ),
    # Regression cases from the P3 checker-block false-positive review
    # (runs/review/checker_blocks.md, D-100): `exit`/`quit` early-return
    # guards and the `if __name__ == "__main__":` idiom are benign.
    (
        "exit_as_early_return_guard",
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': []})\n"
        "if df.empty:\n"
        "    print('no data')\n"
        "    exit()\n",
    ),
    (
        "exit_with_status_code",
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': []})\n"
        "if df.empty:\n"
        "    print('no data')\n"
        "    exit(1)\n",
    ),
    (
        "quit_as_early_return_guard",
        "import pandas as pd\n"
        "df = pd.DataFrame({'a': []})\n"
        "if df.empty:\n"
        "    print('no data')\n"
        "    quit()\n",
    ),
    (
        "main_guard_idiom",
        "import pandas as pd\n\n"
        "def main():\n"
        "    df = pd.DataFrame({'a': [1, 2, 3]})\n"
        "    print(df['a'].mean())\n\n"
        'if __name__ == "__main__":\n'
        "    main()\n",
    ),
]


@pytest.mark.parametrize("name,code", BENIGN_CASES, ids=[c[0] for c in BENIGN_CASES])
def test_benign_code_passes(name, code):
    result = check(code)
    assert result.ok, f"{name} unexpectedly blocked: {result.violations}"


def test_at_least_25_benign_cases():
    assert len(BENIGN_CASES) >= 25
