"""The InfiAgent-DABench benchmark: download, schema, and the dev/test split."""

from .dabench import Label, Question, load_labels, load_questions

__all__ = ["Question", "Label", "load_questions", "load_labels"]
