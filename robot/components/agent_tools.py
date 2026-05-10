"""Helpers for defining model tools as regular Python methods."""

import inspect
from typing import Any

from docstring_parser import parse
from pydantic import Field, create_model


def agent_tool(func):
    """Mark a method as an agent tool.

    Decorated tools must use Google-style docstrings with an Args section.
    The docstring is used to build the model-facing tool schema.
    """
    func._agent_tool = True
    return func


def collect_agent_tools(instance) -> tuple[list[dict], dict[str, Any]]:
    """Collect tool schemas and bound callables from an object."""
    schemas = []
    handlers = {}
    for name in dir(instance):
        value = getattr(instance, name)
        if not callable(value) or not getattr(value, "_agent_tool", False):
            continue
        schema = _schema_for_tool(value)
        schemas.append(schema)
        handlers[schema["name"]] = value
    return schemas, handlers


def _schema_for_tool(func) -> dict:
    description, arg_docs = _parse_google_docstring(func)
    input_schema = _input_schema_for_tool(func, arg_docs)

    return {
        "name": func.__name__,
        "description": _normalize_whitespace(description),
        "input_schema": input_schema,
    }


def _parse_google_docstring(func) -> tuple[str, dict[str, str]]:
    doc = inspect.getdoc(func)
    if not doc:
        raise ValueError(f"Tool {func.__name__} needs a Google-style docstring")

    parsed = parse(doc)
    description = " ".join(
        part for part in [parsed.short_description, parsed.long_description] if part
    ).strip()
    if not description:
        raise ValueError(f"Tool {func.__name__} needs a description before Args")
    arg_docs = {
        param.arg_name: _normalize_whitespace(param.description or "")
        for param in parsed.params
    }
    return description, arg_docs


def _input_schema_for_tool(func, arg_docs: dict[str, str]) -> dict:
    fields = {}
    for name, param in inspect.signature(func).parameters.items():
        if name == "self":
            continue
        if name not in arg_docs:
            raise ValueError(f"Tool {func.__name__} is missing an Args doc for {name}")
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            annotation = Any
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[name] = (
            annotation,
            Field(default, description=arg_docs[name]),
        )

    model = create_model(f"{func.__name__}_input", **fields)
    schema = model.model_json_schema()
    schema.pop("title", None)
    return schema


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())
