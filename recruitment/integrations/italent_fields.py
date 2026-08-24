from collections.abc import Iterable


def is_display_value(value):
    return value not in (None, "", [], {}) and str(value).strip() != "-32767"


def field_entries(payload):
    if not isinstance(payload, dict):
        return []
    values = payload.get("fieldValues")
    if isinstance(values, list):
        return values
    if isinstance(values, dict):
        entries = []
        for name, value in values.items():
            if isinstance(value, dict):
                entry = {"name": name, **value}
            else:
                entry = {"name": name, "value": value, "text": value}
            entries.append(entry)
        return entries
    return []


def field_map(payload):
    fields = {}
    for entry in field_entries(payload):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if name:
            fields[str(name)] = entry
    return fields


def field_value(payload, *names, prefer_text=False, default=""):
    fields = field_map(payload)
    value_order = ("text", "value") if prefer_text else ("value", "text")
    for name in names:
        entry = fields.get(name)
        if not entry:
            continue
        for key in value_order:
            value = entry.get(key)
            if is_display_value(value):
                return value
    return default


def module_records(payload):
    if not isinstance(payload, dict):
        return []
    records = payload.get("moduleInfo")
    if not isinstance(records, list):
        return []
    return [
        record
        for record in records
        if isinstance(record, list)
    ]


def module_record_map(record):
    fields = {}
    if not isinstance(record, Iterable) or isinstance(record, (str, bytes, dict)):
        return fields
    for entry in record:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if name:
            fields[str(name)] = entry
    return fields


def module_value(record, *names, prefer_text=True, default=""):
    fields = module_record_map(record)
    value_order = ("text", "value") if prefer_text else ("value", "text")
    for name in names:
        entry = fields.get(name)
        if not entry:
            continue
        for key in value_order:
            value = entry.get(key)
            if is_display_value(value):
                return value
    return default


def module_text(payload, preferred_fields=()):
    parts = []
    for record in module_records(payload):
        values = []
        if preferred_fields:
            for name in preferred_fields:
                value = module_value(record, name)
                if value and value not in values:
                    values.append(str(value))
        else:
            for entry in record:
                if not isinstance(entry, dict):
                    continue
                value = entry.get("text") or entry.get("value")
                if is_display_value(value) and str(value) not in values:
                    values.append(str(value))
        if values:
            parts.append(" · ".join(values))
    return "\n".join(parts)


def list_text(value):
    if isinstance(value, list):
        values = []
        for item in value:
            if isinstance(item, dict):
                item = (
                    item.get("text")
                    or item.get("name")
                    or item.get("label")
                    or item.get("value")
                )
            if item not in (None, ""):
                values.append(str(item))
        return "、".join(values)
    if isinstance(value, dict):
        return str(
            value.get("text")
            or value.get("name")
            or value.get("label")
            or value.get("value")
            or ""
        )
    return str(value) if value not in (None, "") else ""
