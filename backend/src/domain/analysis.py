import json
from datetime import date
from math import isfinite
from pathlib import Path
from collections import Counter, defaultdict
from math import log2

_SPEC = json.loads(Path(__file__).with_name("spec.json").read_text(encoding="utf-8"))


def _validate_fields(values, fields, *, defaults=False):
    result = {}
    for field in fields:
        key = field["key"]
        value = values.get(key, field.get("default") if defaults else None)
        kind = field["type"]
        if kind == "number" or kind == "integer":
            valid = type(value) in (int, float) and isfinite(value) and field["min"] <= value <= field["max"]
            valid = valid and (kind != "integer" or int(value) == value)
            if valid:
                value = int(value) if kind == "integer" else float(value)
        elif kind == "choice":
            valid = value in field["choices"]
        else:
            valid = isinstance(value, str) and 0 < len(value.strip()) <= 300
            if valid and kind == "date":
                try:
                    valid = date.fromisoformat(value).isoformat() == value
                except ValueError:
                    valid = False
            if valid:
                value = value.strip()
        if not valid:
            raise ValueError(f"「{field['label']}」格式或范围无效")
        result[key] = value
    return result


def validate(row):
    _validate_fields(row, _SPEC["fields"])


def _inputs(rows, parameters, identity="ticket"):
    clean = [_validate_fields(row, _SPEC["fields"]) for row in rows]
    if len({row[identity] for row in clean}) != len(clean):
        raise ValueError(f"存在重复的{next(field['label'] for field in _SPEC['fields'] if field['key'] == identity)}，请检查单据")
    params = _validate_fields(parameters, _SPEC["parameters"], defaults=True)
    return sorted(clean, key=lambda row: (row.get("day", ""), row[identity])), params


def _shown(value, places=2):
    return "—" if value is None else round(float(value), places)


def _output(headline, summary, columns, rows, metrics, chart_name, chart_unit, chart_data):
    return {
        "headline": headline,
        "summary": summary,
        "columns": [{"key": key, "label": label} for key, label in columns],
        "rows": rows,
        "metrics": [{"label": label, "value": value, "unit": unit} for label, value, unit in metrics],
        "chart": {
            "label": chart_name, "unit": chart_unit,
            "points": [{"label": str(label), "value": value} for label, value in chart_data],
        },
    }


COLUMNS = (("direction", "已知标签"), ("label", "现有值"), ("n", "见签数"),
           ("plurality", "候选补填"), ("errors", "候选误填数"), ("decision", "补填建议"))


def _entropy(counts):
    total = sum(counts)
    return -sum(count / total * log2(count / total) for count in counts if count)


def _direction(rows, known, target, caption, minimum):
    groups = defaultdict(Counter)
    for row in rows:
        groups[row[known]][row[target]] += 1
    total_entropy = _entropy(Counter(row[target] for row in rows).values())
    conditional = 0.0
    detail = []
    for label, counts in sorted(groups.items()):
        size = counts.total()
        top = max(counts.values())
        tied = sorted(candidate for candidate, count in counts.items() if count == top)
        conditional += size / len(rows) * _entropy(counts.values())
        if size < minimum:
            decision = "样本薄，保留双标签"
        elif len(tied) > 1:
            decision = "条件众数并列，人工补全"
        else:
            decision = "按候选值送核" if size - top else "当前抽验全匹配"
        detail.append({"direction": caption, "label": label, "n": size,
                       "plurality": "／".join(tied), "errors": size - top, "decision": decision})
    strength = max(0.0, min(1.0, 1 - conditional / total_entropy)) if total_entropy > 0 else None
    return strength, detail


def analyze(rows, parameters):
    rows, options = _inputs(rows, parameters)
    if len(rows) < 4:
        raise ValueError("标签关联至少需要四张绣样签")
    forward, from_stitch = _direction(rows, "stitch", "base", "仅针法", options["minimum"])
    reverse, from_base = _direction(rows, "base", "stitch", "仅底布", options["minimum"])
    eligible = [(label, _shown(value, 4)) for label, value in (("针法推底布", forward), ("底布推针法", reverse)) if value is not None]
    return _output("绣样标签互推核查", "同一批签样分两向计算条件熵，门槛仅控制组内候选值的补填建议。误填数按该组全部填成候选众数估计。",
                   COLUMNS, from_stitch + from_base,
                   [("绣样签", len(rows), "张"), ("针法推底布 U", _shown(forward, 4), ""), ("底布推针法 U", _shown(reverse, 4), "")],
                   "同一样本两向信息增益", "", eligible)


def seed():
    rows = []
    for stitch, counts in zip(("套针", "盘金", "锁绣", "打籽"), ((12, 2, 2), (0, 16, 0), (2, 0, 6), (3, 1, 4))):
        for base, count in zip(("电力纺", "绸缎", "棉绫"), counts):
            for _ in range(count):
                rows.append({"ticket": f"ZX-{len(rows)+1:03}", "stitch": stitch, "base": base})
    return rows
